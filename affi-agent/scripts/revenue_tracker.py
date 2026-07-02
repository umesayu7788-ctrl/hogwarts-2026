"""
revenue_tracker.py
収益トラッカーエージェント

役割:
- 楽天アフィリエイト・Amazonアソシエイトの実績を自動取得
- クリック数・購入数・報酬額を日次でSheetsに記録

注意:
- 楽天アフィリエイトレポートはAPI未公開（2026時点）。スクレイピング or 手動インポートの代替実装
- Amazon アソシエイトレポートも API公開は限定的。Report APIで日次取得可能だが認証要件が厳しい
- 本ファイルは「データが入力される前提のロジック」を実装し、データソース部分は将来差し替え可能に
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
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/sheets_service_account.json")


def fetch_rakuten_revenue(date: str) -> dict:
    """
    楽天アフィリエイトレポートを取得。
    現状APIが公開されていないため、Sheetsの「楽天手動入力」シートから読み取る。
    将来的にスクレイピングやAPIに置き換え可能。

    Returns: {"clicks": int, "purchases": int, "revenue": int}
    """
    try:
        from utils.sheets_logger import _get_client, _PROJECT_ROOT
        creds = GOOGLE_CREDENTIALS_PATH
        if not os.path.isabs(creds):
            creds = os.path.join(_PROJECT_ROOT, creds)
        if not os.path.exists(creds) or not SPREADSHEET_ID:
            return {"clicks": 0, "purchases": 0, "revenue": 0}

        client = _get_client(creds)
        try:
            sheet = client.open_by_key(SPREADSHEET_ID).worksheet("楽天アフィリ実績")
        except Exception:
            logger.info("楽天アフィリ実績シートなし。データ0で記録")
            return {"clicks": 0, "purchases": 0, "revenue": 0}

        rows = sheet.get_all_values()
        if len(rows) < 2:
            return {"clicks": 0, "purchases": 0, "revenue": 0}

        headers = rows[0]
        for row in rows[1:]:
            if row[0] == date:
                return {
                    "clicks": int(row[1]) if len(row) > 1 and row[1].isdigit() else 0,
                    "purchases": int(row[2]) if len(row) > 2 and row[2].isdigit() else 0,
                    "revenue": int(row[3]) if len(row) > 3 and row[3].isdigit() else 0,
                }
        return {"clicks": 0, "purchases": 0, "revenue": 0}
    except Exception as e:
        logger.error(f"楽天データ取得失敗: {e}")
        return {"clicks": 0, "purchases": 0, "revenue": 0}


def fetch_amazon_revenue(date: str) -> dict:
    """
    Amazonアソシエイトレポートを取得。
    現状はSheetsの「Amazon手動入力」シートから読み取る代替実装。
    """
    try:
        from utils.sheets_logger import _get_client, _PROJECT_ROOT
        creds = GOOGLE_CREDENTIALS_PATH
        if not os.path.isabs(creds):
            creds = os.path.join(_PROJECT_ROOT, creds)
        if not os.path.exists(creds) or not SPREADSHEET_ID:
            return {"clicks": 0, "purchases": 0, "revenue": 0}

        client = _get_client(creds)
        try:
            sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Amazonアフィリ実績")
        except Exception:
            logger.info("Amazonアフィリ実績シートなし。データ0で記録")
            return {"clicks": 0, "purchases": 0, "revenue": 0}

        rows = sheet.get_all_values()
        if len(rows) < 2:
            return {"clicks": 0, "purchases": 0, "revenue": 0}

        for row in rows[1:]:
            if row[0] == date:
                return {
                    "clicks": int(row[1]) if len(row) > 1 and row[1].isdigit() else 0,
                    "purchases": int(row[2]) if len(row) > 2 and row[2].isdigit() else 0,
                    "revenue": int(row[3]) if len(row) > 3 and row[3].isdigit() else 0,
                }
        return {"clicks": 0, "purchases": 0, "revenue": 0}
    except Exception as e:
        logger.error(f"Amazonデータ取得失敗: {e}")
        return {"clicks": 0, "purchases": 0, "revenue": 0}


def save_daily_revenue(date: str, rakuten: dict, amazon: dict) -> bool:
    """日次実績をSheetsの「収益サマリ」シートに記録"""
    try:
        from utils.sheets_logger import _get_client, _PROJECT_ROOT
        creds = GOOGLE_CREDENTIALS_PATH
        if not os.path.isabs(creds):
            creds = os.path.join(_PROJECT_ROOT, creds)
        if not os.path.exists(creds) or not SPREADSHEET_ID:
            return False

        client = _get_client(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        sheet_name = "収益サマリ"
        try:
            sheet = spreadsheet.worksheet(sheet_name)
        except Exception:
            import gspread
            sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)
            sheet.insert_row([
                "日付", "楽天クリック", "楽天購入", "楽天報酬",
                "Amazonクリック", "Amazon購入", "Amazon報酬",
                "合計クリック", "合計購入", "合計報酬",
            ], index=1)

        total_clicks = rakuten["clicks"] + amazon["clicks"]
        total_purchases = rakuten["purchases"] + amazon["purchases"]
        total_revenue = rakuten["revenue"] + amazon["revenue"]

        # 既存行を探して更新 or 新規追加
        rows = sheet.get_all_values()
        row_found = False
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] == date:
                sheet.update(f"A{i}:J{i}", [[
                    date,
                    rakuten["clicks"], rakuten["purchases"], rakuten["revenue"],
                    amazon["clicks"], amazon["purchases"], amazon["revenue"],
                    total_clicks, total_purchases, total_revenue,
                ]])
                row_found = True
                break

        if not row_found:
            sheet.append_row([
                date,
                rakuten["clicks"], rakuten["purchases"], rakuten["revenue"],
                amazon["clicks"], amazon["purchases"], amazon["revenue"],
                total_clicks, total_purchases, total_revenue,
            ])

        logger.info(f"収益記録: {date} | 合計報酬{total_revenue}円（クリック{total_clicks}/購入{total_purchases}）")
        return True
    except Exception as e:
        logger.error(f"収益記録失敗: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="",
                        help="対象日（YYYY-MM-DD、空なら昨日）")
    args = parser.parse_args()

    target_date = args.date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info(f"=== 収益トラッカー開始 (対象日: {target_date}) ===")

    rakuten = fetch_rakuten_revenue(target_date)
    amazon = fetch_amazon_revenue(target_date)

    logger.info(f"楽天: クリック{rakuten['clicks']} / 購入{rakuten['purchases']} / 報酬{rakuten['revenue']}円")
    logger.info(f"Amazon: クリック{amazon['clicks']} / 購入{amazon['purchases']} / 報酬{amazon['revenue']}円")

    save_daily_revenue(target_date, rakuten, amazon)

    logger.info("=== 収益トラッカー完了 ===")


if __name__ == "__main__":
    main()
