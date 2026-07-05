"""
malfoy_review.py
マルフォイ担当: 投稿案3案を厳格に校閲し、承認申請または差し戻しを行うスクリプト
ステップ④: 投稿案取得 → チェック → 承認申請 or 差し戻し
"""

import os
import re
import sys
import requests
from datetime import datetime
from utils.github_issues import GitHubIssues
from utils.discord_notify import send_approval_request
from utils.gemini_client import call_gemini
from utils.agent_config import name as _n
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MAX_RETRY      = 2   # 差し戻し最大回数


FORBIDDEN_CHARS = ['*', '"', "'", '“', '”', '‘', '’', '`']


def find_forbidden_chars(text: str) -> list[str]:
    """投稿テキストに禁止文字が含まれるか確認する"""
    return [c for c in FORBIDDEN_CHARS if c in text]


def get_luna_posts(issue_number: int, gh: GitHubIssues) -> str:
    """GitHub IssueのコメントからルーナのAB3案を取得する"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if f"{_n('luna')}より" in comment.body and ("投稿案" in comment.body or "3時間帯" in comment.body):
            return comment.body
    return ""


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUZZ_POSTS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "kb_sys_ref_v001.md")
PRODUCTS_DIR = os.path.join(SCRIPT_DIR, "..", "affi-agent", "operation", "products")


def resolve_post_type() -> str:
    """POST_TYPE 環境変数または曜日から投稿タイプを決定"""
    pt = os.getenv("POST_TYPE", "auto")
    if pt != "auto":
        return pt
    dow = datetime.now().weekday()  # Mon=0
    if dow in (1, 4, 5):
        return "affiliate"
    if dow in (0, 3):
        return "education"
    return "interest"


def load_today_product() -> dict:
    import json as _json
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(PRODUCTS_DIR, f"{today}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = _json.load(f)
        return data.get("selected") or {}
    except (FileNotFoundError, _json.JSONDecodeError):
        return {}


def check_affiliate_slot3(slot3_text: str, product: dict) -> list[str]:
    """アフィリ日の SLOT_3 をコードレベルで検証"""
    issues: list[str] = []
    parts = [p.strip() for p in slot3_text.split("===THREAD===") if p.strip()]
    if len(parts) != 2:
        issues.append(f"SLOT_3は親+ツリー1の2ブロック必須（現在{len(parts)}ブロック）")
        return issues
    parent, tree = parts[0], parts[1]
    if re.search(r"(?i)(?:^|\s)(?:#?pr|【pr】)", parent) or re.search(r"https?://", parent):
        issues.append("親投稿にPR表記またはURLがある（親は体験のみ）")
    if not re.search(r"(?i)(?:^|\s)(?:#?pr|pr\s)", tree):
        issues.append("ツリー1に pr 表記がない")
    url = (product.get("affiliate_url") or product.get("url", "")) if product else ""
    if url and url not in tree:
        issues.append("ツリー1にアフィリURLが含まれていない")
    for bad in ("治る", "効く", "必ず", "100%", "私のリンクから"):
        if bad in parent + tree:
            issues.append(f"禁止表現「{bad}」が含まれている")
    return issues


def load_voice_definition() -> str:
    """kb_sys_ref_v001.mdから声定義を読み込む（マルフォイ審査用）"""
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


def review_posts(posts_text: str, post_type: str = "interest", product: dict | None = None) -> str:
    """Gemini Flash で投稿案を厳格に校閲する（タイムアウト・フォールバック付き）"""

    voice_def = load_voice_definition()
    logger.info(f"マルフォイ声定義ロード: {len(voice_def)}文字")

    affiliate_rules = ""
    if post_type == "affiliate":
        product_hint = ""
        if product:
            product_hint = f"""
紹介商品: {product.get('name', '')}
アフィリURL（ツリー最終行必須）: {product.get('affiliate_url') or product.get('url', '')}
"""
        affiliate_rules = f"""
## アフィリ日追加ルール（SLOT_3のみ・厳守）
{product_hint}
15. SLOT_3は ===THREAD=== を1回だけ（親+ツリー1の2ブロック）。3〜5投稿目は不要
16. 親投稿: PR表記・URL禁止。商品名OK。体験ベース
17. ツリー1: 続き+注意点+末尾に pr + 改行 + アフィリURL
18. 「治る」「効く」「必ず」「100%」「私のリンクから買って」禁止
19. アフィリ日はSLOT_3の180文字ルール（基準14）はツリー1のみ適用（親は80文字目安でOK）
"""

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
投稿タイプ: {post_type}

## 審査対象
{posts_text}

## 差し戻し基準（1つでも該当すれば差し戻し）
1. 禁止語尾（「〜です」「〜ます」「〜ですよ」「〜ませんか」）が1つでも含まれている
2. 「皆さん」が含まれている
3. 1投稿目が声定義の「定番のつかみ」で始まっていない
4. *（アスタリスク）が含まれている
5. 誤情報・誹謗中傷・規約違反
6. CTAに「何を届けるか」の価値提示がない
7. 禁止文字（** / * / " / " " / ' ' / `）が含まれている
8. 同じネタ・切り口が複数スロットで重複している
9. 冒頭60〜80文字に固有名詞がない（腸活/添加物/発酵食品/夜勤/看護師/腸デトックス等）
10. 冒頭60〜80文字に具体的数字がない（−10kg/20年/3人/30分等）
11. 冒頭に曖昧表現あり（「プロ級」「ある〇〇」「最新の〇〇」「神レベル」等）
12. 「稼げる」「月◯万」等の直接的収益表現が含まれている
13. マニアックなベンチマーク比較が含まれている（Kimi K2/Qwen3/Llama等）
14. SLOT_1・SLOT_2の2〜4投稿目のいずれかが180文字未満（アフィリ日のSLOT_3は別ルール）
{affiliate_rules}
## 合格基準
- 声定義の語尾（「〜だよ」「〜んだ」「〜のさ」「〜よね」「〜さ」）が使われていればOK
- 感情フックが機能している
- 3スロットが別テーマ・別角度

## 出力フォーマット

【マルフォイ審査結果】

■ SLOT_1（7時・朝）: [合格 / 差し戻し]
語尾: [禁止語尾の有無。「〜だよ」「〜んだ」は許可なので指摘しない]
つかみ: [定番のつかみで始まっているか]
理由: [具体的なコメント]

■ SLOT_2（18時・夕方）: [合格 / 差し戻し]
語尾: [禁止語尾の有無]
つかみ: [定番のつかみで始まっているか]
理由: [具体的なコメント]

■ SLOT_3（21時・夜）: [合格 / 差し戻し]
語尾: [禁止語尾の有無]
つかみ: [定番のつかみで始まっているか]
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
    """ルーナの投稿案から各スロット（1/2/3）のテキストを抽出する"""
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
    post_type = resolve_post_type()
    product = load_today_product() if post_type == "affiliate" else {}
    logger.info(f"=== マルフォイ 校閲開始 (post_type={post_type}) ===")

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()
    gh.update_pipeline_status(issue.number, "malfoy", "running")

    try:
        luna_posts = get_luna_posts(issue.number, gh)
        if not luna_posts:
            logger.error("ルーナの投稿案が見つかりません。先にluna_write.pyを実行してください。")
            gh.update_pipeline_status(issue.number, "malfoy", "error")
            sys.exit(1)

        # コードレベル禁止文字チェック（投稿本文のみ。コメントのMarkdown見出しは対象外）
        slot_texts_pre = extract_all_slot_texts(luna_posts)
        check_target = "\n".join(slot_texts_pre.values()) if slot_texts_pre else luna_posts
        forbidden_found = find_forbidden_chars(check_target)
        if forbidden_found:
            chars_str = ' '.join(repr(c) for c in forbidden_found)
            logger.warning(f"禁止文字を検出: {chars_str} → 自動差し戻し")
            gh.update_pipeline_status(issue.number, "malfoy", "rejected")
            gh.add_comment(issue.number, f"## 🎩 {_n('malfoy')}より：差し戻し（禁止文字検出）\n\n**審査日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n禁止文字が含まれています: {chars_str}\n\n強調には `**` ではなく「」を使うこと。ルーナに修正させます。")
            sys.exit(10)

        if post_type == "affiliate" and slot_texts_pre.get(3):
            aff_issues = check_affiliate_slot3(slot_texts_pre[3], product)
            if aff_issues:
                msg = "\n".join(f"- {i}" for i in aff_issues)
                logger.warning(f"アフィリルール違反 → 自動差し戻し: {aff_issues}")
                gh.update_pipeline_status(issue.number, "malfoy", "rejected")
                gh.add_comment(issue.number, f"## 🎩 {_n('malfoy')}より：差し戻し（アフィリルール）\n\n**審査日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{msg}\n\nルーナに修正させます。")
                sys.exit(10)

        review_result = review_posts(luna_posts, post_type=post_type, product=product)
        is_approved   = "全スロット承認申請可" in review_result or "承認申請可" in review_result
        logger.info(f"審査結果: {'承認申請可' if is_approved else '差し戻し'}")

        if is_approved:
            slot_texts = extract_all_slot_texts(luna_posts)

            slot1_text = slot_texts.get(1, "（SLOT_1 抽出失敗）")
            slot2_text = slot_texts.get(2, "（SLOT_2 抽出失敗）")
            slot3_text = slot_texts.get(3, "（SLOT_3 抽出失敗）")

            comment_body = f"""## 🎩 {_n('malfoy')}より：承認申請

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
            gh.update_pipeline_status(issue.number, "malfoy", "done", done_ts)
            gh.update_pipeline_status(issue.number, "human", "pending")
            send_approval_request(
                DISCORD_WEBHOOK_URL,
                {"malfoy": ("done", done_ts), "human": ("pending", "-")},
                issue.number, issue.html_url,
                datetime.now().strftime("%Y-%m-%d"),
                post_preview=slot1_text,
            )
            logger.info("承認申請コメントを追加しました（3スロット）")

        else:
            gh.update_pipeline_status(issue.number, "malfoy", "rejected")
            comment_body = f"""## 🎩 {_n('malfoy')}より：差し戻し（自動リトライします）

**審査日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

{review_result}

---
*ルーナに修正指示を送り、自動でリトライします。*
"""
            gh.add_comment(issue.number, comment_body)
            logger.warning("投稿案を差し戻しました → リトライに進みます")
            sys.exit(10)

        logger.info("=== マルフォイ 校閲完了 ===")

    except SystemExit:
        raise  # sys.exit(10) をそのまま通す
    except Exception as e:
        logger.error(f"マルフォイ実行失敗: {type(e).__name__}: {e}")
        gh.update_pipeline_status(issue.number, "malfoy", "error")
        gh.add_comment(issue.number, f"## ❌ {_n('malfoy')}: エラー発生\n\n```\n{type(e).__name__}: {str(e)[:500]}\n```")
        url = os.getenv("DISCORD_WEBHOOK_URL", "")
        if url:
            try:
                requests.post(url, json={"content": f"❌ {_n('malfoy')}実行エラー: {type(e).__name__}: {str(e)[:200]}"}, timeout=10)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
