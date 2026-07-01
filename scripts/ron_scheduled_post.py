"""
ron_scheduled_post.py
ロン担当: スケジュール投稿（18時・21時）
GitHub Issueのマルフォイ承認コメントから該当スロットのテキストを取得して投稿する
GitHub Actions cron で自動実行される。
"""

import os
import sys
import re
import argparse
import requests
import time
from datetime import datetime, timezone, timedelta
from utils.github_issues import GitHubIssues
pass  # discord send_post_complete removed
from utils.sheets_logger import log_post
from utils.agent_config import name as _n
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
    url = f"{THREADS_API_BASE}/{THREADS_USER_ID}/threads"
    payload = {
        "media_type": "TEXT",
        "text": text,
        "access_token": THREADS_ACCESS_TOKEN,
    }
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id
    resp = requests.post(url, data=payload, timeout=15)
    resp.raise_for_status()
    container_id = resp.json().get("id")
    label = "返信コンテナ" if reply_to_id else "コンテナ"
    logger.info(f"{label}作成成功: {container_id}")
    return container_id


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
    """マルフォイの承認コメントから指定スロットのテキストを取得"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if f"{_n('malfoy')}より：承認申請" in comment.body:
            # 推奨投稿案セクション以降のみ対象（レビュー結果のコードブロック誤検出を防止）
            body = comment.body
            marker = "推奨投稿案"
            idx = body.find(marker)
            if idx != -1:
                body = body[idx:]
            code_blocks = re.findall(r'```\n([\s\S]*?)\n```', body)
            if len(code_blocks) >= slot_num:
                text = clean_post_text(code_blocks[slot_num - 1])
                if text:
                    return text
    return ""


def check_approved(issue_number: int, gh: GitHubIssues) -> bool:
    """承認コメントがあるか確認"""
    comments = gh.get_comments(issue_number)
    return any(
        "承認" in c.body and c.user.type != "Bot" and "申請" not in c.body
        for c in comments
    )


def find_approved_issue(gh: GitHubIssues) -> object:
    """当日→前日の順で承認済みIssueを検索する（cron遅延による日付またぎ対策）"""
    JST = timezone(timedelta(hours=9))
    today     = datetime.now(JST).strftime("%Y-%m-%d")
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

    for date_str in [today, yesterday]:
        title_prefix = f"【運用ループ】{date_str}"
        for state in ["open", "closed"]:
            issues = gh.repo.get_issues(state=state, labels=[gh.DAILY_OP_LABEL])
            for issue in issues:
                if issue.title.startswith(title_prefix):
                    if check_approved(issue.number, gh):
                        logger.info(f"承認済みIssueを発見 ({date_str}): #{issue.number}")
                        return issue
                    logger.info(f"Issue #{issue.number} ({date_str}) は未承認")
                    break  # 日付一致Issueは1つのみ
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--slot", type=int, required=True, choices=[2, 3],
        help="スロット番号（2=18時, 3=21時）"
    )
    args = parser.parse_args()

    slot_label = SLOT_LABELS.get(args.slot, f"SLOT_{args.slot}")
    logger.info(f"=== ロン スケジュール投稿開始 [{slot_label}] ===")

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)

    # 当日→前日の順で承認済みIssueを検索（cron遅延による日付またぎ対策）
    issue = find_approved_issue(gh)
    if issue is None:
        logger.info("承認済みのIssueが見つかりません（当日・前日を検索済み）。投稿をスキップします。")
        sys.exit(0)  # exit(0)=正常終了でcronを維持（exit(1)はGitHubがcronを自動無効化する）

    # Python側の投稿済みチェック（yml側チェックとの2重防止）
    # yml側のgrepがコメント形式にマッチしない場合の保険
    slot_keyword = "18時" if args.slot == 2 else "21時"
    comments_for_check = gh.get_comments(issue.number)
    already_posted = any(
        slot_keyword in c.body and "投稿完了" in c.body
        for c in comments_for_check
    )
    if already_posted:
        logger.info(f"SLOT_{args.slot}（{slot_keyword}）は既に投稿済みです。スキップします。")
        sys.exit(0)

    # スロットテキスト取得
    post_text = get_slot_text_from_issue(issue.number, gh, args.slot)
    if not post_text:
        logger.info(f"SLOT_{args.slot} のテキストが見つかりません。投稿をスキップします。")
        sys.exit(0)  # exit(0)=正常終了でcronを維持

    logger.info(f"投稿テキスト（先頭50文字）: {post_text[:50]}...")

    # ツリー投稿
    thread_parts = [p.strip() for p in post_text.split("===THREAD===") if p.strip()]
    logger.info(f"投稿パーツ数: {len(thread_parts)}")

    container_id = create_threads_container(thread_parts[0])
    time.sleep(5)  # コンテナ処理待ち
    post_id      = publish_threads_container(container_id)

    # ツリーをチェーン形式で投稿（親→ツリー1→ツリー2→...）
    last_id = post_id
    for i, part in enumerate(thread_parts[1:], 2):
        time.sleep(5)  # API制限+コンテナ処理待ち
        reply_container = create_threads_container(part, reply_to_id=last_id)
        time.sleep(5)  # 返信コンテナ処理待ち
        reply_id = publish_threads_container(reply_container)
        last_id = reply_id  # 次のツリーはこの投稿に繋げる
        logger.info(f"ツリー{i}投稿完了: {reply_id}")

    posted_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    comment_body = f"""## 📤 {_n('ron')}より：{slot_label} 投稿完了

<!-- SLOT_{args.slot} 投稿完了 -->

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
    logger.info(f"=== ロン スケジュール投稿完了 [{slot_label}] ===")
    print(f"POST_ID={post_id}")
    print(f"ISSUE_NUMBER={issue.number}")


if __name__ == "__main__":
    main()
