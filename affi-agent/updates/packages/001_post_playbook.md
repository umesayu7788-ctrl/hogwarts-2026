# 📦 アップデート 001: 高インプ投稿プレイブック＋ペルソナ確定ガイド

**バージョン**: v1.0
**目的**: 投稿のインプレッション・フォロー転換率を体系的に向上させる
**対象**: SNS発信全般（業種・ジャンル不問）
**実証**: 1投稿で最高7万imp/フォロー+23、別投稿1.0-1.7万imp

---

## 📂 含まれるファイル

このパッケージには以下3ファイルが含まれます（**全て匿名化済み配布版**）：

配布元（パッケージ内の場所）:
```
updates/packages/001_files/
├── _universal_post_playbook.md      （高インプ必勝テンプレ・汎用版）
├── _persona_setup_guide.md           （ペルソナ確定対話ガイド）
└── affiliate_appeal_patterns.md      （アフィリ訴求パターン6種）
```

コピー先（顧客プロジェクト内）:
```
operation/knowledge/
├── _universal_post_playbook.md
├── _persona_setup_guide.md
└── affiliate_appeal_patterns.md
```

各ファイルの内容:
1. **`_universal_post_playbook.md`**
   - 必勝8ステップ構造
   - 絶対NGリスト
   - ジャンル別応用例

2. **`_persona_setup_guide.md`**
   - 7要素の確定プロセス
   - Claude Code への質問テンプレ
   - アンチパターン解説

3. **`affiliate_appeal_patterns.md`**
   - アフィリ訴求パターン6種
   - 商品ジャンル別最適マトリクス

---

## 🎯 適用フロー（Claude Code 実行手順）

### Phase 1: 状況確認（必須）

顧客に以下を質問：

1. **ペルソナ確定状況**：
   - 完全確定（中の人/数字/看板コピー/周辺情報/ジャンル/発信軸が全部明確）
   - 部分確定（一部曖昧）
   - 未確定（これから決めたい）

2. **既存ファイル状況**：
   - `operation/knowledge/buzz_posts.md` の有無
   - `scripts/writer.py` の有無
   - `scripts/content_review.py` の有無
   - `scripts/compliance_officer.py` の有無

→ ファイルが無い場合、相当するファイルを特定するか作成判断

---

### Phase 2: ペルソナ確定（部分・未確定の場合のみ）

`operation/knowledge/_persona_setup_guide.md` を配布パックから顧客プロジェクトにコピー後、
そのガイドの Step 1-7 を顧客と対話で実行：

- Step 1: 中の人プロフィール確定
- Step 2: 経験規模の数字を出す
- Step 3: 看板コピー（ギャップ訴求）の設計
- Step 4: 周辺情報（リアリティ作り）
- Step 5: 発信ジャンル・核の確定
- Step 6: NG・固定ルール
- Step 7: 全体統合と検証

確定したペルソナを既存の `buzz_posts.md`（または相当ファイル）に追加。

**ペルソナ完全確定済みの場合はこの Phase スキップ**。

---

### Phase 3: ファイルコピー

配布パックから以下3ファイルを顧客プロジェクトにコピー：

```
配布パック/updates/packages/001_files/_universal_post_playbook.md
→ 顧客プロジェクト/operation/knowledge/_universal_post_playbook.md

配布パック/updates/packages/001_files/_persona_setup_guide.md
→ 顧客プロジェクト/operation/knowledge/_persona_setup_guide.md

配布パック/updates/packages/001_files/affiliate_appeal_patterns.md
→ 顧客プロジェクト/operation/knowledge/affiliate_appeal_patterns.md
```

---

### Phase 4: writer.py への組み込み

顧客の `scripts/writer.py`（または相当ファイル）のシステムプロンプトに以下を**追記**（上書きしない）：

```python
■ 【最重要】必勝8ステップ構造（実証パターン）
詳細は operation/knowledge/_universal_post_playbook.md 参照

3スロット教育型は以下の構造を厳守：

【1/3 メイン】
- Step 1. 引用フック『○○』（読者の心の声）
- Step 2. 数字権威「○年、○○人見てきて」
- Step 3. 結果先出し「○○が1つだけあった」

【2/3 リプ1】
- Step 4. 答えは1つだけ『○○』
- Step 5. 理由＋なぜ効くか（短く）
- Step 6. 逆ケース対比「逆に○○な人は」

【3/3 リプ2】
- Step 7. 自分の実践（家・現場・自分の体験）
- Step 8. 低コストCTA「今日1回だけ試してみて✨」

■ 数字権威の使い分け
- 個別経験（深い）→ 「○○年、○○人を担当してきて」
- 広域観察（広い）→ 「○○年、○○人見てきて」
- 現場頻度（日常）→ 「毎日○○人にやってる現場で」
```

**追記位置の判断**:
- 既存のシステムプロンプト末尾、または「ルール」セクションがあればその直下に追加
- 既存のペルソナ固定情報セクションは絶対に消さない・触らない
- 既存の独自ルールと矛盾しない形で統合

---

### Phase 5: content_review.py への組み込み

顧客の `scripts/content_review.py`（または相当ファイル）に以下のチェック項目を**追記**：

```python
### 必勝テンプレ準拠チェック（教育型投稿）
1. 引用フック『○○』が含まれているか
2. 数字（年数・人数）が含まれているか
3. 「1つだけ」「1つあった」フレーズが含まれているか
4. 「逆に」対比が含まれているか
5. 自分の実践（家・現場・自分の体験）が含まれているか
6. CTA「○日だけ」「○回だけ」が含まれているか

→ 上記6項目のうち4項目以上欠けていたら差し戻し
```

ファイルが Python の実装ファイルなら、コメントとして追加 + 検知ロジック追加。
ファイルが Markdown ナレッジなら、セクション追加。

---

### Phase 6: compliance_officer.py への組み込み

顧客の `scripts/compliance_officer.py`（または相当ファイル）に以下のNGパターンを**追記**：

```python
# 焦らせ・押し付け訴求NG
URGENCY_NG_PATTERNS = [
    r"\d+/\d+.*セール", r"\d+月\d+日まで",
    r"明後日まで", r"明日まで", r"\d+日後",
    r"今すぐ買", r"急いで", r"在庫切れ.*前に",
    r"気になる人はチェック",
    r"DMで聞かれたので置いとくね",
    r"絶対買って", r"リピート確定",
]

# 乱暴・命令調NG
RUDE_NG_PATTERNS = [
    r"いいから片せ", r"入れろや", r"知らんが",
    r"うるさい", r"黙れ",
]
```

そして `review_post()` 関数に両チェックを組み込み：

```python
violations.extend(check_urgency_ng(post_text))
violations.extend(check_rude_tone(post_text))
```

既存のNGパターンと重複しないよう確認すること。

---

### Phase 7: テスト投稿生成（5本）

`scripts/writer.py` で教育型投稿を5本生成。

各投稿が以下を満たしているか自己評価：

- ✅ 引用フック『○○』が冒頭にあるか
- ✅ 数字権威があるか
- ✅ 「1つだけ」「1つあった」があるか
- ✅ 逆ケース対比があるか
- ✅ 自分の実践があるか
- ✅ 低コストCTAがあるか
- ✅ NG表現がないか

**5本中4本以上クリアなら適用成功**。
3本以下なら writer.py のプロンプト追記位置を見直し。

---

### Phase 8: 適用記録

顧客プロジェクトの `updates/_APPLIED.md` に以下を追記（ファイルがなければ作成）：

```markdown
# 適用済みアップデート

## 001: 高インプ投稿プレイブック＋ペルソナ確定ガイド
- 適用日: YYYY-MM-DD
- 適用範囲: 全Phase完了 / Phase 2 スキップ（既存ペルソナ確定済み）/ etc
- テスト投稿準拠度: X/5
- 備考:
```

---

## ✅ 完了チェックリスト

Claude Code は以下を全て満たしたら完了報告：

- [ ] Phase 1: 状況確認完了
- [ ] Phase 2: ペルソナ確定（必要な場合のみ）
- [ ] Phase 3: ファイルコピー完了
- [ ] Phase 4: writer.py 追記完了
- [ ] Phase 5: content_review.py 追記完了
- [ ] Phase 6: compliance_officer.py 追記完了
- [ ] Phase 7: テスト投稿5本生成・準拠度確認
- [ ] Phase 8: _APPLIED.md 記録完了

完了報告時は以下を含めること：
- 変更したファイル一覧
- テスト投稿の準拠度（5本中何本クリア）
- 未解決の課題・警告（あれば）

---

## ⚠️ 失敗時のフォールバック

各 Phase で問題が起きた場合：

| 問題 | 対応 |
|---|---|
| 既存 writer.py のプロンプト構造が大きく異なる | 顧客と相談して追記位置を確認 |
| ペルソナ確定が30分以上かかる | 一旦中断し、Phase 2を後日再開 |
| テスト投稿で準拠度3本以下 | プロンプト追記位置を見直し |
| 既存NGパターンと重複多数 | 統合せずコメントで参考扱い |

問題が解決できない場合、変更を破棄して状況を報告。

---

## 📚 参考リンク

このアップデートの背景・実証データは以下を参照：
- `_universal_post_playbook.md` の冒頭「実証データ」セクション
- 必勝8ステップの詳細解説
- ジャンル別応用例5種

---

*アップデート 001: 高インプ投稿プレイブック (v1.0)*
