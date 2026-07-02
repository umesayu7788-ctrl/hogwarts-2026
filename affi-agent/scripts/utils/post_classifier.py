"""
post_classifier.py
投稿テキストから感情フック・フォーマット・投稿タイプを自動分類するユーティリティ

情報リサーチ（戦略分析）と投稿・計測（計測記録）の両方から使用される。
"""

import re


def classify_post_type(text: str) -> str:
    """
    投稿テキストから投稿タイプを判定する（アフィリエイトチーム用）。

    Returns: "affiliate" / "education" / "interest"
    """
    if not text:
        return "interest"

    t = text

    # アフィリ判定: #PR / #広告 タグ、アフィリリンク（rakuten.co.jp, amzn.to, amazon.co.jp）
    if re.search(r"#PR|#広告|#アフィリ", t):
        return "affiliate"
    if re.search(r"rakuten\.co\.jp|amzn\.to|amazon\.co\.jp|a\.r10\.to|hb\.afl\.rakuten", t):
        return "affiliate"

    # 教育判定: 学び・知識提供系のキーワード
    if re.search(r"知っておき|押さえて|覚えて|学び|気づき|ポイント|整理|まとめ", t):
        return "education"

    # それ以外は興味付け
    return "interest"


def classify_hook_type(text: str) -> str:
    """
    投稿テキスト冒頭から感情フックの種類を判定する。

    Returns: "好奇心" / "共感" / "驚き" / "危機感" / "不明"

    判定優先順位: 危機感 > 驚き > 好奇心 > 共感 > 不明
    """
    if not text:
        return "不明"

    t = text[:150]  # 冒頭150文字で判定

    # 危機感（損失回避・緊急性）
    if re.search(r"損して|損する|損じゃない|危険|やばい|知らないと|知らなきゃ|"
                 r"差がつく|差が出る|取り残|遅れ|遅い|置いてかれ|頭打ち|"
                 r"消耗して|消耗してる|疲弊|搾取|今すぐ|待って|ちょっと待|まだ[^。]*かい", t):
        return "危機感"

    # 驚き（意外性・衝撃）
    if re.search(r"え[、,!！]|まさか|知らなかった|衝撃|信じられない|"
                 r"実は[^。]{0,5}じゃない|驚[いき]|想像と[^。]*違|"
                 r"嘘[だじ]|本当[はに][^。]*違", t):
        return "驚き"

    # 好奇心（知りたい欲求）
    if re.search(r"知って[るた]？|教えよう|伝える[ねよ]|方法|コツ|秘密|"
                 r"実は|[0-9０-９]+選|仕組み|裏側|舞台裏|"
                 r"[^。]*って知って|どうやって|なぜ[^。]*か", t):
        return "好奇心"

    # 共感（あるある・寄り添い）
    if re.search(r"わかる|あるある|しんどい|疲れた|疲れて|正直|本音|"
                 r"消耗|辛[いか]|大変[だで]|みんな[^。]*よね|"
                 r"思ってた[時期]|悩[んむ]", t):
        return "共感"

    return "不明"


def classify_format_type(text: str) -> str:
    """
    投稿テキストからフォーマットの種類を判定する。

    Returns: "リスト" / "体験談" / "対比" / "質問" / "不明"
    """
    if not text:
        return "不明"

    t = text[:200]  # 冒頭200文字で判定

    # リスト（番号付き列挙）
    if re.search(r"[0-9０-９]+選|[0-9０-９]+つ[のを]|[0-9０-９]+個|"
                 r"[①②③❶❷❸]|ランキング|一覧|まとめ|"
                 r"[1１][.．、][^0-9]", t):
        return "リスト"

    # 対比（比較・ビフォーアフター）
    if re.search(r"[vV][sS]|と[^。]*の違い|前は[^。]*今は|"
                 r"[^。]*より[^。]*方が|ビフォー|アフター|比べ|比較|"
                 r"手動[^。]*自動|[^。]*人と[^。]*人", t):
        return "対比"

    # 質問（問いかけ型）
    if re.search(r"^[^。]{0,30}？", t) or re.search(
            r"どう思う|どっち|ありません[かよ]？|いない[かよ]？|"
            r"してる？|してない？|知ってる？", t):
        return "質問"

    # 体験談（経験ベース）
    if re.search(r"やってみた|使ってみた|試した|試してみ|実際に|"
                 r"した結果|体験|経験[しした]|[^。]*てわかった|"
                 r"[^。]*て気づ[いき]", t):
        return "体験談"

    return "不明"
