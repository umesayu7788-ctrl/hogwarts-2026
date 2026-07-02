"""
luna_write.py
ライター担当: 情報リサーチのブリーフィングをもとに投稿案3案を作成するスクリプト
ステップ③: ブリーフィング取得 → 投稿案3案生成 → GitHub Issues記録
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
import re
import sys
import requests
from datetime import datetime, timezone, timedelta
from utils.github_issues import GitHubIssues
from utils.gemini_client import call_gemini
from dotenv import load_dotenv
from loguru import logger

# 投稿サイクルの日付は JST 基準（runner は UTC）
JST = timezone(timedelta(hours=9))


def _now_jst() -> datetime:
    return datetime.now(JST)

load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUZZ_POSTS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "buzz_posts.md")
OWN_BUZZ_HISTORY_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "own_buzz_history.md")
GENRE_AXIS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "genre_axis_strategy.md")
PERSUASION_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "affiliate_persuasion_psychology.md")
AFFILIATE_STRUCTURE_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "affiliate_post_structure.md")
PRODUCTS_DIR = os.path.join(SCRIPT_DIR, "..", "operation", "products")


def load_affiliate_structure() -> str:
    """参考アカウント分析ナレッジ（2投稿構造・フック型）を読み込む"""
    try:
        with open(AFFILIATE_STRUCTURE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def load_today_product() -> dict:
    """本日の選定商品を取得（アフィリ投稿日のみ意味を持つ）"""
    import json as _json
    today = _now_jst().strftime("%Y-%m-%d")
    path = os.path.join(PRODUCTS_DIR, f"{today}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return data.get("selected") or {}
    except (FileNotFoundError, _json.JSONDecodeError):
        return {}


def load_persuasion_brief() -> str:
    """心理誘導ナレッジから8トリガー〜7ステップ部分を抽出"""
    try:
        with open(PERSUASION_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        start = content.find("## 🧠 8つの心理トリガー")
        end = content.find("## ⚠️ コンプライアンス遵守ライン")
        if start >= 0 and end > start:
            return content[start:end].strip()
        return content[:4000]
    except FileNotFoundError:
        return ""


def load_own_buzz_hooks() -> str:
    """own_buzz_history.mdから過去89投稿の冒頭フック一覧を抽出する"""
    try:
        with open(OWN_BUZZ_HISTORY_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return ""


def load_sleep_axis_brief() -> str:
    """ジャンル軸戦略の要点を抽出（任意ファイル・無くても続行）"""
    try:
        with open(GENRE_AXIS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        # 「投稿テーマ → 軸への接続マップ」セクションがあればそこだけ
        start = content.find("## 🌐 投稿テーマ →")
        end = content.find("## 💰")
        if start >= 0 and end > start:
            return content[start:end].strip()
        return content[:2000]
    except FileNotFoundError:
        return ""



def get_briefing_from_issue(issue_number: int, gh: GitHubIssues) -> str:
    """GitHub Issueのコメントから情報リサーチのブリーフィングを抽出する"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if "情報リサーチより" in comment.body and "ブリーフィング" in comment.body:
            return comment.body
    return ""


def get_malfoy_feedback(issue_number: int, gh: GitHubIssues) -> str:
    """校閲の差し戻し or オーナーの修正指示を取得する（あれば）"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if comment.body.strip().startswith("修正:") and comment.user.type != "Bot":
            return f"【オーナーからの修正指示】\n{comment.body.strip()}"
        if "校閲より：差し戻し" in comment.body:
            return comment.body
    return ""


def load_voice_definition() -> str:
    """buzz_posts.mdから「自分のアカウントの声」定義セクションを抽出する"""
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
    """buzz_posts.mdからバズ要因分析（構造の教訓）だけを抽出する。実際の投稿文は含めない"""
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


def generate_posts(briefing: str, voice_def: str, ref_posts: str, malfoy_feedback: str = "",
                   own_hooks: str = "", sleep_axis: str = "",
                   product: dict = None, persuasion: str = "", post_type: str = "auto") -> str:
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
■ 自然な日本語ルール（最重要）:
- 語尾は声定義のもの（だよ/だね/だよね/なんだ/ちゃった/かも/かもね/だっけ/だったり 等）を**柔軟に混ぜる**。同じ語尾を3連続させない
- 丁寧語（です・ます・ですよ・ましょう）は使わない。フランクな話し言葉
- 「皆さん」NG、「みんな」を使う
- 体言止めや「〜なの。」「〜ね。」「〜なんだよね。」など、自然な余韻の語尾もOK

■ 句点「。」のルール（精密化）:
- **語尾の後の「。」は通常通りつけてOK**（例: 〜なんだよね。／〜なの。／〜だよ。）
- **❌ NG: 「」の直後に「。」を付けない**（例: 「ありがとう」。 ← NG。「ありがとう」 でOK）
- **❌ NG: 絵文字の直後に「。」を付けない**（例: 嬉しい✨。 ← NG。嬉しい✨ でOK）
- 体言止め後は付けない（例: これがコツ。← NG → これがコツ）
- 文末が「！」「？」「…」の時はそのまま（。を追加しない）

■ カギ括弧「」のルール（過剰使用禁止）:
- **1投稿あたり最大2箇所まで**
- 使うのは「実際に発した言葉の引用」or「明確に強調したい固有名詞」のみ
- ❌ NG: 概念や一般名詞をいちいちカッコで括る（「環境」「気分」「ちょっとした工夫」「効果」等の一般用語）
- ✅ OK: 実際の発言の引用1つ／重要な固有名詞1つ（強調1回）
- 強調は**カッコではなく文の流れと改行**で表現する

■ 絶対禁止文字:
- **（マークダウン太字）禁止。強調したくなっても**普通の文**として書く（カッコでも括らない）
- *（アスタリスク単体）禁止
- "（ダブルクオート）「"」「"」「”」「''」全て禁止
- 見出し ## や区切り --- も禁止
- 「」が未閉じ（開きカッコだけで閉じカッコがない）になっていないか必ず最終確認

■ 絶対禁止絵文字:
- 🤭（覗き見・口元手）は使用禁止。不自然な印象を与えるため
- 代替として 🤣 / 💦 / ✨ / 🙌 / 🔥 を使うこと

■ 自然な日本語の例（この感じで書く）:
良い例：
　〇〇って、ほんとつらいよね
　うちもそうだったから気持ちわかる💦
　でね、これ試してみたらいきなり変わったの
　〇〇っていうのを使ってみたら、肌触りがすーっとして
　完璧じゃないけど、試す価値はあるかも🙌

悪い例（カッコ過剰・句点全文末・体言止めなし）：
　〇〇に悩む「あなた」へ。
　「環境」を変えてみて。
　「キーワード」を使うと「効果」が出る。
　「ちょっとした工夫」で変わるよ。
"""

    feedback_section = f"""
## ⚠️ 校閲からの前回差し戻し指摘（必ず反映すること）
{malfoy_feedback}
""" if malfoy_feedback else ""

    # ── アフィリ投稿セクション（post_type=affiliate のみ） ──
    affiliate_section = ""
    if post_type == "affiliate" and product:
        product_name = product.get("name", "")
        product_url = product.get("affiliate_url") or product.get("url", "")
        product_price = product.get("price", 0)
        product_review_count = product.get("review_count", 0)
        product_review_avg = product.get("review_average", 0)
        product_image = product.get("image", "")
        sleep_conn = product.get("sleep_connection", "")
        affiliate_section = f"""
---
## ★今日のアフィリ商品（必ず1つのSLOTで紹介する）★

商品名: {product_name}
価格: ¥{product_price:,}
レビュー: ★{product_review_avg}（{product_review_count}件）
ジャンル軸への接続: {sleep_conn}
アフィリリンク（投稿の最後に必ず挿入）: {product_url}

### アフィリ投稿のルール（厳守・「親 + ツリー1個」の2投稿構造）
**SLOT_3（22時）は ===THREAD=== 区切りを1個だけ使い、合計2ブロックで生成する。**
**3ブロック以上にしないこと。バズ＋成約しているアカウントは全て2投稿構造。**

#### 親投稿（最初のブロック）= 強烈フック+体験+商品名OK
- **3〜5行**で簡潔に
- **強烈なフックを1〜2行目に配置**。型の例：
  - 損失回避型：「マジで広がって欲しくないけど、{{ターゲットの悩み}}な人は〇〇試して」
  - 権威即出し型：「{{あなたの肩書き・経歴}}の私が断言する。{{結論}}」
  - ターゲット呼びかけ型：「{{ターゲットの悩み}}で限界のあなたへ」
  - 体験告白型：「実は私、{{自分の悩み・状況}}だったから話題の〇〇試してみた」
- 商品名は1行目から登場OK（参考アカウントは堂々と出している）
- 体験ベースの具体性。「マジで」「ガチで」「ぶっちゃけ」など口語ラフOK
- 権威の見せ方：1行目に肩書きをサラッと混ぜる（buzz_posts.md の声定義から）
- **絶対NG**：【PR】 / `#PR` / `pr` / `#広告` / アフィリリンク / 「リンクから見て」のCTA

#### ツリー1（最後のブロック）= 続き+pr+リンク
- **2〜4行**で簡潔に
- 親投稿の続き or 補足（弱点・注意・別の使い方など両面提示で信頼UP）
- 末尾に **「pr」または「PR」** を**単独行 or 文末**で配置
- 改行してアフィリリンク（`{product_url}` をそのまま貼る・短縮形OK）

#### 参考フォーマット（厳守）
親投稿（===THREAD===の前）の例：
   {{あなたの肩書き}}の私が断言する。
   {{ターゲット呼びかけ}}、これ試してみて。
   （以下、体験談を2〜3行・具体的な変化・五感）

ツリー1（===THREAD===の後・最終ブロック）の例：
   ちなみに洗濯時はネットに入れてね！pr
   {product_url}

→ ★最重要ルール（絶対遵守）
- `===THREAD===` は **1個だけ**（合計2ブロック）
- 親投稿には **絶対にPR表記とリンクを書かない**
- ツリー1には **必ず pr または PR** を配置（小文字 pr もOK）
- **ツリー1の最終行は以下の文字列をそのままコピーして配置すること（変更・要約・プレースホルダ化禁止）：**
{product_url}
- 上記URLを `[楽天アフィリリンク]` `[ここにリンク]` 等のプレースホルダに置き換えるのは絶対禁止

### 心理誘導トリガー（親+ツリー1の中で最低2つ使う）
{persuasion}

### 体験/未使用の表現出し分け
- 実体験商品：「使ってる」「うちでも買ったの」
- 未使用商品：「気になってる」「ママ友のおすすめ」「試したいなと」
- ※ 嘘の体験を装うのは絶対NG（ステマ規制違反）

### 後悔させない原則
- 商品の弱点や注意点を1つ正直に書く（両面提示効果で信頼UP）
- 「合うかは確かめてみてね」で自由意志を残す

### NG表現
- 「絶対」「必ず」「100%」「治る」「効く」（景表法・薬機法違反）
- 「私のリンクから買って」「DMで教えます」（楽天規約違反）
- 「世界一」「業界No.1」（根拠なき断定）
- 残り2スロット（SLOT_1・SLOT_2）は通常の教育・興味付け投稿（PRなし）
"""

    # ── A/Bテスト構造の検出 ──
    has_ab_test = "安定枠の指示" in briefing and "実験枠の指示" in briefing

    if has_ab_test:
        slot_section = """## 時間帯別トーン＋A/Bテスト構造（最重要）
🌅 SLOT_1【12時・安定枠】ブリーフィングの「勝ちパターン」のフック×フォーマットを使用。ランチ滞在ピーク・気軽インプット用。
🌆 SLOT_2【19:30・安定枠】ブリーフィングの「勝ちパターン」のフック×フォーマットを使用。{{購入直前フェーズ}}の解決策・実践系。
🌙 SLOT_3【22時・実験枠】ブリーフィングの「実験パターン」のフック×フォーマットを意図的に使用。アフィリ集中枠（火・木・金）。
  ★このスロットは「普段と違う」角度を試す枠。ブリーフィングの実験指示に必ず従うこと。"""
        diversity_rule = """## ★超重要★ A/Bテスト構造に従うこと
- SLOT_1/SLOT_2（安定枠）: 勝ちパターンのフック×フォーマットを使い、別テーマ・別角度で2本
- SLOT_3（実験枠）: 実験パターンのフック×フォーマットを使用。安定枠とは意図的に異なるアプローチ
- 3スロット全て別テーマであること（これは変わらない）"""
    else:
        slot_section = """## 時間帯別トーン
🌅 SLOT_1【12時】ランチタイム情報・気軽インプット。「今日から使える知識」
🌆 SLOT_2【19:30】{{購入直前の意思決定フェーズ}}向け実践系。「今夜試せる」
🌙 SLOT_3【22時】自由時間の購買決断・アフィリ集中（火木金）。「気になったら覗いてみて」"""
        diversity_rule = """## ★超重要★ 3スロットそれぞれ異なるネタ・切り口にすること
- SLOT_1/2/3 は必ず別テーマ・別角度
- ブリーフィングのネタは1スロットにのみ使い、残り2スロットは実体験バンクから別の切り口で"""

    prompt = f"""
## 発信テーマ（必須・厳守）
声定義の「発信テーマ・ポジション」「世界観の中心」に書かれた軸で書くこと。
- 声定義のテーマに沿った**自分の実体験・気づき・ノウハウ**として語る
- 情報リサーチのブリーフィングは「ネタのヒント」として使う。そのままコピーしない
- 参考バズデータ（reference_buzz_patterns.md）は**構造・フックだけ**借用し、本文は自分の言葉で

## 【最重要】声定義の完全遵守
「声定義」ブロックは system_instruction でも渡しているが、ここでも念押し：
- 語尾・一人称・呼びかけ語は声定義そのまま
- 絵文字は声定義の「よく使う絵文字」から選ぶ（列挙以外は使わない）
- 「避ける絵文字・表現」に該当するものは絶対NG
- 「理想投稿サンプル」（B-2セクション）があれば、構造・リズム・呼吸をそれに寄せる
- 権威の見せ方も声定義どおり（上から目線NG、自嘲や対等を混ぜる）

## 科学的根拠・専門用語の扱い方
- 専門用語をそのまま使わない（例: 前頭前野→脳の「切り替える部分」、固有感覚→体の「落ち着きスイッチ」）
- 「知ってる？」「実はね、」で読者と同じ目線から入る
- 難しい言葉を使う時は**必ず直後に噛み砕いた1文**を添える

## 自然さのための鉄則（不自然感の主因を潰す）
- 箇条書きの多用を避ける。地の文で呼吸のあるリズムにする
- 完璧な結論より、迷いや余白を残す（〜かもしれない／気のせいかもだけど／たぶんね 等）
- 〜の理由／〜な方法 等の教本調タイトル禁止。会話の続きのように始める
- ハッシュタグ禁止（Threadsでは逆効果）
- 結論→本文のビジネス書構造ではなく、導入→共感→気づき→軽い締め の対話構造
- 同じ接続詞の連続使用禁止（でも・だから を3連続で使わない）
- 読者に問いかける瞬間を1箇所入れる（〜ってなかった？／みんなどう？ 等）

## ★ AIっぽさを消す具体ルール（最重要） ★

### 句点「。」の使い方（精密ルール）
- **語尾の後の「。」は通常通り**（〜だよね。／〜なの。／〜なんだ。 はOK）
- **「」（カギ括弧）の直後に「。」を付けない**
  - ❌「{{相手の状態を心配する一文}}」。 ← 不自然
  - ✅「{{相手の状態を心配する一文}}」
- **絵文字の直後に「。」を付けない**
  - ❌ 嬉しい✨。 ← 不自然
  - ✅ 嬉しい✨
- 文末が「！」「？」「…」の時はそのまま、追加で「。」を付けない

### カギ括弧「」の使い方
- 1投稿（ツリー含む全体）で**最大2箇所まで**
- 使うのは「実際の言葉の引用」or「明確に強調したい固有名詞ひとつだけ」
- ❌ 概念名や一般用語をいちいち括らない（一般用語・概念名を全部「」で囲むのはAI的）
- ✅ そのまま地の文で書いて、強調したい1語だけ括弧 or 太字なし

### 体言止め・余韻の活用
- 全部「〜だよ。」で締めず、「〜だね」「〜なの」「〜しちゃう」「〜なんだよね」「〜かも」「〜って感じ」を混ぜる
- 体言止め（夜のルーティンが大事／これがコツ）も自然
- 文末を絵文字や「…」「、」で切る形もOK

### ★話しかけるような語り口（最重要）★
読者の顔を見ながら一対一で話している雰囲気を作る。

【NG（独り言・宣言調・ぶっきらぼう）— 絶対避ける】
- 〜だ。／〜なんだ。／〜なのだ。
- 〜である。／〜と思う。
- 例:
  ❌ 気づいたことがあったんだ。
  ❌ これが大事なんだ。
  ❌ 変わったんだ。
  ❌ 効果があったんだ。

【OK（話しかける・共有する・共感を求める）】
- 〜だよね。／〜なんだよね。／〜だったんだよね。／〜だったんだよ。／〜だったの。
- 〜よ／〜の／〜じゃない？／〜よね？／〜って思わない？
- 〜してね／〜してみて／〜気がする
- 体言止めも自然（「これがコツ」「夜のルーティンが大事」）
- 例（NGをOKに変換）:
  ✅ 気づいたことがあったんだよね。／気づいたことがあったの。
  ✅ これが大事なんだよね。／これが本当に大事だったの。
  ✅ 変わったんだよね、ほんとに。／変わったの、ほんとに。
  ✅ 効果があったんだよ。／効果があったの。／効果あったんだよね。
  ✅ 私も最初は同じだったんだよね…
  ✅ 試してみたら違ったんだよね。

### ★ 不要な「」を入れない ★
- **語り掛け文（地の文）の冒頭に「」を付けない**
- ❌ NG例：
  - 「{{良かれと思ってやってたことが裏目に出る系の気づき文}}」
- ✅ OK例（カッコなしで地の文として語る）：
  - {{良かれと思ってやってたことが裏目に出る系の気づき文}}
- 「」は**実際の発話の引用**（例：『どうしたらいいの！』って途方に暮れた）でのみ使う

### ★ 1日3スロットでの言い回し重複禁止 ★
- 同じ冒頭フレーズを2スロット以上で使わない
- ❌ NG例：
  - SLOT_1冒頭：「{{ターゲット呼びかけフック}}」
  - SLOT_2冒頭：「{{ターゲット呼びかけフック}}」（同じ！）
- 各スロットで別々の冒頭・別々の悩み軸・別々の体験談を出すこと

### 句読点・感嘆符の自然な使い方
- 「！！」のように感情表現の強調はOK（「すごくわかる！！」「ほんとに！」）
- 締めの絵文字は付けすぎない（1〜2個まで）
- 「…」（三点リーダー）は迷い・余韻を出したい時だけ

### 共感・呼びかけのバリエーションを散りばめる
- 「〜じゃない？」「〜よね？」「〜って思わない？」（同意を求める）
- 「私もね、」「うちもね、」（並走している感）
- 「わかる、」「ほんとに、」（短い相槌）
- 「ね、」「ね？」（直接的な呼びかけ）
- 「って思うんだ」「って気がするの」（自分の意見の柔らかい提示）

### 切り出し・展開の自然さ
- 急に「では、」「さて、」「実は、」を多用しない
- 「あのね、」「でね、」「そういえば、」「だからね、」など、おしゃべりっぽい接続詞を混ぜる

### 良い文/悪い文の対比

【悪い例】（AIっぽい・カッコ過剰・全文。あり）
　「〇〇」に悩む「あなた」へ。
　「環境」を変えるのが大事です。
　「キーワード」を使うと「効果」が入ります。
　「ちょっとした工夫」で変わります。

【良い例】（自然・カッコ最小・余韻あり）
　{{ターゲット共感文}}
　うちも昔そうだった
　で、試してみて変わったのがコレ
　〇〇っていうの使ってみると、不思議と感覚が変わるの
　完璧じゃないけど試す価値あるかも🙌

### 句読点の自然なリズム
- 短文と長文を混ぜる
- 読点「、」を多めに使うと話し言葉っぽくなる（例: でね、こう思ったの）
- 改行で間を作る（句点で締めなくても改行で区切れる）

## ★書き出しの多様化★（ハイブリッド設計：過去バズ89フックを活用）

### 3スロットの書き出し選定ルール（★厳守★）

own_buzz_history.md に**過去の万バズ投稿89件**の冒頭30文字が一覧化されている。これは自分のアカウントで実際にバズった型。以下のルールで**毎回違う書き出し**を生成すること：

**🔸 SLOT_1（昼・12時）：過去バズフックから直接選択**
- own_buzz_history.md のフック一覧から**1つ選択**し、**そのリズムと雰囲気を再現**する
- 「え〜、」「あのー、」「え？ちょっと、」「実はね、」など、自分のアカウントの声そのままで書き出す（buzz_posts.md の声定義参照）
- 過去の閲覧数が高いフック（10万超）を優先的に参考にする
- ただし本文内容は今日のブリーフィングに合わせて新規に書く

**🔸 SLOT_2（夜・19:30）：新規生成（SLOT_1と違う型）**
- 過去フックの「雰囲気」だけ学び、**新しいフレーズを生成**
- SLOT_1で使ったパターンは絶対に避ける

**🔸 SLOT_3（深夜寄り・22時）：新規生成（SLOT_1/2と違う型）**
- 同じく新規生成
- SLOT_1/2で使った型は避ける

### 書き出しパターンの例（SLOT_2/3 用）

- 共感呼びかけ型：「○○で悩んでるママへ！」「○○を繰り返すうちの子、こうすると落ち着いたよ」
- 自己開示型：「実はね、うちの子も○○で…」「正直に言うと、私○○で失敗したんだよね」
- 驚き型：「え、知ってた？○○って…」「びっくりするくらい変わったのが」
- 肩書き権威型：「○○として△△を見てきて、わかったのが」「保育の現場で気づいたこと」
- 問いかけ型：「○○、どうしてる？」「みんなの家では、○○どんな感じ？」
- 体験ストーリー型：「昨日、うちの子が○○してて…」「この前○○があって、そこで気づいたんだけど」
- ネガポジ対比型：「○○するくらいなら、△△に変えてみて」「××だと思ってたけど、実は逆で」

### 絶対NG
- 3スロット全て同じ書き出し型
- 「ってママへ！」を3スロット全てで使う
- 「え〜」や「実はね」等の口語を3スロット全てで使う
- 冒頭の記号（「」や…）も全スロット同一にしない
- 同じ終助詞での終わりも3連発NG（「〜だよ。」で3スロット全て終わらせない）

---

## ★ジャンル軸の接続（週全体で自然に織り込む）

**このアカウントは buzz_posts.md で定義された「世界観の中心」を持つ。ただし毎投稿でその軸を明示する必要はない。**
以下の方針で扱うこと：

### ジャンル軸の幅広い射程
あなたの世界観の中心となる軸（buzz_posts.md A項目で定義）に、日常の様々なテーマが繋がると捉える。
日常の生活・体験・学びの中から、軸につながる気づきを取り出して語る。

### 接続強度のルール
- **3スロット中 最低1つ**でジャンル軸への接続を明示する（直接/間接どちらでも）
- 残り2スロットは**日常ネタだけでもOK**（軸を無理に付けない）
- 週全体で **アカウントのブランドが伝わる頻度**（3日以上は軸に直接言及）が基準
- 矛盾NG（軸と相反する商品を紹介する等）

### 接続の自然な出し方
- 締めの1文で軽く「〇〇って、最終的には{{あなたの軸}}にも繋がるんだよね」
- または気づきベースで「実は〇〇は△△から来てるんだよね」
- 軸の単語を毎回使う必要はない。言い換え・連想語でもOK

---
## ★自分の過去バズ89投稿のフック一覧（SLOT_1で1つ選んで使用）★
{own_hooks}

---
## ジャンル軸の接続マップ（Q2ルール：接続は週全体で自然に）
{sleep_axis}

---
## バズ構造の型（「型」だけ参考にする。本文は自分の言葉で）
{ref_posts}

---
## 情報リサーチのブリーフィング（ネタのヒントとして使う）
{briefing}
{feedback_section}
{affiliate_section}

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

{diversity_rule}

## ★改行ルール★
- 文の途中で絶対に改行しない（句点・文末語尾の後のみ）
- ❌ NG：「SNS投稿やデータ分析まで、\\n自動化できる。」
- ✅ OK：「SNS投稿やデータ分析まで自動化できる。\\n作業時間が10分の1になったのさ。」

## ★絶対禁止文字★
- * （アスタリスク）は絶対に使用禁止。1つでも含まれていたら即差し戻し
- 強調したい場合は「」（カギ括弧）を使うこと

{slot_section}

## ツリー投稿形式（内容の密度に応じて3〜5投稿を使い分ける）

### ⛔ 各投稿の文字数（★厳守★ 短すぎ禁止）

**自然さルールに従っても、以下の文字数は必ず守ること。短すぎる投稿は内容の薄い投稿として楽天規約違反になりうる。**

- **1投稿目（フック）：60〜100文字** — 興味を引く一文＋ターゲット呼びかけ
- **2投稿目以降（本文）：各150〜300文字** — 具体例・ノウハウ・体験談・科学的根拠を展開
  - ❌ 70字や100字で本文を済ませない
  - ✅ 体験談を膨らませて150字以上にする
- **最終投稿（CTA）：80〜130文字** — まとめ＋具体的な価値提示

### 文字数を満たすコツ（短くしすぎないため）
- 1文を短く切るのは良いが、**1パーツ全体は150字以上**に保つ
- 体験談を1個足す（「私もね、◯◯した時期があってね…」を入れる）
- 具体例・固有名詞を入れる（実体験エピソード・固有名詞・時間/場所の特定）
- Before/Afterを入れる（「今までは○○だった、今は△△になった」）
- 読者への小さな問いかけを入れる（「みんなはどう？」「○○ってない？」）

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

🌅 SLOT_1【12時・ランチ投稿】（情報・発見系）
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

🌆 SLOT_2【19:30・夜投稿】（解決策・実践系）
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

🌙 SLOT_3【22時・深夜寄り投稿】（購買決断・アフィリ集中系）
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

    # 定番つかみが1投稿目に含まれていない場合、強制的に挿入する
    if opening_line:
        result = force_opening_line(result, opening_line)

    # ── 禁止文字のサニタイズ（AIが誤って出力しても除去する保険） ──
    result = sanitize_post_text(result)

    # ── アフィリ投稿のリンクプレースホルダを実URLで置換（保険） ──
    if post_type == "affiliate" and product:
        actual_url = product.get("affiliate_url") or product.get("url", "")
        if actual_url:
            placeholder_patterns = [
                r'\[楽天アフィリ(?:エイト)?リンク\]',
                r'\[ここにリンク[^\]]*\]',
                r'\[アフィリ(?:エイト)?リンク\]',
                r'\[商品リンク[^\]]*\]',
                r'\[楽天リンク[^\]]*\]',
            ]
            for pat in placeholder_patterns:
                result = re.sub(pat, actual_url, result)

    # ── compliance_officer が参照するファイルを書き出す ──
    # affiliate-cycle.yml の compliance step が /tmp/writer_post.txt を cat するため
    try:
        with open("/tmp/writer_post.txt", "w", encoding="utf-8") as f:
            f.write(result)
        logger.info("/tmp/writer_post.txt に投稿案を書き出しました（compliance用）")
    except Exception as e:
        logger.warning(f"/tmp/writer_post.txt 書き出し失敗（非致命・続行）: {e}")

    return result


def sanitize_post_text(text: str) -> str:
    """投稿本文から禁止文字を除去（過剰なカッコを生まない）。
    - **text** → text（プレーンに、カッコは追加しない）
    - * 単体 → 削除
    - ダブルクオート類 → 削除（カッコに変換しない）
    - 見出し記号 ## / 区切り --- → 削除
    - 未閉じの「（開きカッコだけで終わる行）→ 開きカッコを削除
    """
    import re
    # **text** → text（カッコは増やさない）
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # 残った * を削除
    text = text.replace('*', '')
    # ダブルクオート類はすべて削除（カッコに変換しない）
    for q in ['"', '"', '"', '“', '”', '＂']:
        text = text.replace(q, '')
    # シングルクオートの連続 '' も除去
    text = text.replace("''", '').replace("''", '')
    # マークダウン見出し / 区切り
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^-{3,}\s*$', '', text, flags=re.MULTILINE)

    # 「」のバランスチェック：開きと閉じの数が合わない場合、過剰な記号を削除
    fixed_lines = []
    for line in text.split("\n"):
        opens = line.count("「")
        closes = line.count("」")
        if opens > closes:
            diff = opens - closes
            for _ in range(diff):
                idx = line.rfind("「")
                if idx >= 0:
                    line = line[:idx] + line[idx+1:]
        elif closes > opens:
            diff = closes - opens
            for _ in range(diff):
                idx = line.find("」")
                if idx >= 0:
                    line = line[:idx] + line[idx+1:]
        fixed_lines.append(line)
    text = "\n".join(fixed_lines)

    # ── 各SLOT単位でカギ括弧を最大3ペアまでに制限 ──
    # 4個目以降の「」ペアは削除（引用・強調が必要なケース1〜3個まで許容）
    text = limit_brackets_per_slot(text, max_pairs=3)

    # ── 禁止絵文字の除去 ──
    # 🤭（U+1F92D）は不自然なため削除
    text = text.replace("🤭", "")

    # ── 不自然な句点除去 ──
    # 「」直後の。を削除
    text = text.replace("」。", "」")
    # 絵文字の直後の。を削除（一般的な絵文字範囲）
    import re as _re
    text = _re.sub(r'([\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF])。', r'\1', text)
    # 体言止め系の「！」「？」「…」直後の。も削除（二重句読点）
    text = text.replace("！。", "！").replace("？。", "？").replace("…。", "…")

    return text


def limit_brackets_per_slot(text: str, max_pairs: int = 3) -> str:
    """各SLOT（===THREAD===区切り含む全体）内で「」ペアを最大数までに制限。
    超過分は単純な括弧削除で平文化する。"""
    import re
    # SLOT区切り（オーナー用テンプレ）または ===THREAD=== で分割せず、
    # 全体を一塊として処理（プロンプト全体で2-3個ルールに合わせる）
    matches = list(re.finditer(r'「([^」]*)」', text))
    if len(matches) <= max_pairs:
        return text
    # 最初のmax_pairs個は保持、それ以降は「」を外す
    # 後ろから処理して位置ずれを防ぐ
    excess = matches[max_pairs:]
    for m in reversed(excess):
        full_match = m.group(0)  # 「xxx」
        inner = m.group(1)       # xxx
        # シンプルに「」を取り除く
        start, end = m.span()
        text = text[:start] + inner + text[end:]
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
    import argparse as _argparse
    parser = _argparse.ArgumentParser()
    parser.add_argument("--post-type", choices=["education", "interest", "affiliate", "auto"],
                        default="auto", help="投稿タイプ（アフィリチーム用）")
    args = parser.parse_args()

    logger.info(f"=== ライター 投稿案作成開始 (post_type={args.post_type}) ===")

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()
    gh.update_pipeline_status(issue.number, "writer", "running")

    try:
        briefing = get_briefing_from_issue(issue.number, gh)
        if not briefing:
            logger.error("情報リサーチのブリーフィングが見つかりません。先にhermione_research.pyを実行してください。")
            gh.update_pipeline_status(issue.number, "writer", "error")
            sys.exit(1)

        voice_def = load_voice_definition()
        logger.info(f"声定義ロード: {len(voice_def)}文字, persona={extract_persona_name(voice_def)}, opening={extract_opening_line(voice_def)}")
        ref_posts = load_reference_posts()
        own_hooks = load_own_buzz_hooks()
        logger.info(f"過去バズフック一覧ロード: {len(own_hooks)}文字")
        sleep_axis = load_sleep_axis_brief()
        logger.info(f"ジャンル軸戦略ロード: {len(sleep_axis)}文字")
        # アフィリ投稿日は商品データと心理誘導ナレッジをロード
        product = {}
        persuasion = ""
        if args.post_type == "affiliate":
            product = load_today_product()
            persuasion = load_persuasion_brief()
            structure = load_affiliate_structure()
            if structure:
                persuasion = f"{persuasion}\n\n---\n# 参考アカウント分析（必読・2投稿構造の根拠）\n\n{structure}"
            if product:
                logger.info(f"今日のアフィリ商品: {product.get('name', '')[:50]}... ★{product.get('review_average')} ¥{product.get('price')}")
            else:
                logger.warning("アフィリ投稿日だが商品データが見つかりません。商品リサーチが先に実行されているか確認してください。")
        malfoy_feedback = get_malfoy_feedback(issue.number, gh)
        if malfoy_feedback:
            logger.info("校閲の差し戻しコメントを取得しました。フィードバックを反映して再生成します。")

        posts = generate_posts(briefing, voice_def, ref_posts, malfoy_feedback,
                               own_hooks=own_hooks, sleep_axis=sleep_axis,
                               product=product, persuasion=persuasion,
                               post_type=args.post_type)
        logger.info("投稿案3案生成完了")

        comment_body = f"""## ✍️ ライターより：3時間帯投稿案 完成

**作成日時:** {_now_jst().strftime('%Y-%m-%d %H:%M')}

{posts}

---
*校閲、3スロット分の校閲をお願いします。*
"""
        done_ts = _now_jst().strftime("%H:%M")
        gh.add_comment(issue.number, comment_body)
        gh.update_pipeline_status(issue.number, "writer", "done", done_ts)
        logger.info(f"GitHub Issue #{issue.number} に投稿案を追加しました")
        logger.info("=== ライター 投稿案作成完了 ===")

    except Exception as e:
        logger.error(f"ライター実行失敗: {type(e).__name__}: {e}")
        gh.update_pipeline_status(issue.number, "writer", "error")
        gh.add_comment(issue.number, f"## ❌ ライター: エラー発生\n\n```\n{type(e).__name__}: {str(e)[:500]}\n```")
        url = os.getenv("DISCORD_WEBHOOK_URL", "")
        if url:
            try:
                requests.post(url, json={"content": f"❌ ライター実行エラー: {type(e).__name__}: {str(e)[:200]}"}, timeout=10)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
