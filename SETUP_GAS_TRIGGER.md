# ⏰ 時刻トリガー設定ガイド（Google Apps Script）

GitHub Actionsのcronは数時間遅延することがあります。  
このガイドの設定を行うと、**18時・21時の投稿が時間通りに行われます**。

- 所要時間：約10分
- 費用：無料
- 必要なもの：Googleアカウント（新規登録不要）

---

## Step 1：GitHub トークンを作成する

> ⚠️ すでに持っている `GITHUB_TOKEN` とは**別のトークン**が必要です（workflow権限が追加で必要なため）。

1. https://github.com/settings/tokens を開く
2. 「Generate new token (classic)」をクリック
3. 以下の通り設定する：
   - **Note**：`gas-scheduler`（任意の名前でOK）
   - **Expiration**：`No expiration`
   - **Scopes**：`repo` と `workflow` の両方にチェック
4. 「Generate token」をクリック
5. 表示された `ghp_xxxxx...` をコピーして**必ず保存する**

> ⚠️ この画面を閉じると二度と確認できません

---

## Step 2：Google Apps Script プロジェクトを作成する

1. https://script.google.com を開く（Googleアカウントでログイン）
2. 「新しいプロジェクト」をクリック
3. プロジェクト名を `threads-slot-scheduler` に変更
4. エディタ内の既存コードをすべて削除し、以下をコピー＆ペーストする
5. `{GitHubユーザー名}` と `{リポジトリ名}` を自分のものに書き換える
6. `Ctrl + S` で保存

```javascript
const GITHUB_OWNER = '{GitHubユーザー名}';
const GITHUB_REPO  = '{リポジトリ名}';
const BRANCH_REF   = 'main';  // デフォルトブランチが master の場合は 'master' に変更

function triggerSlot2() {
  triggerWorkflow('scheduled-post-slot2.yml', 'SLOT_2');
}

function triggerSlot3() {
  triggerWorkflow('scheduled-post-slot3.yml', 'SLOT_3');
}

function triggerWorkflow(workflowFile, slotName) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) {
    throw new Error('GITHUB_TOKENがScript Propertiesに設定されていません');
  }
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${workflowFile}/dispatches`;
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/vnd.github.v3+json'
    },
    payload: JSON.stringify({ ref: BRANCH_REF }),
    muteHttpExceptions: true
  };
  const response = UrlFetchApp.fetch(url, options);
  const code = response.getResponseCode();
  if (code === 204) {
    Logger.log(`✅ ${slotName} トリガー成功`);
  } else {
    Logger.log(`❌ ${slotName} トリガー失敗: ${code} ${response.getContentText()}`);
    throw new Error(`${slotName} failed: ${code}`);
  }
}

function testTrigger() {
  triggerSlot2();
}
```

---

## Step 3：GitHub トークンを保存する

1. 左メニューの「⚙ プロジェクトの設定」をクリック
2. ページ下部「スクリプト プロパティ」までスクロール
3. 「スクリプト プロパティを追加」をクリック
4. 以下を入力する：
   - **プロパティ**：`GITHUB_TOKEN`
   - **値**：`ghp_xxxxx...`（Step 1のトークン）
5. 「スクリプト プロパティを保存」をクリック

---

## Step 4：動作テストをする

1. 左メニューの「&lt;&gt;」（エディタ）に戻る
2. 上部ドロップダウンから `testTrigger` を選択して「実行」をクリック
3. **初回のみ**認証画面が表示される：
   - 「権限を確認」→ Googleアカウント選択 → 「詳細」→「プロジェクト（安全ではありません）に移動」→「許可」
4. 実行ログに `✅ SLOT_2 トリガー成功` と表示されればOK
5. GitHubの「Actions」タブで `Scheduled Post SLOT_2` が動いていることを確認

---

## Step 5：時刻トリガーを設定する

1. 左メニューの「⏰」（トリガー）をクリック
2. 右下の「トリガーを追加」をクリック
3. **18時投稿（SLOT_2）**：

   | 項目 | 設定値 |
   |---|---|
   | 実行する関数 | `triggerSlot2` |
   | 実行するデプロイ | `Head` |
   | イベントのソース | 時間主導型 |
   | タイプ | 日付ベースのタイマー |
   | 時刻 | 午後5時〜6時 |

4. 「保存」をクリック
5. **21時投稿（SLOT_3）**も同様に追加：

   | 項目 | 設定値 |
   |---|---|
   | 実行する関数 | `triggerSlot3` |
   | 時刻 | 午後8時〜9時 |

---

## うまくいかない場合

| エラー | 確認すること |
|---|---|
| 401エラー | Step 3のトークン値が正しいか・`workflow` スコープがあるか |
| 404エラー | `GITHUB_OWNER` / `GITHUB_REPO` の値・ワークフローファイル名 |
| ワークフローが動かない | `BRANCH_REF` が `'main'` か `'master'` か確認 |
| トークンが漏れた | https://github.com/settings/tokens で即削除 → 新規作成 → Step 3 を更新 |

---

## 補足

- GASのトリガーは±15分以内に発火します（GitHub Actionsの数時間遅延より大幅に安定）
- GitHub Actionsのcronはそのまま残してください（バックアップとして機能）
- 両方が発火しても、システム内の重複チェックにより**二重投稿は自動防止**されます
