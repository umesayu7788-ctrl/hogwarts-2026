"""
ron_fetch.py
ロン担当: Threads投稿のエンゲージメント計測スクリプト
ステップ⑥: 投稿24時間後に自動実行 → データ取得 → GitHub Issues記録 → バズ判定
"""

import os
import argparse
import requests
from datetime import datetime
from utils.github_issues import GitHubIssues
from utils.sheets_logger import update_engagement
from utils.agent_config import name as _n
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

THREADS_ACCESS_TOKEN    = os.getenv("THREADS_ACCESS_TOKEN")
GITHUB_TOKEN            = os.getenv("GITHUB_TOKEN")
GITHUB_REPO             = os.getenv("GITHUB_REPO")
SPREADSHEET_ID          = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/sheets_service_account.json")

THREADS_API_BASE  = "https://graph.threads.net/v1.0"
BUZZ_THRESHOLD    = 30   # バズ判定のいいね閾値
BUZZ_VIEWS_THRESHOLD = 3000  # バズ判定の閲覧数閾値
SCRIPT_DIR        = os.path.dirname(os.path.abspath(__file__))
BUZZ_POSTS_PATH   = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "kb_sys_ref_v001.md")


def fetch_post_insights(post_id: str, max_retries: int = 2) -> dict:
    """
    Threads APIで投稿のインサイト（エンゲージメント指標）を取得する。
    400エラー時はリトライし、最終的に取得不可なら空dictを返す。
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
                logger.info(f"インサイト取得成功: {insights}")
                return insights

            if resp.status_code == 400:
                error_msg = resp.json().get("error", {}).get("message", "")
                logger.warning(f"Post {post_id}: 400エラー (attempt {attempt}): {error_msg[:100]}")
                if attempt < max_retries:
                    time.sleep(3)
                    continue
                raise requests.exceptions.HTTPError(f"400: {error_msg}")

            resp.raise_for_status()

        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                time.sleep(3)
                continue
            logger.error(f"Threadsインサイト取得失敗 (post_id={post_id})")
            raise

    return {}


def get_post_text_from_issue(issue_number: int, gh: GitHubIssues) -> str:
    """GitHub Issueのコメントから投稿テキストを取得する"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if f"{_n('ron')}より：投稿完了" in comment.body:
            lines = comment.body.split("\n")
            in_text_block = False
            text_lines = []
            for line in lines:
                if line.startswith("```") and in_text_block:
                    break
                if in_text_block:
                    text_lines.append(line)
                if "投稿テキスト:" in line:
                    in_text_block = True
            return "\n".join(text_lines).strip()
    return ""


def get_theme_from_issue(issue: object) -> str:
    """GitHub IssueのタイトルからテーマID（themeXXX）を取得する"""
    title = issue.title
    # タイトル例: 「【運用ループ】2026-04-01 - AI活用テーマ」
    parts = title.split(" - ")
    if len(parts) > 1:
        return parts[-1]
    return "不明"


def update_buzz_posts(post_text: str, likes: int, date_str: str, theme: str):
    """いいね50以上の場合、kb_sys_ref_v001.mdに追記する"""
    if likes < BUZZ_THRESHOLD:
        return

    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # 通算No.を計算（既存の行数から）
        existing_posts = content.count("| No.")
        new_no = existing_posts  # ヘッダー行を除いた数

        new_row = f"| {new_no:03d} | {date_str} | {likes} | {theme} | - | {post_text[:30]}... |"

        # テーブルの最後に追記
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

        logger.info(f"🎉 バズ投稿として kb_sys_ref_v001.md に追記しました (いいね: {likes})")

    except FileNotFoundError:
        logger.warning(f"{BUZZ_POSTS_PATH} が見つかりません")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", required=True, help="Threads Post ID")
    parser.add_argument("--issue-number", required=True, type=int, help="GitHub Issue number")
    args = parser.parse_args()

    logger.info("=== ロン エンゲージメント計測開始 ===")

    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_issue(args.issue_number)

    # インサイト取得
    insights = fetch_post_insights(args.post_id)
    likes     = insights.get("likes", 0)
    replies   = insights.get("replies", 0)
    reposts   = insights.get("reposts", 0)
    quotes    = insights.get("quotes", 0)
    views     = insights.get("views", 0)

    is_buzz   = likes >= BUZZ_THRESHOLD or views >= BUZZ_VIEWS_THRESHOLD
    date_str  = datetime.now().strftime("%Y-%m-%d")
    theme     = get_theme_from_issue(issue)
    post_text = get_post_text_from_issue(args.issue_number, gh)

    # GitHub Issueに計測結果を記録
    comment_body = f"""## 📊 {_n('ron')}より：エンゲージメント計測結果（24時間後）

**計測日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**投稿ID:** `{args.post_id}`

### ▼ エンゲージメント（24時間）
| 指標 | 数値 |
|---|---|
| いいね | **{likes}** {'🎉 バズ！' if likes >= BUZZ_THRESHOLD else ''} |
| 返信 | {replies} |
| リポスト | {reposts} |
| 引用 | {quotes} |
| インプレッション | **{views}** {'🎉 バズ！' if views >= BUZZ_VIEWS_THRESHOLD else ''} |

### ▼ バズ判定
{'✅ **バズ投稿！** → kb_sys_ref_v001.md に追記しました' if is_buzz else f'📝 通常投稿（いいね {likes} / 閾値 {BUZZ_THRESHOLD}、閲覧 {views} / 閾値 {BUZZ_VIEWS_THRESHOLD}）'}

### ▼ {_n('hermione')}へのフィードバック
{'この投稿の要素（感情フック・構成）を次回のブリーフィングで優先的に活用してください。' if is_buzz else '今回のパターンは効果が限定的でした。次回は別の角度を試してください。'}

---
*このIssueをクローズします。*
"""
    gh.add_comment(args.issue_number, comment_body)

    # Issueをクローズ
    gh.close_issue(args.issue_number)
    logger.info(f"GitHub Issue #{args.issue_number} をクローズしました")

    # Google Sheetsのエンゲージメントデータを更新（いいね・返信・リポスト・閲覧数）
    update_engagement(
        SPREADSHEET_ID, GOOGLE_CREDENTIALS_PATH,
        post_id=args.post_id,
        likes=likes, replies=replies, reposts=reposts, views=views,
    )

    # バズ判定でkb_sys_ref_v001.mdを更新
    if is_buzz and post_text:
        update_buzz_posts(post_text, likes, date_str, theme)

    logger.info("=== ロン エンゲージメント計測完了 ===")


if __name__ == "__main__":
    main()
