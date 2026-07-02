# セキュリティ運用ルール

アフィリエイトチームを安全に運用するための必須ルール。

---

## 🔐 必須事項（設定時）

### 1. リポジトリは必ず Private

- 誤って Public 設定にしないこと
- Public になるとコミット履歴から過去のSecret漏洩も追跡される可能性

### 2. GitHub 2要素認証（2FA）必須

- https://github.com/settings/security で Enabled を確認
- **認証アプリ**（Google Authenticator等）推奨。SMSは非推奨
- Recovery Codes を安全な場所に保管

### 3. APIキーは GitHub Secrets で管理

- `.env` ファイルをリポジトリにコミットしない
- `.gitignore` で `.env` が除外されていることを確認
- Codespaces利用時は Secrets から自動注入される

### 4. Personal Access Token は最小スコープ

- 必要なスコープのみ付与：
  - `repo`: Issues・コードの読み書き
  - `workflow`: GitHub Actions制御
- 他のスコープは不要
- 有効期限: `No expiration` は Codespaces用途のみ。人間が手動で使うトークンは期限付き推奨

### 5. サービスアカウント権限の最小化

- Google Sheetsのサービスアカウントには**対象シートのみ編集権限**を付与
- Googleアカウント全体のアクセス権は与えない

---

## 🚨 緊急時の対応

### APIキーが漏洩した場合

**1. 即座に Revoke**

| サービス | Revoke手順 |
|---|---|
| GitHub PAT | Settings → Developer settings → Personal access tokens → Revoke |
| Gemini | Google AI Studio → 該当キー → 削除 |
| Threads | Meta Developers → App → 再発行 |
| 楽天 | 楽天ウェブサービス → アプリ管理 → 削除 |

**2. 新しいキーを発行**

**3. GitHub Secrets を更新**

**4. 漏洩原因を調査**
- コミット履歴の確認（`git log`）
- スクリーンショット・ログに含まれていないか確認

### GitHub アカウント乗っ取りの疑い

1. https://github.com/settings/security でログイン履歴確認
2. 不審なセッションをすべて Revoke
3. パスワード変更
4. 2FAのリセット（Recovery Code使用）
5. 全Secretsを再発行

---

## 📋 定期チェック（月1回推奨）

- [ ] GitHub Security log に不審な操作がないか確認
- [ ] Personal Access Token の有効期限が近いものがないか
- [ ] Codespaces使用量が通常範囲内か
- [ ] Secrets に使用していないものがないか（削除）
- [ ] gitignore が正しく機能しているか（`.env` が Untracked になっていないか）

---

## ⚖️ 法令遵守ルール

### ステマ規制（景品表示法・2023年10月施行）

- **アフィリ投稿には必ず `#PR` または `#広告` を含める**
- `compliance_officer` が自動付与するが、目視でも確認

### 景表法（優良誤認・有利誤認）

- 使用禁止表現：
  - 「必ず」「絶対」「100%」「世界一」「業界No.1」
  - 「確実に効果があります」等の断定

### 薬機法（医薬品医療機器等法）

- 化粧品・サプリ・健康食品について以下は禁止：
  - 「治る」「治療」「完治」
  - 「シミが消える」「肌が若返る」
  - 「ダイエット効果」「痩せる」

### アフィリエイトプログラム規約

- 楽天アフィリエイト規約: https://affiliate.rakuten.co.jp/guide/policy/
- Amazonアソシエイト規約: https://affiliate.amazon.co.jp/help/operating/agreement
- 違反時はアカウント停止・報酬没収のリスク

---

## 🛡️ Codespaces のセキュリティ

### Codespacesが他者から見られる可能性

- Private リポジトリの Codespace は **あなた専用**
- 他のコラボレーターが追加されない限り誰も見れない
- 組織リポジトリの場合は組織管理者の設定に依存

### Codespace停止・削除

- 30分操作なしで自動停止
- 使い終わったら明示的に停止推奨：
  - https://github.com/codespaces で該当Codespace → Stop

### 完全削除

- 長期間使わない場合は削除：
  - https://github.com/codespaces → 該当Codespace → Delete
- リポジトリは残るので、次回はCreate codespaceで新規作成

---

## 🔍 監査ログの確認方法

### GitHub
- Settings → Security log

### Codespaces
- https://github.com/settings/codespaces で起動履歴確認

### API
- 各サービスの管理画面でAPI呼び出しログを確認（対応している場合）
