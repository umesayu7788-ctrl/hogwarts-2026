"""
auth_check.py — 認証（U2 Discord在籍 ＋ 月次トークンの二重判定）/ AFFI システム
─────────────────────────────────────────────────────────────────────
U2: DISCORD_USER_ID（環境変数 または auth_member.txt）が kit-auth Worker で「在籍中」なら認証OK。
    そうでなければ従来の月次トークン(.key)で判定（移行期の二重判定）。
    Worker障害・未設定時も旧トークン判定へフォールバック＝既存稼働を壊さない。
新規顧客はトークン不要：自分のDiscordユーザーIDを auth_member.txt に入れるだけで在籍確認が通る。
このファイルは編集禁止です（.claude/settings.json で deny されています）。
"""

import os
import re
import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

PREFIX = "AFFI"
COMMUNITY = "affi-agent"
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 36 chars

# 正規表現: AFFI-AUTH-YYYY-MM-XXXXXXXX (8文字以上、最後2文字がチェックサム)
TOKEN_REGEX = re.compile(rf"^{PREFIX}-AUTH-(\d{{4}})-(\d{{2}})-([A-Z0-9]{{6,}})([A-Z0-9]{{2}})$")

# ── U2（Discord在籍チェック）設定（env優先・既定は本番kit-auth） ──────────
_U2_ENDPOINT_DEFAULT = "https://kit-auth.8stn-y1010.workers.dev/"
_U2_KIT_DEFAULT = "affili"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _get_uid() -> str:
    """DiscordユーザーIDを取得：GitHub Actions は env、ローカルは auth_member.txt。"""
    uid = os.environ.get("DISCORD_USER_ID", "").strip()
    if uid:
        return uid
    try:
        return (_repo_root() / "auth_member.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _u2_member_active() -> bool:
    """在籍中か kit-auth Worker に確認。未設定・非在籍・通信失敗はすべて False（→旧トークン判定へ）。"""
    uid = _get_uid()
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


def _checksum(year: int, month: int, body: str) -> str:
    """独自チェックサム計算（AFFI 専用・ホグワーツ版とは異なる乗数・加数を使用）"""
    digit_sum = year + month
    for ch in body:
        digit_sum += CHARSET.index(ch)
    idx1 = (digit_sum * 5) % 36
    idx2 = (digit_sum * 7 + 13) % 36
    return CHARSET[idx1] + CHARSET[idx2]


def generate_token(year: int, month: int, body: Optional[str] = None) -> str:
    """新規トークンを生成（運営者専用）。"""
    import secrets
    if body is None:
        body = "".join(secrets.choice(CHARSET) for _ in range(6))
    cs = _checksum(year, month, body)
    return f"{PREFIX}-AUTH-{year:04d}-{month:02d}-{body}{cs}"


def _last_day_of_next_month(year: int, month: int) -> date:
    """発行月の翌月末日を返す（1ヶ月有効）"""
    if month == 12:
        next_y, next_m = year + 1, 1
    else:
        next_y, next_m = year, month + 1
    if next_m == 12:
        following_y, following_m = next_y + 1, 1
    else:
        following_y, following_m = next_y, next_m + 1
    from datetime import timedelta
    return date(following_y, following_m, 1) - timedelta(days=1)


def _kb_sys_ver() -> Optional[str]:
    """kb_sys_ref_v001.md のフロントマターから sys_ver を抽出"""
    kb_path = _repo_root() / "operation" / "knowledge" / "kb_sys_ref_v001.md"
    if not kb_path.exists():
        return None
    try:
        content = kb_path.read_text(encoding="utf-8")
        m = re.search(r"sys_ver:\s*([A-Z0-9\-]+)", content)
        return m.group(1) if m else None
    except Exception:
        return None


def check_auth() -> Tuple[bool, str]:
    """U2(Discord在籍)を優先。activeなら即OK。そうでなければ従来の月次トークン判定（二重判定）。"""
    if _u2_member_active():
        return True, "✅ 認証OK（Discord在籍 / U2）"
    return _legacy_check_auth()


def _legacy_check_auth() -> Tuple[bool, str]:
    """（従来）月次トークンの有効性を多層検証する。Returns: (ok, message)"""
    auth_dir = _repo_root() / "operation" / "auth"
    if not auth_dir.exists():
        return False, "コミュニティ会員（Discord在籍）が確認できませんでした。\nDiscordユーザーIDが正しいか、コミュニティに参加中かをご確認ください。"

    keys = list(auth_dir.glob(f"access_{PREFIX}-*.key"))
    if not keys:
        return False, "コミュニティ会員（Discord在籍）が確認できませんでした。\nDiscordユーザーIDが正しいか、コミュニティに参加中かをご確認ください。"

    keys.sort(reverse=True)
    key_file = keys[0]
    try:
        content = key_file.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"トークンファイルの読み込みに失敗: {e}"

    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return False, "トークンファイルが空です。"
    token = lines[0]

    m = TOKEN_REGEX.match(token)
    if not m:
        return False, f"トークン形式が不正です: {token}\n期待形式: {PREFIX}-AUTH-YYYY-MM-XXXXXXXX[CS]"

    year_s, month_s, body, cs = m.group(1), m.group(2), m.group(3), m.group(4)
    year, month = int(year_s), int(month_s)

    expected_cs = _checksum(year, month, body)
    if cs != expected_cs:
        return False, "チェックサム検証に失敗しました（偽造の可能性）。コミュニティ管理者から正しいトークンを再取得してください。"

    meta = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()

    issued_by = meta.get("issued_by", "")
    if issued_by != COMMUNITY:
        return False, f"発行元が不正です（期待: {COMMUNITY}, 実際: {issued_by}）"

    valid_until_s = meta.get("valid_until", "")
    if not valid_until_s:
        return False, "valid_until が記載されていません。"
    try:
        y, mo, d = [int(x) for x in valid_until_s.split("-")]
        valid_until = date(y, mo, d)
    except Exception:
        return False, f"valid_until の日付形式が不正です: {valid_until_s}"
    today = date.today()
    if today > valid_until:
        return False, "コミュニティ会員（Discord在籍）が確認できませんでした。継続中かご確認ください。"

    pack_ref = meta.get("pack_ref", "")
    kb_sys_ver = _kb_sys_ver()
    if pack_ref and kb_sys_ver and pack_ref != kb_sys_ver:
        return False, f"pack_ref ({pack_ref}) と kb_sys_ref_v001.md の sys_ver ({kb_sys_ver}) が一致しません。\n運営者にお問い合わせください。"

    return True, f"✅ 認証OK（有効期限: {valid_until_s}, 発行元: {issued_by}）"


if __name__ == "__main__":
    ok, msg = check_auth()
    print(msg)
    if not ok:
        import sys
        sys.exit(1)
