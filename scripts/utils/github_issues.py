"""
github_issues.py
GitHub Issuesをエージェント間の外部メモリとして操作するユーティリティ
"""

import re
from datetime import datetime, timezone, timedelta
from github import Github, GithubException
from loguru import logger
try:
    from utils.agent_config import name as _n
except ImportError:
    from agent_config import name as _n

JST = timezone(timedelta(hours=9))


# パイプラインの全ステップ定義（順番・表示名）
PIPELINE_STEPS = [
    ("hermione", "①② リサーチ＆分析", f"🔍 {_n('hermione')}"),
    ("luna",     "③  ライティング",    f"✍️  {_n('luna')}"),
    ("malfoy",   "④  校閲",            f"🧐 {_n('malfoy')}"),
    ("human",    "⑤  人間承認",        "👤 オーナー"),
    ("ron_post", "⑥  投稿",            f"📤 {_n('ron')}"),
    ("ron_fetch","⑦  計測（24h後）",   f"📊 {_n('ron')}"),
]

STATUS_ICON = {
    "waiting":  "🔒 待機中",
    "running":  "⚡ 実行中",
    "done":     "✅ 完了",
    "pending":  "⏳ 承認待ち",
    "skipped":  "⏭️  スキップ",
    "error":    "❌ エラー",
    "rejected": "🔄 差し戻し→リトライ中",
    "rejected_final": "⚠️ 差し戻し（要手動対応）",
}

PIPELINE_START = "<!-- PIPELINE_STATUS_START -->"
PIPELINE_END   = "<!-- PIPELINE_STATUS_END -->"


def _build_pipeline_table(statuses: dict) -> str:
    """パイプラインステータステーブルのMarkdownを生成する"""
    rows = []
    for key, label, agent in PIPELINE_STEPS:
        status_text, ts = statuses.get(key, ("waiting", "-"))
        icon = STATUS_ICON.get(status_text, status_text)
        rows.append(f"| {label} | {agent} | {icon} | {ts} |")

    table = (
        "| ステップ | エージェント | 状態 | 時刻 |\n"
        "|---|---|---|---|\n"
        + "\n".join(rows)
    )
    return f"{PIPELINE_START}\n{table}\n{PIPELINE_END}"


def _parse_pipeline_statuses(body: str) -> dict:
    """Issue本文からパイプラインステータスを解析する"""
    statuses = {}
    match = re.search(
        rf"{re.escape(PIPELINE_START)}\n(.*?)\n{re.escape(PIPELINE_END)}",
        body, re.DOTALL
    )
    if not match:
        return statuses

    for line in match.group(1).split("\n"):
        if not line.startswith("|") or "---" in line or "ステップ" in line:
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 4:
            continue
        label_cell = cols[0]
        for key, label, _ in PIPELINE_STEPS:
            if label.strip() in label_cell:
                # 状態アイコンから status_key を逆引き
                status_col = cols[2]
                status_key = next(
                    (k for k, v in STATUS_ICON.items() if v in status_col),
                    status_col
                )
                statuses[key] = (status_key, cols[3])
                break
    return statuses


class GitHubIssues:
    """GitHub Issues を外部メモリとして操作するクラス"""

    DAILY_OP_LABEL    = "daily-operation"
    PERF_LOG_LABEL    = "投稿実績ログ"
    APPROVAL_LABEL    = "承認待ち"

    def __init__(self, token: str, repo_name: str):
        self.gh   = Github(token)
        self.repo = self.gh.get_repo(repo_name)
        self._ensure_labels()

    def _ensure_labels(self):
        """必要なラベルが存在しない場合は作成する"""
        existing = {label.name for label in self.repo.get_labels()}
        labels_to_create = {
            self.DAILY_OP_LABEL: ("0075ca", "毎日の運用ループ管理"),
            self.PERF_LOG_LABEL: ("e4e669", "投稿パフォーマンス記録"),
            self.APPROVAL_LABEL: ("d93f0b", "人間承認待ちの投稿案"),
        }
        for name, (color, desc) in labels_to_create.items():
            if name not in existing:
                try:
                    self.repo.create_label(name=name, color=color, description=desc)
                    logger.info(f"ラベル作成: {name}")
                except GithubException as e:
                    logger.warning(f"ラベル作成スキップ: {name} ({e})")

    def get_or_create_today_issue(self) -> object:
        """
        本日の運用ループIssueを取得または作成する。
        タイトル形式: 「【運用ループ】YYYY-MM-DD」
        """
        today = datetime.now(JST).strftime("%Y-%m-%d")
        title_prefix = f"【運用ループ】{today}"

        # 既存のIssueを探す
        issues = self.repo.get_issues(state="open", labels=[self.DAILY_OP_LABEL])
        for issue in issues:
            if issue.title.startswith(title_prefix):
                logger.info(f"既存のIssueを使用: #{issue.number}")
                return issue

        # パイプライン初期状態（全て待機中）
        initial_statuses = {key: ("waiting", "-") for key, _, _ in PIPELINE_STEPS}
        pipeline_table = _build_pipeline_table(initial_statuses)

        label = self.repo.get_label(self.DAILY_OP_LABEL)
        new_issue = self.repo.create_issue(
            title=f"{title_prefix} - 運用ループ",
            body=f"""# 🏰 本日の運用ループ

**日付:** {today}

## パイプライン状況（自動更新）

{pipeline_table}

---

このIssueはエージェント間の通信掲示板です。
各エージェントが順番にコメントを追加していきます。

> 承認する場合は「承認」とコメントしてください。
""",
            labels=[label],
        )
        logger.info(f"新規Issue作成: #{new_issue.number}")
        return new_issue

    def update_pipeline_status(
        self,
        issue_number: int,
        step_key: str,
        status: str,
        timestamp: str = None,
    ):
        """
        Issue本文のパイプラインステータステーブルを更新する。

        Args:
            step_key: "hermione" / "luna" / "malfoy" / "human" / "ron_post" / "ron_fetch"
            status:   "waiting" / "running" / "done" / "pending" / "skipped" / "error"
            timestamp: 表示する時刻文字列（省略時は現在時刻）
        """
        if timestamp is None:
            timestamp = datetime.now(JST).strftime("%H:%M") if status != "waiting" else "-"

        issue = self.repo.get_issue(issue_number)
        body = issue.body or ""

        # 現在のステータスを解析
        statuses = _parse_pipeline_statuses(body)

        # 前のステップを "done" に保ちつつ対象ステップを更新
        statuses[step_key] = (status, timestamp)

        # テーブルを再生成して置換
        new_table = _build_pipeline_table(statuses)

        if PIPELINE_START in body:
            new_body = re.sub(
                rf"{re.escape(PIPELINE_START)}.*?{re.escape(PIPELINE_END)}",
                new_table,
                body,
                flags=re.DOTALL,
            )
        else:
            new_body = body + f"\n\n## パイプライン状況\n\n{new_table}\n"

        issue.edit(body=new_body)
        logger.info(f"パイプライン状況更新: {step_key} → {status}")

    def get_issue(self, issue_number: int) -> object:
        """Issue番号でIssueを取得する"""
        return self.repo.get_issue(issue_number)

    def add_comment(self, issue_number: int, body: str) -> object:
        """Issueにコメントを追加する"""
        issue = self.repo.get_issue(issue_number)
        comment = issue.create_comment(body)
        logger.info(f"Issue #{issue_number} にコメント追加 (ID: {comment.id})")
        return comment

    def get_comments(self, issue_number: int) -> list:
        """Issueのコメント一覧を取得する"""
        issue = self.repo.get_issue(issue_number)
        return list(issue.get_comments())

    def close_issue(self, issue_number: int):
        """Issueをクローズする"""
        issue = self.repo.get_issue(issue_number)
        issue.edit(state="closed")
        logger.info(f"Issue #{issue_number} をクローズ")

    def add_label(self, issue_number: int, label_name: str):
        """Issueにラベルを追加する"""
        issue = self.repo.get_issue(issue_number)
        label = self.repo.get_label(label_name)
        issue.add_to_labels(label)

    def get_performance_logs(self, limit: int = 30) -> list:
        """
        「投稿実績ログ」ラベルのIssueを取得する（ハーマイオニーの分析用）
        """
        issues = self.repo.get_issues(
            state="closed",
            labels=[self.PERF_LOG_LABEL],
            sort="created",
            direction="desc"
        )
        return list(issues)[:limit]
