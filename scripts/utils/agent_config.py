"""
agent_config.py
エージェント表示名を operation/config/agent_names.json から読み込むユーティリティ。
スクリプト起動時に一度だけ読み込み、以降はキャッシュを使う。
"""
import json
import os

_DEFAULTS = {
    "system_name": "エージェントホグワーツ",
    "harry":    "ハリー",
    "hermione": "ハーマイオニー",
    "luna":     "ルーナ",
    "malfoy":   "マルフォイ",
    "ron":      "ロン",
    "snape":    "スネイプ",
}

_CONF = None
_CONF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "operation", "config", "agent_names.json"
)


def _load() -> dict:
    global _CONF
    if _CONF is None:
        try:
            with open(_CONF_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # _comment キーは無視する
            _CONF = {k: v for k, v in data.items() if not k.startswith("_")}
        except FileNotFoundError:
            _CONF = dict(_DEFAULTS)
    return _CONF


def name(role: str) -> str:
    """ロールIDから表示名を返す。例: name('hermione') → 'ハーマイオニー'"""
    return _load().get(role, _DEFAULTS.get(role, role))


def system_name() -> str:
    """システム名を返す。例: 'エージェントホグワーツ'"""
    return _load().get("system_name", _DEFAULTS["system_name"])
