"""
auth_gate.py - 月次認証ゲート（GitHub Actions / ローカル両対応）

GitHub Actions環境:  HOG_MONTHLY_TOKEN シークレットで認証
ローカル環境:        operation/auth/*.key ファイルで認証

【月次キー受け取り時のClaude Code操作】
.key ファイルを受け取って「更新」と言うと、
Claude Code が自動でローカルファイルと GitHub Secret の両方を更新する。
"""

import os
import re
import sys
from datetime import date


_CS_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _expected_checksum(year: int, month: int) -> str:
    digit_sum = sum(int(c) for c in f"{year}{month:02d}")
    idx1 = digit_sum % 36
    idx2 = (digit_sum * 3 + 7) % 36
    return _CS_CHARS[idx1] + _CS_CHARS[idx2]


def _verify_token(token: str) -> tuple[bool, str]:
    """トークン文字列を検証する。Returns: (is_valid, message)"""
    m = re.match(r"^HOG-AUTH-(\d{4})-(\d{2})-([A-Z0-9]{8,})$", token)
    if not m:
        return False, "トークン形式が不正です。"

    token_year, token_month = int(m.group(1)), int(m.group(2))

    # チェックサム検証（偽造検知）
    suffix = m.group(3)
    cs = _expected_checksum(token_year, token_month)
    if not suffix.endswith(cs):
        return False, "トークンの整合性チェックに失敗しました（偽造の可能性）。"

    # 月の有効性チェック（当月のみ有効）
    today = date.today()
    if (token_year, token_month) != (today.year, today.month):
        return False, (
            f"トークンの月（{token_year}-{token_month:02d}）が現在の月と一致しません。\n"
            "コミュニティ管理者から最新のキーファイルを受け取ってください。"
        )

    return True, f"認証OK（{token_year}-{token_month:02d}）"


def main():
    # ── GitHub Actions環境: HOG_MONTHLY_TOKEN シークレットで認証 ─────────
    if os.environ.get("GITHUB_ACTIONS") == "true":
        token = os.environ.get("HOG_MONTHLY_TOKEN", "").strip()

        if not token:
            print(
                "[認証失敗] HOG_MONTHLY_TOKEN シークレットが設定されていません。\n"
                "月次キーファイルを受け取り、Claude Code で「更新」と入力して\n"
                "GitHub Secret を更新してください。",
                file=sys.stderr,
            )
            sys.exit(1)

        ok, msg = _verify_token(token)
        if not ok:
            print(f"[認証失敗] {msg}", file=sys.stderr)
            sys.exit(1)

        print(f"[認証OK] {msg} （GitHub Secret 確認済み）")
        return

    # ── ローカル環境: .key ファイルで認証 ────────────────────────────────
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from utils.auth_check import check_auth

    ok, msg = check_auth()
    if not ok:
        print(f"[認証失敗] {msg}", file=sys.stderr)
        sys.exit(1)

    print(f"[認証OK] {msg}")


if __name__ == "__main__":
    main()
