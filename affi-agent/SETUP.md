# セットアップ手順書

アフィリエイトチームのセットアップを**約10分**で完了させる手順。

---

## 前提条件チェックリスト

セットアップ前に以下を準備してください：

- [ ] GitHubアカウント（2FA有効化済み）
- [ ] 楽天アフィリエイトアカウント
- [ ] 楽天ウェブサービスのアプリケーションID
- [ ] Googleアカウント（Sheets用）
- [ ] Threadsアカウント（アフィリ用）
- [ ] Meta Developersアプリ（Threads API用）
- [ ] Discord Webhook URL（通知用・推奨）
- [ ] Gemini APIキー
- [ ] ナレッジ3本の下書き（別ドキュメントで準備済み）

---

## Step 1: GitHub Privateリポジトリ作成（5分）

1. https://github.com/new にアクセス
2. 設定：
   - Repository name: `affiliate-threads-agent`（任意）
   - Visibility: **Private** ★必須
   - Initialize: README等は追加しない（テンプレート側で持つため）
3. **Create repository** をクリック

## Step 2: テンプレートコンテンツをプッシュ（3分）

### 方法A: 手動コピー（推奨）

1. 本テンプレートの `member-kit/` フォルダの中身を全てコピー
2. 作成したリポジトリにプッシュ：
   ```bash
   git clone https://github.com/YOUR_USERNAME/affiliate-threads-agent.git
   cd affiliate-threads-agent
   # member-kit/ の中身をここに配置
   git add .
   git commit -m "Initial template setup"
   git push origin main
   ```

### 方法B: GitHub Web UIで直接アップロード

1. リポジトリ画面で **Add file** → **Upload files**
2. `template-affiliate/` の中身を全てドラッグ&ドロップ
3. コミットメッセージを入力して **Commit changes**

## Step 3: GitHub Secrets設定（5分）

リポジトリの **Settings → Secrets and variables → Actions** で以下を設定：

> ⚠️ **「Codespaces」タブではなく「Actions」タブに設定してください。** Codespaces Secrets は GitHub Actions ワークフロー（自動化）では読み込まれません。

### 必須Secrets

| Secret名 | 取得先 | 備考 |
|---|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/app/apikey | 無料（全エージェントのAI処理に使用） |
| `THREADS_ACCESS_TOKEN` | Meta Developers | アフィリ用新アカウント |
| `THREADS_USER_ID` | Meta Developers | 同上 |
| `YOUTUBE_API_KEY` | Google Cloud Console | 無料枠 |
| `RAKUTEN_APP_ID` | https://webservice.rakuten.co.jp/ | 19桁前後の数字 |
| `RAKUTEN_ACCESS_KEY` | 同上（アクセスキー欄） | 2026年2月以降の新仕様で**必須** |
| `RAKUTEN_AFFILIATE_ID` | https://affiliate.rakuten.co.jp/ | 英数字20桁 |
| `GOOGLE_CREDENTIALS_JSON` | Google Cloud Console | サービスアカウント |
| `SPREADSHEET_ID` | Google Sheetsの URL から | 新規シート作成 |
| `DISCORD_WEBHOOK_URL` | Discord設定 | 通知用 |
| `GITHUB_TOKEN` | GitHub Settings | repo + workflow scope |

### 任意Secrets（Amazon追加時のみ）

| Secret名 | 備考 |
|---|---|
| `AMAZON_ACCESS_KEY` | Amazonアソシエイト審査通過後 |
| `AMAZON_SECRET_KEY` | 同上 |
| `AMAZON_ASSOCIATE_TAG` | `xxxxxxx-22`形式 |

## Step 4: Codespaces起動（1分）

1. リポジトリのトップページで **Code** ボタン
2. **Codespaces** タブ → **Create codespace on main**
3. 30秒〜1分で環境起動
4. 初回は `pip install` と `npm install` が自動実行される

## Step 4.5: アクセスキーファイルを配置（重要・忘れずに）

GitHub へのプッシュ時、`.key` ファイルはセキュリティ保護のためリポジトリに含まれません。
Codespaces 起動後に**手動で配置**が必要です。

1. Codespaces 左サイドバーの「エクスプローラー」を開く
2. `operation/auth/` フォルダを右クリック → **Upload...**（または「ファイルをアップロード」）
3. コミュニティ Discord の配布チャンネルから `access_AFFI-YYYY-MM.key` をダウンロードしてアップロード
4. `operation/auth/` 内にファイルが表示されれば完了

> ⚠️ **このファイルがないと「始める」コマンドが最初の認証チェックで止まります。**

---

## Step 5: ナレッジ3本を記入（最重要・30分〜1時間）

Codespaces内のエディタで以下3ファイルを開き、**事前準備した内容を貼り付け**：

1. `operation/knowledge/product_purchase_rules.md`
2. `operation/knowledge/threads_affiliate_knowledge.md`
3. `operation/knowledge/six_education_framework.md`

各ファイルの「このファイルはユーザーが記入してください」という文言は削除する。

記入完了後、gitにコミット：
```bash
git add operation/knowledge/
git commit -m "Add knowledge files"
git push
```

## Step 6: GitHub Actions有効化（1分）

1. リポジトリの **Actions** タブ
2. Privateリポジトリの場合、初回は **I understand my workflows, go ahead and enable them** をクリック

## Step 7: 各ワークフローを手動で1回実行（5分）

GitHub Actions cronを活性化するため、各ワークフローを手動で1回実行：

1. **Actions** タブ
2. 各ワークフローを順に：
   - `Affiliate Daily Cycle` → Run workflow
   - `Revenue Tracker Daily` → Run workflow
   - `Scheduled Post SLOT_2` → Run workflow（slot=2）
   - `Scheduled Post SLOT_3` → Run workflow（slot=3）
   - `Monitor Daily` → Run workflow

これでcronが「活性化」され、翌日以降自動実行が安定します。

## Step 8: 外部スケジューラー設定（Google Apps Script）

cron遅延対策として、Google Apps Script で18時・21時投稿を確実に発火させます。

既存のアフィリエージェントで同じ設定をしている場合は、**新リポジトリ用に別プロジェクトを作成**して同様に設定してください。

詳細な手順は [SETUP_GAS_HEALTHCHECK.md](SETUP_GAS_HEALTHCHECK.md) を参照してください。

## Step 9: 動作確認

Codespacesのターミナルで：

```bash
claude
```

Claude Code起動後：

```
始める
```

以下を順に確認：
- [ ] ナレッジ3本が記入されていると判定されるか
- [ ] APIキー未設定の指摘が出ないか
- [ ] PHASE 3の運用メニューが表示されるか

---

## トラブルシューティング

### Codespacesが起動しない
- ブラウザをリロード
- 別のブラウザ（Chrome推奨）で試す
- 無料枠を使い切っていないか確認

### GitHub Secretsが反映されない
- Codespaceを一度停止して再起動
- Settings → Codespaces secrets → リポジトリが紐付いているか確認

### ナレッジファイルに「未記入」と判定される
- 「このファイルはユーザーが記入してください」の文言が残っていないか確認

### 楽天APIが401エラー
- `RAKUTEN_APP_ID`（9桁数字）が正しく設定されているか
- https://webservice.rakuten.co.jp/ でアプリが有効か確認
