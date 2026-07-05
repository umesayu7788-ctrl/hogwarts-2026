"""
rakuten_api.py
楽天ウェブサービス（商品検索・ランキング・レビュー）のラッパー

要件:
- RAKUTEN_APP_ID 環境変数が必要
- 楽天アフィリエイトID (RAKUTEN_AFFILIATE_ID) は任意
"""

import os
import re
import requests
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from loguru import logger


def _clean_affiliate_url(url: str) -> str:
    """新APIが返す affiliateUrl から rafcid 等の壊れる原因パラメータを除去する。
    rafcid (新portal applicationId tracking) が付くと redirect server が
    「リンク先が無効です」と判定するため。
    """
    if not url:
        return url
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        # 楽天アフィリのリダイレクトを壊す可能性があるパラメータを除外
        params.pop("rafcid", None)
        new_query = urlencode(params, doseq=True)
        cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path,
                              parsed.params, new_query, parsed.fragment))
        return cleaned
    except Exception:
        return url

RAKUTEN_APP_ID       = os.getenv("RAKUTEN_APP_ID", "")
RAKUTEN_AFFILIATE_ID = os.getenv("RAKUTEN_AFFILIATE_ID", "")
RAKUTEN_ACCESS_KEY   = os.getenv("RAKUTEN_ACCESS_KEY", "")

# 2026-02-10 以降の新API（旧 app.rakuten.co.jp は 2026-05-13 完全停止）
BASE_URL = "https://openapi.rakuten.co.jp/ichibams/api"


def _do_request(endpoint: str, params: dict) -> tuple[dict, int, str]:
    """楽天APIの内部リクエスト。戻り値: (data, status, body)
    新ポータル(2026-02以降)は許可ウェブサイトlistと一致するRefererヘッダーが必須。
    """
    headers = {
        "Referer": "https://github.com/umesayu7788-ctrl/hogwarts-2026",
        "Origin": "https://github.com",
        "User-Agent": "Mozilla/5.0 (compatible; AffiAgent/1.0)",
    }
    try:
        resp = requests.get(f"{BASE_URL}{endpoint}", params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return {}, resp.status_code, resp.text[:500]
        return resp.json(), 200, ""
    except Exception as e:
        return {}, 0, str(e)[:500]


def _request(endpoint: str, params: dict) -> dict:
    """楽天APIの共通リクエスト処理。
    400 エラー時は response body をログ出力。
    affiliateId が原因と思われる場合は除外して再試行。
    """
    if not RAKUTEN_APP_ID:
        logger.warning("RAKUTEN_APP_IDが未設定です")
        return {}

    params["applicationId"] = RAKUTEN_APP_ID
    if RAKUTEN_ACCESS_KEY:
        params["accessKey"] = RAKUTEN_ACCESS_KEY
    if RAKUTEN_AFFILIATE_ID:
        params["affiliateId"] = RAKUTEN_AFFILIATE_ID
    params["format"] = "json"

    data, status, body = _do_request(endpoint, params)
    if status == 200:
        return data

    # エラー時は本体ログ
    logger.error(f"楽天API失敗 ({endpoint}) status={status} body={body}")

    # 400 で affiliateId 起因の可能性が高ければ除外して再試行
    if status == 400 and "affiliateId" in params and (
        "affiliate" in body.lower() or "wrong parameter" in body.lower() or "invalid" in body.lower()
    ):
        logger.warning("affiliateId を除外して再試行します（アフィリリンクは無効化）")
        retry_params = {k: v for k, v in params.items() if k != "affiliateId"}
        data2, status2, body2 = _do_request(endpoint, retry_params)
        if status2 == 200:
            return data2
        logger.error(f"再試行も失敗 status={status2} body={body2}")

    return {}


def search_products(keyword: str, max_price: Optional[int] = None,
                    min_review_count: int = 10, min_review_average: float = 3.5,
                    hits: int = 10) -> list[dict]:
    """
    商品検索。価格帯・レビュー条件でフィルタリング。

    Returns: [{"name", "price", "url", "image", "review_count", "review_average", "item_code"}, ...]
    """
    params = {
        "keyword": keyword,
        "hits": hits,
        "sort": "-reviewCount",  # レビュー数の多い順（人気＝信頼）
    }
    if max_price:
        params["maxPrice"] = max_price

    data = _request("/IchibaItem/Search/20260401", params)
    items = []
    raw_items = data.get("items", data.get("Items", []))
    for entry in raw_items:
        item = entry.get("item", entry.get("Item", entry if isinstance(entry, dict) else {}))
        try:
            rc = int(item.get("reviewCount", item.get("review_count", 0)) or 0)
            ra = float(item.get("reviewAverage", item.get("review_average", 0)) or 0)
        except (TypeError, ValueError):
            rc, ra = 0, 0
        if rc < min_review_count:
            continue
        if ra < min_review_average:
            continue
        items.append({
            "name": item.get("itemName", ""),
            "price": item.get("itemPrice", 0),
            "url": item.get("itemUrl", ""),
            "affiliate_url": _clean_affiliate_url(item.get("affiliateUrl", "")),
            "image": (item.get("mediumImageUrls") or [{}])[0].get("imageUrl", ""),
            "review_count": item.get("reviewCount", 0),
            "review_average": item.get("reviewAverage", 0),
            "item_code": item.get("itemCode", ""),
            "shop_name": item.get("shopName", ""),
        })
    return items


def get_ranking(genre_id: Optional[str] = None, age: Optional[str] = None,
                sex: Optional[str] = None, hits: int = 30) -> list[dict]:
    """
    楽天ランキングを取得（旬・売れ筋商品）。

    genre_id: 楽天ジャンルID（指定なしで総合ランキング）
    age: 年代（10, 20, 30, 40, 50）
    sex: 性別（0=男性 / 1=女性）
    """
    params = {"page": 1}
    if genre_id:
        params["genreId"] = genre_id
    if age:
        params["age"] = age
    if sex:
        params["sex"] = sex

    data = _request("/IchibaItem/Ranking/20220601", params)  # ランキングAPIは新仕様の有無未確認・実装次回
    items = []
    for entry in data.get("items", data.get("Items", []))[:hits]:
        item = entry.get("item", entry.get("Item", entry if isinstance(entry, dict) else {}))
        items.append({
            "rank": item.get("rank", 0),
            "name": item.get("itemName", ""),
            "price": item.get("itemPrice", 0),
            "url": item.get("itemUrl", ""),
            "affiliate_url": _clean_affiliate_url(item.get("affiliateUrl", "")),
            "review_count": item.get("reviewCount", 0),
            "review_average": item.get("reviewAverage", 0),
            "item_code": item.get("itemCode", ""),
        })
    return items


def get_reviews(item_code: str) -> list[dict]:
    """
    商品のレビューを取得（楽天はレビューAPIが限定的のため、商品情報から取得する代替実装）
    現状、楽天APIではレビュー本文の取得は一部制限されている。
    """
    params = {"itemCode": item_code}
    data = _request("/IchibaItem/Search/20260401", params)
    items = data.get("Items", [])
    if not items:
        return []

    item = items[0].get("Item", {})
    return [{
        "review_count": item.get("reviewCount", 0),
        "review_average": item.get("reviewAverage", 0),
        "item_name": item.get("itemName", ""),
    }]
