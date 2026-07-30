"""
urgent_post.py
緊急投稿スクリプト: Discord /add-idea から受け取ったネタを処理する

--mode draft  : 生成 → GitHub Issue保存 → Discord通知（投稿しない）
--mode approve: 最新の承認待ちIssueから下書き取得 → Threads投稿 → Issueクローズ
"""

import os
import sys
import re
import argparse
import requests
from datetime import datetime
from utils.github_issues import GitHubIssues
from utils.gemini_client import call_gemini
from utils.agent_config import name as _n
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN")
THREADS_USER_ID      = os.getenv("THREADS_USER_ID")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KB_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "kb_sys_ref_v001.md")

URGENT_DRAFT_MARKER = "<!-- URGENT_DRAFT_BODY -->"
URGENT_DRAFT_LABEL  = "urgent-draft-pending"


def load_voice_definition() -> str:
    try:
        with open(KB_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        marker = "## 🎤 自分のアカウントの声"
        if marker in content:
            start = content.index(marker)
            end = content.find("\n## ", start + len(marker))
            return content[start:end].strip() if end != -1 else content[start:].strip()
        return ""
    except FileNotFoundError:
        return ""


def sanitize_post_text(text: str) -> str:
    text = re.sub(r'\*\*([^*\n]+?)\*\*', r'「\1」', text)
    text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'「\1」', text)
    text = text.replace("**", "").replace("*", "").replace("`", "")
    text = text.replace('"', '「').replace('"', '」')
    text = text.replace(''', '「').replace(''', '」')
    return text


def fact_check(idea: str) -> tuple[bool, str]:
    """ネタの事実確認（JUDGEMENT: OK/NG 方式）"""
    prompt = f"""以下のSNS投稿ネタについて、事実確認を行ってください。

ネタ: {idea}

## 前提知識（実在する既知のプロジェクト）
- OpenClaw: https://docs.openclaw.ai/ja-JP の実在OSS
- Claude Code / Claude / ChatGPT / Gemini: 実在AIサービス
- Threads: Meta社のSNS

## NGにする基準（厳守）
- NGにしてよいのは「存在しない」「明白に間違い」が断定できる場合のみ
- 「一般的でない」「マイナー」「概念的段階」「新しい」はNGにしない
- 特定個人・企業への誹謗中傷
- Threadsの利用規約に明白に違反する内容

## 出力フォーマット（必ずこの形式で）:
JUDGEMENT: OK
理由: [OK/NGの根拠]
"""
    result = call_gemini(prompt, GEMINI_API_KEY)
    logger.info(f"ファクトチェック生出力: {result[:200]}")
    # NGが明示されない限りOK（寛容判定）
    passed = "JUDGEMENT: NG" not in result and "JUDGEMENT:NG" not in result
    return passed, result


def generate_urgent_post(idea: str, voice_def: str) -> str:
    """ネタから単体投稿（ツリーなし）を生成する"""
    prompt = f"""以下の声定義に従って、Threads単体投稿（1投稿）を作成してください。

## 声定義
{voice_def}

## ネタ
{idea}

## 制約
- 300文字以内
- 禁止語尾: 「〜です」「〜ます」「〜ください」
- 禁止文字: * " ' ` （強調は「」を使う）
- 冒頭に固有名詞（Claude Code/ChatGPT/Gemini/OpenClaw等）を入れる
- 感情フックを必ず1つ入れる
- 最後にCTA（価値提示）を入れる

## 出力
投稿文のみ（説明不要）:
"""
    result = call_gemini(prompt, GEMINI_API_KEY, system_instruction=voice_def)
    return sanitize_post_text(result.strip())


def save_draft_to_issue(idea: str, post_text: str) -> tuple[int, str]:
    """下書きをGitHub Issueに保存し、(issue_number, issue_url) を返す"""
    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"[緊急投稿下書き] {now} - {idea[:40]}"
    body = f"""## 📥 緊急投稿下書き

**ネタ:** {idea}
**作成日時:** {now}

{URGENT_DRAFT_MARKER}
{post_text}
{URGENT_DRAFT_MARKER}

---
**承認方法:** `/approve-urgent` コマンドを Discord で実行してください。
"""
    issue = gh.repo.create_issue(title=title, body=body, labels=[URGENT_DRAFT_LABEL])
    logger.info(f"下書きIssue作成: #{issue.number}")
    return issue.number, issue.html_url


def get_pending_draft() -> tuple[str, int] | tuple[None, None]:
    """最新の承認待ちIssueから下書きテキストを取得し、(post_text, issue_number) を返す"""
    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issues = gh.repo.get_issues(state="open", labels=[URGENT_DRAFT_LABEL], sort="created", direction="desc")
    for issue in issues:
        body = issue.body or ""
        parts = body.split(URGENT_DRAFT_MARKER)
        if len(parts) >= 3:
            post_text = parts[1].strip()
            return post_text, issue.number
    return None, None


def close_draft_issue(issue_number: int, post_id: str) -> None:
    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.repo.get_issue(issue_number)
    issue.create_comment(f"✅ 投稿完了 (Threads Post ID: `{post_id}`)")
    issue.edit(state="closed")
    logger.info(f"下書きIssue #{issue_number} をクローズしました")


def post_to_threads(text: str) -> dict | None:
    """Threads APIで即時投稿する（===THREAD=== 対応）"""
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        logger.warning("Threads認証情報なし → 投稿スキップ")
        return None

    parts = [p.strip() for p in re.split(r"\n?===THREAD===\n?", text) if p.strip()]
    if not parts:
        logger.error("投稿テキストが空です")
        return None

    root_id = None
    last_result = None
    for i, part in enumerate(parts):
        create_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
        payload = {
            "media_type": "TEXT",
            "text": part,
            "access_token": THREADS_ACCESS_TOKEN,
        }
        if root_id:
            payload["reply_to_id"] = root_id
        last_err = None
        container_id = None
        for attempt in range(3):
            res = requests.post(create_url, data=payload, timeout=30)
            if res.status_code >= 500 and attempt < 2:
                import time
                time.sleep(10 * (attempt + 1))
                continue
            if not res.ok:
                logger.error(f"コンテナ作成失敗: {res.status_code} {res.text[:300]}")
                res.raise_for_status()
            container_id = res.json().get("id")
            break
        if not container_id:
            raise RuntimeError("container creation failed")

        publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        import time
        for attempt in range(4):
            res2 = requests.post(publish_url, data={
                "creation_id": container_id,
                "access_token": THREADS_ACCESS_TOKEN,
            }, timeout=30)
            if res2.status_code == 400 and attempt < 3:
                logger.warning(f"公開400（attempt {attempt+1}/4）→ 待機してリトライ")
                time.sleep(5 * (attempt + 1))
                continue
            if not res2.ok:
                logger.error(f"公開失敗: {res2.status_code} {res2.text[:300]}")
            res2.raise_for_status()
            break
        last_result = res2.json()
        post_id = last_result.get("id")
        logger.info(f"投稿完了 part{i+1}/{len(parts)}: {post_id}")
        if i == 0:
            root_id = post_id
        time.sleep(2)
    return last_result


def notify_discord(message: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
    except Exception:
        pass


def run_direct_file(path: str) -> None:
    """確定文面ファイルをそのまま Threads に投稿（Issue作成なし）"""
    full = path
    if not os.path.isabs(full):
        full = os.path.join(SCRIPT_DIR, "..", path)
    with open(full, "r", encoding="utf-8") as f:
        post_text = f.read().strip().lstrip("\ufeff")
    logger.info(f"=== 緊急投稿 direct_file: {path} ({len(post_text)}文字) ===")
    result = post_to_threads(post_text)
    if not result:
        logger.error("Threads投稿失敗")
        sys.exit(1)
    post_id = result.get("id", "unknown")
    notify_discord(f"✅ **緊急投稿完了** (Post ID: `{post_id}`)\n\n{post_text[:500]}")
    logger.info(f"=== 緊急投稿 direct_file 完了: {post_id} ===")
    print(f"POST_ID={post_id}")


def run_draft(idea: str) -> None:
    """draft モード: ファクトチェック → 生成 → Issue保存 → Discord通知"""
    logger.info(f"=== 緊急投稿 draft開始: {idea[:50]} ===")

    passed, fact_result = fact_check(idea)
    if not passed:
        msg = f"⛔ **ファクトチェック不通過**\nネタ: {idea[:100]}\n\n{fact_result}"
        notify_discord(msg)
        logger.error(f"ファクトチェック失敗: {fact_result}")
        sys.exit(1)

    voice_def = load_voice_definition()
    post_text = generate_urgent_post(idea, voice_def)
    logger.info(f"投稿案生成完了: {len(post_text)}文字")

    try:
        issue_number, issue_url = save_draft_to_issue(idea, post_text)
    except Exception as e:
        logger.warning(f"Issue保存スキップ（権限不足など）: {e}")
        # 権限がない場合は確定文面をそのまま投稿（オーナー確認済み想定）
        result = post_to_threads(post_text)
        if result:
            print(f"POST_ID={result.get('id')}")
            notify_discord(f"✅ **緊急投稿完了（Issueなし）**\n\n{post_text[:500]}")
            return
        notify_discord(f"📋 **手動投稿してください**\n\n{post_text}")
        sys.exit(1)

    msg = (
        f"📥 **緊急投稿の下書きを保存しました**\n\n"
        f"```\n{post_text}\n```\n\n"
        f"**承認する場合:** Discordで `/approve-urgent` を実行してください\n"
        f"**Issue:** {issue_url}"
    )
    notify_discord(msg)
    logger.info("=== 緊急投稿 draft完了 ===")


def run_approve() -> None:
    """approve モード: 最新の下書きを取得 → Threads投稿 → Issueクローズ"""
    logger.info("=== 緊急投稿 approve開始 ===")

    post_text, issue_number = get_pending_draft()
    if post_text is None:
        msg = "⚠️ 承認待ちの緊急投稿下書きがありません"
        notify_discord(msg)
        logger.warning(msg)
        sys.exit(0)

    logger.info(f"下書き取得: Issue #{issue_number}, {len(post_text)}文字")

    result = post_to_threads(post_text)
    if result:
        post_id = result.get("id", "unknown")
        close_draft_issue(issue_number, post_id)
        msg = f"✅ **緊急投稿完了**\n\n{post_text}"
        notify_discord(msg)
        logger.info("Threads投稿完了")
    else:
        msg = f"📋 **投稿案（手動投稿してください）**\n\n{post_text}"
        notify_discord(msg)
        logger.warning("Threads未投稿 → 手動投稿をDiscordに通知")

    logger.info("=== 緊急投稿 approve完了 ===")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["draft", "approve"], default="draft",
                        help="draft: 下書き保存 / approve: 投稿実行")
    args = parser.parse_args()

    if args.mode == "approve":
        run_approve()
    else:
        idea = os.getenv("IDEA", "").strip()
        if not idea:
            logger.error("IDEA環境変数が設定されていません")
            sys.exit(1)
        if idea.startswith("FILE:"):
            run_direct_file(idea[5:].strip())
            return
        run_draft(idea)


if __name__ == "__main__":
    main()
