"""
malfoy_review.py
校閲担当: 投稿案3案を厳格に校閲し、承認申請または差し戻しを行うスクリプト
ステップ④: 投稿案取得 → チェック → 承認申請 or 差し戻し
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
import requests
from datetime import datetime
from utils.github_issues import GitHubIssues
from utils.discord_notify import send_approval_request
from utils.gemini_client import call_gemini
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MAX_RETRY      = 2   # 差し戻し最大回数


def get_luna_posts(issue_number: int, gh: GitHubIssues) -> str:
    """GitHub IssueのコメントからライターのAB3案を取得する"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if "ライターより" in comment.body and ("投稿案" in comment.body or "3時間帯" in comment.body):
            return comment.body
    return ""


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUZZ_POSTS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "buzz_posts.md")


def load_voice_definition() -> str:
    """buzz_posts.mdから声定義を読み込む（校閲審査用）"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        marker = "## 🎤 自分のアカウントの声"
        if marker in content:
            start = content.index(marker)
            end = content.find("\n## ", start + len(marker))
            return content[start:end].strip() if end != -1 else content[start:].strip()
        return ""
    except FileNotFoundError:
        return ""


def review_posts(posts_text: str) -> str:
    """Gemini Flash で投稿案を厳格に校閲する（タイムアウト・フォールバック付き）"""

    voice_def = load_voice_definition()
    logger.info(f"校閲声定義ロード: {len(voice_def)}文字")

    system_instruction = f"""あなたはThreads投稿の品質管理責任者です。
以下の声定義を基準にして投稿案を審査してください。

{voice_def}

■ 審査で確認すべき語尾ルール:
- 許可される語尾: 「〜だよ」「〜んだ」「〜のさ」「〜よね」「〜さ」（声定義に書かれた語尾は全て許可）
- 禁止される語尾: 「〜です」「〜ます」「〜ですよ」「〜ませんか」「〜しましょう」「〜ください」
- 「皆さん」は禁止（「みんな」が正しい）
- 「〜だよ」「〜んだ」は許可された語尾。これを差し戻し理由にしてはならない
"""

    prompt = f"""以下の投稿案を審査しろ。

## 審査対象
{posts_text}

## 差し戻し基準（1つでも該当すれば差し戻し）
1. 禁止語尾（「〜です」「〜ます」「〜ですよ」「〜ませんか」）が1つでも含まれている
2. 「皆さん」が含まれている
3. *（アスタリスク）／**（マークダウン太字）が含まれている
4. 🤭が含まれている（禁止絵文字）
5. 誤情報・誹謗中傷・規約違反
6. CTAに「何を届けるか」の価値提示がない
7. 3スロットの冒頭フレーズが同じor極めて類似（言い回しの被り）
8. 「ってママへ！」形式が3スロット中2つ以上で使われている

## 合格基準（フック多様化を優先）
- 1投稿目の冒頭はバラエティ豊かであればOK。以下のいずれかでOK：
  - 過去バズフック（own_buzz_history.md）から選択した形式（「えーっと、」「実はね、」など、buzz_posts.md声定義由来）
  - 共感呼びかけ型（「○○で悩んでるママへ！」「○○なママさん、」等）
  - 自己開示型（「正直に言うと、」「実は私、」等）
  - 問いかけ型（「みんなどう？」「○○って思わない？」等）
  - 驚き型（「え、知ってた？」「びっくりするくらい」等）
  - 体験ストーリー型（「昨日、うちの子が」「この前」等）
- 「ってママへ！」を必須にしない。3スロット中1回まで使ってOK、使わなくてもOK
- 声定義の語尾（だよ/だね/だよね/なんだ/なの/かも 等）が使われていればOK
- 感情フックが機能している
- 3スロットが別テーマ・別角度・別冒頭フレーズ

## 出力フォーマット

【校閲審査結果】

■ SLOT_1（7時・朝）: [合格 / 差し戻し]
語尾: [禁止語尾の有無。「〜だよ」「〜んだ」は許可なので指摘しない]
つかみ: [冒頭が多様化されているか・他スロットと被っていないか]
理由: [具体的なコメント]

■ SLOT_2（18時・夕方）: [合格 / 差し戻し]
語尾: [禁止語尾の有無]
つかみ: [冒頭が多様化されているか・他スロットと被っていないか]
理由: [具体的なコメント]

■ SLOT_3（21時・夜）: [合格 / 差し戻し]
語尾: [禁止語尾の有無]
つかみ: [冒頭が多様化されているか・他スロットと被っていないか]
理由: [具体的なコメント]

■ 総合判定: [全スロット承認申請可 / 差し戻しあり]
差し戻し理由（差し戻しがある場合）: [具体的な修正指示]
"""

    return call_gemini(prompt, GEMINI_API_KEY, system_instruction=system_instruction)


def clean_post_text(text: str) -> str:
    """投稿テキストからフォーマットラベルを除去する"""
    import re
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if re.match(r'^\[?\d+投稿目[：:].+\]?$', line.strip()):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def extract_all_slot_texts(luna_posts: str) -> dict:
    """ライターの投稿案から各スロット（1/2/3）のテキストを抽出する"""
    slots = {}
    slot_markers = [("SLOT_1", 1), ("SLOT_2", 2), ("SLOT_3", 3)]

    for marker, slot_num in slot_markers:
        if marker not in luna_posts:
            continue
        start = luna_posts.find(marker)
        section = luna_posts[start:]
        lines = section.split("\n")
        bars = [i for i, line in enumerate(lines) if "━" in line]
        if len(bars) >= 2:
            text_lines = lines[bars[0] + 1:bars[1]]
            extracted = clean_post_text("\n".join(text_lines))
            if extracted:
                slots[slot_num] = extracted

    return slots


def main():
    logger.info("=== 校閲 校閲開始 ===")

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()
    gh.update_pipeline_status(issue.number, "reviewer", "running")

    try:
        luna_posts = get_luna_posts(issue.number, gh)
        if not luna_posts:
            logger.error("ライターの投稿案が見つかりません。先にluna_write.pyを実行してください。")
            gh.update_pipeline_status(issue.number, "reviewer", "error")
            sys.exit(1)

        review_result = review_posts(luna_posts)
        is_approved   = "全スロット承認申請可" in review_result or "承認申請可" in review_result
        logger.info(f"審査結果: {'承認申請可' if is_approved else '差し戻し'}")

        if is_approved:
            slot_texts = extract_all_slot_texts(luna_posts)

            slot1_text = slot_texts.get(1, "（SLOT_1 抽出失敗）")
            slot2_text = slot_texts.get(2, "（SLOT_2 抽出失敗）")
            slot3_text = slot_texts.get(3, "（SLOT_3 抽出失敗）")

            comment_body = f"""## 🎩 校閲より：承認申請

**審査日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

{review_result}

---
### 📋 推奨投稿案（3時間帯・オーナー一括承認用）

**🌅 SLOT_1【7時・即時投稿】**
```
{slot1_text}
```

**🌆 SLOT_2【18時・夕方投稿】**
```
{slot2_text}
```

**🌙 SLOT_3【21時・夜投稿】**
```
{slot3_text}
```

**オーナーへ:** このIssueに「承認」とコメントしてください。
- SLOT_1（7時）→ 承認後すぐに投稿されます
- SLOT_2（18時）→ GitHub Actionsが自動投稿します
- SLOT_3（21時）→ GitHub Actionsが自動投稿します
"""
            done_ts = datetime.now().strftime("%H:%M")
            gh.add_comment(issue.number, comment_body)
            gh.add_label(issue.number, GitHubIssues.APPROVAL_LABEL)
            gh.update_pipeline_status(issue.number, "reviewer", "done", done_ts)
            gh.update_pipeline_status(issue.number, "human", "pending")
            send_approval_request(
                DISCORD_WEBHOOK_URL,
                {"reviewer": ("done", done_ts), "human": ("pending", "-")},
                issue.number, issue.html_url,
                datetime.now().strftime("%Y-%m-%d"),
                post_preview=slot1_text,
            )
            logger.info("承認申請コメントを追加しました（3スロット）")

        else:
            gh.update_pipeline_status(issue.number, "reviewer", "rejected")
            comment_body = f"""## 🎩 校閲より：差し戻し（自動リトライします）

**審査日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

{review_result}

---
*ライターに修正指示を送り、自動でリトライします。*
"""
            gh.add_comment(issue.number, comment_body)
            logger.warning("投稿案を差し戻しました → リトライに進みます")
            sys.exit(10)

        logger.info("=== 校閲 校閲完了 ===")

    except SystemExit:
        raise  # sys.exit(10) をそのまま通す
    except Exception as e:
        logger.error(f"校閲実行失敗: {type(e).__name__}: {e}")
        gh.update_pipeline_status(issue.number, "reviewer", "error")
        gh.add_comment(issue.number, f"## ❌ 校閲: エラー発生\n\n```\n{type(e).__name__}: {str(e)[:500]}\n```")
        url = os.getenv("DISCORD_WEBHOOK_URL", "")
        if url:
            try:
                requests.post(url, json={"content": f"❌ 校閲実行エラー: {type(e).__name__}: {str(e)[:200]}"}, timeout=10)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
