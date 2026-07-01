"""
restore_tree_history.py
過去のGitHub IssueのロンコメントからツリーテキストをSheetsの3〜5投稿目列に復元する。
既存データは上書きしない（空白セルのみ追記）。
"""

import os
import re
import time
import sys
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json")
SHEET_NAME = os.getenv("SHEETS_LOG_NAME", "投稿ログ")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Google Sheets APIレート制限対応: 60req/min → 1.2秒待機
SHEETS_REQUEST_INTERVAL = 1.2
SHEETS_RETRY_WAIT = 70
SHEETS_MAX_RETRIES = 3


def _get_sheets_client(credentials_path: str):
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        logger.error("gspread が未インストールです: pip install gspread google-auth")
        sys.exit(1)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if not os.path.isabs(credentials_path):
        credentials_path = os.path.join(_PROJECT_ROOT, credentials_path)

    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return gspread.authorize(creds)


def _sheets_update_with_retry(sheet, row: int, col: int, value: str) -> bool:
    for attempt in range(1, SHEETS_MAX_RETRIES + 1):
        try:
            time.sleep(SHEETS_REQUEST_INTERVAL)
            sheet.update_cell(row, col, value)
            return True
        except Exception as e:
            if "429" in str(e) or "Quota" in str(e):
                if attempt < SHEETS_MAX_RETRIES:
                    logger.warning(f"Sheets 429エラー。{SHEETS_RETRY_WAIT}秒待機して再試行 ({attempt}/{SHEETS_MAX_RETRIES})")
                    time.sleep(SHEETS_RETRY_WAIT)
                else:
                    logger.error(f"Sheets 429エラー: 最大リトライ回数超過。スキップします。")
                    return False
            else:
                logger.warning(f"Sheets更新エラー: {e}")
                return False
    return False


def fetch_all_issues() -> list:
    import urllib.request
    import json

    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.error("GITHUB_TOKEN または GITHUB_REPO が未設定です")
        sys.exit(1)

    issues = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/issues?state=closed&per_page=100&page={page}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        })
        with urllib.request.urlopen(req) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        issues.extend(batch)
        page += 1
        time.sleep(0.5)

    logger.info(f"GitHub Issueを{len(issues)}件取得しました")
    return issues


def fetch_issue_comments(issue_number: int) -> list:
    import urllib.request
    import json

    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues/{issue_number}/comments"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def extract_tree_parts(comment_body: str) -> list[str]:
    """
    ロンの投稿完了コメントから===THREAD===区切りのツリーテキストを抽出する。
    """
    # 「投稿完了」コメントブロックを検出
    pattern = r"投稿(?:完了|しました)[^\n]*\n(.*?)(?:\n---|\Z)"
    match = re.search(pattern, comment_body, re.DOTALL)
    if match:
        block = match.group(1).strip()
    else:
        # コメント全体から===THREAD===を探す
        if "===THREAD===" not in comment_body:
            return []
        block = comment_body

    parts = [p.strip() for p in block.split("===THREAD===") if p.strip()]
    return parts


def get_post_id_from_comment(comment_body: str) -> str:
    match = re.search(r"Post ID[:\s]+([0-9]+)", comment_body)
    if match:
        return match.group(1)
    return ""


def restore_history():
    from utils.sheets_logger import HEADERS

    if not SPREADSHEET_ID:
        logger.error("SPREADSHEET_ID が未設定です")
        sys.exit(1)

    client = _get_sheets_client(GOOGLE_CREDENTIALS_PATH)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        import gspread
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except Exception as e:
        logger.error(f"シート '{SHEET_NAME}' が見つかりません: {e}")
        sys.exit(1)

    # シートの全データを取得
    all_values = sheet.get_all_values()
    if not all_values:
        logger.warning("シートにデータがありません")
        return

    header_row = all_values[0]

    try:
        post_id_col = header_row.index("投稿ID")
        text3_col   = header_row.index("3投稿目テキスト（ツリー）")
        text4_col   = header_row.index("4投稿目テキスト（ツリー）")
        text5_col   = header_row.index("5投稿目テキスト（ツリー）")
    except ValueError as e:
        logger.error(f"必要な列が見つかりません。sheets_logger.pyのHEADERSを更新してシートのヘッダーを再作成してください: {e}")
        sys.exit(1)

    # post_id → 行インデックス のマップを作成
    post_id_to_row = {}
    for i, row in enumerate(all_values[1:], start=2):
        if len(row) > post_id_col and row[post_id_col].strip():
            post_id_to_row[row[post_id_col].strip()] = i

    logger.info(f"シートに{len(post_id_to_row)}件の投稿IDが見つかりました")

    # GitHub Issuesを取得してツリーテキストを復元
    issues = fetch_all_issues()
    restored_count = 0
    skipped_count = 0

    for issue in issues:
        issue_number = issue["number"]
        try:
            comments = fetch_issue_comments(issue_number)
        except Exception as e:
            logger.warning(f"Issue #{issue_number} のコメント取得失敗: {e}")
            continue
        time.sleep(0.3)

        for comment in comments:
            body = comment.get("body", "")
            if "===THREAD===" not in body:
                continue

            post_id = get_post_id_from_comment(body)
            parts = extract_tree_parts(body)

            if len(parts) < 3:
                continue

            if not post_id or post_id not in post_id_to_row:
                logger.debug(f"Issue #{issue_number}: Post ID {post_id!r} がシートに見つかりません")
                continue

            sheet_row_idx = post_id_to_row[post_id]
            row_data = all_values[sheet_row_idx - 1]

            def _cell_empty(col_idx: int) -> bool:
                return len(row_data) <= col_idx or not row_data[col_idx].strip()

            updated = False
            if len(parts) > 2 and _cell_empty(text3_col):
                if _sheets_update_with_retry(sheet, sheet_row_idx, text3_col + 1, parts[2]):
                    updated = True

            if len(parts) > 3 and _cell_empty(text4_col):
                if _sheets_update_with_retry(sheet, sheet_row_idx, text4_col + 1, parts[3]):
                    updated = True

            if len(parts) > 4 and _cell_empty(text5_col):
                if _sheets_update_with_retry(sheet, sheet_row_idx, text5_col + 1, parts[4]):
                    updated = True

            if updated:
                restored_count += 1
                logger.info(f"Issue #{issue_number} / Post {post_id}: {len(parts)}投稿分を復元しました")
            else:
                skipped_count += 1

    logger.info(f"復元完了: {restored_count}件復元 / {skipped_count}件スキップ（既存データあり）")


if __name__ == "__main__":
    restore_history()
