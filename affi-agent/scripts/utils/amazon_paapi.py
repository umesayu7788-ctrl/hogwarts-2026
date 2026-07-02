"""
amazon_paapi.py
Amazon Product Advertising API v5 のラッパー

要件:
- AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, AMAZON_ASSOCIATE_TAG 環境変数が必要
- python-amazon-paapi5 パッケージが必要

注意: PA-APIは過去30日に1件以上のAmazonアソシエイト売上が必要（初期は利用不可）
"""

import os
from typing import Optional
from loguru import logger

AMAZON_ACCESS_KEY    = os.getenv("AMAZON_ACCESS_KEY", "")
AMAZON_SECRET_KEY    = os.getenv("AMAZON_SECRET_KEY", "")
AMAZON_ASSOCIATE_TAG = os.getenv("AMAZON_ASSOCIATE_TAG", "")
AMAZON_COUNTRY       = os.getenv("AMAZON_COUNTRY", "JP")


def _get_client():
    """PA-APIクライアントを取得"""
    if not (AMAZON_ACCESS_KEY and AMAZON_SECRET_KEY and AMAZON_ASSOCIATE_TAG):
        logger.warning("AmazonのAPI認証情報が未設定です")
        return None
    try:
        from amazon_paapi import AmazonApi
        return AmazonApi(
            AMAZON_ACCESS_KEY,
            AMAZON_SECRET_KEY,
            AMAZON_ASSOCIATE_TAG,
            AMAZON_COUNTRY,
        )
    except ImportError:
        logger.warning("amazon_paapiパッケージが未インストールです。pip install python-amazon-paapi")
        return None
    except Exception as e:
        logger.error(f"Amazon PA-APIクライアント生成失敗: {e}")
        return None


def search_products(keyword: str, max_price: Optional[int] = None,
                    min_reviews: int = 10, hits: int = 10) -> list[dict]:
    """
    商品検索。
    Returns: [{"name", "price", "url", "affiliate_url", "image", "review_count", "asin"}, ...]
    """
    client = _get_client()
    if not client:
        return []

    try:
        params = {
            "keywords": keyword,
            "item_count": hits,
        }
        if max_price:
            params["max_price"] = max_price * 100  # 円→銭

        result = client.search_items(**params)
        items = []
        for item in result.items or []:
            price_obj = getattr(item, "offers", None)
            price = 0
            if price_obj and price_obj.listings:
                price = price_obj.listings[0].price.amount

            items.append({
                "name": item.item_info.title.display_value if item.item_info and item.item_info.title else "",
                "price": int(price) if price else 0,
                "url": item.detail_page_url or "",
                "affiliate_url": item.detail_page_url or "",  # 既にアソシエイトタグ付与される
                "image": item.images.primary.large.url if item.images and item.images.primary else "",
                "asin": item.asin or "",
            })
        return items
    except Exception as e:
        logger.error(f"Amazon検索失敗: {e}")
        return []


def get_item_by_asin(asin: str) -> dict:
    """ASINで商品詳細を取得"""
    client = _get_client()
    if not client:
        return {}

    try:
        result = client.get_items(items=[asin])
        if not result.items:
            return {}
        item = result.items[0]
        return {
            "name": item.item_info.title.display_value if item.item_info and item.item_info.title else "",
            "url": item.detail_page_url or "",
            "asin": asin,
        }
    except Exception as e:
        logger.error(f"ASIN検索失敗 ({asin}): {e}")
        return {}
