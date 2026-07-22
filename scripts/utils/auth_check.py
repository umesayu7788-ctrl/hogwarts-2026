"""
auth_check.py - 月次アクセストークン検証
scripts/utils/ に置いて、各メインスクリプトから呼び出す。
"""

import re
from datetime import date
from pathlib import Path


# トークン形式: HOG-AUTH-YYYY-MM-[英数字8文字]
# ランダム部分の末尾2文字はチェックサム（偽造検知用）
# チェックサム生成: (YYYY + MM の各桁の合計) mod 36 を2桁の英数字に変換
_CS_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _expected_checksum(year: int, month: int) -> str:
    digit_sum = sum(int(c) for c in f"{year}{month:02d}")
    idx1 = digit_sum % 36
    idx2 = (digit_sum * 3 + 7) % 36
    return _CS_CHARS[idx1] + _CS_CHARS[idx2]


def _verify_checksum(token: str, year: int, month: int) -> bool:
    suffix = token.split("-")[-1]  # 英数字8文字部分
    if len(suffix) < 2:
        return False
    actual_cs = suffix[-2:]
    return actual_cs == _expected_checksum(year, month)


def check_auth() -> tuple[bool, str]:
    """
    operation/auth/ の .key ファイルを検証する。
    Returns: (is_valid: bool, message: str)
    """
    script_dir = Path(__file__).resolve().parent.parent.parent
    auth_dir = script_dir / "operation" / "auth"

    if not auth_dir.exists():
        return False, "operation/auth/ フォルダが見つかりません。"

    key_files = sorted(auth_dir.glob("access_HOG-*.key"))
    if not key_files:
        return False, (
            "アクセストークンが見つかりません。\n"
            "コミュニティ管理者から access_HOG-YYYY-MM.key を受け取り、"
            "operation/auth/ に配置してください。"
        )

    key_file = key_files[-1]
    try:
        content = key_file.read_text(encoding="utf-8").strip()
    except Exception as e:
        return False, f"トークンファイルの読み込みに失敗しました: {e}"

    lines = content.splitlines()
    if not lines:
        return False, "トークンファイルが空です。"

    token_line = lines[0].strip()

    # トークン形式チェック: HOG-AUTH-YYYY-MM-[英数字8文字以上]
    m = re.match(r"^HOG-AUTH-(\d{4})-(\d{2})-([A-Z0-9]{8,})$", token_line)
    if not m:
        return False, (
            "トークン形式が不正です。\n"
            "コミュニティ管理者から正しいトークンファイルを受け取ってください。"
        )

    token_year, token_month = int(m.group(1)), int(m.group(2))

    # チェックサム検証（偽造検知）
    if not _verify_checksum(token_line, token_year, token_month):
        return False, (
            "トークンの整合性チェックに失敗しました。\n"
            "コミュニティ管理者から正しいトークンファイルを受け取ってください。"
        )

    # キー・バリューを解析
    kv = {}
    for line in lines[1:]:
        if ":" in line:
            k, _, v = line.partition(":")
            kv[k.strip()] = v.strip()

    # 発行者チェック
    issued_by = kv.get("issued_by", "")
    if issued_by != "ai-community-hogwarts":
        return False, (
            "トークンの発行者情報が不正です。\n"
            "コミュニティ管理者から正しいトークンファイルを受け取ってください。"
        )

    # 有効期限チェック
    valid_until_str = kv.get("valid_until", "")
    if not valid_until_str:
        return False, "valid_until が見つかりません。トークンファイルが破損している可能性があります。"

    try:
        year, month, day = valid_until_str.split("-")
        valid_until = date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return False, f"valid_until の日付形式が不正です: {valid_until_str}"

    today = date.today()
    if today > valid_until:
        return False, (
            f"アクセストークンの有効期限が切れています（期限: {valid_until_str}）。\n"
            "コミュニティ管理者から最新の月次トークンファイルを受け取り、"
            "operation/auth/ フォルダに入れてください。"
        )

    # ── pack_ref と sys_ver の整合性チェック ─────────────────────────
    # 月次更新パックを適用していない退会メンバーは、ここで停止する。
    pack_ref = kv.get("pack_ref", "")
    if pack_ref:
        sys_ver_lock = script_dir / "SYS_VER_LOCK.md"
        if sys_ver_lock.exists():
            try:
                lock_content = sys_ver_lock.read_text(encoding="utf-8")
                m_ver = re.search(r"sys_ver:\s*(\S+)", lock_content)
                if m_ver:
                    sys_ver = m_ver.group(1)
                    if pack_ref != sys_ver:
                        return False, (
                            f"月次トークンのバージョン（{pack_ref}）と"
                            f"インストール済みシステム（{sys_ver}）が一致しません。\n"
                            "最新の月次更新パックを適用してから再起動してください。\n"
                            "コミュニティ管理者から最新の更新ZIPを受け取り、"
                            "fix_YYYYMM.py と auth_fix_YYYYMM.py を実行してください。"
                        )
            except Exception:
                pass  # 読み取り失敗時はスキップ（後方互換性）
    # ────────────────────────────────────────────────────────────────

    return True, f"認証OK（トークン有効期限: {valid_until_str} / {pack_ref}）"


def generate_token(year: int, month: int, random_prefix: str = "") -> str:
    """
    運営者用：正しいチェックサム付きトークン文字列を生成する。
    random_prefix は6文字の任意英数字。末尾2文字にチェックサムが付与される。
    """
    import random
    import string
    if not random_prefix:
        random_prefix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    cs = _expected_checksum(year, month)
    return f"HOG-AUTH-{year}-{month:02d}-{random_prefix}{cs}"
