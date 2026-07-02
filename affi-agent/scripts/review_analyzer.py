"""
review_analyzer.py
口コミ審査担当エージェント

役割:
- 商品の口コミから高評価・低評価を抽出
- 投稿文に反映できる形で簡潔にまとめる

出力: operation/reviews/<product_id>.md
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
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
REVIEWS_DIR = SCRIPT_DIR.parent / "operation" / "reviews"
PRODUCTS_DIR = SCRIPT_DIR.parent / "operation" / "products"


def analyze_reviews_with_gemini(product: dict) -> str:
    """
    Geminiで商品情報から口コミ傾向を分析。
    実際の口コミ本文取得は楽天/Amazon APIの制約で限定的なため、
    レビュー数・平均評価・商品名から傾向を推論する。
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return "（Gemini未設定のため分析スキップ）"

    try:
        from utils.gemini_client import call_gemini
        prompt = f"""以下の商品について、レビュー数と平均評価から「買った人が高く評価しそうなポイント」
と「不満として出やすいポイント」を推論してください。
投稿文で使える「刺さる訴求ワード」を3つ提案してください。

商品名: {product.get('name', '')}
価格: {product.get('price', 0)}円
レビュー数: {product.get('review_count', 0)}
平均評価: {product.get('review_average', 0)}

出力フォーマット:
## 高評価の傾向
- （箇条書き3件）

## 低評価の傾向
- （箇条書き2件）

## 刺さる訴求ワード
1.
2.
3.
"""
        return call_gemini(prompt, gemini_key)
    except Exception as e:
        logger.error(f"Gemini分析失敗: {e}")
        return "（分析失敗）"


def save_review_analysis(product_id: str, product: dict, analysis: str) -> Path:
    """分析結果をMarkdownに保存"""
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = product_id.replace(":", "_").replace("/", "_")
    filepath = REVIEWS_DIR / f"{safe_id}.md"

    content = f"""# 口コミ分析: {product.get('name', 'Unknown')}

**商品ID**: {product_id}
**価格**: {product.get('price', 0)}円
**レビュー数**: {product.get('review_count', 0)}
**平均評価**: {product.get('review_average', 0)}
**分析日時**: {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

{analysis}

---

**URL**: {product.get('url', '')}
"""
    filepath.write_text(content, encoding="utf-8")
    logger.info(f"口コミ分析保存: {filepath.name}")
    return filepath


def analyze_products_from_file(date_str: str):
    """指定日のproducts.jsonから全商品の口コミを分析"""
    products_file = PRODUCTS_DIR / f"{date_str}.json"
    if not products_file.exists():
        logger.error(f"{products_file} が見つかりません。先に product_researcher.py を実行してください")
        sys.exit(1)

    data = json.loads(products_file.read_text(encoding="utf-8"))
    products = data.get("products", [])

    logger.info(f"=== 口コミ分析開始（{len(products)}件） ===")
    for product in products:
        pid = product.get("item_code") or product.get("asin") or product.get("url", "")[:50]
        analysis = analyze_reviews_with_gemini(product)
        save_review_analysis(pid, product, analysis)

    logger.info(f"=== 口コミ分析完了 ===")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="",
                        help="対象日（YYYY-MM-DD、空なら今日）")
    args = parser.parse_args()

    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    analyze_products_from_file(target_date)


if __name__ == "__main__":
    main()
