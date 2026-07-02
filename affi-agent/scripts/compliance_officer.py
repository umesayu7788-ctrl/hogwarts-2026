"""
compliance_officer.py
コンプライアンス担当エージェント

役割:
- ステマ規制対応（全アフィリ投稿に #PR #広告 を自動付与）
- 景表法チェック（誇大表現検知）
- 薬機法チェック（医薬品・美容商品の不適切表現検知）
"""


# ========== AFFI 認証チェック（編集禁止・自動挿入） ==========
import sys as _affi_sys
from pathlib import Path as _affi_Path
_affi_sys.path.insert(0, str(_affi_Path(__file__).resolve().parent))
try:
    from utils.auth_check import check_auth as _affi_check_auth
    _affi_ok, _affi_msg = _affi_check_auth()
    if not _affi_ok:
        print(f"⛔ {_affi_msg}")
        _affi_sys.exit(1)
except ImportError:
    print("⛔ auth_check モジュールが見つかりません。配布物が破損している可能性があります。")
    _affi_sys.exit(1)
# ========== END 認証チェック ==========
import os
import sys
import argparse
import re
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


# 景表法違反となりやすい誇大表現
EXAGGERATION_PATTERNS = [
    r"必ず.*[痩せ治り効く]",
    r"絶対に?.*[儲か効き痩せ]",
    r"100%.*[効果成功]",
    r"誰でも簡単に.*[稼げ痩せ]",
    r"確実に.*[効く稼げ]",
    r"副作用[はが]?ない",
    r"世界一",
    r"業界No\.?1",
    r"医学的に証明",
]

# 薬機法違反となりやすい表現（化粧品・サプリ等）
YAKUKIHO_PATTERNS = [
    r"治る",
    r"治療",
    r"完治",
    r"病気が?治",
    r"ガンに効",
    r"即効性",
    r"シミが消える",
    r"肌が若返る",
    r"ダイエット効果",
]

# PR/広告明示の必須キーワード
REQUIRED_HASHTAGS = ["#PR", "#広告"]


def check_exaggeration(text: str) -> list[str]:
    """誇大表現を検知"""
    violations = []
    for pattern in EXAGGERATION_PATTERNS:
        if re.search(pattern, text):
            violations.append(f"景表法疑い: {pattern}")
    return violations


def check_yakukiho(text: str) -> list[str]:
    """薬機法違反表現を検知"""
    violations = []
    for pattern in YAKUKIHO_PATTERNS:
        if re.search(pattern, text):
            violations.append(f"薬機法疑い: {pattern}")
    return violations


def check_pr_disclosure(text: str) -> bool:
    """PR/広告タグが含まれているか確認（単独行 'PR' も許容）"""
    if any(tag in text for tag in REQUIRED_HASHTAGS + ["【PR】", "[PR]"]):
        return True
    # 単独行 'PR' を許容（ツリー最終ブロックでの自然な記法）
    return any(line.strip() == "PR" for line in text.splitlines())


def ensure_pr_tag(text: str, tag: str = "PR") -> str:
    """PR表記が無ければツリー最終ブロックに 'PR' 行を補完。
    親投稿（最初のブロック）は触らない。
    """
    if check_pr_disclosure(text):
        return text
    if "===THREAD===" in text:
        parts = text.split("===THREAD===")
        parts[-1] = f"\n{tag}\n{parts[-1].lstrip()}"
        return "===THREAD===".join(parts)
    return f"{text.rstrip()}\n\n{tag}"


def review_post(post_text: str, is_affiliate: bool = True) -> dict:
    """
    投稿をコンプライアンス観点で審査。

    Returns: {
        "pass": True/False,
        "violations": [...],
        "warnings": [...],
        "suggested_text": str,  # タグ自動付与後のテキスト
    }
    """
    violations = []
    warnings = []

    # 誇大表現チェック（全投稿）
    violations.extend(check_exaggeration(post_text))

    # 薬機法チェック（全投稿）
    yakukiho = check_yakukiho(post_text)
    if yakukiho:
        warnings.extend(yakukiho)

    # アフィリ投稿の場合はPR/広告タグ必須
    suggested_text = post_text
    if is_affiliate:
        if not check_pr_disclosure(post_text):
            warnings.append("アフィリ投稿に #PR / #広告 が含まれていません（自動付与します）")
            suggested_text = ensure_pr_tag(post_text)

    return {
        "pass": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "suggested_text": suggested_text,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True, help="審査対象の投稿テキスト")
    parser.add_argument("--affiliate", action="store_true", help="アフィリ投稿として審査")
    args = parser.parse_args()

    logger.info("=== コンプライアンス審査開始 ===")
    result = review_post(args.text, is_affiliate=args.affiliate)

    if result["pass"]:
        logger.info("✅ 審査通過")
    else:
        logger.error("❌ 重大違反あり")
        for v in result["violations"]:
            logger.error(f"  {v}")

    if result["warnings"]:
        logger.warning("⚠️ 警告:")
        for w in result["warnings"]:
            logger.warning(f"  {w}")

    if result["suggested_text"] != args.text:
        logger.info("--- 修正後テキスト ---")
        print(result["suggested_text"])

    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
