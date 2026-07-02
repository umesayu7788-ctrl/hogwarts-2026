"""
funnel_designer.py
ファネル設計担当エージェント

役割:
- 1週間の投稿バランスを設計（教育5:興味付け4:アフィリ2 等）
- 「6つの教育」の要素を週単位で網羅
- アフィリ投稿のタイミング調整

出力: operation/weekly/funnel_YYYYWXX.md
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
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
WEEKLY_DIR = SCRIPT_DIR.parent / "operation" / "weekly"
KNOWLEDGE_DIR = SCRIPT_DIR.parent / "operation" / "knowledge"


# デフォルトの週次バランス（11投稿/週 = 1日1-2投稿 × 7日）
# ユーザーのナレッジに合わせて調整可能
DEFAULT_WEEKLY_BALANCE = {
    "education": 5,      # 教育投稿
    "interest": 4,       # 興味付け投稿
    "affiliate": 2,      # アフィリ投稿（週2回まで推奨）
}

# 推奨配置: 週7日 × 朝/夕/夜の3スロット = 21スロットのうち11投稿
# アフィリは週の中盤（フォロワーが温まった頃）に配置
DEFAULT_SCHEDULE = {
    "月": {"slot_1": "education", "slot_2": "interest", "slot_3": "skip"},
    "火": {"slot_1": "education", "slot_2": "skip", "slot_3": "interest"},
    "水": {"slot_1": "interest", "slot_2": "skip", "slot_3": "affiliate"},
    "木": {"slot_1": "education", "slot_2": "skip", "slot_3": "skip"},
    "金": {"slot_1": "education", "slot_2": "affiliate", "slot_3": "skip"},
    "土": {"slot_1": "education", "slot_2": "skip", "slot_3": "interest"},
    "日": {"slot_1": "interest", "slot_2": "skip", "slot_3": "skip"},
}


def load_six_education() -> str:
    """6つの教育ナレッジを読み込む"""
    path = KNOWLEDGE_DIR / "six_education_framework.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    if "このファイルはユーザーが記入してください" in content:
        logger.warning("6つの教育ナレッジが未記入です")
        return ""
    return content


def design_week(week_start: datetime) -> dict:
    """1週間のファネルを設計"""
    week_num = week_start.strftime("%YW%V")
    schedule = dict(DEFAULT_SCHEDULE)

    # 6つの教育の要素を5つの教育投稿に割り当て（例: 週5つの教育要素を網羅）
    education_slots = []
    for day, slots in schedule.items():
        for slot_key, post_type in slots.items():
            if post_type == "education":
                education_slots.append((day, slot_key))

    return {
        "week": week_num,
        "week_start": week_start.strftime("%Y-%m-%d"),
        "schedule": schedule,
        "balance": DEFAULT_WEEKLY_BALANCE,
        "education_slots_count": len(education_slots),
    }


def save_plan(plan: dict) -> Path:
    """週次計画を保存"""
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    filepath = WEEKLY_DIR / f"funnel_{plan['week']}.md"

    lines = [
        f"# 週次ファネル計画 {plan['week']}",
        "",
        f"**週開始日**: {plan['week_start']}",
        "",
        "## 投稿バランス",
        f"- 教育: {plan['balance']['education']}投稿",
        f"- 興味付け: {plan['balance']['interest']}投稿",
        f"- アフィリ: {plan['balance']['affiliate']}投稿（週2回まで）",
        "",
        "## 曜日別スケジュール",
        "",
        "| 曜日 | SLOT_1 (7時) | SLOT_2 (18時) | SLOT_3 (21時) |",
        "|---|---|---|---|",
    ]
    for day, slots in plan["schedule"].items():
        row = f"| {day} | {slots['slot_1']} | {slots['slot_2']} | {slots['slot_3']} |"
        lines.append(row)

    lines += [
        "",
        "## ライターへの指示",
        "- この計画に従って毎日の投稿タイプを選択",
        "- 教育投稿では「6つの教育」の要素を週で網羅",
        "- アフィリ投稿時は compliance_officer の審査を必ず通す",
        "- skipスロットの日は投稿生成をスキップ（品質優先）",
        "",
        "## 情報リサーチへの指示",
        "- 教育投稿: 一般的な学び・気づき・業界知識をリサーチ",
        "- 興味付け投稿: 読者の関心を引く切り口をリサーチ",
        "- アフィリ投稿: product_researcher の出力を参照",
    ]

    filepath.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"週次計画保存: {filepath.name}")
    return filepath


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="今週のファネルを初期化")
    parser.add_argument("--week-start", default="",
                        help="週開始日（YYYY-MM-DD、空なら今週の月曜）")
    args = parser.parse_args()

    logger.info("=== ファネル設計開始 ===")

    # 6つの教育ナレッジ確認
    six_edu = load_six_education()
    if not six_edu:
        logger.warning("6つの教育ナレッジが未記入のため、デフォルトバランスで設計します")

    # 週開始日の決定
    if args.week_start:
        week_start = datetime.strptime(args.week_start, "%Y-%m-%d")
    else:
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())

    plan = design_week(week_start)
    save_plan(plan)

    logger.info(f"=== ファネル設計完了 ({plan['week']}) ===")


if __name__ == "__main__":
    main()
