"""
snape_daily.py
スネイプ担当：日次監視官

責務:
1. パイプライン健全性監視（タイムアウト・停滞検知 → 再実行指示）
2. 3パスリフレクション品質チェック（批評→擁護→統合の深層思考）
3. 整合性検証（ブリーフィング→投稿案→審査の一貫性）
4. API エラー検知・対処提案
5. 承認タイムアウト時の Discord 再通知
6. 考えられる問題の先読みと予防措置

実行タイミング: daily-cycle.yml の各ステップ後、またはスタンドアロンで
"""

import os
import json
import re
import sys
import requests
from datetime import datetime, timezone, timedelta
from google import genai
from utils.github_issues import GitHubIssues, PIPELINE_STEPS
from utils.discord_notify import send_board
from utils.sheets_logger import _get_client, _PROJECT_ROOT, GSPREAD_AVAILABLE
from dotenv import load_dotenv
from loguru import logger
from utils.agent_config import name as _n

load_dotenv()

GEMINI_API_KEY       = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN         = os.getenv("GITHUB_TOKEN")
GITHUB_REPO          = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL  = os.getenv("DISCORD_WEBHOOK_URL")
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN")
THREADS_USER_ID      = os.getenv("THREADS_USER_ID")
SPREADSHEET_ID       = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/sheets_service_account.json")
GEMINI_MODEL         = "gemini-2.5-flash"
THREADS_API_BASE     = "https://graph.threads.net/v1.0"

SCRIPT_DIR          = os.path.dirname(os.path.abspath(__file__))
BUZZ_POSTS_PATH     = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "kb_sys_ref_v001.md")

# ── タイムアウト閾値（分） ─────────────────────────
TIMEOUT_MINUTES = {
    "hermione": 15,   # リサーチは15分以内に完了するはず
    "luna":     10,   # ライティングは10分以内
    "malfoy":   10,   # 校閲は10分以内
    "human":   120,   # 人間承認は2時間まで待つ
    "ron_post":  5,   # 投稿は5分以内
    "ron_fetch": 5,   # 計測は5分以内
}

# ── スコア閾値 ──────────────────────────────────────
QUALITY_PASS_SCORE = 50  # 50点以上で合格（マルフォイとの判定矛盾を防ぐため調整済み）


def load_buzz_voice() -> str:
    """kb_sys_ref_v001.md から「自分のアカウントの声」セクション全体を読み込む（### 子セクション含む）"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        # 「自分のアカウントの声」セクション開始位置を見つける
        start = content.find("## 🎤 自分のアカウントの声")
        if start < 0:
            return content[:1000]

        rest = content[start:]
        # 次の同レベル ## セクション（### は含める）を探して切り出す
        next_h2 = re.search(r"\n## [^#]", rest[1:])
        if next_h2:
            voice_section = rest[:next_h2.start() + 1]
        else:
            voice_section = rest

        logger.info(f"スネイプ声定義ロード: {len(voice_section)}文字")
        return voice_section[:2000]
    except FileNotFoundError:
        return "（声定義なし）"


def get_comments(gh: GitHubIssues, issue_number: int) -> list:
    return gh.get_comments(issue_number)


def extract_briefing(comments: list) -> str:
    """ハーマイオニーのブリーフィングを抽出"""
    for c in reversed(comments):
        if f"{_n('hermione')}より" in c.body and "ブリーフィング" in c.body:
            return c.body[:3000]
    return ""


def extract_luna_posts(comments: list) -> str:
    """ルーナの投稿案3案を抽出"""
    for c in reversed(comments):
        if f"{_n('luna')}より" in c.body and "投稿案3案" in c.body:
            return c.body[:4000]
    return ""


def extract_recommended_post(comments: list) -> str:
    """マルフォイが選んだ推奨投稿案を抽出"""
    for c in reversed(comments):
        if f"{_n('malfoy')}より：承認申請" in c.body:
            code_match = re.search(r"```\n([\s\S]*?)\n```", c.body)
            if code_match:
                return code_match.group(1).strip()
    return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 0. フォロワー数追跡
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def create_follower_chart() -> bool:
    """
    Google Sheetsの「フォロワー推移」シートに折れ線グラフを作成する。
    既にグラフがある場合はスキップ。
    """
    if not SPREADSHEET_ID or not GOOGLE_CREDENTIALS_PATH:
        return False
    creds_path = GOOGLE_CREDENTIALS_PATH
    if not os.path.isabs(creds_path):
        creds_path = os.path.join(_PROJECT_ROOT, creds_path)
    if not os.path.exists(creds_path):
        return False

    try:
        from googleapiclient.discovery import build
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        service = build("sheets", "v4", credentials=creds)

        # スプレッドシート情報を取得
        spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_id = None
        has_chart = False
        for sheet in spreadsheet.get("sheets", []):
            if sheet["properties"]["title"] == "フォロワー推移":
                sheet_id = sheet["properties"]["sheetId"]
                has_chart = len(sheet.get("charts", [])) > 0
                break

        if sheet_id is None or has_chart:
            if has_chart:
                logger.info("フォロワー推移グラフは既に存在します")
            return False

        # 折れ線グラフを作成
        chart_request = {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "📈 フォロワー数推移",
                        "basicChart": {
                            "chartType": "LINE",
                            "legendPosition": "BOTTOM_LEGEND",
                            "axis": [
                                {"position": "BOTTOM_AXIS", "title": "日付"},
                                {"position": "LEFT_AXIS",   "title": "フォロワー数"}
                            ],
                            "domains": [{
                                "domain": {
                                    "sourceRange": {
                                        "sources": [{
                                            "sheetId": sheet_id,
                                            "startRowIndex": 1,
                                            "endRowIndex": 1000,
                                            "startColumnIndex": 0,
                                            "endColumnIndex": 1,
                                        }]
                                    }
                                }
                            }],
                            "series": [{
                                "series": {
                                    "sourceRange": {
                                        "sources": [{
                                            "sheetId": sheet_id,
                                            "startRowIndex": 1,
                                            "endRowIndex": 1000,
                                            "startColumnIndex": 3,
                                            "endColumnIndex": 4,
                                        }]
                                    }
                                },
                                "targetAxis": "LEFT_AXIS",
                                "lineStyle": {"width": 2, "type": "SOLID"},
                            }],
                            "headerCount": 0,
                        }
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {
                                "sheetId": sheet_id,
                                "rowIndex": 1,
                                "columnIndex": 6,
                            },
                            "widthPixels": 600,
                            "heightPixels": 371,
                        }
                    }
                }
            }
        }

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [chart_request]}
        ).execute()
        logger.info("✅ フォロワー推移グラフを作成しました（Google Sheetsで確認できます）")
        return True

    except Exception as e:
        logger.warning(f"グラフ作成スキップ: {e}")
        return False


def fetch_follower_count() -> int | None:
    """Threads APIで現在のフォロワー数を取得する"""
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        logger.warning("THREADS_ACCESS_TOKEN / THREADS_USER_ID が未設定のためフォロワー数取得をスキップ")
        return None
    try:
        resp = requests.get(
            f"{THREADS_API_BASE}/{THREADS_USER_ID}",
            params={"fields": "followers_count", "access_token": THREADS_ACCESS_TOKEN},
            timeout=10,
        )
        resp.raise_for_status()
        count = resp.json().get("followers_count")
        logger.info(f"フォロワー数取得: {count}")
        return count
    except Exception as e:
        logger.warning(f"フォロワー数取得失敗: {e}")
        return None


def log_follower_count(count: int) -> bool:
    """フォロワー数をGoogle Sheetsの「フォロワー推移」シートに記録する"""
    if not GSPREAD_AVAILABLE or not SPREADSHEET_ID or not GOOGLE_CREDENTIALS_PATH:
        logger.warning("Sheets未設定のためフォロワー数記録をスキップ")
        return False

    creds_path = GOOGLE_CREDENTIALS_PATH
    if not os.path.isabs(creds_path):
        creds_path = os.path.join(_PROJECT_ROOT, creds_path)
    if not os.path.exists(creds_path):
        logger.warning(f"認証ファイルが見つかりません: {creds_path}")
        return False

    try:
        import gspread
        client = _get_client(creds_path)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        sheet_name = "フォロワー推移"
        try:
            sheet = spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=5)
            sheet.insert_row(["日付", "曜日", "時刻", "フォロワー数", "前日比"], index=1)
            logger.info(f"シート '{sheet_name}' を新規作成しました")

        # 前回のフォロワー数を取得して差分計算
        all_values = sheet.get_all_values()
        prev_count = None
        if len(all_values) >= 2:
            try:
                prev_count = int(all_values[-1][3])
            except (ValueError, IndexError):
                pass

        now = datetime.now()
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        diff = (count - prev_count) if prev_count is not None else 0
        diff_str = f"+{diff}" if diff >= 0 else str(diff)

        sheet.append_row([
            now.strftime("%Y-%m-%d"),
            weekdays[now.weekday()],
            now.strftime("%H:%M"),
            count,
            diff_str if prev_count is not None else "-",
        ])
        logger.info(f"フォロワー数を記録: {count} ({diff_str})")
        return True
    except Exception as e:
        logger.warning(f"フォロワー数記録失敗: {e}")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. パイプライン健全性監視
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def check_pipeline_health(issue, statuses: dict) -> list[dict]:
    """
    各ステップのタイムアウト・停滞を検出する。
    戻り値: [{"step": key, "problem": str, "action": str}, ...]
    """
    issues_found = []
    now = datetime.now()

    # Issue作成時刻を基準に経過時間を推定
    created_at = issue.created_at.replace(tzinfo=None) if issue.created_at else now

    for key, label, agent in PIPELINE_STEPS:
        s, ts = statuses.get(key, ("waiting", "-"))

        if s == "running":
            # running のまま止まっていないか
            # タイムスタンプが取れる場合はそこから、なければ作成時刻から推定
            elapsed = (now - created_at).seconds // 60
            threshold = TIMEOUT_MINUTES.get(key, 20)
            if elapsed > threshold + 30:  # バッファ30分
                issues_found.append({
                    "step": key,
                    "agent": agent,
                    "problem": f"{label}が{elapsed}分経っても完了していません（閾値: {threshold}分）",
                    "action": f"{agent}を再実行してください。Gemini APIのクォータ超過の可能性があります。",
                    "severity": "high",
                })

        elif s == "pending" and key == "human":
            # 承認待ちが2時間を超えた
            elapsed = (now - created_at).seconds // 60
            if elapsed > TIMEOUT_MINUTES["human"]:
                issues_found.append({
                    "step": key,
                    "agent": agent,
                    "problem": f"承認待ちが{elapsed}分を経過しています",
                    "action": "Discordに再通知します",
                    "severity": "medium",
                })

        elif s == "error":
            issues_found.append({
                "step": key,
                "agent": agent,
                "problem": f"{label}でエラーが発生しています",
                "action": "GitHub Issueのコメントを確認してください",
                "severity": "high",
            })

    return issues_found


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 3パスリフレクション品質チェック（スネイプの核心）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def three_pass_quality_check(
    post_text: str,
    briefing: str,
    buzz_voice: str,
    luna_posts: str,
) -> dict:
    """
    3回の深層思考でルーナの投稿案を徹底検証する。

    Pass 1: 批評官として全問題点を列挙（マルフォイより厳格に）
    Pass 2: 擁護官として反論・良点を列挙
    Pass 3: 統合官として両者を踏まえた最終判定と改善提案

    戻り値: {
        "score": int,          # 0-100
        "verdict": str,        # "pass" | "fail"
        "pass1": str,          # 批評
        "pass2": str,          # 擁護
        "pass3": str,          # 統合判定
        "revision_needed": bool,
        "revision_instruction": str,  # ルーナへの改善指示
        "risk_flags": list,    # 要注意リスト
    }
    """
    client = genai.Client(api_key=GEMINI_API_KEY)

    # ── PASS 1: 徹底批評 ──────────────────────────────
    prompt_p1 = f"""
あなたは投稿品質の「批評官スネイプ」です。感情なく、合理的に問題点を全て列挙してください。
妥協は一切しません。良い点には言及せず、悪い点だけを徹底的に洗い出してください。

【検証対象の投稿案】
{post_text}

【今日のブリーフィング（意図・テーマ）】
{briefing[:1500]}

【オーナーの声の定義（厳守事項）】
{buzz_voice[:1500]}

以下の観点で全問題点を箇条書きで列挙せよ（問題がなければ「なし」と記載）:

■ A. 文体・語尾の逸脱
（声定義で指定された語尾・口調が守られているか。NGワードはないか）

■ B. ブリーフィングとの整合性
（テーマ・感情フック・推奨角度と投稿内容が一致しているか）

■ C. バズ要素の欠落
（冒頭の引き力、ツリー誘導の仕掛け、数字の具体性、締めの行動喚起）

■ D. 情報リスク
（誤情報・誇張・根拠なき断言・法的リスク・Threads利用規約違反の可能性）

■ E. 構成上の問題
（読者が途中で離脱しそうな箇所、論理の飛躍、唐突な展開）

■ F. その他のリスク
（競合への言及・センシティブな内容・炎上可能性）

最後に: 最も致命的な問題を1つだけ選んで「最重要問題点:」として記載せよ。
"""
    logger.info("Snape 3パス検証: Pass 1（批評）実行中")
    pass1 = client.models.generate_content(model=GEMINI_MODEL, contents=prompt_p1).text

    # ── PASS 2: 擁護・反論 ────────────────────────────
    prompt_p2 = f"""
あなたは投稿品質の「擁護官」です。今度はこの投稿案の「良い点」を探し、Pass 1の批評に反論してください。

【検証対象の投稿案】
{post_text}

【Pass 1の批評結果】
{pass1[:2000]}

以下の観点で投稿案を擁護せよ:

■ A. 文体・語尾について
（批評が過剰に厳しい点はないか。声定義のキャラとして自然な表現はどれか）

■ B. ブリーフィングとの整合性について
（テーマの本質は伝わっているか。些細なズレを重大視しすぎていないか）

■ C. バズ要素について
（実際に機能している引きや仕掛けはどれか）

■ D. 情報リスクについて
（批評が過剰反応していないか。一般的な表現として許容範囲か）

■ E. この投稿案が持つ「強み」を3つ挙げよ

最後に: 「この投稿案が合格に値する理由を1文で」記載せよ。
"""
    logger.info("Snape 3パス検証: Pass 2（擁護）実行中")
    pass2 = client.models.generate_content(model=GEMINI_MODEL, contents=prompt_p2).text

    # ── PASS 3: 統合・最終判定 ────────────────────────
    prompt_p3 = f"""
あなたは「統合判定官スネイプ」です。批評と擁護の両方を公平に評価し、最終判定を下してください。

【検証対象の投稿案】
{post_text}

【Pass 1: 批評結果】
{pass1[:1500]}

【Pass 2: 擁護結果】
{pass2[:1500]}

【判定基準】
- 65点以上: 合格（投稿可）
- 50〜64点: 条件付き合格（軽微な修正で合格）
- 50点未満: 不合格（ルーナに再作成を指示）

以下のフォーマットで最終判定を出力せよ:

【3パス統合判定結果】

総合スコア: [0-100点]
判定: [合格 / 条件付き合格 / 不合格]

採択した批評点（重要なもの3つまで）:
1.
2.
3.

却下した批評点（過剰批判として棄却）:
1.

採択した強み:
1.
2.

必須修正点（条件付き合格・不合格の場合）:
-

{_n('luna')}への改善指示（不合格の場合のみ。具体的かつ簡潔に）:


{_n('snape')}の総評（1〜2文）:
"""
    logger.info("Snape 3パス検証: Pass 3（統合判定）実行中")
    pass3 = client.models.generate_content(model=GEMINI_MODEL, contents=prompt_p3).text

    # スコアと判定を解析
    score_match = re.search(r"総合スコア[：:]\s*(\d+)", pass3)
    score = int(score_match.group(1)) if score_match else 50

    verdict = "pass" if score >= QUALITY_PASS_SCORE else "fail"
    revision_needed = score < QUALITY_PASS_SCORE

    # ルーナへの改善指示を抽出
    revision_match = re.search(rf"{re.escape(_n('luna'))}への改善指示[（(]不合格.*?[)）].*?\n([\s\S]*?)(?=\n{re.escape(_n('snape'))}の総評|\Z)", pass3)
    revision_instruction = revision_match.group(1).strip() if revision_match else ""

    # リスクフラグ（致命的問題）を抽出
    risk_match = re.search(r"最重要問題点[:：]\s*(.+)", pass1)
    risk_flags = [risk_match.group(1).strip()] if risk_match else []

    return {
        "score": score,
        "verdict": verdict,
        "pass1": pass1,
        "pass2": pass2,
        "pass3": pass3,
        "revision_needed": revision_needed,
        "revision_instruction": revision_instruction,
        "risk_flags": risk_flags,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 整合性検証
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def check_consistency(post_text: str, briefing: str, luna_posts: str) -> dict:
    """ブリーフィング→投稿案の一貫性を検証する"""
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
{_n('hermione')}が「このテーマ・この角度で」と指示したブリーフィングに対して、
{_n('luna')}の投稿案が意図通りに応えているか検証してください。

【ブリーフィング（{_n('hermione')}の指示）】
{briefing[:1500]}

【採用投稿案】
{post_text}

以下を判定せよ:
1. テーマの一致度（1-10）: [スコア] / 理由:
2. 感情フックの一致度（1-10）: [スコア] / 理由:
3. 角度・切り口の一致度（1-10）: [スコア] / 理由:
4. 総合整合スコア（1-10）:

判定: [整合 / 部分整合 / 不整合]
コメント（1文）:
"""
    result = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text

    consistency_match = re.search(r"総合整合スコア.*?(\d+)", result)
    consistency_score = int(consistency_match.group(1)) if consistency_match else 5

    return {
        "score": consistency_score,
        "detail": result,
        "is_consistent": consistency_score >= 6,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. API エラー検知
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def detect_api_errors(comments: list) -> list[dict]:
    """コメント内のエラーパターンを検知する"""
    # 文脈付きパターン: 投稿IDなど正常値の数字列への誤検知を防止
    error_patterns = [
        (r"(?:status|error|Error|エラー).*429|429.*(?:status|error|Error|エラー)",
         "Gemini API レート制限超過",       "1分待って再実行。またはモデルをgemini-2.0-flash-liteに変更", False),
        (r"(?:status|error|Error|エラー).*403|403.*(?:status|error|Error|エラー)",
         "YouTube/Threads API 権限エラー",  "APIキーのスコープ・有効化状態を確認",                       True),
        (r"(?:status|error|Error|エラー).*(?:401|190)|(?:401|190).*(?:status|error|Error|エラー)",
         "Threads トークン期限切れ",        "scripts/refresh_threads_token.py を実行してトークンを更新", True),
        (r"(?:status|error|Error|エラー).*(?:500|502|503)|(?:500|502|503).*(?:status|error|Error|エラー)",
         "外部APIサーバーエラー",           "10分後に再試行（自動復旧することが多い）",                  False),
        (r"ModuleNotFoundError",
         "Pythonモジュール未インストール",  "pip install -r scripts/requirements.txt を実行",            True),
        (r"FileNotFoundError",
         "必要なファイルが見つからない",    "kb_sys_ref_v001.mdまたは設定ファイルの存在を確認",          True),
    ]

    # 正常コメントはエラー検索対象から除外（投稿IDに403等が含まれる誤検知を防止）
    SKIP_KEYWORDS = ["投稿完了", "承認申請", "リサーチ＆分析完了", "投稿案"]

    found_errors = []
    for comment in comments:
        body = comment.body or ""
        if any(kw in body for kw in SKIP_KEYWORDS):
            continue
        for pattern, name, solution, critical in error_patterns:
            if re.search(pattern, body, re.IGNORECASE):
                found_errors.append({
                    "error": name,
                    "solution": solution,
                    "critical": critical,
                    "comment_id": comment.id,
                })
    return found_errors


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 先読みリスク分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def analyze_proactive_risks(post_text: str, briefing: str) -> list[dict]:
    """
    まだ顕在化していないが、将来問題になりそうなリスクを先読みして検出する。
    例: トレンドとのズレ、競合投稿との類似、季節性の考慮漏れ 等
    """
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
以下の投稿案について、「今は問題ないが将来リスクになる可能性がある点」を先読みしてください。

【投稿案】
{post_text}

【今日のブリーフィング】
{briefing[:800]}

先読みリスクを以下の観点で検討せよ（各観点で0〜2件、なければ「なし」）:

1. 情報の鮮度リスク（この情報はすぐに陳腐化しないか）
2. 表現の永続的安全性（将来的に問題になりうる表現はないか）
3. トレンドとのズレ（このトピックは今後1週間以内に話題になりそうか）
4. フォロワー期待値管理（このキャラクターとして投稿し続けた場合の一貫性）
5. 競合リスク（同じ内容を他のアカウントが先に投稿している可能性）

フォーマット:
リスク名: [リスクの名前]
詳細: [1文の説明]
推奨対処: [具体的なアクション]
---
（リスクがなければ「先読みリスク: なし」と出力）
"""
    result = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text

    risks = []
    for block in result.split("---"):
        risk_match    = re.search(r"リスク名[:：]\s*(.+)", block)
        detail_match  = re.search(r"詳細[:：]\s*(.+)", block)
        action_match  = re.search(r"推奨対処[:：]\s*(.+)", block)
        if risk_match and "なし" not in risk_match.group(1):
            risks.append({
                "risk":   risk_match.group(1).strip(),
                "detail": detail_match.group(1).strip() if detail_match else "",
                "action": action_match.group(1).strip() if action_match else "",
            })
    return risks


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["health", "quality", "full"], default="full",
                        help="health: 健全性チェックのみ / quality: 品質チェックのみ / full: 全チェック")
    args = parser.parse_args()

    logger.info("=== スネイプ 日次監視開始 ===")

    # 月次認証チェック
    try:
        from utils.auth_check import check_auth
    except ImportError:
        from auth_check import check_auth
    is_valid, auth_msg = check_auth()
    if not is_valid:
        logger.error(f"認証エラー: {auth_msg}")
        sys.exit(1)
    logger.info(auth_msg)

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()
    today = datetime.now().strftime("%Y-%m-%d")

    # 現在のステータスを取得
    from utils.github_issues import _parse_pipeline_statuses
    statuses = _parse_pipeline_statuses(issue.body or "")
    comments = get_comments(gh, issue.number)

    report_sections = []
    action_required    = False
    has_critical_issue = False

    # ── 0. フォロワー数追跡 ────────────────────────────
    follower_count = fetch_follower_count()
    if follower_count is not None:
        log_follower_count(follower_count)
        create_follower_chart()   # グラフがまだなければ自動作成
        report_sections.append(
            f"### 👥 フォロワー数\n\n**現在: {follower_count:,}人**\n"
            f"（Google Sheets「フォロワー推移」シートに記録済み）\n"
        )

    # ── 1. パイプライン健全性チェック ─────────────────
    if args.mode in ("health", "full"):
        logger.info("健全性チェック実行中...")
        health_issues = check_pipeline_health(issue, statuses)
        api_errors    = detect_api_errors(comments)

        critical_api_errors = [e for e in api_errors if e.get("critical")]
        minor_api_errors    = [e for e in api_errors if not e.get("critical")]

        if health_issues or api_errors:
            action_required = True
            if critical_api_errors:
                has_critical_issue = True
            section = "### ⚠️ 健全性チェック結果\n\n"
            for issue_item in health_issues:
                sev = "🔴" if issue_item["severity"] == "high" else "🟡"
                section += f"{sev} **{issue_item['agent']}**: {issue_item['problem']}\n"
                section += f"   → 対処: {issue_item['action']}\n\n"
            for err in critical_api_errors:
                section += f"🔴 **重大APIエラー**: {err['error']}\n"
                section += f"   → 対処: {err['solution']}\n\n"
            for err in minor_api_errors:
                section += f"🟡 **一時エラー（自動復旧）**: {err['error']}\n"
                section += f"   → 対処: {err['solution']}\n\n"
        else:
            section = "### ✅ 健全性チェック: 異常なし\n\n"
        report_sections.append(section)

    # ── 2. 品質チェック（投稿案が存在する場合のみ）──────
    if args.mode in ("quality", "full"):
        # ── ガード①: 品質チェック済みスキップ ──────────────
        # 同じIssueに既に「3パス品質チェック結果」コメントがあれば再実行しない
        already_checked = any("3パス品質チェック結果" in c.body for c in comments)
        if already_checked:
            logger.info("品質チェック済みのIssueです。スキップします。")
        else:
            post_text = extract_recommended_post(comments)
            briefing  = extract_briefing(comments)
            luna_posts = extract_luna_posts(comments)

        if not already_checked and post_text:
            # ── ガード②: 承認済みステータス確認 ──────────────
            # マルフォイ承認申請済み / 人間承認済み / ロン投稿済みの場合、差し戻し処理はスキップ
            human_status   = statuses.get("human", ("waiting", "-"))[0]
            ron_status     = statuses.get("ron_post", ("waiting", "-"))[0]
            malfoy_approved = any(f"{_n('malfoy')}より：承認申請" in c.body for c in comments)
            skip_revision  = malfoy_approved or human_status == "done" or ron_status == "done"

            logger.info("3パスリフレクション品質チェック実行中...")
            buzz_voice = load_buzz_voice()

            quality = three_pass_quality_check(post_text, briefing, buzz_voice, luna_posts)

            verdict_icon = "✅" if quality["verdict"] == "pass" else "❌"
            section = f"""### {verdict_icon} 3パス品質チェック結果

**総合スコア: {quality['score']}点 / 100点**（合格ライン: {QUALITY_PASS_SCORE}点）
**判定: {'合格' if quality['verdict'] == 'pass' else f'不合格 → {_n("luna")}に再作成を指示'}**

<details>
<summary>Pass 1: 批評（クリックで展開）</summary>

{quality['pass1']}
</details>

<details>
<summary>Pass 2: 擁護・反論（クリックで展開）</summary>

{quality['pass2']}
</details>

**Pass 3: 統合判定**
{quality['pass3']}
"""
            if quality["risk_flags"]:
                section += f"\n**⚠️ 最重要リスク:** {', '.join(quality['risk_flags'])}\n"

            if quality["revision_needed"]:
                if skip_revision:
                    # ── ガード③: 差し戻しスキップ時のログ ────────
                    logger.info(
                        f"スコアは{quality['score']}点ですが、承認済みのため差し戻しはスキップしました"
                        f"（human={human_status}, ron_post={ron_status}）"
                    )
                    section += (
                        f"\n**ℹ️ スコア{quality['score']}点（基準{QUALITY_PASS_SCORE}点未満）ですが、"
                        f"承認済みのため差し戻しはスキップしました。**\n"
                    )
                else:
                    action_required = True
                    section += f"\n**{_n('luna')}への改善指示:**\n{quality['revision_instruction']}\n"
                    # ルーナに差し戻しコメントを追加
                    gh.add_comment(issue.number, f"""## 🔦 {_n('snape')}より：品質チェック差し戻し

3パスリフレクションの結果、品質基準（{QUALITY_PASS_SCORE}点）を満たしませんでした。

**スコア: {quality['score']}点**

**{_n('luna')}への改善指示:**
{quality['revision_instruction']}

---
*{_n('luna')}、上記指示に従って投稿案を修正してください。*
""")
                    gh.update_pipeline_status(issue.number, "luna", "running")
            report_sections.append(section)

            # 整合性チェック
            if briefing:
                logger.info("整合性チェック実行中...")
                consistency = check_consistency(post_text, briefing, luna_posts)
                cons_icon   = "✅" if consistency["is_consistent"] else "⚠️"
                section = f"""### {cons_icon} ブリーフィング整合性チェック

**整合スコア: {consistency['score']}/10**

{consistency['detail'][:500]}
"""
                report_sections.append(section)

            # 先読みリスク分析
            if args.mode == "full":
                logger.info("先読みリスク分析中...")
                proactive_risks = analyze_proactive_risks(post_text, briefing)
                if proactive_risks:
                    section = "### 🔮 先読みリスク分析\n\n"
                    for r in proactive_risks:
                        section += f"- **{r['risk']}**: {r['detail']}\n  → 推奨対処: {r['action']}\n"
                    report_sections.append(section)
        elif not already_checked:
            logger.info("投稿案がまだありません。品質チェックをスキップします。")

    # ── スネイプ監視レポートを Issue にコメント ─────────
    if report_sections:
        report_body = f"""## 🔦 {_n('snape')}より：日次監視レポート

**監視日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**モード:** {args.mode}
{'**⚠️ アクションが必要です**' if action_required else '**✅ 問題なし**'}

---

{''.join(report_sections)}

---
*{_n('snape')}より: 何事も最初から完璧ではない。問題は早期発見してこそ意味がある。*
"""
        gh.add_comment(issue.number, report_body)
        logger.info("監視レポートをGitHub Issueに追加しました")

        # Discord にも送信（重大エラーのみ：403権限エラー・401トークン期限切れ・ModuleNotFound・FileNotFound）
        if DISCORD_WEBHOOK_URL and has_critical_issue:
            import requests
            requests.post(DISCORD_WEBHOOK_URL, json={
                "embeds": [{
                    "title": "🔦 スネイプ監視レポート 🔴 重大エラー検知",
                    "description": f"[Issue #{issue.number} を確認]({issue.html_url})",
                    "color": 0xF04747,
                    "fields": [
                        {"name": "検出された問題", "value": "\n".join(
                            s[:100] for s in report_sections[:3]
                        )[:1000], "inline": False}
                    ]
                }]
            })

    logger.info("=== スネイプ 日次監視完了 ===")


if __name__ == "__main__":
    main()
