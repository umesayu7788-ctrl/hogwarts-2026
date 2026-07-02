"""
discord_notify.py
各エージェントの稼働状況をDiscordにリッチエンベッドで送信するユーティリティ

見え方のイメージ（3列カード）:
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ ① 情報リサーチ│ │ ② ライター     │ │ ③ 校閲 │
│ リサーチ&分析  │ │ ライティング  │ │ 校閲         │
│ ✅ 完了 07:02 │ │ ✅ 完了 07:08│ │ ✅ 完了 07:12│
└──────────────┘ └──────────────┘ └──────────────┘
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ ④ オーナー   │ │ ⑤ 投稿・計測       │ │ ⑥ 投稿・計測       │
│ 承認          │ │ 投稿         │ │ 計測（24h後） │
│ ⏳ 承認待ち  │ │ 🔒 待機中    │ │ 🔒 待機中    │
└──────────────┘ └──────────────┘ └──────────────┘
"""

import os
import requests
from loguru import logger

# 13体エージェント表示名（Discord webhook username用）
# 各エージェントがDiscord通知を送るときに `agent_key` を渡すと、このマップから表示名が引かれる
AGENT_DISPLAY_NAMES = {
    "commander":        "🏰 司令塔",
    "info_researcher":  "🔍 情報リサーチ",
    "writer":           "✍️ ライター",
    "reviewer":         "🧐 校閲",
    "poster":           "📤 投稿・計測",
    "monitor":          "🦉 監視",
    "product_researcher":  "🛒 商品リサーチ",
    "review_analyzer":     "⭐ 口コミ審査",
    "analytics_officer":   "📊 分析官",
    "compliance_officer":  "⚖️ コンプライアンス",
    "funnel_designer":     "📐 ファネル設計",
    "revenue_tracker":     "💰 収益トラッカー",
    "owner":               "👤 オーナー",
}


def _agent_payload_extras(agent_key: str | None) -> dict:
    """agent_keyに応じたusername等のペイロード追加項目を返す"""
    if not agent_key:
        return {}
    name = AGENT_DISPLAY_NAMES.get(agent_key)
    return {"username": name} if name else {}


# パイプラインステップ定義（github_issues.py と同期）
PIPELINE_STEPS = [
    ("info_researcher", "①② リサーチ＆分析", "🔍 情報リサーチ"),
    ("writer",     "③  ライティング",    "✍️  ライター"),
    ("reviewer",   "④  校閲",            "🧐 校閲"),
    ("human",    "⑤  人間承認",        "👤 オーナー"),
    ("ron_post", "⑥  投稿",            "📤 投稿・計測"),
    ("ron_fetch","⑦  計測（24h後）",   "📊 投稿・計測"),
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
    agent_key: str | None = None,
):
    """
    エージェントボードをDiscordに送信する。

    Args:
        statuses:      {step_key: (status, timestamp)} の辞書
        issue_number:  今日のGitHub Issue番号
        issue_url:     今日のGitHub Issue URL
        date_str:      日付文字列（例: "2026-04-05"）
        title_suffix:  タイトルに追加するメッセージ（例: "情報リサーチ完了"）
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

    title = "🏰 アフィリエージェント 運用ボード"
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

    resp = requests.post(webhook_url, json={**payload, **_agent_payload_extras(locals().get("agent_key"))})
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
    agent_key: str | None = None,
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
            "title": "🏰 アフィリエージェント ｜ 承認待ち",
            "description": (
                f"**{date_str}**\n\n"
                f"ライターと校閲が投稿案を作成しました。\n"
                f"[Issue #{issue_number} を開いて「承認」とコメント]({issue_url})してください。"
            ),
            "color": STATUS_COLOR["pending"],
            "fields": fields,
            "footer": {"text": "Issue に「承認」とコメント → 投稿・計測が投稿を実行します"},
        }]
    }

    resp = requests.post(webhook_url, json={**payload, **_agent_payload_extras(locals().get("agent_key"))})
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
    agent_key: str | None = None,
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
            "footer": {"text": "24時間後に投稿・計測が計測します"},
        }]
    }
    resp = requests.post(webhook_url, json={**payload, **_agent_payload_extras(locals().get("agent_key"))})
    if resp.status_code in (200, 204):
        logger.info("Discord 投稿完了通知送信")
    else:
        logger.error(f"Discord 通知失敗: {resp.status_code} {resp.text}")
