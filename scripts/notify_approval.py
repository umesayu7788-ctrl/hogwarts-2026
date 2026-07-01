"""
notify_approval.py
オーナーのスマホ/PCに承認通知を送るスクリプト
Discord Webhook（推奨・無料）または Make Webhook に対応
"""

import os
import requests
from datetime import datetime
from utils.github_issues import GitHubIssues
from utils.discord_notify import send_approval_request
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MAKE_WEBHOOK_URL    = os.getenv("MAKE_WEBHOOK_URL")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")


def notify_make(issue_number: int, issue_url: str, issue_title: str):
    """Make Webhook に承認依頼通知を送る（LINEやメール等に転送可能）"""
    payload = {
        "issue_number": issue_number,
        "issue_url": issue_url,
        "issue_title": issue_title,
        "message": (
            f"投稿案の承認をお願いします。\n"
            f"GitHub Issueに「承認」とコメントしてください。\n"
            f"{issue_url}"
        ),
        "timestamp": datetime.now().isoformat(),
    }
    resp = requests.post(MAKE_WEBHOOK_URL, json=payload)
    if resp.status_code == 200:
        logger.info("Make Webhook通知を送信しました")
    else:
        logger.error(f"Make Webhook通知失敗: {resp.status_code} {resp.text}")


def main():
    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()

    sent = False

    # Discord優先（設定されていれば）
    if DISCORD_WEBHOOK_URL:
        send_approval_request(
            DISCORD_WEBHOOK_URL,
            {},  # ステータスはmalfoy_review.pyが既に送付済みのためここでは省略
            issue.number, issue.html_url,
            datetime.now().strftime("%Y-%m-%d"),
        )
        sent = True

    # Make（設定されていれば追加で送る）
    if MAKE_WEBHOOK_URL and "your_webhook_id_here" not in MAKE_WEBHOOK_URL:
        notify_make(issue.number, issue.html_url, issue.title)
        sent = True

    if not sent:
        logger.warning(
            "通知先が設定されていません。\n"
            "Discord: .env に DISCORD_WEBHOOK_URL を設定してください。\n"
            f"手動確認: {issue.html_url}"
        )
        # 通知なしでもIssue URLをログに出力して手動確認できるようにする
        logger.info(f"今日のIssue: {issue.html_url}")


if __name__ == "__main__":
    main()
