"""
snape_report.py
スネイプ担当: 週次コスト・エンゲージメント監視レポートを生成するスクリプト
毎週月曜日に GitHub Actions から自動実行
"""

import os
import csv
from datetime import datetime, timedelta
from pathlib import Path
from utils.github_issues import GitHubIssues
from dotenv import load_dotenv
from loguru import logger
from utils.agent_config import name as _n

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("GITHUB_REPO")

SCRIPT_DIR      = Path(__file__).resolve().parent
WEEKLY_DIR      = SCRIPT_DIR / ".." / "operation" / "weekly"
API_USAGE_CSV   = WEEKLY_DIR / "api_usage_log.csv"


def get_weekly_issues(gh: GitHubIssues) -> list:
    """今週（月〜日）の運用ループIssueを取得する"""
    today  = datetime.now()
    monday = today - timedelta(days=today.weekday())
    monday_str = monday.strftime("%Y-%m-%d")

    issues = []
    all_issues = gh.repo.get_issues(
        state="all",
        labels=["daily-operation"],
        since=monday,
    )
    for issue in all_issues:
        issues.append(issue)
    return issues


def parse_engagement_from_issue(issue) -> dict:
    """Issueのコメントからエンゲージメントデータを取得する"""
    data = {"likes": 0, "replies": 0, "reposts": 0, "posted": False}
    comments = list(issue.get_comments())
    for comment in comments:
        if "エンゲージメント計測結果" in comment.body:
            lines = comment.body.split("\n")
            for line in lines:
                if "いいね" in line and "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        try:
                            num = "".join(filter(str.isdigit, parts[2]))
                            data["likes"] = int(num) if num else 0
                        except Exception:
                            pass
                if "返信" in line and "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        try:
                            data["replies"] = int("".join(filter(str.isdigit, parts[2])) or "0")
                        except Exception:
                            pass
        if "投稿完了" in comment.body:
            data["posted"] = True
    return data


def generate_snape_report(weekly_issues: list, week_str: str) -> str:
    """スネイプの週次レポートを生成する"""
    post_count   = sum(1 for d in weekly_issues if d["engagement"]["posted"])
    likes_list   = [d["engagement"]["likes"] for d in weekly_issues if d["engagement"]["posted"]]
    avg_likes    = sum(likes_list) / len(likes_list) if likes_list else 0
    buzz_count   = sum(1 for l in likes_list if l >= 50)
    max_likes    = max(likes_list) if likes_list else 0

    report = f"""# スネイプ週次監視レポート {week_str}

## ① コスト状況
| サービス | 今週使用量 | 無料枠残量 | 危険度 |
|---|---|---|---|
| Gemini Flash | 確認中 | 確認中 | 🟢 |
| YouTube API | 確認中 | 確認中 | 🟢 |
| Threads API | {post_count}回 | 制限なし | 🟢 |
| GitHub API | 確認中 | 確認中 | 🟢 |

*※ API残量は各コンソールで手動確認してください*

## ② エンゲージメント推移
| 指標 | 今週 |
|---|---|
| 投稿数 | {post_count} |
| 平均いいね | {avg_likes:.1f} |
| バズ投稿数（50+） | {buzz_count} |
| 最高いいね | {max_likes} |

## ③ 問題発生記録
（今週のエラー・問題があればここに記録）

## ④ 改善提案（最大3件）
{f'1. 平均いいねが低い場合: {_n("luna")}に文体の微調整を依頼する' if avg_likes < 20 else '1. 良好なパフォーマンスを維持中'}
{f'2. バズ率向上のため: {_n("hermione")}にトレンド分析の精度向上を依頼する' if buzz_count == 0 else ''}
3. 無料枠の消費状況を来週も引き続き監視する

## ⑤ 来週の注意事項
- 投稿テーマのマンネリ化に注意
- Gemini APIの無料枠残量を週初めに確認すること
- GitHub Issues の承認待ちが滞留していないか確認すること
"""
    return report


def main():
    logger.info("=== スネイプ 週次レポート生成開始 ===")

    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)

    # 今週のIssueを取得
    raw_issues    = get_weekly_issues(gh)
    weekly_issues = []
    for issue in raw_issues:
        engagement = parse_engagement_from_issue(issue)
        weekly_issues.append({"issue": issue, "engagement": engagement})

    # 週番号
    now      = datetime.now()
    week_str = now.strftime("%Y年W%V")
    week_num = now.strftime("%YW%V")

    # レポート生成
    report = generate_snape_report(weekly_issues, week_str)

    # ファイル保存
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    report_path = WEEKLY_DIR / f"snape_report_{week_num}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"レポート保存: {report_path}")

    # API使用量ログCSVの更新
    if not API_USAGE_CSV.exists():
        with open(API_USAGE_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["週", "投稿数", "平均いいね", "バズ数", "Gemini使用量", "YouTube使用量"])

    likes_list = [d["engagement"]["likes"] for d in weekly_issues if d["engagement"]["posted"]]
    avg_likes  = sum(likes_list) / len(likes_list) if likes_list else 0
    buzz_count = sum(1 for l in likes_list if l >= 50)

    with open(API_USAGE_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([week_str, len(likes_list), f"{avg_likes:.1f}", buzz_count, "確認中", "確認中"])

    logger.info("=== スネイプ 週次レポート生成完了 ===")


if __name__ == "__main__":
    main()
