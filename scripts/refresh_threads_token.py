"""
refresh_threads_token.py
Threadsアクセストークンを自動リフレッシュするスクリプト
GitHub Actions から50日ごとに自動実行される
"""

import os
import requests
import sys
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN")
GITHUB_TOKEN         = os.getenv("GITHUB_TOKEN")
GITHUB_REPO          = os.getenv("GITHUB_REPO")


def refresh_token(current_token: str) -> str:
    """Threadsトークンをリフレッシュして新しいトークンを返す（有効期限60日に更新）"""
    try:
        r = requests.get("https://graph.threads.net/refresh_access_token", params={
            "grant_type":   "th_refresh_token",
            "access_token": current_token,
        }, timeout=15)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"トークンリフレッシュAPIリクエスト失敗") from e
    data = r.json()
    if "access_token" not in data:
        raise ValueError("リフレッシュ失敗: レスポンスにaccess_tokenが含まれていません")
    expires_days = data.get("expires_in", 0) // 86400
    logger.info(f"トークンリフレッシュ成功 → 有効期限: {expires_days}日")
    return data["access_token"]


def update_github_secret(new_token: str):
    """GitHub Actions SecretのTHREADS_ACCESS_TOKENを更新する"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.warning("GITHUB_TOKEN / GITHUB_REPO が未設定。GitHub Secretの自動更新をスキップします。")
        logger.info("手動でGitHub Secrets を更新してください: THREADS_ACCESS_TOKEN")
        return

    from github import Github
    g    = Github(GITHUB_TOKEN)
    repo = g.get_repo(GITHUB_REPO)

    try:
        # GitHub Secrets はAPIで更新可能（要admin権限）
        # 暗号化が必要なため libsodium が必要 → 手動更新を案内
        logger.info("GitHub Secretsの自動更新には追加ライブラリが必要です。")
        logger.info("以下の手順で手動更新してください:")
        logger.info(f"  1. https://github.com/{GITHUB_REPO}/settings/secrets/actions")
        logger.info(f"  2. THREADS_ACCESS_TOKEN を新しい値に更新")
    except Exception as e:
        logger.error(f"GitHub Secret更新エラー: {e}")


def main():
    logger.info("=== Threadsトークン自動リフレッシュ開始 ===")
    logger.info(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    if not THREADS_ACCESS_TOKEN:
        logger.error("THREADS_ACCESS_TOKEN が設定されていません")
        sys.exit(1)

    # トークンリフレッシュ
    new_token = refresh_token(THREADS_ACCESS_TOKEN)

    # .envを更新（ローカル実行時）
    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()
        import re
        new_content = re.sub(
            r"THREADS_ACCESS_TOKEN=.*",
            f"THREADS_ACCESS_TOKEN={new_token}",
            content
        )
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(".env を更新しました")

    # GitHub Secretsへの更新案内
    update_github_secret(new_token)

    # 新トークンをファイルに出力（GitHub Actions で使用）
    token_path = "new_token.txt"
    try:
        with open(token_path, "w") as f:
            f.write(new_token)
        logger.info("new_token.txt に保存しました（GitHub Actionsが読み取ります）")
    finally:
        # ローカル実行時は即座に削除（GitHub Actions上ではworkflow側でrm -fする）
        import atexit
        atexit.register(lambda: os.path.exists(token_path) and os.remove(token_path))
    logger.info("=== リフレッシュ完了 ===")


if __name__ == "__main__":
    main()
