"""
auth_check.py - 認証（U2 Discord在籍 ＋ 月次トークンの二重判定）
scripts/utils/ に置いて、各メインスクリプトから呼び出す。

U2: DISCORD_USER_ID が kit-auth Worker で「在籍中」なら認証OK。
    そうでなければ従来の月次トークン(.key)で判定（移行期の二重判定）。
    Worker障害・未設定時も旧トークン判定へフォールバック＝既存稼働を壊さない。
"""

import os
import re
import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path


# ── U2（Discord在籍チェック）設定（env優先・既定は本番kit-auth） ──────────
_U2_ENDPOINT_DEFAULT = "https://kit-auth.8stn-y1010.workers.dev/"
_U2_KIT_DEFAULT = "hog"


def _u2_member_active() -> bool:
    """DISCORD_USER_ID が在籍中か kit-auth Worker に確認。
    未設定・非在籍・通信失敗のいずれも False（→ 旧月次トークン判定にフォールバック）。"""
    uid = os.environ.get("DISCORD_USER_ID", "").strip()
    if not uid:  # ローカル(始める)では auth_member.txt から取得
        try:
            uid = (Path(__file__).resolve().parent.parent.parent / "auth_member.txt").read_text(encoding="utf-8").strip()
        except Exception:
            uid = ""
    if not uid:
        return False
    endpoint = os.environ.get("LM_AUTH_ENDPOINT", _U2_ENDPOINT_DEFAULT)
    kit = os.environ.get("LM_AUTH_KIT", _U2_KIT_DEFAULT)
    try:
        sep = "&" if "?" in endpoint else "?"
        url = endpoint + sep + urllib.parse.urlencode({"id": uid, "kit": kit})
        req = urllib.request.Request(url, headers={"User-Agent": "lm-kit/1.0"})  # CloudflareがUA無しを403でブロックするため必須
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return bool(data.get("active"))
    except Exception:
        return False  # Worker障害等 → 旧トークン判定へ（fail-open・既存稼働を壊さない）


# トークン形式: HOG-AUTH-YYYY-MM-[英数字8文字]
# ランダム部分の末尾2文字はチェックサム（偽造検知用）
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
    """U2(Discord在籍)を優先。activeなら即OK。そうでなければ従来の月次トークン判定（二重判定）。"""
    if _u2_member_active():
        return True, "認証OK（Discord在籍 / U2）"
    return _legacy_check_auth()


def _legacy_check_auth() -> tuple[bool, str]:
    """（従来）operation/auth/ の .key ファイルを検証する。
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
