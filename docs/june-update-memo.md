# 6月更新予定メモ（第11報）

作成日：2026-04-16  
対象バージョン：member-kit v2.0（2026年6月リリース予定）

---

## 概要

A/Bテスト自動化 + 戦略自動分析機能の追加。
全て後方互換（データ不足時は既存動作にフォールバック）。

---

## 変更ファイル一覧

### 1. scripts/utils/post_classifier.py（新規作成）

- `classify_hook_type(text)`: 感情フック（好奇心／共感／驚き／危機感）を正規表現で自動分類
- `classify_format_type(text)`: フォーマット（リスト／体験談／対比／質問）を自動分類
- APIコール不要・コストゼロ

### 2. scripts/hermione_research.py（変更）

変更箇所：`load_performance_summary()` と `generate_briefing()` の2関数

- `load_performance_summary()` に追加：
  - `hook_analysis`：感情フック別の平均ER分析
  - `format_analysis`：フォーマット別の平均ER分析
  - `winning_pattern`：勝ちパターンの自動特定
  - `experiment_suggestion`：実験内容の提案

- `generate_briefing()` に追加：
  - SLOT_1/2 = 安定枠（勝ちパターン指示）
  - SLOT_3 = 実験枠（新パターン指示）
  - データ不足時は既存の汎用ディレクティブにフォールバック

### 3. scripts/luna_write.py（変更）

変更箇所：`generate_posts()` 内の `slot_section` と `diversity_rule`

- ブリーフィングに「安定枠の指示」「実験枠の指示」が含まれるか自動検出
  - 含まれる場合：SLOT_1/2=勝ちパターン、SLOT_3=実験パターンで生成
  - 含まれない場合：既存の時間帯別トーンにフォールバック

### 4. scripts/ron_auto_measure.py（変更）

変更箇所：レポート生成セクション + Google Sheets書込セクション

- 各投稿のフック・フォーマット分類を計測レポートに表示
- SLOT_3（実験枠）と安定枠の比較評価を自動実施
- Google Sheetsの「使用感情フック」列に分類結果を自動書込

---

## 4月時点で適用済みの修正（第11報に含まれるが適用不要）

- snape_daily.py の誤検知防止（第10報で適用済み）

---

## 6月リリース時の作業手順

1. `post_classifier.py` を `scripts/utils/` に新規作成
2. `hermione_research.py` の上記2関数を置き換え
3. `luna_write.py` の `generate_posts()` を修正
4. `ron_auto_measure.py` のレポート・Sheets書込セクションを修正
5. member-kit テストフォルダで動作確認
6. ZIPを再作成してGoogleドライブを更新
7. Discordの kit-リクエスト チャンネルに更新通知を投稿
