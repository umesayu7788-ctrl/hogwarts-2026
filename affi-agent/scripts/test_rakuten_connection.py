"""
test_rakuten_connection.py
楽天API（商品検索）の接続テスト。Secrets 設定後に手動実行する。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.rakuten_api import (
    RAKUTEN_ACCESS_KEY,
    RAKUTEN_AFFILIATE_ID,
    RAKUTEN_APP_ID,
    search_products,
)


def main() -> int:
    missing = []
    if not RAKUTEN_APP_ID:
        missing.append("RAKUTEN_APP_ID")
    if not RAKUTEN_ACCESS_KEY:
        missing.append("RAKUTEN_ACCESS_KEY")
    if not RAKUTEN_AFFILIATE_ID:
        missing.append("RAKUTEN_AFFILIATE_ID")

    if missing:
        print("未設定:", ", ".join(missing))
        print("GitHub Secrets または .env に3つすべて設定してください。")
        return 1

    print("楽天API接続テスト: キーワード「腸活 サプリ」...")
    items = search_products("腸活 サプリ", max_price=5000, hits=5)
    if not items:
        print("接続失敗、または条件に合う商品なし。APP_ID / ACCESS_KEY を確認してください。")
        return 2

    print(f"成功: {len(items)}件取得")
    for i, item in enumerate(items[:3], 1):
        name = (item.get("name") or "")[:50]
        price = item.get("price", "?")
        aff = "あり" if item.get("affiliate_url") else "なし"
        print(f"  {i}. {name} … {price}円（アフィリURL: {aff}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
