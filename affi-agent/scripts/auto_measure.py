"""
ron_auto_measure.py
投稿・計測担当: 前日の全投稿エンゲージメントを自動計測するスクリプト

毎日22:00 JST に auto-measure.yml から自動実行される。
前日のIssueから投稿IDを取得し、Threads APIで計測 → Google Sheets更新 → Issue記録。

■ パフォーマンス判定基準:
  🔥 大バズ:  いいね30以上 OR 閲覧3000以上 OR (ER5%以上 かつ 閲覧500以上)
  ✅ 好調:    ER3%以上 OR いいね15以上 OR 閲覧1000以上
  📝 普通:    ER1〜3%
  ⚠️ 要改善:  ER1%未満 OR 閲覧800未満

■ ナレッジ保管条件（buzz_posts.md に自動追記）:
  - いいね30以上
  - 閲覧3000以上
  - フォロワーが前日比+10以上増えた日の全投稿（成長に貢献した投稿）
"""


# ========== AFFI 認証チェック（編集禁止・自動挿入） ==========
import sys as _affi_sys
from pathlib import Path as _affi_Path
_affi_sys.path.insert(0, str(_affi_Path(__file__).resolve().parent))
try:
    from utils.auth_check import check_auth as _affi_check_auth
    _affi_ok, _affi_msg = _affi_check_auth()
    if not _affi_ok:
        print(f"⛔ {_affi_msg}")
        _affi_sys.exit(1)
except ImportError:
    print("⛔ auth_check モジュールが見つかりません。配布物が破損している可能性があります。")
    _affi_sys.exit(1)
# ========== END 認証チェック ==========
import os
import re
import sys
import argparse
import requests
from datetime import datetime, timedelta, timezone
from utils.github_issues import GitHubIssues
from utils.sheets_logger import update_engagement
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

THREADS_ACCESS_TOKEN    = os.getenv("THREADS_ACCESS_TOKEN")
THREADS_USER_ID         = os.getenv("THREADS_USER_ID")
GITHUB_TOKEN            = os.getenv("GITHUB_TOKEN")
GITHUB_REPO             = os.getenv("GITHUB_REPO")
SPREADSHEET_ID          = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/sheets_service_account.json")
THREADS_API_BASE        = "https://graph.threads.net/v1.0"

JST = timezone(timedelta(hours=9))

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
BUZZ_POSTS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "buzz_posts.md")

# ── パフォーマンス判定閾値 ──
BUZZ_LIKES_THRESHOLD     = 30    # いいね数バズ閾値（伸びている）
BUZZ_VIEWS_THRESHOLD     = 3000  # 閲覧数バズ閾値（伸びている）
HIGH_ER_THRESHOLD        = 3.0   # ER%「好調」以上
GREAT_ER_THRESHOLD       = 5.0   # ER%「大バズ」
LOW_ER_THRESHOLD         = 1.0   # ER%「要改善」
MIN_VIEWS_FOR_ER_BUZZ    = 500   # ER基準大バズの最低閲覧数
GOOD_VIEWS_THRESHOLD     = 1000  # 閲覧数「好調」
LOW_VIEWS_THRESHOLD      = 800   # 閲覧数「要改善」
FOLLOWER_GROWTH_THRESHOLD = 10   # フォロワー増加「成長日」閾値

# ── note展開候補の閾値 ──
NOTE_CANDIDATE_VIEWS     = 1000  # 閲覧数がこれ以上ならnote候補
NOTE_CANDIDATE_LIKES     = 10   # いいね数がこれ以上ならnote候補
NOTE_DRAFTS_DIR = os.path.join(SCRIPT_DIR, "..", "operation", "note_drafts")


def fetch_post_insights(post_id: str, max_retries: int = 2) -> dict:
    """
    Threads APIで投稿のインサイトを取得する。
    400エラー（投稿削除/権限なし）の場合はリトライ後、全投稿一覧から
    代替取得を試みる。それでもダメなら空dictを返す。
    """
    import time

    url = f"{THREADS_API_BASE}/{post_id}/insights"
    params = {
        "metric": "likes,replies,reposts,quotes,views",
        "access_token": THREADS_ACCESS_TOKEN,
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                insights = {}
                for item in data.get("data", []):
                    metric_name = item.get("name")
                    values = item.get("values", [])
                    if values:
                        insights[metric_name] = values[0].get("value", 0)
                    else:
                        insights[metric_name] = item.get("total_value", {}).get("value", 0)
                return insights

            if resp.status_code == 400:
                error_msg = resp.json().get("error", {}).get("message", "")
                if "does not exist" in error_msg:
                    logger.warning(
                        f"Post {post_id}: 投稿が存在しない/権限なし（削除済み or ツリー返信）"
                        f"{'、リトライ中...' if attempt < max_retries else ''}"
                    )
                    if attempt < max_retries:
                        time.sleep(3)
                        continue
                    # 最終手段: ユーザーの全投稿一覧から該当IDを探す
                    return _fallback_fetch_from_user_posts(post_id)
                else:
                    logger.error(f"Post {post_id}: 400エラー: {error_msg}")
                    return {}

            resp.raise_for_status()

        except requests.exceptions.RequestException as e:
            logger.error(f"インサイト取得失敗 (post_id={post_id}, attempt {attempt}): {e}")
            if attempt < max_retries:
                time.sleep(3)
                continue

    return {}


def _fallback_fetch_from_user_posts(target_post_id: str) -> dict:
    """
    ユーザーの投稿一覧APIから特定post_idのインサイトを取得するフォールバック。
    insights が非対応の投稿（ツリー返信等）でも、一覧APIから基本情報を取れる場合がある。
    """
    if not THREADS_USER_ID:
        return {}

    try:
        # ユーザーの最新投稿一覧を取得
        resp = requests.get(
            f"{THREADS_API_BASE}/{THREADS_USER_ID}/threads",
            params={
                "fields": "id",
                "limit": 50,
                "access_token": THREADS_ACCESS_TOKEN,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return {}

        posts = resp.json().get("data", [])
        if not any(p.get("id") == target_post_id for p in posts):
            logger.info(f"Post {target_post_id}: ユーザー投稿一覧に見つからず（削除済みの可能性）")
            return {}

        # 一覧に存在する → insights を再取得
        resp2 = requests.get(
            f"{THREADS_API_BASE}/{target_post_id}/insights",
            params={
                "metric": "likes,replies,reposts,quotes,views",
                "access_token": THREADS_ACCESS_TOKEN,
            },
            timeout=15,
        )
        if resp2.status_code == 200:
            data = resp2.json()
            insights = {}
            for item in data.get("data", []):
                metric_name = item.get("name")
                values = item.get("values", [])
                if values:
                    insights[metric_name] = values[0].get("value", 0)
                else:
                    insights[metric_name] = item.get("total_value", {}).get("value", 0)
            if insights:
                logger.info(f"Post {target_post_id}: フォールバック取得成功 {insights}")
                return insights

        logger.info(f"Post {target_post_id}: 投稿は存在するがインサイト取得不可（ツリー返信の可能性）")
        return {}

    except Exception as e:
        logger.warning(f"フォールバック取得失敗: {e}")
        return {}


def fetch_follower_count() -> int | None:
    """現在のフォロワー数を取得する"""
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        return None
    try:
        resp = requests.get(
            f"{THREADS_API_BASE}/{THREADS_USER_ID}",
            params={"fields": "followers_count", "access_token": THREADS_ACCESS_TOKEN},
            timeout=15,
        )
        return resp.json().get("followers_count")
    except Exception:
        return None


def get_yesterday_follower_count() -> int | None:
    """Google Sheetsのフォロワー推移シートから前日のフォロワー数を取得する"""
    if not SPREADSHEET_ID or not GOOGLE_CREDENTIALS_PATH:
        return None
    try:
        from utils.sheets_logger import _get_client, _PROJECT_ROOT
        creds_path = GOOGLE_CREDENTIALS_PATH
        if not os.path.isabs(creds_path):
            creds_path = os.path.join(_PROJECT_ROOT, creds_path)
        if not os.path.exists(creds_path):
            return None
        client = _get_client(creds_path)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet("フォロワー推移")
        all_values = sheet.get_all_values()
        if len(all_values) >= 2:
            return int(all_values[-1][3])  # 最新行のフォロワー数
    except Exception:
        pass
    return None


def judge_performance(likes: int, views: int, er: float) -> tuple[str, str]:
    """
    パフォーマンスを判定する。
    Returns: (label, reason)
    """
    # 🔥 大バズ: いいね30+ / 閲覧3000+ / 高ER×高閲覧
    if likes >= BUZZ_LIKES_THRESHOLD:
        return "🔥 大バズ", f"いいね{likes}件突破"
    if views >= BUZZ_VIEWS_THRESHOLD:
        return "🔥 大バズ", f"閲覧{views}件突破"
    if er >= GREAT_ER_THRESHOLD and views >= MIN_VIEWS_FOR_ER_BUZZ:
        return "🔥 大バズ", f"ER{er}%×閲覧{views}"
    # ✅ 好調: ER3%+ / いいね15+ / 閲覧1000+
    if er >= HIGH_ER_THRESHOLD:
        return "✅ 好調", f"ER{er}%"
    if likes >= 15:
        return "✅ 好調", f"いいね{likes}件"
    if views >= GOOD_VIEWS_THRESHOLD:
        return "✅ 好調", f"閲覧{views}件"
    # ⚠️ 要改善
    if views < LOW_VIEWS_THRESHOLD:
        return "⚠️ 要改善", f"閲覧{views}件（リーチ不足）"
    if er < LOW_ER_THRESHOLD:
        return "⚠️ 要改善", f"ER{er}%（刺さり不足）"
    return "📝 普通", f"ER{er}%"


def should_save_as_knowledge(likes: int, views: int, er: float, is_follower_growth_day: bool) -> tuple[bool, str]:
    """
    ナレッジ（buzz_posts.md）に保管すべきかを判定する。
    Returns: (should_save, reason)
    """
    reasons = []
    if likes >= BUZZ_LIKES_THRESHOLD:
        reasons.append(f"いいね{likes}件バズ")
    if views >= BUZZ_VIEWS_THRESHOLD:
        reasons.append(f"閲覧{views}件バズ")
    if is_follower_growth_day:
        reasons.append("フォロワー成長日")
    if reasons:
        return True, " / ".join(reasons)
    return False, ""


def find_target_issue(gh: GitHubIssues, target_date: str):
    """指定日のdaily-operation Issueを検索する"""
    title_prefix = f"【運用ループ】{target_date}"
    for state in ["open", "closed"]:
        issues = gh.repo.get_issues(state=state, labels=["daily-operation"], sort="created", direction="desc")
        for issue in issues:
            if issue.title.startswith(title_prefix):
                return issue
    return None


def extract_post_ids(issue, gh: GitHubIssues) -> list:
    """
    投稿完了コメントから (post_id, slot_num, post_text) を抽出する。
    同一スロットに複数の投稿完了がある場合は最新のもの（最後のコメント）を採用。
    """
    comments = gh.get_comments(issue.number)
    slot_map = {}  # slot_num -> (post_id, slot_num, post_text) 最新で上書き

    for comment in comments:
        body = comment.body
        if "投稿・計測より" not in body or "投稿完了" not in body:
            continue

        m = re.search(r'\*\*(?:1投稿目ID|投稿ID):\*\*\s*`(\d+)`', body)
        if not m:
            continue
        post_id = m.group(1)

        if "18時" in body or "SLOT_2" in body:
            slot = 2
        elif "21時" in body or "SLOT_3" in body:
            slot = 3
        else:
            slot = 1

        # 投稿テキストも抽出
        text_match = re.search(r'```\n([\s\S]*?)\n```', body)
        post_text = text_match.group(1) if text_match else ""

        # 同一スロットは最新で上書き（コメントは時系列順なので最後が最新）
        if slot in slot_map:
            old_id = slot_map[slot][0]
            logger.info(f"SLOT_{slot}: 重複検出。{old_id} → {post_id} に更新")
        slot_map[slot] = (post_id, slot, post_text)

    results = [slot_map[s] for s in sorted(slot_map.keys())]
    logger.info(f"抽出結果: {len(results)}件（重複排除済み）: "
                f"{', '.join(f'SLOT_{r[1]}={r[0]}' for r in results)}")
    return results


def save_knowledge(post_text: str, likes: int, views: int, er: float,
                   date_str: str, slot_label: str, reason: str, follower_diff: int | None):
    """成果投稿をbuzz_posts.mdにナレッジとして追記する"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        existing_posts = content.count("| No.")
        new_no = existing_posts

        follower_str = f" / F{'+' if follower_diff and follower_diff > 0 else ''}{follower_diff}" if follower_diff is not None else ""
        tag = reason
        new_row = (
            f"| {new_no:03d} | {date_str} | {likes} | {views} | "
            f"ER{er}% | {slot_label} | {tag}{follower_str} | {post_text[:30]}... |"
        )

        if "| --- |" in content:
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("| --- |"):
                    lines.insert(i + existing_posts + 1, new_row)
                    break
            updated_content = "\n".join(lines)
        else:
            updated_content = content + f"\n{new_row}"

        with open(BUZZ_POSTS_PATH, "w", encoding="utf-8") as f:
            f.write(updated_content)

        logger.info(f"📚 ナレッジ保管: {slot_label} ({reason}) → buzz_posts.md")
    except FileNotFoundError:
        logger.warning(f"{BUZZ_POSTS_PATH} が見つかりません")


def is_note_candidate(likes: int, views: int) -> bool:
    """投稿がnote記事への展開候補かどうかを判定する"""
    return views >= NOTE_CANDIDATE_VIEWS or likes >= NOTE_CANDIDATE_LIKES


def generate_note_outline(post_text: str, likes: int, views: int, er: float,
                          date_str: str, slot_label: str) -> str:
    """
    伸びた投稿からnote記事の骨子（アウトライン）を自動生成する。
    Gemini APIで生成。API未設定なら簡易テンプレートで代替。
    """
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    prompt = f"""以下のThreads投稿が大きく伸びました。この投稿テーマを深掘りした
note記事の骨子（アウトライン）を作成してください。

【元の投稿テキスト】
{post_text}

【実績データ】
- 日付: {date_str} / {slot_label}
- 閲覧数: {views:,}
- いいね: {likes}
- エンゲージメント率: {er}%

【重要ルール】
- 著者「出木杉」の一人称視点で、実体験として語る構成にする
- note記事は「体験記・思考録」として書く。HOW TO（具体的な手順解説）は絶対に書かない
- テンプレートの中身・実装手順・コード・設定方法は一切含めない
- 読者がこの記事だけで100%満足できる、完結した内容にする
- 「続きはコミュニティで」「詳しくはこちら」のような外部誘導は入れない
- 想定文字数: 3,000〜5,000字

【出力ルール】
- 各章の「書くべき内容の要点」には、読者が読む本文の方向性だけを書く
- 「〜は書かない」「〜に注意」等のメタ指示・制作ノートは含めない
- 設定方法・インストール手順・コード例は章の要点にも含めない

【出力フォーマット】
タイトル案: （3案）
想定読者: （1文）
感情の流れ: （読者が記事を通じて感じる感情の変化）

■ 導入（400字）
- 書くべき内容の要点

■ 第1章「（章タイトル）」（800字）
- 書くべき内容の要点

■ 第2章「（章タイトル）」（800字）
- 書くべき内容の要点

■ 第3章「（章タイトル）」（800字）
- 書くべき内容の要点（実績データ: 閲覧{views:,}等をここで活用）

■ 結び（400字）
- 書くべき内容の要点（読後感「面白かった・やってみたい」で終わる）
"""

    if GEMINI_API_KEY:
        try:
            from utils.gemini_client import call_gemini
            outline = call_gemini(prompt, GEMINI_API_KEY)
            return outline
        except Exception as e:
            logger.warning(f"Geminiでのnote骨子生成に失敗: {e}")

    # フォールバック: 簡易テンプレート
    return f"""# note記事候補 — 骨子（自動生成）

## 元投稿（{date_str} {slot_label}）
{post_text}

## 実績
- 閲覧: {views:,} / いいね: {likes} / ER: {er}%

## タイトル案
1. （要検討）
2. （要検討）
3. （要検討）

## 構成案
- 導入: この投稿のテーマに至った背景・きっかけ
- 第1章: 投稿で触れた課題の深掘り
- 第2章: 自分の体験・試行錯誤
- 第3章: 結果と気づき（実績データを活用）
- 結び: 読後感「面白かった」で終わる
"""


def save_note_draft(outline: str, date_str: str, slot_label: str) -> str:
    """note骨子をファイルに保存する。保存パスを返す。"""
    os.makedirs(NOTE_DRAFTS_DIR, exist_ok=True)
    safe_slot = slot_label.replace("（", "_").replace("）", "").replace(" ", "")
    filename = f"note_draft_{date_str}_{safe_slot}.md"
    filepath = os.path.join(NOTE_DRAFTS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(outline)

    logger.info(f"📝 note骨子を保存: {filename}")
    return filepath


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", default="",
                        help="計測対象日（YYYY-MM-DD、空白=昨日）")
    args = parser.parse_args()

    if args.target_date:
        target_date = args.target_date
    else:
        target_date = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"=== 投稿・計測 自動計測開始 (対象日: {target_date}) ===")

    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)

    # 対象日のIssueを検索
    issue = find_target_issue(gh, target_date)
    if not issue:
        logger.info(f"{target_date} の運用Issueが見つかりません。計測をスキップします。")
        sys.exit(0)

    logger.info(f"対象Issue: #{issue.number} - {issue.title}")

    # 投稿IDを抽出
    post_entries = extract_post_ids(issue, gh)
    if not post_entries:
        logger.info("投稿完了コメントが見つかりません。計測をスキップします。")
        sys.exit(0)

    logger.info(f"計測対象: {len(post_entries)}件の投稿")

    # ── フォロワー増減を計算 ──
    prev_followers = get_yesterday_follower_count()
    current_followers = fetch_follower_count()
    follower_diff = None
    is_follower_growth_day = False
    if prev_followers is not None and current_followers is not None:
        follower_diff = current_followers - prev_followers
        is_follower_growth_day = follower_diff >= FOLLOWER_GROWTH_THRESHOLD
        logger.info(f"フォロワー: {prev_followers} → {current_followers} (差分: {follower_diff:+d})")

    # ── 各投稿を計測 ──
    slot_labels = {1: "SLOT_1（7時）", 2: "SLOT_2（18時）", 3: "SLOT_3（21時）"}
    results = []

    for post_id, slot_num, post_text in post_entries:
        label = slot_labels.get(slot_num, f"SLOT_{slot_num}")
        logger.info(f"計測中: {label} / Post ID: {post_id}")
        insights = fetch_post_insights(post_id)
        if not insights:
            logger.warning(f"Post ID {post_id} のインサイト取得に失敗")
            results.append((post_id, slot_num, post_text, None))
            continue

        likes   = insights.get("likes", 0)
        replies = insights.get("replies", 0)
        reposts = insights.get("reposts", 0)
        quotes  = insights.get("quotes", 0)
        views   = insights.get("views", 0)

        # Google Sheetsを更新
        update_engagement(
            SPREADSHEET_ID, GOOGLE_CREDENTIALS_PATH,
            post_id=post_id,
            likes=likes, replies=replies, reposts=reposts, views=views,
        )

        # フック/フォーマット分類をSheetsの「使用感情フック」列に書き込み
        from utils.post_classifier import classify_hook_type, classify_format_type
        if post_text:
            hook_cls = classify_hook_type(post_text[:150])
            fmt_cls = classify_format_type(post_text[:200])
            try:
                from utils.sheets_logger import _get_client, _PROJECT_ROOT, HEADERS
                creds = GOOGLE_CREDENTIALS_PATH
                if not os.path.isabs(creds):
                    creds = os.path.join(_PROJECT_ROOT, creds)
                if os.path.exists(creds) and SPREADSHEET_ID:
                    client = _get_client(creds)
                    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("投稿ログ")
                    pid_col = HEADERS.index("投稿ID") + 1
                    cell = sheet.find(str(post_id), in_column=pid_col)
                    if cell:
                        hook_col = HEADERS.index("使用感情フック") + 1
                        sheet.update_cell(cell.row, hook_col, f"{hook_cls}/{fmt_cls}")
            except Exception as e:
                logger.warning(f"フック分類書き込みスキップ: {e}")

        results.append((post_id, slot_num, post_text, {
            "likes": likes, "replies": replies, "reposts": reposts,
            "quotes": quotes, "views": views,
        }))

    # ── ベストER投稿を特定 + フォロワー貢献度を按分 ──
    best_er_idx = -1
    best_er_val = -1
    total_engagement = 0  # 全投稿のエンゲージメント合計（按分の分母）
    for i, (_, _, _, data) in enumerate(results):
        if data is None:
            continue
        er = data["likes"] / data["views"] * 100 if data["views"] > 0 else 0
        if er > best_er_val:
            best_er_val = er
            best_er_idx = i
        # フォロワー按分用: いいね + リポスト + 返信（エンゲージ数）
        total_engagement += data["likes"] + data["reposts"] + data["replies"]

    # 各投稿の推定フォロワー貢献度を計算
    follower_contributions = {}
    if follower_diff is not None and follower_diff > 0 and total_engagement > 0:
        for i, (post_id, _, _, data) in enumerate(results):
            if data is None:
                continue
            post_eng = data["likes"] + data["reposts"] + data["replies"]
            ratio = post_eng / total_engagement
            estimated = round(follower_diff * ratio, 1)
            follower_contributions[post_id] = {
                "estimated": estimated,
                "ratio_pct": round(ratio * 100, 1),
            }

    # ── ナレッジ保管判定 + レポート生成 ──
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    report_lines = [
        f"## 📊 投稿・計測より：エンゲージメント自動計測結果\n",
        f"**計測日時:** {now}",
        f"**対象日:** {target_date}",
    ]
    if follower_diff is not None:
        growth_icon = "📈" if follower_diff > 0 else ("📉" if follower_diff < 0 else "➡️")
        report_lines.append(
            f"**フォロワー推移:** {prev_followers} → {current_followers} "
            f"(**{follower_diff:+d}人**) {growth_icon}"
            f"{' 🎉 成長日！' if is_follower_growth_day else ''}"
        )
    report_lines.append("")

    total_likes = 0
    total_views = 0
    knowledge_saved = []

    for i, (post_id, slot_num, post_text, data) in enumerate(results):
        label = slot_labels.get(slot_num, f"SLOT_{slot_num}")
        if data is None:
            report_lines.append(f"### {label}\n⚠️ 計測失敗 (Post ID: `{post_id}`)\n")
            continue

        likes = data["likes"]
        views = data["views"]
        er = round(likes / views * 100, 2) if views > 0 else 0

        total_likes += likes
        total_views += views

        # パフォーマンス判定
        perf_label, perf_reason = judge_performance(likes, views, er)

        # ナレッジ保管判定
        should_save, save_reason = should_save_as_knowledge(
            likes, views, er, is_follower_growth_day
        )
        if should_save and post_text:
            save_knowledge(post_text, likes, views, er, target_date, label, save_reason, follower_diff)
            knowledge_saved.append((label, save_reason))

        report_lines.append(f"### {label} {perf_label}")
        report_lines.append(f"| 指標 | 数値 |")
        report_lines.append(f"|---|---|")
        report_lines.append(f"| いいね | **{likes}** |")
        report_lines.append(f"| 返信 | {data['replies']} |")
        report_lines.append(f"| リポスト | {data['reposts']} |")
        report_lines.append(f"| 引用 | {data['quotes']} |")
        report_lines.append(f"| 閲覧数 | **{views}** |")
        report_lines.append(f"| エンゲージメント率 | **{er}%** |")
        report_lines.append(f"| 判定 | {perf_label}（{perf_reason}） |")
        # フック/フォーマット分類
        if post_text:
            from utils.post_classifier import classify_hook_type as _ch, classify_format_type as _cf
            report_lines.append(f"| 感情フック | {_ch(post_text[:150])} |")
            report_lines.append(f"| フォーマット | {_cf(post_text[:200])} |")
        # フォロワー貢献度
        fc = follower_contributions.get(post_id)
        if fc:
            report_lines.append(
                f"| 📊 推定フォロワー貢献 | **+{fc['estimated']}人**"
                f"（全体の{fc['ratio_pct']}%） |"
            )
        if should_save:
            report_lines.append(f"| 📚 ナレッジ保管 | ✅ {save_reason} |")
        report_lines.append("")

    # ── サマリー ──
    avg_er = round(total_likes / total_views * 100, 2) if total_views > 0 else 0
    report_lines.append("### 📈 本日のサマリー")
    report_lines.append(f"- 合計いいね: **{total_likes}** / 合計閲覧: **{total_views}**")
    report_lines.append(f"- 平均エンゲージメント率: **{avg_er}%**")
    if follower_diff is not None:
        report_lines.append(f"- フォロワー増減: **{follower_diff:+d}人**")
    if knowledge_saved:
        report_lines.append(f"- 📚 ナレッジ保管: {len(knowledge_saved)}件")
        for label, reason in knowledge_saved:
            report_lines.append(f"  - {label}: {reason}")
    report_lines.append("")

    # ── 情報リサーチへのフィードバック（具体的な改善指示） ──
    report_lines.append("### 🔄 情報リサーチへのフィードバック")

    # 最高パフォーマンス投稿の分析
    if best_er_idx >= 0:
        _, best_slot, _, best_data = results[best_er_idx]
        best_label = slot_labels.get(best_slot)
        best_er_pct = round(best_data["likes"] / best_data["views"] * 100, 2) if best_data["views"] > 0 else 0
        report_lines.append(
            f"- **伸びた投稿:** {best_label}（ER {best_er_pct}%）"
            f"→ この時間帯・切り口のパターンを次回も活用すること"
        )

    # 最低パフォーマンス投稿の分析
    worst_er_val = 999
    worst_info = None
    for _, slot_num, _, data in results:
        if data is None:
            continue
        er = data["likes"] / data["views"] * 100 if data["views"] > 0 else 0
        if er < worst_er_val:
            worst_er_val = er
            worst_info = (slot_labels.get(slot_num), data)

    if worst_info and worst_er_val < HIGH_ER_THRESHOLD:
        w_label, w_data = worst_info
        w_er = round(worst_er_val, 2)
        if w_data["views"] < LOW_VIEWS_THRESHOLD:
            report_lines.append(f"- **伸びなかった投稿:** {w_label}（閲覧{w_data['views']}）→ フックが弱い。冒頭の訴求力を強化すること")
        elif w_er < LOW_ER_THRESHOLD:
            report_lines.append(f"- **伸びなかった投稿:** {w_label}（ER {w_er}%）→ 閲覧はあるが刺さらなかった。テーマ・角度を変更すること")
        else:
            report_lines.append(f"- **改善余地:** {w_label}（ER {w_er}%）→ 次回は異なるフォーマット・感情フックを試すこと")

    # フォロワー成長日の分析 + 貢献度フィードバック
    if is_follower_growth_day:
        report_lines.append(f"- **🎉 フォロワー成長日！** (+{follower_diff}人)")
        # 最もフォロワーに貢献した投稿を特定
        if follower_contributions:
            top_fc = max(follower_contributions.items(), key=lambda x: x[1]["estimated"])
            top_post_id = top_fc[0]
            # post_idからスロットラベルを逆引き
            for _, sn, _, d in results:
                if d and top_post_id == _:
                    break
            for pid, sn, _, d in results:
                if pid == top_post_id:
                    fc_label = slot_labels.get(sn, f"SLOT_{sn}")
                    report_lines.append(
                        f"  → **フォロワー増加に最も貢献:** {fc_label}"
                        f"（推定+{top_fc[1]['estimated']}人 / 貢献度{top_fc[1]['ratio_pct']}%）"
                    )
                    break
        report_lines.append("  → この日の全投稿をナレッジ保管済み。パターンを重点的に再現すること")
    elif follower_diff is not None and follower_diff <= 0:
        report_lines.append(f"- フォロワー増減なし。フォローCTAの「何を届けるか」の具体性を高めること")

    if avg_er < LOW_ER_THRESHOLD:
        report_lines.append("- ⚠️ 全体ERが1%未満。根本的にフック・テーマ選定を見直すべき")
    report_lines.append("")

    # ── 🧪 実験枠（SLOT_3）の評価 ──
    from utils.post_classifier import classify_hook_type as _clh, classify_format_type as _clf
    slot3_result = None
    slot12_ers = []
    for _, sn, pt, d in results:
        if d is None:
            continue
        er_val = d["likes"] / d["views"] * 100 if d["views"] > 0 else 0
        if sn == 3:
            slot3_result = (d, er_val, pt)
        else:
            slot12_ers.append(er_val)

    if slot3_result:
        s3_data, s3_er, s3_text = slot3_result
        avg_stable = sum(slot12_ers) / len(slot12_ers) if slot12_ers else 0
        s3_hook = _clh(s3_text[:150]) if s3_text else "不明"
        s3_fmt = _clf(s3_text[:200]) if s3_text else "不明"

        report_lines.append("### 🧪 実験枠（SLOT_3）評価")
        if s3_er > avg_stable and avg_stable > 0:
            report_lines.append(
                f"- **実験枠が安定枠を上回った！** "
                f"ER {round(s3_er, 2)}% vs 安定枠平均 {round(avg_stable, 2)}%"
            )
            report_lines.append(
                f"  → フック「{s3_hook}」×フォーマット「{s3_fmt}」を**明日から安定枠に昇格**させること"
            )
        else:
            report_lines.append(
                f"- 実験枠: ER {round(s3_er, 2)}% / 安定枠平均: {round(avg_stable, 2)}%"
            )
            report_lines.append(
                f"  → フック「{s3_hook}」×フォーマット「{s3_fmt}」は不採用。次回は別の組み合わせを実験"
            )
        report_lines.append("")

    # ── note展開候補の検出 + 骨子生成 ──
    note_candidates = []
    for post_id, slot_num, post_text, data in results:
        if data is None or not post_text:
            continue
        likes = data["likes"]
        views = data["views"]
        if is_note_candidate(likes, views):
            er = round(likes / views * 100, 2) if views > 0 else 0
            label = slot_labels.get(slot_num, f"SLOT_{slot_num}")
            note_candidates.append((post_text, likes, views, er, label))

    if note_candidates:
        report_lines.append("### 📝 note記事 展開候補")
        report_lines.append("")
        report_lines.append(
            f"以下の **{len(note_candidates)}件** の投稿はnote記事への展開候補です"
            f"（閲覧{NOTE_CANDIDATE_VIEWS:,}以上 or いいね{NOTE_CANDIDATE_LIKES}以上）。"
        )
        report_lines.append("骨子（アウトライン）を自動生成し、`operation/note_drafts/` に保存しました。")
        report_lines.append("")

        for post_text, likes, views, er, label in note_candidates:
            # 骨子を生成・保存
            outline = generate_note_outline(post_text, likes, views, er, target_date, label)
            saved_path = save_note_draft(outline, target_date, label)

            report_lines.append(f"**{label}** — 閲覧**{views:,}** / いいね**{likes}**")
            report_lines.append(f"> {post_text[:100]}...")
            report_lines.append(f"→ 骨子保存先: `{os.path.basename(saved_path)}`")
            report_lines.append("")

        report_lines.append("*骨子を元に、別途note記事として仕上げてください。*")
        report_lines.append("")

    comment_body = "\n".join(report_lines)
    gh.add_comment(issue.number, comment_body)

    # Issueをクローズ
    try:
        issue.edit(state="closed")
        logger.info(f"Issue #{issue.number} をクローズしました")
    except Exception as e:
        logger.warning(f"Issueクローズ失敗: {e}")

    logger.info(f"=== 投稿・計測 自動計測完了 ({len(results)}件, ナレッジ保管{len(knowledge_saved)}件) ===")


if __name__ == "__main__":
    main()
