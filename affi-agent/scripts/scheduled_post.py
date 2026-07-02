"""
ron_scheduled_post.py
投稿・計測担当: スケジュール投稿（18時・21時）
GitHub Issueの校閲承認コメントから該当スロットのテキストを取得して投稿する
GitHub Actions cron で自動実行される。
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
import sys
import re
import argparse
import requests
import time
from datetime import datetime
from utils.github_issues import GitHubIssues
from utils.discord_notify import send_post_complete
from utils.sheets_logger import log_post


def notify_error_discord(slot_num: int, message: str):
    """スケジュール投稿失敗時のDiscord通知（token切れ・rate limit・抽出失敗等）"""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={
            "username": "🚨 投稿・計測",
            "content": f"@here ⚠️ **SLOT_{slot_num} 投稿失敗**",
            "embeds": [{
                "title": "Threads API / 投稿処理エラー",
                "description": message[:1500],
                "color": 0xF04747,
                "footer": {"text": "手動確認が必要です"}
            }]
        }, timeout=10)
    except Exception as e:
        logger.error(f"Discord通知失敗: {e}")


def _has_pr_marker(text: str) -> bool:
    """PR表記が text のどこかにあるか判定。
    単独行 'PR'、'#PR'、'#広告'、'[PR]'、'【PR】' をすべて許容。
    """
    if any(tag in text for tag in ["#PR", "#広告", "[PR]", "【PR】", "#pr"]):
        return True
    # 単独行の "PR"（前後が改行 or 文頭文末）
    for line in text.splitlines():
        if line.strip() == "PR":
            return True
    return False


def ensure_pr_tag(text: str, is_affiliate: bool = False) -> str:
    """アフィリ投稿なのに PR表記が無ければツリー最終ブロックの頭に挿入。
    親投稿（最初のブロック）は触らない（ツリー投稿時のフック汚染を防ぐ）。
    """
    if not is_affiliate:
        return text
    if _has_pr_marker(text):
        return text
    # 安全網: 最後のブロックに PR を補完（親投稿は触らない）
    if "===THREAD===" in text:
        parts = text.split("===THREAD===")
        last = parts[-1].lstrip()
        parts[-1] = f"\nPR\n{last}"
        return "===THREAD===".join(parts)
    # ツリー化されていない単発投稿の場合のみ、末尾に PR 行を追加
    return f"{text.rstrip()}\nPR"


def looks_like_affiliate(text: str) -> bool:
    """楽天/Amazonリンクや商品紹介語を検出してアフィリ投稿か判定"""
    signals = ["a.r10.to", "rakuten.co.jp", "amzn.to", "amazon.co.jp", "楽天で",
               "Amazon で", "プロモーション", "ご紹介", "商品リンク"]
    return any(s in text for s in signals)
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

THREADS_ACCESS_TOKEN    = os.getenv("THREADS_ACCESS_TOKEN")
THREADS_USER_ID         = os.getenv("THREADS_USER_ID")
GITHUB_TOKEN            = os.getenv("GITHUB_TOKEN")
GITHUB_REPO             = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL     = os.getenv("DISCORD_WEBHOOK_URL")
SPREADSHEET_ID          = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/sheets_service_account.json")
THREADS_API_BASE        = "https://graph.threads.net/v1.0"

SLOT_LABELS = {
    2: "🌆 18時・夕方投稿",
    3: "🌙 21時・夜投稿",
}


def create_threads_container(text: str, reply_to_id: str = None) -> str:
    """コンテナ作成。5xx/ネットワーク一時障害に備えて3回リトライ"""
    url = f"{THREADS_API_BASE}/{THREADS_USER_ID}/threads"
    payload = {
        "media_type": "TEXT",
        "text": text,
        "access_token": THREADS_ACCESS_TOKEN,
    }
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.post(url, data=payload, timeout=15)
            if resp.status_code >= 500:
                logger.warning(f"コンテナ作成 5xx(試行{attempt+1}): {resp.status_code}")
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            container_id = resp.json().get("id")
            label = "返信コンテナ" if reply_to_id else "コンテナ"
            logger.info(f"{label}作成成功: {container_id}")
            return container_id
        except requests.exceptions.RequestException as e:
            last_err = e
            logger.warning(f"コンテナ作成 一時失敗(試行{attempt+1}): {e}")
            time.sleep(5 * (attempt + 1))
    raise last_err if last_err else RuntimeError("container creation failed")


def publish_threads_container(container_id: str) -> str:
    url = f"{THREADS_API_BASE}/{THREADS_USER_ID}/threads_publish"
    payload = {
        "creation_id": container_id,
        "access_token": THREADS_ACCESS_TOKEN,
    }
    # リトライ付き（コンテナ処理に時間がかかる場合がある）
    for attempt in range(3):
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code == 400 and attempt < 2:
            logger.warning(f"公開リクエスト400エラー（attempt {attempt+1}/3）→ {5*(attempt+1)}秒待機してリトライ")
            time.sleep(5 * (attempt + 1))
            continue
        resp.raise_for_status()
        break
    post_id = resp.json().get("id")
    logger.info(f"Threads投稿成功: Post ID = {post_id}")
    return post_id


def clean_post_text(text: str) -> str:
    """投稿テキストからフォーマットラベルを除去する"""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if re.match(r'^\[?\d+投稿目[：:].+\]?$', line.strip()):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def get_slot_text_from_issue(issue_number: int, gh: GitHubIssues, slot_num: int) -> str:
    """校閲の承認コメントから指定スロットのテキストを取得（SLOTラベルで明示抽出）"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if "校閲より：承認申請" in comment.body:
            body = comment.body
            marker = "推奨投稿案"
            idx = body.find(marker)
            if idx != -1:
                body = body[idx:]
            # SLOT_1/2/3 ラベルで明示的に対応するブロックを抽出
            pattern = rf'SLOT_{slot_num}[^\n]*\n[\s\S]*?```\s*\n([\s\S]*?)\n```'
            m = re.search(pattern, body)
            if m:
                text = clean_post_text(m.group(1))
                if text and not is_placeholder(text):
                    return text
            # フォールバック：ラベル抽出失敗時は旧ロジック（インデックス）で試す
            code_blocks = re.findall(r'```\n([\s\S]*?)\n```', body)
            if len(code_blocks) >= slot_num:
                text = clean_post_text(code_blocks[slot_num - 1])
                if text and not is_placeholder(text):
                    return text
    return ""


def is_placeholder(text: str) -> bool:
    """プレースホルダー・抽出失敗マーカーが含まれていれば True"""
    if not text or len(text.strip()) < 10:
        return True
    markers = ["抽出失敗", "（SLOT_", "ここに本題", "[", "投稿内容なし", "TODO"]
    lower = text[:200]
    return any(m in lower for m in markers)


def _strip_rafcid_from_text(text: str) -> str:
    """投稿テキスト中の楽天アフィリURLから rafcid パラメータを除去する。
    rafcid（新portal applicationId tracking）が含まれるとリダイレクト先が無効になる。
    """
    import re as _re

    def _clean(match):
        url = match.group(0)
        # rafcid=xxxx を除去（先頭&でも先頭?でも対応）
        url = _re.sub(r'[?&]rafcid=[^&\s]*', lambda m: '?' if m.group(0).startswith('?') else '', url)
        # 末尾に & が残ったら除去
        url = _re.sub(r'[?&]+$', '', url)
        # ?& が残った場合の修復
        url = url.replace('?&', '?')
        return url

    # 楽天アフィリリダイレクトURLにマッチ
    # hb.afl.rakuten.co.jp / pt.afl.rakuten.co.jp / a.r10.to / r10.to
    pattern = r'https?://(?:(?:hb|pt)\.afl\.rakuten\.co\.jp|a\.r10\.to|r10\.to)/\S+'
    return _re.sub(pattern, _clean, text)


def _replace_affiliate_placeholder(text: str) -> str:
    """SLOT_3 アフィリ投稿でAIがリンクをプレースホルダ化した場合に実URLで置換する。
    本日のproductファイル（JST日付）から affiliate_url を取得して差し替える。
    """
    import re as _re
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    # プレースホルダパターン
    patterns = [
        r'\[楽天アフィリ(?:エイト)?リンク[^\]]*\]',
        r'\[ここにリンク[^\]]*\]',
        r'\[アフィリ(?:エイト)?リンク[^\]]*\]',
        r'\[商品リンク[^\]]*\]',
        r'\[楽天リンク[^\]]*\]',
    ]
    has_placeholder = any(_re.search(p, text) for p in patterns)
    if not has_placeholder:
        return text

    # 本日（JST）のproduct fileから実URL取得。なければ前日（UTC date混在の互換）。
    jst = _tz(_td(hours=9))
    now_jst = _dt.now(jst)
    candidates = [
        now_jst.strftime("%Y-%m-%d"),
        (now_jst - _td(days=1)).strftime("%Y-%m-%d"),
    ]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    actual_url = ""
    for date_str in candidates:
        product_path = os.path.join(script_dir, "..", "operation", "products", f"{date_str}.json")
        try:
            with open(product_path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            selected = data.get("selected") or {}
            url = selected.get("affiliate_url") or selected.get("url", "")
            if url:
                actual_url = url
                logger.info(f"プレースホルダ用URL取得: {date_str}.json から")
                break
        except (FileNotFoundError, _json.JSONDecodeError):
            continue

    if not actual_url:
        logger.warning("プレースホルダ検出だが実URL取得失敗。差し替え不可。")
        return text

    for pat in patterns:
        text = _re.sub(pat, actual_url, text)
    logger.info(f"アフィリリンクプレースホルダを実URLで置換しました: {actual_url[:60]}...")
    return text


def check_approved(issue_number: int, gh: GitHubIssues) -> bool:
    """承認コメントがあるか確認（誤判定防止：否定表現を除外）"""
    comments = gh.get_comments(issue_number)
    for c in comments:
        if c.user.type == "Bot":
            continue
        body = (c.body or "").strip()
        if not body:
            continue
        # 明示的な否定・保留は除外
        if any(ng in body for ng in ["承認しない", "否認", "差し戻し", "保留", "承認待ち", "承認申請"]):
            continue
        # シンプルに「承認」が含まれていればOK（既存の挙動を維持しつつ誤検知は上で除外）
        if "承認" in body:
            return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--slot", type=int, required=True, choices=[2, 3],
        help="スロット番号（2=18時, 3=21時）"
    )
    args = parser.parse_args()

    slot_label = SLOT_LABELS.get(args.slot, f"SLOT_{args.slot}")
    logger.info(f"=== 投稿・計測 スケジュール投稿開始 [{slot_label}] ===")

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)

    # 当日のIssueを検索。見つからない or 承認がなければ前日のIssueも探す
    # （GitHub Actionsのcron遅延で日付をまたぐケースに対応）
    from datetime import timedelta, timezone
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST).strftime("%Y-%m-%d")
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

    issue = None
    for target_date in [today, yesterday]:
        title_prefix = f"【運用ループ】{target_date}"
        for state in ["open", "closed"]:
            issues = gh.repo.get_issues(state=state, labels=["daily-operation"], sort="created", direction="desc")
            for iss in issues:
                if iss.title.startswith(title_prefix):
                    if check_approved(iss.number, gh):
                        issue = iss
                        logger.info(f"承認済みIssue発見: #{iss.number} ({target_date})")
                        break
            if issue:
                break
        if issue:
            break

    if not issue:
        logger.info("承認済みのIssueが見つかりません（当日・前日を検索済み）。投稿をスキップします。")
        sys.exit(0)

    # ── 投稿済みチェック（重複投稿防止） ──
    comments = gh.get_comments(issue.number)
    already_posted = False
    for c in comments:
        body = c.body or ""
        if "投稿・計測より" in body and "投稿完了" in body:
            if args.slot == 2 and ("18時" in body or "SLOT_2" in body):
                already_posted = True
            elif args.slot == 3 and ("21時" in body or "SLOT_3" in body):
                already_posted = True
    if already_posted:
        logger.info(f"SLOT_{args.slot} は既に投稿済みです。スキップします。")
        sys.exit(0)

    # スロットテキスト取得
    post_text = get_slot_text_from_issue(issue.number, gh, args.slot)
    if not post_text:
        msg = f"SLOT_{args.slot} のテキストが見つかりません。投稿を中止します。"
        logger.error(msg)
        notify_error_discord(args.slot, msg + f"\nIssue: {issue.html_url}")
        sys.exit(1)

    # アフィリリンクプレースホルダ → 実URL置換（writerがプレースホルダで出した時の保険）
    post_text = _replace_affiliate_placeholder(post_text)

    # 楽天アフィリURLの rafcid パラメータを除去（リダイレクト先無効になる原因）
    post_text = _strip_rafcid_from_text(post_text)

    # プレースホルダー検知（抽出失敗の文言が投稿されるのを防ぐ最終防衛）
    if is_placeholder(post_text):
        msg = f"SLOT_{args.slot} のテキストにプレースホルダーが含まれています。投稿を中止します。\n先頭200文字:\n{post_text[:200]}"
        logger.error(msg)
        notify_error_discord(args.slot, msg + f"\nIssue: {issue.html_url}")
        sys.exit(1)

    # アフィリ投稿なら #PR/【PR】を強制付与（ステマ規制対策）
    is_aff = looks_like_affiliate(post_text)
    post_text = ensure_pr_tag(post_text, is_affiliate=is_aff)
    if is_aff:
        logger.info("アフィリ投稿と判定。PR表記を確認・付与済み。")

    logger.info(f"投稿テキスト（先頭50文字）: {post_text[:50]}...")

    # ツリー投稿（各APIコール失敗時はDiscord通知）
    thread_parts = [p.strip() for p in post_text.split("===THREAD===") if p.strip()]
    logger.info(f"投稿パーツ数: {len(thread_parts)}")

    try:
        container_id = create_threads_container(thread_parts[0])
        time.sleep(5)
        post_id = publish_threads_container(container_id)
    except Exception as e:
        msg = f"SLOT_{args.slot} 親投稿のThreads API失敗: {e}"
        logger.error(msg)
        notify_error_discord(args.slot, msg + f"\nIssue: {issue.html_url}\n原因候補: トークン期限切れ / レート制限 / 一時的障害")
        sys.exit(1)

    # ツリーをチェーン形式で投稿
    last_id = post_id
    for i, part in enumerate(thread_parts[1:], 2):
        try:
            time.sleep(5)
            reply_container = create_threads_container(part, reply_to_id=last_id)
            time.sleep(5)
            reply_id = publish_threads_container(reply_container)
            last_id = reply_id
            logger.info(f"ツリー{i}投稿完了: {reply_id}")
        except Exception as e:
            msg = f"SLOT_{args.slot} ツリー{i}投稿失敗: {e}"
            logger.error(msg)
            notify_error_discord(args.slot, msg + f"\n親投稿ID: {post_id}\n以降のツリーも投稿されません")
            # 親投稿は成功しているので、ここで break してログだけ残す
            break

    posted_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    comment_body = f"""## 📤 投稿・計測より：{slot_label} 投稿完了

**投稿日時:** {posted_at}
**投稿ID:** `{post_id}`

**投稿テキスト:**
```
{post_text}
```

**ステータス:** 投稿成功{"（" + str(len(thread_parts)) + "連投）" if len(thread_parts) > 1 else ""}
"""
    gh.add_comment(issue.number, comment_body)
    # Google Sheets に記録
    log_post(SPREADSHEET_ID, GOOGLE_CREDENTIALS_PATH,
             slot=args.slot, post_text=post_text, post_id=post_id, issue_number=issue.number)
    logger.info(f"=== 投稿・計測 スケジュール投稿完了 [{slot_label}] ===")
    print(f"POST_ID={post_id}")
    print(f"ISSUE_NUMBER={issue.number}")


if __name__ == "__main__":
    main()
