---
name: run-daily-cycle
description: Threads運用の6ステップ・日次ループを実行するスキル。ハーマイオニー（収集/分析）→ルーナ（執筆）→マルフォイ（校閲）→人間承認→ロン（投稿）の流れを自律実行する。毎日の主要スキル。
---

# 6ステップ・日次運用ループ実行

## 準備
- サブエージェントとして、ハーマイオニーエージェント(`.github/agents/hermione.agent.md`)をモデル"gemini-1.5-flash"で実行します。
- サブエージェントとして、ルーナエージェント(`.github/agents/luna.agent.md`)をモデル"gemini-1.5-flash"で実行します。
- サブエージェントとして、マルフォイエージェント(`.github/agents/malfoy.agent.md`)をモデル"gemini-1.5-flash"で実行します。
- サブエージェントとして、ロンエージェント(`.github/agents/ron.agent.md`)をモデル"gemini-1.5-flash"で実行します。
- サブエージェントとして、ハリーエージェント(`.github/agents/harry.agent.md`)をモデル"gemini-1.5-flash"で実行します。

## 事前確認
1. `operation/themes/` から最新の `themeXXX.md` を読み、本日のテーマを確認する
2. 本日のGitHub Issueが作成されていることを確認する（未作成なら `/set-theme` を先に実行）
3. `operation/knowledge/kb_sys_ref_v001.md` が存在することを確認する

---

## ステップ①②：ハーマイオニー（リサーチ + 分析）

ハーマイオニーエージェントを使い、以下を実行する：

1. `scripts/hermione_research.py` を実行してYouTube・RSSから情報収集
2. `operation/knowledge/kb_sys_ref_v001.md` と GitHub Issues の過去実績を分析
3. 本日の投稿ネタブリーフィングを作成
4. 当日GitHub Issueに「ハーマイオニーより：ブリーフィング完了」コメントを追加

**タイムボックス：15分以内**

---

## ステップ③：ルーナ（投稿案作成）

ハーマイオニーのブリーフィングが完了したら、ルーナエージェントを使い：

1. ブリーフィングと `operation/knowledge/kb_sys_ref_v001.md` を読み込む
2. 案A（直球型）・案B（共感型）・案C（挑発型）を作成
3. 当日GitHub Issueに「ルーナより：投稿案3案 完成」コメントを追加

**タイムボックス：10分以内**

---

## ステップ④：マルフォイ（校閲・承認申請）

ルーナの投稿案が完成したら、マルフォイエージェントを使い：

1. チェックリスト全項目を審査
2. 差し戻しの場合：ルーナに修正指示を出す（最大2回まで）
3. 承認申請可の場合：当日GitHub Issueに「承認申請」コメントを追加
4. Makeのwebhookを呼び出し、オーナーのスマホに承認通知を送る

**差し戻し込みのタイムボックス：20分以内**

---

## ⚠️ 人間承認ゲート ⚠️

この時点でループは**一時停止**する。

```
オーナーがGitHub Issueに「承認」とコメントするまで待機する。
ロンは承認コメントを確認するまで絶対に投稿しない。
```

承認確認は `scripts/ron_post.py` の冒頭で自動チェックされる。

---

## ステップ⑤：ロン（投稿実行）

GitHub Issueに「承認」コメントが確認されたら、ロンエージェントを使い：

1. `scripts/ron_post.py` を実行してThreads APIで投稿
2. 投稿成功後、GitHub Issueに「投稿完了」コメントを追加
3. 24時間後の計測タスクをGitHub Actions（計測ワークフロー）にスケジュール

---

## ステップ⑥：ロン（計測）※24時間後に自動実行

GitHub Actions `measure.yml` が24時間後に自動起動し、ロンエージェントを使い：

1. `scripts/ron_fetch.py` を実行してエンゲージメントデータを取得
2. GitHub Issuesの「投稿実績ログ」Issueに記録
3. いいね50以上の場合、`operation/knowledge/kb_sys_ref_v001.md` に追記

---

## ハリーによる全体管理

ハリーエージェントが全ステップを通じて：
- 各ステップの完了を確認する
- 問題があれば適切なエージェントに差し戻す
- 本日の運用サマリーを `operation/weekly/` に記録する
- スネイプへの日次レポートを生成する

## 完了条件
- 全6ステップが完了（または承認待ちで一時停止）している
- 当日のGitHub Issueに全エージェントのコメントが記録されている
- `operation/weekly/` に本日の記録が追記されている
