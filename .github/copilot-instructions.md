# エージェントホグワーツ - AI運用チーム インストラクション

このリポジトリはThreadsの投稿運用を自律的に行う「AIスクラムチーム方式」のプロジェクトです。
GitHub Copilot / Claude Code どちらでも動作するよう設計されています。

## プロジェクト構成

```
.github/
└── agents/                     # AIエージェント定義（キャラクター・役割）
│   ├── harry.agent.md          # ハリー: 司令塔
│   ├── hermione.agent.md       # ハーマイオニー: リサーチ・分析
│   ├── luna.agent.md           # ルーナ: 投稿ライター
│   ├── malfoy.agent.md         # マルフォイ: 校閲・品質管理
│   ├── ron.agent.md            # ロン: 投稿実行・計測
│   └── snape.agent.md          # スネイプ: コスト・システム監視
└── skills/                     # スラッシュコマンド（運用スキル）
    ├── set-theme/SKILL.md      # テーマ設定
    ├── run-daily-cycle/SKILL.md # 日次6ステップループ
    ├── weekly-planning/SKILL.md # 週次計画
    ├── weekly-review/SKILL.md  # 週次レビュー
    └── weekly-retro/SKILL.md   # 週次振り返り

operation/                      # 運用成果物
├── themes/                     # 毎日のテーマ（themeXXX.md）
├── knowledge/kb_sys_ref_v001.md     # バズ投稿ナレッジ・文体サンプル
├── memory/                     # GitHub Issues外部メモリ説明
└── weekly/                     # 週次レポート・API使用量ログ

scripts/                        # Pythonスクリプト
├── hermione_research.py        # リサーチ・分析
├── luna_write.py               # 投稿案作成
├── malfoy_review.py            # 校閲・承認申請
├── ron_post.py                 # Threads投稿実行
├── ron_fetch.py                # エンゲージメント計測
├── snape_report.py             # 週次監視レポート
├── notify_approval.py          # 承認通知（Make連携）
├── utils/github_issues.py      # GitHub Issues操作
└── requirements.txt

```

## 全体ルール

- 全ての成果物は **日本語** で記述すること
- **APIキーは `.env` ファイルで管理**（ハードコーディング禁止）
- 人間（オーナー）の承認なしに Threads への投稿を実行しない
- Python は仮想環境(`.venv`)を使用すること
- LLMは **Gemini 1.5 Flash（Google AI Studio無料枠）** を優先使用
- CSV ファイルは UTF-8（BOM付き: utf-8-sig）で保存すること

## 運用スキルの使い方

```
/set-theme          # 毎日の投稿テーマを設定
/run-daily-cycle    # 6ステップ日次ループを実行
/weekly-planning    # 週次コンテンツ計画（月曜日推奨）
/weekly-review      # 週次パフォーマンスレビュー（金曜日推奨）
/weekly-retro       # 週次振り返り（日曜日推奨）
```

## 重要：人間承認ゲート

マルフォイが投稿案を承認申請したら、**必ず人間（オーナー）が**
GitHub Issueのコメント欄に「**承認**」と入力してから投稿が実行されます。
ロンは承認コメントなしには絶対に投稿しません。
