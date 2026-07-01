"""
ron_post.py
ロン担当: Threads APIへの投稿実行スクリプト
ステップ⑤: 人間の承認確認 → Threads投稿（または下書き保存） → 結果記録

--draft モード:
  コンテナ作成のみ（publishしない）。
  投稿テキストをIssue/Discordに表示し、Threadsアプリから手動投稿 or
  後から `--publish-container <container_id>` で公開できる。
"""

import os
import sys
import argparse
import requests
from datetime import datetime
from utils.github_issues import GitHubIssues
pass  # discord notifications removed
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

THREADS_API_BASE = "https://graph.threads.net/v1.0"


def check_human_approval(issue_number: int, gh: GitHubIssues) -> tuple[bool, dict]:
    """
    GitHub Issueのコメントに「承認」という文字があるか確認する。
    承認されていれば (True, {1: text, 2: text, 3: text}) を返す。
    旧フォーマット（単一コードブロック）にも後方互換で対応。
    """
    import re
    comments = gh.get_comments(issue_number)
    slot_texts = {}

    for comment in reversed(comments):
        body = comment.body
        if f"{_n('malfoy')}より：承認申請" in body:
            # 推奨投稿案セクション以降のみ対象（レビュー結果のコードブロック誤検出を防止）
            post_section = body
            marker = "推奨投稿案"
            idx = body.find(marker)
            if idx != -1:
                post_section = body[idx:]
            code_blocks = re.findall(r'```\n([\s\S]*?)\n```', post_section)
            for i, block in enumerate(code_blocks[:3], 1):
                stripped = clean_post_text(block)
                if stripped:
                    slot_texts[i] = stripped
            # 旧フォーマットフォールバック
            if not slot_texts:
                lines = body.split("\n")
                in_code_block = False
                code_lines = []
                for line in lines:
                    if line.strip() == "```" and not in_code_block:
                        in_code_block = True
                        continue
                    if line.strip() == "```" and in_code_block:
                        break
                    if in_code_block:
                        code_lines.append(line)
                if code_lines:
                    slot_texts[1] = "\n".join(code_lines).strip()
            break

    for comment in comments:
        if ("承認" in comment.body
                and comment.user.type != "Bot"
                and "申請" not in comment.body):
            if slot_texts:
                logger.info(f"人間承認確認: @{comment.user.login}")
                return True, slot_texts

    logger.warning("人間承認が確認できません。投稿を中止します。")
    return False, {}


def clean_post_text(text: str) -> str:
    """投稿テキストからフォーマットラベルを除去する"""
    import re
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        # [1投稿目：フック] [2投稿目：本文] 等のラベル行を除去
        if re.match(r'^\[?\d+投稿目[：:].+\]?$', line.strip()):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def create_threads_container(text: str, reply_to_id: str = None) -> str:
    """
    Threads APIでメディアコンテナを作成する（Step 1）。
    reply_to_id を指定するとツリー返信コンテナを作成する。
    戻り値: container_id
    コンテナの有効期限は約24時間。
    """
    url = f"{THREADS_API_BASE}/{THREADS_USER_ID}/threads"
    payload = {
        "media_type": "TEXT",
        "text": text,
        "access_token": THREADS_ACCESS_TOKEN,
    }
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id
    try:
        resp = requests.post(url, data=payload, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Threadsコンテナ作成失敗")
        raise
    container_id = resp.json().get("id")
    label = "返信コンテナ" if reply_to_id else "コンテナ"
    logger.info(f"{label}作成成功: {container_id}")
    return container_id


def publish_threads_container(container_id: str) -> str:
    """
    作成済みコンテナを公開する（Step 2）。
    戻り値: post_id
    """
    url = f"{THREADS_API_BASE}/{THREADS_USER_ID}/threads_publish"
    payload = {
        "creation_id": container_id,
        "access_token": THREADS_ACCESS_TOKEN,
    }
    import time as _time
    # リトライ付き（コンテナ処理に時間がかかる場合がある）
    for attempt in range(3):
        try:
            resp = requests.post(url, data=payload, timeout=15)
            if resp.status_code == 400 and attempt < 2:
                logger.warning(f"公開リクエスト400エラー（attempt {attempt+1}/3）→ {5*(attempt+1)}秒待機してリトライ")
                _time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            if attempt < 2 and "400" in str(e):
                logger.warning(f"公開リクエスト失敗（attempt {attempt+1}/3）→ リトライ")
                _time.sleep(5 * (attempt + 1))
                continue
            logger.error(f"Threads公開リクエスト失敗")
            raise
    post_id = resp.json().get("id")
    logger.info(f"Threads投稿成功: Post ID = {post_id}")
    return post_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text",    default="", help="投稿テキスト（省略時はGitHub Issueから自動取得）")
    parser.add_argument("--draft",   action="store_true",
                        help="下書きモード: コンテナ作成のみ。公開はしない。")
    parser.add_argument("--publish-container", default="",
                        help="指定したコンテナIDを公開する（--draftで作成済みの場合）")
    parser.add_argument("--check-approval", action="store_true", help="承認確認モード（後方互換）")
    args = parser.parse_args()

    logger.info("=== ロン 投稿実行開始 ===")

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
    gh.update_pipeline_status(issue.number, "ron_post", "running")

    # ── 既存コンテナを公開するモード ──────────────────
    if args.publish_container:
        container_id = args.publish_container
        logger.info(f"既存コンテナを公開します: {container_id}")
        post_id   = publish_threads_container(container_id)
        posted_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        gh.add_comment(issue.number, f"""## 📤 {_n('ron')}より：投稿完了（手動公開）

**投稿日時:** {posted_at}
**投稿ID:** `{post_id}`
**ステータス:** 投稿成功
""")
        gh.update_pipeline_status(issue.number, "ron_post", "done")
        gh.update_pipeline_status(issue.number, "human",    "done")
        print(f"POST_ID={post_id}")
        print(f"ISSUE_NUMBER={issue.number}")
        return

    # ── 通常フロー: 承認確認 ──────────────────────────
    approved, slot_texts = check_human_approval(issue.number, gh)
    if not approved:
        logger.error("人間の承認なしに投稿を実行することはできません。処理を終了します。")
        gh.update_pipeline_status(issue.number, "ron_post", "waiting")
        sys.exit(1)

    gh.update_pipeline_status(issue.number, "human", "done")

    # SLOT_1（即時投稿）のテキストを取得
    post_text = args.text if args.text else slot_texts.get(1, "")
    if not post_text:
        logger.error("SLOT_1の投稿テキストが取得できませんでした。")
        sys.exit(1)

    total_slots = len(slot_texts)
    logger.info(f"投稿テキスト（先頭50文字）: {post_text[:50]}...")
    logger.info(f"スロット数: {total_slots}（SLOT_1を即時投稿、残りはスケジュール投稿）")

    # ── 下書きモード（コンテナ作成のみ）──────────────
    if args.draft:
        thread_parts = [p.strip() for p in post_text.split("===THREAD===") if p.strip()]
        container_id = create_threads_container(thread_parts[0])
        saved_at     = datetime.now().strftime("%Y-%m-%d %H:%M")

        thread_note = ""
        if len(thread_parts) > 1:
            thread_note = f"\n⚠️ ツリー投稿 {len(thread_parts)}パーツ。公開後に返信コンテナを別途作成してください。"

        comment_body = f"""## 📋 {_n('ron')}より：下書き保存完了

**保存日時:** {saved_at}
**コンテナID（1投稿目）:** `{container_id}`
⚠️ コンテナの有効期限は **約24時間** です。{thread_note}

### 投稿テキスト（Threadsアプリから手動投稿する場合はコピーしてください）
```
{post_text}
```

### 今すぐ公開する場合
以下のコマンドを実行してください：
```bash
python scripts/ron_post.py --publish-container {container_id}
```
または GitHub Actions `post-to-threads` ワークフローを手動実行してください。
"""
        gh.add_comment(issue.number, comment_body)
        gh.update_pipeline_status(issue.number, "ron_post", "pending")
        logger.info(f"下書きコンテナを作成しました: {container_id}")
        logger.info("=== ロン 下書き保存完了 ===")
        print(f"CONTAINER_ID={container_id}")
        print(f"ISSUE_NUMBER={issue.number}")
        return

    # ── 通常モード: 即時公開 ──────────────────────────
    # ツリー投稿対応: ===THREAD=== でパーツを分割
    thread_parts = [p.strip() for p in post_text.split("===THREAD===") if p.strip()]
    logger.info(f"投稿パーツ数: {len(thread_parts)}")

    # 1投稿目を公開
    import time
    container_id = create_threads_container(thread_parts[0])
    time.sleep(5)  # コンテナ処理待ち
    post_id      = publish_threads_container(container_id)
    posted_at    = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 2投稿目以降をツリー返信として投稿（チェーン形式: 親→ツリー1→ツリー2→...）
    reply_ids = []
    last_id = post_id  # 最初は親投稿に返信、以降は直前の投稿に返信
    for i, part in enumerate(thread_parts[1:], 2):
        time.sleep(5)  # API制限+コンテナ処理待ち
        reply_container = create_threads_container(part, reply_to_id=last_id)
        time.sleep(5)  # 返信コンテナ処理待ち
        reply_id = publish_threads_container(reply_container)
        reply_ids.append(reply_id)
        last_id = reply_id  # 次のツリーはこの投稿に繋げる
        logger.info(f"ツリー{i}投稿: {reply_id}（返信先: {last_id}）")

    thread_info = ""
    if reply_ids:
        thread_info = f"\n**ツリー返信ID:** {', '.join([f'`{r}`' for r in reply_ids])}"

    comment_body = f"""## 📤 {_n('ron')}より：投稿完了{"（ツリー投稿）" if reply_ids else ""}

**投稿日時:** {posted_at}
**1投稿目ID:** `{post_id}`{thread_info}

**投稿テキスト:**
```
{post_text}
```

**ステータス:** 投稿成功{"（" + str(len(thread_parts)) + "連投）" if len(thread_parts) > 1 else ""}
**24時間後計測:** GitHub Actions `measure.yml` を起動してください

---
*{_n('snape')}へ: この投稿IDを記録してください → `{post_id}`*
"""
    done_ts = datetime.now().strftime("%H:%M")
    gh.add_comment(issue.number, comment_body)
    gh.update_pipeline_status(issue.number, "ron_post", "done", done_ts)
    # Google Sheets に記録（SLOT_1）
    log_post(SPREADSHEET_ID, GOOGLE_CREDENTIALS_PATH,
             slot=1, post_text=post_text, post_id=post_id, issue_number=issue.number)
    logger.info(f"GitHub Issue #{issue.number} に投稿完了コメントを追加")
    logger.info("=== ロン 投稿実行完了 ===")

    print(f"POST_ID={post_id}")
    print(f"ISSUE_NUMBER={issue.number}")


if __name__ == "__main__":
    main()
