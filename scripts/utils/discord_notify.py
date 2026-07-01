"""
discord_notify.py
各エージェントの稼働状況をDiscordにリッチエンベッドで送信するユーティリティ

見え方のイメージ（3列カード）:
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ ① ハーマイオニー│ │ ② ルーナ     │ │ ③ マルフォイ │
│ リサーチ&分析  │ │ ライティング  │ │ 校閲         │
│ ✅ 完了 07:02 │ │ ✅ 完了 07:08│ │ ✅ 完了 07:12│
└──────────────┘ └──────────────┘ └──────────────┘
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ ④ オーナー   │ │ ⑤ ロン       │ │ ⑥ ロン       │
│ 承認          │ │ 投稿         │ │ 計測（24h後） │
│ ⏳ 承認待ち  │ │ 🔒 待機中    │ │ 🔒 待機中    │
└──────────────┘ └──────────────┘ └──────────────┘
"""

import os
import requests
from loguru import logger
try:
    from utils.agent_config import name as _n, system_name as _sn
except ImportError:
    from agent_config import name as _n, system_name as _sn

# パイプラインステップ定義（github_issues.py と同期）
PIPELINE_STEPS = [
    ("hermione", "①② リサーチ＆分析", f"🔍 {_n('hermione')}"),
    ("luna",     "③  ライティング",    f"✍️  {_n('luna')}"),
    ("malfoy",   "④  校閲",            f"🧐 {_n('malfoy')}"),
    ("human",    "⑤  人間承認",        "👤 オーナー"),
    ("ron_post", "⑥  投稿",            f"📤 {_n('ron')}"),
    ("ron_fetch","⑦  計測（24h後）",   f"📊 {_n('ron')}"),
]

STATUS_ICON = {
    "waiting":  "🔒 待機中",
    "running":  "⚡ 実行中",
    "done":     "✅ 完了",
    "pending":  "⏳ 承認待ち",
    "skipped":  "⏭️  スキップ",
    "error":    "❌ エラー",
}

# ステータスに対応するエンベッドカラー
STATUS_COLOR = {
    "running":  0xF0A500,   # オレンジ（実行中）
    "done":     0x43B581,   # 緑（完了）
    "pending":  0xFAA61A,   # 黄（承認待ち）
    "error":    0xF04747,   # 赤（エラー）
    "default":  0x7289DA,   # 青（デフォルト）
}


def _get_embed_color(statuses: dict) -> int:
    """現在のパイプライン状態に応じた色を返す"""
    values = [s for s, _ in statuses.values()]
    if "error"   in values: return STATUS_COLOR["error"]
    if "running" in values: return STATUS_COLOR["running"]
    if "pending" in values: return STATUS_COLOR["pending"]
    all_done = all(s in ("done", "skipped") for s in values)
    if all_done: return STATUS_COLOR["done"]
    return STATUS_COLOR["default"]


def send_board(
    webhook_url: str,
    statuses: dict,
    issue_number: int,
    issue_url: str,
    date_str: str,
    title_suffix: str = "",
):
    """
    エージェントボードをDiscordに送信する。

    Args:
        statuses:      {step_key: (status, timestamp)} の辞書
        issue_number:  今日のGitHub Issue番号
        issue_url:     今日のGitHub Issue URL
        date_str:      日付文字列（例: "2026-04-05"）
        title_suffix:  タイトルに追加するメッセージ（例: "ハーマイオニー完了"）
    """
    if not webhook_url:
        logger.warning("DISCORD_WEBHOOK_URL が設定されていません。通知をスキップします。")
        return

    # 3列カードとしてfieldsを構築
    fields = []
    for key, label, agent_display in PIPELINE_STEPS:
        s, ts = statuses.get(key, ("waiting", "-"))
        icon = STATUS_ICON.get(s, s)
        fields.append({
            "name": f"{agent_display}",
            "value": f"{label}\n{icon}\n{ts}",
            "inline": True,  # 横3列に並ぶ
        })

    title = f"🏰 {_sn()} 運用ボード"
    if title_suffix:
        title += f"  ｜  {title_suffix}"

    payload = {
        "embeds": [{
            "title": title,
            "description": f"**{date_str}**  ｜  [Issue #{issue_number} を開く]({issue_url})",
            "color": _get_embed_color(statuses),
            "fields": fields,
            "footer": {
                "text": "GitHub Issue に「承認」とコメントすると投稿が進みます"
            },
        }]
    }

    resp = requests.post(webhook_url, json=payload)
    if resp.status_code in (200, 204):
        logger.info(f"Discord ボード通知送信: {title_suffix or 'update'}")
    else:
        logger.error(f"Discord 通知失敗: {resp.status_code} {resp.text}")


def send_approval_request(
    webhook_url: str,
    statuses: dict,
    issue_number: int,
    issue_url: str,
    date_str: str,
    post_preview: str = "",
):
    """承認依頼専用の通知（投稿プレビュー付き）"""
    if not webhook_url:
        return

    fields = []
    for key, label, agent_display in PIPELINE_STEPS:
        s, ts = statuses.get(key, ("waiting", "-"))
        icon = STATUS_ICON.get(s, s)
        fields.append({
            "name": agent_display,
            "value": f"{label}\n{icon}\n{ts}",
            "inline": True,
        })

    # 投稿プレビューフィールド
    if post_preview:
        preview_text = post_preview[:300] + ("…" if len(post_preview) > 300 else "")
        fields.append({
            "name": "📋 推奨投稿案（プレビュー）",
            "value": f"```\n{preview_text}\n```",
            "inline": False,
        })

    payload = {
        "content": "@here 👀 **投稿案の承認をお願いします！**",
        "embeds": [{
            "title": f"🏰 {_sn()} ｜ 承認待ち",
            "description": (
                f"**{date_str}**\n\n"
                f"{_n('luna')}と{_n('malfoy')}が投稿案を作成しました。\n"
                f"[Issue #{issue_number} を開いて「承認」とコメント]({issue_url})してください。"
            ),
            "color": STATUS_COLOR["pending"],
            "fields": fields,
            "footer": {"text": f"Issue に「承認」とコメント → {_n('ron')}が投稿を実行します"},
        }]
    }

    resp = requests.post(webhook_url, json=payload)
    if resp.status_code in (200, 204):
        logger.info("Discord 承認依頼通知送信")
    else:
        logger.error(f"Discord 通知失敗: {resp.status_code} {resp.text}")


def send_post_complete(
    webhook_url: str,
    issue_number: int,
    issue_url: str,
    post_id: str,
    post_text: str,
    date_str: str,
):
    """投稿完了通知"""
    if not webhook_url:
        return

    preview = post_text[:200] + ("…" if len(post_text) > 200 else "")
    payload = {
        "embeds": [{
            "title": "📤 Threads 投稿完了！",
            "description": f"**{date_str}**  ｜  [Issue #{issue_number}]({issue_url})",
            "color": STATUS_COLOR["done"],
            "fields": [
                {"name": "投稿ID", "value": f"`{post_id}`", "inline": True},
                {"name": "投稿テキスト", "value": f"```\n{preview}\n```", "inline": False},
            ],
            "footer": {"text": f"24時間後に{_n('ron')}が計測します"},
        }]
    }
    resp = requests.post(webhook_url, json=payload)
    if resp.status_code in (200, 204):
        logger.info("Discord 投稿完了通知送信")
    else:
        logger.error(f"Discord 通知失敗: {resp.status_code} {resp.text}")
