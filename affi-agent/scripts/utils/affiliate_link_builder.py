"""
affiliate_link_builder.py
商品URLをアフィリエイトリンクに変換する共通インターフェース
"""

import os
import re
from urllib.parse import quote
from loguru import logger

RAKUTEN_AFFILIATE_ID = os.getenv("RAKUTEN_AFFILIATE_ID", "")
AMAZON_ASSOCIATE_TAG = os.getenv("AMAZON_ASSOCIATE_TAG", "")


def build_rakuten_affiliate_url(product_url: str) -> str:
    """
    楽天商品URLをアフィリエイトリンクに変換
    形式: https://hb.afl.rakuten.co.jp/hgc/{AFFILIATE_ID}/?pc={エンコード済みURL}

    注意: 楽天APIから取得したaffiliateUrlを使う方が推奨。
    これは手動変換用。
    """
    if not RAKUTEN_AFFILIATE_ID:
        logger.warning("RAKUTEN_AFFILIATE_IDが未設定")
        return product_url

    encoded_url = quote(product_url, safe="")
    return f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/?pc={encoded_url}&m={encoded_url}"


def build_amazon_affiliate_url(product_url: str) -> str:
    """
    Amazon商品URLにアソシエイトタグを付与
    """
    if not AMAZON_ASSOCIATE_TAG:
        logger.warning("AMAZON_ASSOCIATE_TAGが未設定")
        return product_url

    # 既存の tag= パラメータがあれば置換、なければ追加
    if "tag=" in product_url:
        return re.sub(r"tag=[^&]*", f"tag={AMAZON_ASSOCIATE_TAG}", product_url)

    separator = "&" if "?" in product_url else "?"
    return f"{product_url}{separator}tag={AMAZON_ASSOCIATE_TAG}"


def build_affiliate_url(product_url: str, platform: str = "auto") -> str:
    """
    プラットフォーム自動判定でアフィリリンクを生成

    platform: "rakuten" / "amazon" / "auto"（URLから自動判定）
    """
    if platform == "auto":
        if "rakuten" in product_url:
            platform = "rakuten"
        elif "amazon" in product_url or "amzn" in product_url:
            platform = "amazon"
        else:
            logger.warning(f"プラットフォーム不明なURL: {product_url[:80]}")
            return product_url

    if platform == "rakuten":
        return build_rakuten_affiliate_url(product_url)
    elif platform == "amazon":
        return build_amazon_affiliate_url(product_url)
    else:
        return product_url


def extract_product_info_from_url(url: str) -> dict:
    """
    URLから商品識別情報を抽出
    Returns: {"platform": "rakuten"/"amazon", "id": 商品ID}
    """
    if "rakuten" in url:
        # 楽天URLから itemCode を抽出
        m = re.search(r"/([^/]+)/([^/]+)/?(\?|$)", url)
        return {"platform": "rakuten", "id": f"{m.group(1)}:{m.group(2)}" if m else ""}
    elif "amazon" in url:
        # AmazonURLからASINを抽出
        m = re.search(r"/dp/([A-Z0-9]{10})", url)
        return {"platform": "amazon", "id": m.group(1) if m else ""}
    return {"platform": "unknown", "id": ""}
