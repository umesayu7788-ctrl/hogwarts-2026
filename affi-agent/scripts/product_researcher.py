"""
product_researcher.py
商品リサーチ担当エージェント（ジャンル可変版）

役割:
- operation/config/genre_config.yaml で設定したジャンルから3候補をスコアリング選定
- レビューキーワードからの訴求語抽出
- 選定商品をライターが使える形でJSON保存

出力: operation/products/YYYY-MM-DD.json
  - top3: スコア順にTOP3の商品
  - selected: 自動選定された1商品（最高スコア）
  - sleep_connection: ジャンル軸への接続文（ライター用・キー名は後方互換のため固定）
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
import json
import argparse
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

# Issue 日付と一致させるため JST で揃える（GitHub Actions runner は UTC のため）
JST = timezone(timedelta(hours=9))


def _now_jst() -> datetime:
    return datetime.now(JST)

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
PRODUCTS_DIR = SCRIPT_DIR.parent / "operation" / "products"
KNOWLEDGE_DIR = SCRIPT_DIR.parent / "operation" / "knowledge"
GENRE_CONFIG_PATH = SCRIPT_DIR.parent / "operation" / "config" / "genre_config.yaml"


def _load_genre_config() -> dict:
    """ジャンル設定ファイルを読み込む（必須・空または未記入ならハードストップ）"""
    if not GENRE_CONFIG_PATH.exists():
        logger.error(f"ジャンル設定ファイルが見つかりません: {GENRE_CONFIG_PATH}")
        logger.error("Claude Code で「始める」と入力してジャンル設定を行ってください。")
        sys.exit(1)
    try:
        import yaml
        with open(GENRE_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"ジャンル設定の読み込みに失敗: {e}")
        sys.exit(1)
    # プレースホルダ残存チェック
    raw = GENRE_CONFIG_PATH.read_text(encoding="utf-8")
    if "{{" in raw and "}}" in raw:
        logger.error("operation/config/genre_config.yaml にプレースホルダ {{...}} が残っています。")
        logger.error("「始める」コマンドで質問に答えるか、手動で全ての {{...}} を実際の値に置き換えてください。")
        sys.exit(1)
    return cfg


def _genre_keywords() -> list[str]:
    cfg = _load_genre_config()
    return [k for k in cfg.get("product_keywords", []) if k and "{{" not in k]


def get_seasonal_keywords() -> list[str]:
    cfg = _load_genre_config()
    season_map = cfg.get("seasonal_keywords", {}) or {}
    m = _now_jst().month
    if m in (3, 4, 5):
        season = "spring"
    elif m in (6, 7, 8):
        season = "summer"
    elif m in (9, 10, 11):
        season = "autumn"
    else:
        season = "winter"
    return [k for k in (season_map.get(season) or []) if k and "{{" not in k]


def _max_price() -> int:
    cfg = _load_genre_config()
    return int((cfg.get("price_range") or {}).get("max", 5000))


def _genre_bonus_keywords() -> list[str]:
    cfg = _load_genre_config()
    return [k for k in (cfg.get("genre_bonus_keywords") or []) if k and "{{" not in k]


def _genre_connection_map() -> list[dict]:
    cfg = _load_genre_config()
    return cfg.get("genre_connection_map") or []


def load_purchase_rules() -> str:
    path = KNOWLEDGE_DIR / "product_purchase_rules.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def search_genre_products() -> list[dict]:
    """ジャンル設定のキーワードで楽天検索し、候補を集める"""
    try:
        from utils.rakuten_api import search_products
    except ImportError as e:
        logger.error(f"rakuten_api import失敗: {e}")
        return []

    base_kw = _genre_keywords()
    if not base_kw:
        logger.error("operation/config/genre_config.yaml の product_keywords が空です。")
        sys.exit(1)
    keywords = list(base_kw) + get_seasonal_keywords()
    random.seed(int(_now_jst().strftime("%Y%m%d")))
    random.shuffle(keywords)
    keywords = keywords[:5]  # 1日5キーワードのみ呼び出し（API節約）

    max_price = _max_price()
    import time as _time
    all_items = []
    for kw in keywords:
        items = search_products(
            keyword=kw,
            max_price=max_price,
            min_review_count=10,       # レビュー数10以上
            min_review_average=4.0,    # ★4.0以上
            hits=10,
        )
        for it in items:
            it["search_keyword"] = kw
        all_items.extend(items)
        _time.sleep(1.2)  # 楽天新APIのレート制限対策（1QPS設定）

    # 重複（同じitem_code）を排除
    seen = set()
    deduped = []
    for it in all_items:
        code = it.get("item_code", "")
        if code in seen:
            continue
        seen.add(code)
        deduped.append(it)

    return deduped


def score_product(p: dict) -> float:
    """商品スコアリング（高いほど良い）

    要素:
    - レビュー数（多いほど良い、log scale）
    - レビュー平均（高いほど良い）
    - 価格（中価格帯ボーナス）
    - ジャンルボーナスキーワード合致
    """
    import math

    review_count = p.get("review_count", 0)
    review_avg = p.get("review_average", 0)
    price = p.get("price", 0)

    # レビュー数（log）: 50件→2.5, 500件→5, 5000件→7.5
    review_score = math.log10(max(review_count, 10)) if review_count > 0 else 0

    # レビュー平均: 4.0→4, 4.5→6, 4.8→7.2
    avg_score = (review_avg - 3.5) * 4 if review_avg >= 3.5 else 0

    # 価格バランス: 1000-3500円が最も買われやすい
    if 1000 <= price <= 3500:
        price_score = 3.0
    elif price < 1000:
        price_score = 1.5
    elif price <= 5000:
        price_score = 2.0
    else:
        price_score = 0.5

    # 商品名のジャンル軸キーワード合致（genre_config.yaml の genre_bonus_keywords）
    name = p.get("name", "").lower()
    bonus_keywords = _genre_bonus_keywords()
    genre_score = sum(1 for k in bonus_keywords if k.lower() in name) * 0.5

    return review_score + avg_score + price_score + genre_score


def detect_genre_connection(p: dict) -> str:
    """商品からジャンル軸への接続文を自動生成（genre_config.yaml の genre_connection_map ベース）"""
    name = p.get("name", "").lower()
    for entry in _genre_connection_map():
        kws = entry.get("keywords") or []
        conn = entry.get("connection") or ""
        if not conn:
            continue
        if any(k.lower() in name for k in kws if k):
            return conn
    return "毎日の暮らしの工夫が、最終的にあなたのジャンル軸の価値に繋がる商品。"


def select_top_candidates(items: list[dict], n: int = 3) -> list[dict]:
    """スコア順でTOP-Nを選出"""
    scored = [(score_product(p), p) for p in items]
    scored.sort(key=lambda x: -x[0])

    top = []
    for score, p in scored[:n]:
        p_with_score = dict(p)
        p_with_score["score"] = round(score, 2)
        p_with_score["sleep_connection"] = detect_genre_connection(p)  # 後方互換のキー名
        top.append(p_with_score)
    return top


def save_products(top3: list[dict], target_date: str) -> Path:
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = PRODUCTS_DIR / f"{target_date}.json"

    selected = top3[0] if top3 else None  # 自動選定はスコア最高

    payload = {
        "date": target_date,
        "generated_at": _now_jst().isoformat(),
        "top3": top3,
        "selected": selected,  # ライターはこれを使う
        "selection_mode": "auto",  # 将来的に "manual" 対応予定
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(f"商品リスト保存: {filepath}")
    if selected:
        logger.info(f"自動選定: {selected['name'][:60]}... (score={selected['score']})")
    return filepath


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="genre",
                        choices=["genre", "trending", "keyword"])
    parser.add_argument("--keyword", default="")
    parser.add_argument("--date", default="")
    args = parser.parse_args()

    target_date = args.date or _now_jst().strftime("%Y-%m-%d")
    logger.info(f"=== 商品リサーチ開始 (mode={args.mode}, date={target_date}) ===")

    rules = load_purchase_rules()
    if not rules or "このファイルはユーザーが記入してください" in rules:
        logger.warning("商品購入ルール未記入だが続行")

    if args.mode == "genre":
        items = search_genre_products()
    elif args.mode == "trending":
        from utils.rakuten_api import get_ranking
        items = get_ranking(hits=30)
    elif args.mode == "keyword":
        if not args.keyword:
            logger.error("--keyword 必須"); sys.exit(1)
        from utils.rakuten_api import search_products
        items = search_products(keyword=args.keyword, max_price=5000, hits=15)
    else:
        items = []

    if not items:
        logger.warning("商品が見つかりませんでした。空ファイルを保存します。")
        save_products([], target_date)
        return

    top3 = select_top_candidates(items, n=3)
    save_products(top3, target_date)

    logger.info(f"=== 商品リサーチ完了 ({len(top3)}/{len(items)}件) ===")
    for i, p in enumerate(top3, 1):
        logger.info(f"  候補{i}: {p['name'][:50]}... ★{p['review_average']} ({p['review_count']}件) ¥{p['price']}")


if __name__ == "__main__":
    main()
