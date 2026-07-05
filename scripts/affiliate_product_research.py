"""
affiliate_product_research.py
楽天商品リサーチ（hogwarts daily-cycle 用）

affi-agent/operation/products/YYYY-MM-DD.json を生成する。
"""

import json
import math
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
AFFI_SCRIPTS = SCRIPT_DIR.parent / "affi-agent" / "scripts"
PRODUCTS_DIR = SCRIPT_DIR.parent / "affi-agent" / "operation" / "products"
GENRE_CONFIG = SCRIPT_DIR.parent / "affi-agent" / "operation" / "config" / "genre_config.yaml"

sys.path.insert(0, str(AFFI_SCRIPTS))
from utils.rakuten_api import search_products  # noqa: E402

JST = timezone(timedelta(hours=9))


def _load_genre_config() -> dict:
    with open(GENRE_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _keywords(cfg: dict) -> list[str]:
    base = [k for k in cfg.get("product_keywords", []) if k]
    season_map = cfg.get("seasonal_keywords") or {}
    m = datetime.now(JST).month
    season = "spring" if m in (3, 4, 5) else "summer" if m in (6, 7, 8) else "autumn" if m in (9, 10, 11) else "winter"
    seasonal = [k for k in (season_map.get(season) or []) if k]
    kws = list(dict.fromkeys(base + seasonal))
    random.seed(int(datetime.now(JST).strftime("%Y%m%d")))
    random.shuffle(kws)
    return kws[:5]


def _score(p: dict, bonus: list[str]) -> float:
    rc = p.get("review_count", 0)
    ra = p.get("review_average", 0)
    price = p.get("price", 0)
    review_score = math.log10(max(rc, 10)) if rc > 0 else 0
    avg_score = (ra - 3.5) * 4 if ra >= 3.5 else 0
    if 1000 <= price <= 3500:
        price_score = 3.0
    elif price < 1000:
        price_score = 1.5
    elif price <= 5000:
        price_score = 2.0
    else:
        price_score = 0.5
    name = p.get("name", "").lower()
    genre_score = sum(0.5 for k in bonus if k.lower() in name)
    return review_score + avg_score + price_score + genre_score


def _connection(p: dict, conn_map: list[dict]) -> str:
    name = p.get("name", "").lower()
    for entry in conn_map:
        if any(k.lower() in name for k in (entry.get("keywords") or [])):
            return entry.get("connection") or ""
    return "腸活・食事デトックスの文脈で自然につながる商品"


def main() -> int:
    cfg = _load_genre_config()
    max_price = int((cfg.get("price_range") or {}).get("max", 5000))
    bonus = [k for k in (cfg.get("genre_bonus_keywords") or []) if k]
    conn_map = cfg.get("genre_connection_map") or []
    target_date = datetime.now(JST).strftime("%Y-%m-%d")

    print(f"=== Affiliate product research ({target_date}) ===")
    items: list[dict] = []
    seen: set[str] = set()
    for kw in _keywords(cfg):
        for p in search_products(keyword=kw, max_price=max_price, min_review_count=10,
                                 min_review_average=4.0, hits=10):
            code = p.get("item_code") or p.get("name", "")
            if code in seen:
                continue
            seen.add(code)
            p["search_keyword"] = kw
            items.append(p)
        time.sleep(1.2)

    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PRODUCTS_DIR / f"{target_date}.json"

    if not items:
        print("No products found")
        out_path.write_text(json.dumps({"date": target_date, "top3": [], "selected": None}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    scored = sorted(
        [{**p, "score": round(_score(p, bonus), 2), "sleep_connection": _connection(p, conn_map)} for p in items],
        key=lambda x: -x["score"],
    )
    top3 = scored[:3]
    payload = {
        "date": target_date,
        "generated_at": datetime.now(JST).isoformat(),
        "top3": top3,
        "selected": top3[0],
        "selection_mode": "auto",
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {out_path}")
    for i, p in enumerate(top3, 1):
        print(f"  {i}. {p['name'][:50]}... ¥{p['price']} score={p['score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
