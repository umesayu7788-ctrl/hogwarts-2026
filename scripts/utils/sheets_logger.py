"""
sheets_logger.py
投稿データをGoogle Sheetsに記録するユーティリティ
"""

import os
import json
from datetime import datetime
from loguru import logger

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# プロジェクトルート（scripts/ の親）を基準にパスを解決する
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# スプレッドシートのヘッダー定義
HEADERS = [
    "日付", "曜日", "スロット", "投稿時刻",
    "1投稿目テキスト", "2投稿目テキスト（ツリー）",
    "3投稿目テキスト（ツリー）", "4投稿目テキスト（ツリー）", "5投稿目テキスト（ツリー）",
    "投稿ID", "いいね数", "返信数", "リポスト数", "閲覧数",
    "GitHub Issue", "テーマ", "使用感情フック"
]


def _get_client(credentials_path: str):
    """gspreadクライアントを返す"""
    if not GSPREAD_AVAILABLE:
        raise ImportError("gspread が未インストールです。pip install gspread google-auth を実行してください。")
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.authorize(creds)


def ensure_sheet_headers(sheet) -> None:
    """シートにヘッダーがなければ追加する"""
    first_row = sheet.row_values(1)
    if not first_row or first_row[0] != "日付":
        sheet.insert_row(HEADERS, index=1)
        logger.info("Google Sheetsにヘッダーを追加しました")


def log_post(
    spreadsheet_id: str,
    credentials_path: str,
    slot: int,
    post_text: str,
    post_id: str,
    issue_number: int,
    sheet_name: str = "投稿ログ",
) -> bool:
    """
    投稿データをGoogle Sheetsに記録する。

    Args:
        spreadsheet_id: GoogleスプレッドシートのID（URLの /d/〇〇/ 部分）
        credentials_path: サービスアカウントJSONのパス
        slot: スロット番号（1=7時, 2=18時, 3=21時）
        post_text: 投稿テキスト（===THREAD=== 区切り込み）
        post_id: ThreadsのPost ID
        issue_number: GitHub Issue番号
        sheet_name: 書き込むシート名
    Returns:
        成功したら True
    """
    if not GSPREAD_AVAILABLE:
        logger.warning("gspreadが未インストールのためSheets記録をスキップします")
        return False

    if not spreadsheet_id or not credentials_path:
        logger.warning("SPREADSHEET_ID または GOOGLE_CREDENTIALS_PATH が未設定です")
        return False

    # 相対パスの場合はプロジェクトルートから解決する
    if not os.path.isabs(credentials_path):
        credentials_path = os.path.join(_PROJECT_ROOT, credentials_path)

    if not os.path.exists(credentials_path):
        logger.warning(f"認証ファイルが見つかりません: {credentials_path}")
        return False

    try:
        client = _get_client(credentials_path)
        spreadsheet = client.open_by_key(spreadsheet_id)

        # シートを取得（なければ作成）
        try:
            sheet = spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(HEADERS))
            logger.info(f"シート '{sheet_name}' を新規作成しました")

        ensure_sheet_headers(sheet)

        # テキストをツリー部分に分割（最大5投稿）
        parts = [p.strip() for p in post_text.split("===THREAD===") if p.strip()]
        text1 = parts[0] if len(parts) > 0 else post_text
        text2 = parts[1] if len(parts) > 1 else ""
        text3 = parts[2] if len(parts) > 2 else ""
        text4 = parts[3] if len(parts) > 3 else ""
        text5 = parts[4] if len(parts) > 4 else ""

        now = datetime.now()
        slot_labels = {1: "SLOT_1 (7時)", 2: "SLOT_2 (18時)", 3: "SLOT_3 (21時)"}
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]

        row = [
            now.strftime("%Y-%m-%d"),          # 日付
            weekdays[now.weekday()],            # 曜日
            slot_labels.get(slot, f"SLOT_{slot}"),  # スロット
            now.strftime("%H:%M"),              # 投稿時刻
            text1,                              # 1投稿目テキスト
            text2,                              # 2投稿目テキスト
            text3,                              # 3投稿目テキスト
            text4,                              # 4投稿目テキスト
            text5,                              # 5投稿目テキスト
            post_id,                            # 投稿ID
            "",                                 # いいね数（後で計測）
            "",                                 # 返信数
            "",                                 # リポスト数
            "",                                 # 閲覧数（後で計測）
            f"#{issue_number}",                 # GitHub Issue
            "",                                 # テーマ（手動入力用）
            "",                                 # 感情フック（手動入力用）
        ]

        sheet.append_row(row)
        logger.info(f"Google Sheetsに投稿データを記録しました: SLOT_{slot} / Post ID: {post_id}")
        return True

    except Exception as e:
        logger.warning(f"Google Sheets記録に失敗しました（スキップ）: {e}")
        return False


def update_engagement(
    spreadsheet_id: str,
    credentials_path: str,
    post_id: str,
    likes: int,
    replies: int,
    reposts: int,
    views: int = 0,
    sheet_name: str = "投稿ログ",
) -> bool:
    """
    24時間後のエンゲージメントデータ（いいね・返信・リポスト・閲覧数）をシートに更新する。
    """
    if not GSPREAD_AVAILABLE or not spreadsheet_id or not credentials_path:
        return False

    if not os.path.isabs(credentials_path):
        credentials_path = os.path.join(_PROJECT_ROOT, credentials_path)

    try:
        client = _get_client(credentials_path)
        sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)

        # post_idで行を検索
        post_id_col = HEADERS.index("投稿ID") + 1
        cell = sheet.find(str(post_id), in_column=post_id_col)
        if not cell:
            logger.warning(f"Post ID {post_id} がシートに見つかりません")
            return False

        row = cell.row
        likes_col   = HEADERS.index("いいね数") + 1
        replies_col = HEADERS.index("返信数") + 1
        reposts_col = HEADERS.index("リポスト数") + 1
        views_col   = HEADERS.index("閲覧数") + 1

        sheet.update_cell(row, likes_col,   likes)
        sheet.update_cell(row, replies_col, replies)
        sheet.update_cell(row, reposts_col, reposts)
        sheet.update_cell(row, views_col,   views)

        logger.info(f"エンゲージメントデータを更新: Post {post_id} → いいね{likes}/閲覧{views}")
        return True

    except Exception as e:
        logger.warning(f"エンゲージメント更新に失敗しました: {e}")
        return False
