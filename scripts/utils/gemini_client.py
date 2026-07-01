"""
gemini_client.py
Gemini API呼び出しの共通ユーティリティ
タイムアウト・3段階フォールバック・エラーハンドリングを一元管理する

フォールバックチェーン（各モデルは別クォータ）:
  1. gemini-2.5-flash       (高品質・25件/日)
  2. gemini-2.5-flash-lite   (軽量・別枠)
  3. gemini-3-flash-preview  (次世代・別枠)
"""

import os
import time
from google import genai
from google.genai import types
from loguru import logger

# モデルチェーン: すべて異なるクォータを持つモデル
# ※ gemini-2.0-flash / gemini-2.0-flash-lite は2026年時点でfree tier枠=0のため使用しない
GEMINI_MODEL_CHAIN = [
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
]

# リクエストタイムアウト（ミリ秒）— 90秒でAPIが返さなければ強制終了
REQUEST_TIMEOUT_MS = 90_000


def _make_config(timeout_ms: int = REQUEST_TIMEOUT_MS) -> types.GenerateContentConfig:
    """タイムアウト付きのGenerateContentConfigを作る"""
    return types.GenerateContentConfig(
        httpOptions=types.HttpOptions(timeout=timeout_ms)
    )


def _is_retryable(e: Exception) -> bool:
    """フォールバックすべきエラーかどうか判定（429/503/500）"""
    err_str = str(e)
    return any(code in err_str for code in [
        "429", "RESOURCE_EXHAUSTED",  # レート制限
        "503", "UNAVAILABLE",          # サーバー過負荷
        "500", "INTERNAL",             # サーバー内部エラー
    ])


def call_gemini(prompt: str, api_key: str = None, system_instruction: str = None) -> str:
    """
    Gemini APIを呼び出す共通関数。

    Args:
        prompt: ユーザープロンプト
        api_key: APIキー（省略時は環境変数から取得）
        system_instruction: システム指示（声定義等をここに入れるとモデルが強く従う）

    動作:
    1. GEMINI_MODEL_CHAIN の各モデルを順番に試す
    2. 429 (レート制限) → 次のモデルへフォールバック
    3. タイムアウト / その他エラー → 即座にraiseして呼び出し元へ
    4. 全モデルが429 → 明確なRuntimeErrorを送出

    保証:
    - 最大待ち時間 = 90秒 × 3モデル + 5秒 × 2回sleep = 280秒（約5分）
    - 永久ハングは絶対にしない（90秒タイムアウトで強制切断）
    """
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")

    client = genai.Client(api_key=api_key)

    # system_instructionがある場合はconfigに含める
    if system_instruction:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            httpOptions=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        )
    else:
        config = _make_config()

    exhausted_models = []

    for i, model in enumerate(GEMINI_MODEL_CHAIN):
        try:
            logger.info(f"Gemini API呼び出し: {model} (attempt {i+1}/{len(GEMINI_MODEL_CHAIN)})")
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            if i > 0:
                logger.info(f"フォールバック成功: {model}")
            return response.text

        except Exception as e:
            if _is_retryable(e):
                exhausted_models.append(model)
                logger.warning(f"{model} → {type(e).__name__}: {str(e)[:100]}")
                if i < len(GEMINI_MODEL_CHAIN) - 1:
                    logger.info(f"→ 次のモデル {GEMINI_MODEL_CHAIN[i+1]} にフォールバック")
                    time.sleep(3)
                continue
            else:
                logger.error(f"{model} エラー: {type(e).__name__}: {str(e)[:300]}")
                raise

    model_list = ", ".join(exhausted_models)
    raise RuntimeError(
        f"Gemini API: 全モデルがレート制限中です ({model_list})。"
        f" 日の無料枠を使い切った可能性があります。"
        f" 1〜2時間後に自動リトライするか、手動でワークフローを再実行してください。"
    )
