"""
analytics_officer.py
分析官エージェント

役割:
- クリック数・購入数・報酬額を多角的に分析
- 同じ商品の繰り返し投稿戦略（意識付け）の判断
- クリック数に基づく投稿内容の戦略調整

出力: operation/analytics/YYYY-MM-DD.md
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
ANALYTICS_DIR = SCRIPT_DIR.parent / "operation" / "analytics"

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/sheets_service_account.json")


def load_affiliate_logs(days: int = 14) -> list[dict]:
    """Google Sheetsから直近のアフィリ投稿ログを取得"""
    try:
        from utils.sheets_logger import _get_client, _PROJECT_ROOT
        creds = GOOGLE_CREDENTIALS_PATH
        if not os.path.isabs(creds):
            creds = os.path.join(_PROJECT_ROOT, creds)
        if not os.path.exists(creds):
            logger.warning("認証ファイルなし。Sheets取得スキップ")
            return []

        client = _get_client(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet("投稿ログ")
        rows = sheet.get_all_values()
        if len(rows) < 2:
            return []

        headers = rows[0]
        data = []
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        def col(name):
            return headers.index(name) if name in headers else -1

        idx = {
            "date": col("日付"),
            "slot": col("スロット"),
            "likes": col("いいね数"),
            "views": col("閲覧数"),
            "affiliate": col("アフィリリンク"),
            "clicks": col("クリック数"),
            "purchases": col("購入数"),
            "revenue": col("報酬額"),
        }

        for row in rows[1:]:
            if idx["date"] < 0 or len(row) <= idx["date"]:
                continue
            if row[idx["date"]] < cutoff:
                continue
            data.append({
                "date": row[idx["date"]],
                "slot": row[idx["slot"]] if idx["slot"] >= 0 else "",
                "likes": int(row[idx["likes"]]) if idx["likes"] >= 0 and row[idx["likes"]].isdigit() else 0,
                "views": int(row[idx["views"]]) if idx["views"] >= 0 and row[idx["views"]].isdigit() else 0,
                "affiliate": row[idx["affiliate"]] if idx["affiliate"] >= 0 else "",
                "clicks": int(row[idx["clicks"]]) if idx["clicks"] >= 0 and row[idx["clicks"]].isdigit() else 0,
                "purchases": int(row[idx["purchases"]]) if idx["purchases"] >= 0 and row[idx["purchases"]].isdigit() else 0,
                "revenue": int(row[idx["revenue"]]) if idx["revenue"] >= 0 and row[idx["revenue"]].isdigit() else 0,
            })
        return data
    except Exception as e:
        logger.error(f"Sheets取得失敗: {e}")
        return []


def analyze(logs: list[dict]) -> dict:
    """アフィリ投稿の分析を実施"""
    affiliate_logs = [l for l in logs if l.get("affiliate")]
    if not affiliate_logs:
        return {"summary": "アフィリ投稿データなし"}

    total_clicks = sum(l["clicks"] for l in affiliate_logs)
    total_purchases = sum(l["purchases"] for l in affiliate_logs)
    total_revenue = sum(l["revenue"] for l in affiliate_logs)
    total_views = sum(l["views"] for l in affiliate_logs)

    ctr = round(total_clicks / total_views * 100, 2) if total_views > 0 else 0
    cvr = round(total_purchases / total_clicks * 100, 2) if total_clicks > 0 else 0

    # 商品別の集計
    by_product = {}
    for l in affiliate_logs:
        key = l["affiliate"][:50]
        if key not in by_product:
            by_product[key] = {"count": 0, "clicks": 0, "purchases": 0, "revenue": 0}
        by_product[key]["count"] += 1
        by_product[key]["clicks"] += l["clicks"]
        by_product[key]["purchases"] += l["purchases"]
        by_product[key]["revenue"] += l["revenue"]

    # 再投稿候補: クリック多いが購入少ない商品（意識付けで伸びる可能性）
    reinvest_candidates = [
        (k, v) for k, v in by_product.items()
        if v["clicks"] > 5 and v["purchases"] == 0 and v["count"] < 3
    ]
    # 昇格候補: 購入実績ある商品（繰り返し投稿で継続的に売れる）
    winners = [
        (k, v) for k, v in by_product.items()
        if v["purchases"] > 0
    ]

    return {
        "period_days": 14,
        "total_posts": len(affiliate_logs),
        "total_views": total_views,
        "total_clicks": total_clicks,
        "total_purchases": total_purchases,
        "total_revenue": total_revenue,
        "ctr": ctr,
        "cvr": cvr,
        "reinvest_candidates": reinvest_candidates[:5],
        "winners": winners[:5],
        "by_product": by_product,
    }


def save_report(analysis: dict, target_date: str) -> Path:
    """分析レポートをMarkdownで保存"""
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = ANALYTICS_DIR / f"{target_date}.md"

    lines = [
        f"# アフィリ分析レポート {target_date}",
        "",
        f"**分析期間**: 直近{analysis.get('period_days', 14)}日",
        f"**アフィリ投稿数**: {analysis.get('total_posts', 0)}件",
        f"**合計閲覧数**: {analysis.get('total_views', 0):,}",
        f"**合計クリック数**: {analysis.get('total_clicks', 0):,}",
        f"**合計購入数**: {analysis.get('total_purchases', 0):,}",
        f"**合計報酬額**: {analysis.get('total_revenue', 0):,}円",
        f"**CTR（クリック率）**: {analysis.get('ctr', 0)}%",
        f"**CVR（購入率）**: {analysis.get('cvr', 0)}%",
        "",
        "## 🔁 再投稿候補（クリックあり・未購入 → 意識付けで育てる）",
    ]
    for k, v in analysis.get("reinvest_candidates", []):
        lines.append(f"- `{k[:40]}` ({v['count']}回投稿 / クリック{v['clicks']} / 購入0)")

    lines += ["", "## 🏆 勝ちパターン商品（購入実績あり → 繰り返し投稿推奨）"]
    for k, v in analysis.get("winners", []):
        lines.append(f"- `{k[:40]}` ({v['count']}回投稿 / 購入{v['purchases']} / 報酬{v['revenue']}円)")

    lines += ["", "## 🎯 ライターへの戦略指示"]
    if analysis.get("winners"):
        lines.append("- 勝ちパターン商品を**週1-2回繰り返し投稿**。別角度で訴求")
    if analysis.get("reinvest_candidates"):
        lines.append("- 再投稿候補は**訴求を変えて再挑戦**。クリックはされているので商品は悪くない")
    if analysis.get("cvr", 0) < 2:
        lines.append("- CVRが低い。**口コミ引用・Before/After・比較型**の訴求を試す")
    if analysis.get("ctr", 0) < 0.5:
        lines.append("- CTRが低い。**冒頭フック・画像訴求**を強化")

    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")
    logger.info(f"分析レポート保存: {filepath.name}")
    return filepath


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--date", default="")
    args = parser.parse_args()

    logger.info("=== 分析官 実行開始 ===")
    logs = load_affiliate_logs(args.days)
    logger.info(f"ログ取得: {len(logs)}件")

    analysis = analyze(logs)
    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    save_report(analysis, target_date)

    logger.info("=== 分析官 完了 ===")


if __name__ == "__main__":
    main()
