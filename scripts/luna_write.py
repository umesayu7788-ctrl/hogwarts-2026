"""
luna_write.py
ルーナ担当: ハーマイオニーのブリーフィングをもとに投稿案3案を作成するスクリプト
ステップ③: ブリーフィング取得 → 投稿案3案生成 → GitHub Issues記録
"""

import os
import re
import sys
import requests
from datetime import datetime
from utils.github_issues import GitHubIssues
from utils.agent_config import name as _n
from utils.gemini_client import call_gemini
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUZZ_POSTS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "kb_sys_ref_v001.md")


def get_briefing_from_issue(issue_number: int, gh: GitHubIssues) -> str:
    """GitHub Issueのコメントからハーマイオニーのブリーフィングを抽出する"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if f"{_n('hermione')}より" in comment.body and "ブリーフィング" in comment.body:
            return comment.body
    return ""


def get_malfoy_feedback(issue_number: int, gh: GitHubIssues) -> str:
    """マルフォイの差し戻し or オーナーの修正指示を取得する（あれば）"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if comment.body.strip().startswith("修正:") and comment.user.type != "Bot":
            return f"【オーナーからの修正指示】\n{comment.body.strip()}"
        if f"{_n('malfoy')}より：差し戻し" in comment.body:
            return comment.body
    return ""


def load_voice_definition() -> str:
    """kb_sys_ref_v001.mdから「自分のアカウントの声」定義セクションを抽出する"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        marker = "## 🎤 自分のアカウントの声"
        if marker in content:
            start = content.index(marker)
            end = content.find("\n## ", start + len(marker))
            return content[start:end].strip() if end != -1 else content[start:].strip()
        return content[2000:4000]
    except FileNotFoundError:
        return "（声定義なし）"


def extract_persona_name(voice_def: str) -> str:
    """声定義からキャラ名を動的に抽出する"""
    m = re.search(r'\*{0,2}キャラ名\*{0,2}[：:]\s*(.+)', voice_def)
    if m:
        return m.group(1).strip().strip('*')
    return "キャラクター"


def extract_opening_line(voice_def: str) -> str:
    """声定義から定番のつかみフレーズを動的に抽出する"""
    m = re.search(r'「(.+?)」は定番のつかみ', voice_def)
    if m:
        return m.group(1)
    return ""


def load_reference_posts() -> str:
    """kb_sys_ref_v001.mdからバズ要因分析（構造の教訓）だけを抽出する。実際の投稿文は含めない"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        marker = "## 🎤 自分のアカウントの声"
        if marker in content:
            ref_section = content[:content.index(marker)]
        else:
            ref_section = content[:3000]
        # ```コードブロック（実際の投稿文）を除去し、構造分析だけ残す
        ref_section = re.sub(r'```[\s\S]*?```', '[投稿文は省略・構造分析のみ参照]', ref_section)
        return ref_section[:3000]
    except FileNotFoundError:
        return "（参考投稿なし）"


def generate_posts(briefing: str, voice_def: str, ref_posts: str, malfoy_feedback: str = "") -> str:
    """Gemini Flash で投稿案3案を生成する（タイムアウト・フォールバック付き）"""

    persona_name = extract_persona_name(voice_def)
    opening_line = extract_opening_line(voice_def)

    # 声定義をsystem_instructionとして渡す（Geminiがシステムレベルで強制的に従う）
    opening_rule = f"""
■ 最重要ルール: 全SLOTの1投稿目は必ず「{opening_line}」で始めること。
この後に本題のフックを続ける。例外なし。この行がない投稿は全て差し戻しになる。
""" if opening_line else ""

    system_instruction = f"""あなたは「{persona_name}」というSNSキャラクターです。
以下の声定義に100%従ってください。これはシステムレベルの絶対ルールです。

{voice_def}
{opening_rule}
■ 絶対遵守ルール:
- 語尾は声定義に書かれたもの（「〜だよ」「〜んだ」「〜のさ」「〜よね」「〜さ」等）だけを使うこと
- 「〜です」「〜ます」「〜ですよ」「〜ませんか」「〜しましょう」は使用禁止
- 「皆さん」は使用禁止。「みんな」を使うこと
- 「〜してください」「〜しませんか」等の丁寧語は使用禁止
- *（アスタリスク）は使用禁止。強調は「」を使うこと
"""

    feedback_section = f"""
## ⚠️ マルフォイからの前回差し戻し指摘（必ず反映すること）
{malfoy_feedback}
""" if malfoy_feedback else ""

    prompt = f"""
## 発信テーマ（必須・厳守）
声定義の「発信テーマ・ポジション」に書かれたテーマが軸。
- 声定義のテーマに沿った**自分の実体験・気づき・ノウハウ**として語ること
- 単なるAIニュース紹介・製品比較はNG
- 無関係な製品比較もNG

## 【最重要】自分の実体験バンク（必ずここからネタを選ぶこと）
以下の実体験・気づきをベースに投稿を書くこと。
参考投稿のネタ・リストを使うことは厳禁。ここにある素材だけを使うこと。

### 💡 AIエージェント導入で得た本質的な変化
- AIエージェントが自分の「思考の拡張装置」になった。一人では出せなかった深さの分析・考察ができるようになった
- 「作業時間を減らす」ではなく「思考の質が上がる」という感覚。AIが補佐することで人間の判断力が上がる
- 圧倒的な時短。今まで何時間もかかっていた作業が、承認ボタンを押すだけで完結する
- 空いた時間で別のことに集中できる。時間の使い方が根本から変わった

### ⚙️ Threads自動運用の実際の仕組み（キャラ名は出さず、仕組みとして語る）
- 毎朝決まった時間にAIが自動起動し、最新トレンドをリサーチして投稿案を3本自動生成する
- 自分はスマホで承認するだけ。朝の2〜3分で1日3投稿が完結する
- AIが自動でYouTubeやニュースを収集・分析し、今日のネタを選んでくれる
- 別のAIが品質チェックし、基準を満たさなければ自動で作り直す（人間は最終判断のみ）
- ツリー投稿（返信連投）も自動で全部つながる。3〜5連投が1クリックで完成する

### 🎯 使ってみてわかった「本当の価値」
- 完璧を目指さなくていい。AIがドラフトを出してくれるから、人間は「方向性の判断」だけでいい
- 毎日続けることのハードルが下がる。「今日は疲れた」でも投稿が止まらない
- 仕組みを一度作ったら、あとは改善だけ。雪だるま式に効率が上がっていく

### 💰 副収入を得たい人に刺さる「解像度の高い現実」
- Threadsで稼ぐのに必要なのは「毎日投稿し続ける体力」ではなく「仕組みを作る1週間」
- 手動で毎日投稿している人は、労働時間を売っている。仕組み化した人は、寝ている間も資産が積まれる
- フォロワーが増えるほど「単価×数量」が上がる。でも投稿コストはゼロのまま。これがレバレッジ
- 1アカウントで稼げるようになった仕組みは、そのまま2つ目・3つ目のアカウントにコピーできる
- 「AIに任せると自分らしさが消える」と思ってる人へ：自分の体験・考えをAIに渡せば、自分らしさは残る。むしろ磨かれる
- 今手動でやっている人と、AI自動化している人では、6ヶ月後にフォロワー数で10倍差がつく可能性がある

---
## バズ構造の型（「型」だけ参考にする。内容は実体験バンクのものを使うこと）
{ref_posts}

---
## ハーマイオニーのブリーフィング（ネタのヒントとして使う）
{briefing}
{feedback_section}

---
## ★有益さと密度の基準★

### 4種類のエンゲージメントトリガー（各スロット最低1つ必ず入れる）

**【いいね】共感・発見トリガー**
- 「あるある」「わかるー」と思わせる瞬間
- 例：「手動で毎日投稿してた頃、正直しんどかった」

**【再投稿・保存】シェアしたくなるトリガー**
- 番号付きリスト形式 or 対比・比較形式
- ★3スロットのうち必ず1つはリスト形式か対比形式にすること

**【フォロー】価値提示トリガー（最重要・必ず入れる）**
- ❌ NG：「フォローしてくれると嬉しいよ」← 理由がない
- ✅ OK：「何を届けるか」を具体的に書く
- **CTAには必ず「何を届けるか」を具体的に書く。「嬉しいよ」だけは禁止**

**【ツリーへの引き】続きを読ませるトリガー**
- 「ただし落とし穴が1つある」「具体的な手順は次のツリーで」

## ★超重要★ 3スロットそれぞれ異なるネタ・切り口にすること
- SLOT_1/2/3 は必ず別テーマ・別角度
- ブリーフィングのネタは1スロットにのみ使い、残り2スロットは実体験バンクから別の切り口で

## ★改行ルール★
- 文の途中で絶対に改行しない（句点・文末語尾の後のみ）
- ❌ NG：「SNS投稿やデータ分析まで、\\n自動化できる。」
- ✅ OK：「SNS投稿やデータ分析まで自動化できる。\\n作業時間が10分の1になったのさ。」

## ★絶対禁止文字★
- * （アスタリスク）は絶対に使用禁止。1つでも含まれていたら即差し戻し
- 強調したい場合は「」（カギ括弧）を使うこと

## ★フック必須3要素★
| 必須要素 | OK例 | NG例 |
|---|---|---|
| 固有名詞 | Claude Code/ChatGPT/Gemini/OpenClaw | 最新AI/あるツール/人気のAI |
| 具体的数字 | 2万円/10倍/3年/60日 | すごく/劇的に/だいぶ |
| 読者の生活インパクト | 給料以外の選択肢が増える/朝の時間が空く | 便利/効率的/クール |

## ⛔ 絶対禁止フック
- 「プロ級の」「神レベルの」（程度が曖昧）
- 「ある質問」「ある方法」（具体性なし）
- 「最新の」（単独使用禁止・固有名詞と組み合わせるならOK）
- 「〇〇な人」（ターゲット曖昧）
- ベンチマーク・モデル比較（Kimi K2/Qwen3/Llama等）

## 💰 「稼げる」系の遠回し表現（規約配慮）
❌ 直接: 「これで月10万稼げる」「副業で稼げる」「収入が3倍に」
✅ 遠回し:
- 「給料以外の柱が立つ」「収入の選択肢が増える」
- 「会社に依存しない働き方ができる」
- 「やりたい仕事だけ選べるように」
- 「経済的余白が生まれる」

## 🎯 ネタ軸は3つだけに絞る
1. 時間軸（効率化・自動化・時短）
2. コスト軸（無料代替・節約）
3. 不安解消軸（取り残される恐怖・知らないと損）

## 時間帯別トーン
🌅 SLOT_1【7時】情報系・発見系。「今日から使える知識」
🌆 SLOT_2【18時】共感系。仕事終わりに「わかるー」「大事だな」
🌙 SLOT_3【21時】感情フック強め。「え、知らなかった」「これ面白い」

## ツリー投稿形式（内容の密度に応じて3〜5投稿を使い分ける）

### ⛔ 各投稿の文字数制限（厳守）
- **1投稿目（フック）：80文字以内** — 興味を引く一文だけ。続きを読みたくなる引き
- **2投稿目以降（本文）：各150〜300文字** — 具体例・ノウハウ・体験談を展開
- **最終投稿（CTA）：100文字以内** — まとめ＋「何を届けるか」を明示

### ツリー数の目安
- **3投稿（最低）**: シンプルなメッセージ。フック→本文→CTA
- **4投稿（標準）**: 体験談や具体例を1つ深掘り。フック→本文①→本文②→CTA
- **5投稿（リスト・ノウハウ系）**: 複数のポイントを列挙。フック→ポイント①→ポイント②→ポイント③→CTA
- 内容が薄くなるくらいなら少なく、密度を保てるなら多く。質が最優先

### CTAのルール（最終投稿に必ず入れる）
- ❌ 禁止：「フォローしてくれると嬉しいよ」「フォローしてね」だけ
- ✅ 必須：「何を届けるか」を具体的に書く

---
## 出力フォーマット
※ 各SLOTは3〜5投稿で構成する。===THREAD=== で区切る
※ 全SLOTの1投稿目は必ず「{opening_line}」で始めること！
※ 投稿の順序が正しいことを確認（フック→本文→…→CTA）

🌅 SLOT_1【7時・朝投稿】（情報・発見系）
━━━━━━━━━━━━━━━━━━━━
{opening_line}
[この後に本題のフックを続ける。合計80文字以内]
===THREAD===
[2投稿目：本文・導入]
===THREAD===
[3投稿目：本文・具体例や深掘り]
===THREAD===
[4投稿目：まとめ＋価値提示型CTA]
━━━━━━━━━━━━━━━━━━━━

🌆 SLOT_2【18時・夕方投稿】（共感・体験系）
━━━━━━━━━━━━━━━━━━━━
{opening_line}
[この後に本題のフックを続ける。合計80文字以内]
===THREAD===
[2投稿目：本文・体験や共感]
===THREAD===
[3投稿目：本文・気づきや転換]
===THREAD===
[4投稿目：まとめ＋価値提示型CTA]
━━━━━━━━━━━━━━━━━━━━

🌙 SLOT_3【21時・夜投稿】（感情フック・リスト系）
━━━━━━━━━━━━━━━━━━━━
{opening_line}
[この後に本題のフックを続ける。合計80文字以内]
===THREAD===
[2投稿目：本文①]
===THREAD===
[3投稿目：本文②]
===THREAD===
[4投稿目：本文③（リスト系なら追加ポイント）]
===THREAD===
[5投稿目：まとめ＋価値提示型CTA]
━━━━━━━━━━━━━━━━━━━━
"""

    result = call_gemini(prompt, GEMINI_API_KEY, system_instruction=system_instruction)

    result = sanitize_post_text(result)

    if opening_line:
        result = force_opening_line(result, opening_line)

    return result


def _replace_quotes_alternating(text: str, char: str, open_q: str, close_q: str) -> str:
    """半角クォートを開閉交互置換する（1個目→開き括弧、2個目→閉じ括弧、...）"""
    parts = text.split(char)
    result = parts[0]
    for i, part in enumerate(parts[1:]):
        result += open_q if i % 2 == 0 else close_q
        result += part
    return result


def sanitize_post_text(text: str) -> str:
    """投稿テキストから禁止文字を除去・変換する（最終防衛線）"""
    # **xxx** -> 「xxx」
    text = re.sub(r'\*\*([^*\n]+?)\*\*', r'「\1」', text)
    # *xxx* -> 「xxx」
    text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'「\1」', text)
    text = text.replace("**", "")
    text = text.replace("*", "")
    text = text.replace("`", "")
    # スマートクォート(全角) -> 「」（\u エスケープ表記で再破損を防ぐ）
    text = text.replace("“", "「").replace("”", "」")
    text = text.replace("‘", "「").replace("’", "」")
    # 半角クォート -> 開閉ペア交互置換
    text = _replace_quotes_alternating(text, '"', '「', '」')
    text = _replace_quotes_alternating(text, "'", '「', '」')
    return text


def force_opening_line(text: str, opening: str) -> str:
    """各SLOTの1投稿目冒頭に定番つかみを強制挿入する"""
    lines = text.split("\n")
    result_lines = []
    in_slot = False
    slot_first_line_done = False

    for line in lines:
        stripped = line.strip()
        # SLOT開始を検知（━━━の罫線の後）
        if "━━━" in stripped:
            if not in_slot:
                in_slot = True
                slot_first_line_done = False
            else:
                # 2つ目の罫線 = SLOT終了
                in_slot = False
            result_lines.append(line)
            continue

        # SLOT内の最初の非空行にopening_lineを挿入
        if in_slot and not slot_first_line_done and stripped:
            slot_first_line_done = True
            if opening not in stripped:
                result_lines.append(opening)
            result_lines.append(line)
            continue

        result_lines.append(line)

    return "\n".join(result_lines)


def main():
    logger.info("=== ルーナ 投稿案作成開始 ===")

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()
    gh.update_pipeline_status(issue.number, "luna", "running")

    try:
        briefing = get_briefing_from_issue(issue.number, gh)
        if not briefing:
            logger.error("ハーマイオニーのブリーフィングが見つかりません。先にhermione_research.pyを実行してください。")
            gh.update_pipeline_status(issue.number, "luna", "error")
            sys.exit(1)

        voice_def = load_voice_definition()
        logger.info(f"声定義ロード: {len(voice_def)}文字, persona={extract_persona_name(voice_def)}, opening={extract_opening_line(voice_def)}")
        ref_posts = load_reference_posts()
        malfoy_feedback = get_malfoy_feedback(issue.number, gh)
        if malfoy_feedback:
            logger.info("マルフォイの差し戻しコメントを取得しました。フィードバックを反映して再生成します。")

        posts = generate_posts(briefing, voice_def, ref_posts, malfoy_feedback)
        logger.info("投稿案3案生成完了")

        comment_body = f"""## ✍️ {_n('luna')}より：3時間帯投稿案 完成

**作成日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

{posts}

---
*{_n('malfoy')}、3スロット分の校閲をお願いします。*
"""
        done_ts = datetime.now().strftime("%H:%M")
        gh.add_comment(issue.number, comment_body)
        gh.update_pipeline_status(issue.number, "luna", "done", done_ts)
        logger.info(f"GitHub Issue #{issue.number} に投稿案を追加しました")
        logger.info("=== ルーナ 投稿案作成完了 ===")

    except Exception as e:
        logger.error(f"ルーナ実行失敗: {type(e).__name__}: {e}")
        gh.update_pipeline_status(issue.number, "luna", "error")
        gh.add_comment(issue.number, f"## ❌ {_n('luna')}: エラー発生\n\n```\n{type(e).__name__}: {str(e)[:500]}\n```")
        url = os.getenv("DISCORD_WEBHOOK_URL", "")
        if url:
            try:
                requests.post(url, json={"content": f"❌ {_n('luna')}実行エラー: {type(e).__name__}: {str(e)[:200]}"}, timeout=10)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
