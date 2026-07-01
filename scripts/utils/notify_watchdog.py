"""
notify_watchdog.py
GAS Watchdog 警報通知ユーティリティ
gas-watchdog.yml から呼び出す（heredocのYAML構文エラーを避けるため別ファイル化）
"""

import os
import sys
import requests
import datetime


def send_watchdog_alert(status: str, webhook_url: str) -> None:
    """Watchdog警報をDiscordに送信する"""
    now_str = datetime.datetime.now().strftime("%H:%M JST")

    cause_map = {
        "no_issue": "GAS未発火の可能性（05:00に発火しなかった）",
        "hermione_not_done": "GASは発火したがハーマイオニー段階まで進んでいない",
    }
    cause = cause_map.get(status, f"不明な状態: {status}")

    message = (
        f"🔴 **GAS Watchdog 警報** （{now_str} 検知）\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"## 🚦 今あなたがすること: ⏳ **待つだけ**（追加対応不要）\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏰ 次の通知: 5〜10分後に通常の承認依頼通知が届きます\n"
        f"✅ 8:15 JST 承認デッドライン: 余裕で間に合います\n\n"
        f"📊 状況サマリ:\n"
        f"  ・推定原因: {cause}\n"
        f"  ・自動復旧: daily-cycle.yml を起動済み\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"## 📋 後で確認する場合\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"トラブルシュート手順書: `operation/WATCHDOG_TROUBLESHOOTING.md` を参照"
    )

    if not webhook_url:
        print("DISCORD_WEBHOOK_URL未設定 - 通知スキップ")
        return

    try:
        resp = requests.post(webhook_url, json={"content": message}, timeout=10)
        resp.raise_for_status()
        print(f"Discord Watchdog通知送信完了")
    except Exception as e:
        print(f"Discord通知失敗: {e}", file=sys.stderr)


if __name__ == "__main__":
    status = os.getenv("WATCHDOG_STATUS", "unknown")
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    send_watchdog_alert(status, webhook)
