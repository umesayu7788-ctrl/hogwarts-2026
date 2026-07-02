# 🛡️ GAS ヘルスチェック（追加設定）

**目的**: GitHub Actions の cron が遅延/スキップされた時に、**自動で検知して手動起動**する仕組み。

## セットアップ手順（5分）

### Step 1: 既存の GAS プロジェクトに関数を追加

既に作成済みの `affiliate-threads-scheduler` を開き、以下のコードを**末尾に追加**：

```javascript
/**
 * 朝のヘルスチェック（改善版 2026-04-24）
 * 本日のIssue（daily-operation ラベル）の存在で判定。
 * SKIPされたワークフロー実行は「実行あり」と誤判定しないよう修正。
 */
function morningHealthCheck() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) {
    Logger.log('❌ GITHUB_TOKEN 未設定');
    return;
  }

  const today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd');
  Logger.log(`🔍 ヘルスチェック開始: ${today}`);

  // 本日のIssueが存在するかで実体判定（SKIP実行は「稼働済み」と誤認しない）
  const issuesUrl = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/issues?labels=daily-operation&state=all&per_page=10`;
  const issuesResp = UrlFetchApp.fetch(issuesUrl, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/vnd.github.v3+json'
    },
    muteHttpExceptions: true
  });

  if (issuesResp.getResponseCode() !== 200) {
    Logger.log(`❌ Issue API取得失敗: ${issuesResp.getResponseCode()}`);
    return;
  }

  const issues = JSON.parse(issuesResp.getContentText()) || [];
  const todayIssue = issues.find(i => i.title && i.title.indexOf(today) !== -1);

  if (todayIssue) {
    Logger.log(`✅ 本日のIssue #${todayIssue.number} 既に作成済み。スキップ。`);
    return;
  }

  // 未作成 → 強制起動
  Logger.log('⚠️ 本日のIssue未作成。Affiliate Daily Cycleを強制起動します。');
  triggerWorkflow('affiliate-cycle.yml', 'AFFILIATE_HEALTHCHECK');
}

/**
 * 夜のヘルスチェック
 * 22:45 JST までに Revenue Tracker が起動していなければ強制起動
 */
function eveningHealthCheck() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) return;

  const today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd');

  const runsUrl = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/revenue-tracker-daily.yml/runs?per_page=10`;
  const runsResp = UrlFetchApp.fetch(runsUrl, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/vnd.github.v3+json'
    },
    muteHttpExceptions: true
  });

  if (runsResp.getResponseCode() !== 200) return;

  const runs = JSON.parse(runsResp.getContentText()).workflow_runs || [];
  const todayRuns = runs.filter(r => {
    const createdJst = Utilities.formatDate(new Date(r.created_at), 'Asia/Tokyo', 'yyyy-MM-dd');
    return createdJst === today;
  });

  if (todayRuns.length === 0) {
    Logger.log('⚠️ Revenue Tracker 未起動。強制起動します。');
    triggerWorkflow('revenue-tracker-daily.yml', 'REVENUE_HEALTHCHECK');
  }

  // Auto-Measureも同様にチェック
  const autoUrl = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/auto-measure.yml/runs?per_page=10`;
  const autoResp = UrlFetchApp.fetch(autoUrl, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/vnd.github.v3+json'
    },
    muteHttpExceptions: true
  });
  if (autoResp.getResponseCode() === 200) {
    const autoRuns = JSON.parse(autoResp.getContentText()).workflow_runs || [];
    const todayAuto = autoRuns.filter(r => {
      const createdJst = Utilities.formatDate(new Date(r.created_at), 'Asia/Tokyo', 'yyyy-MM-dd');
      return createdJst === today;
    });
    if (todayAuto.length === 0) {
      Logger.log('⚠️ Auto-Measure 未起動。強制起動します。');
      triggerWorkflow('auto-measure.yml', 'AUTOMEASURE_HEALTHCHECK');
    }
  }
}
```

---

### Step 2: 時刻トリガーを2つ追加

GAS の ⏰ トリガー画面で「**トリガーを追加**」：

#### 朝のヘルスチェック
| 項目 | 値 |
|---|---|
| 実行する関数 | `morningHealthCheck` |
| イベントのソース | 時間主導型 |
| タイプ | 日付ベースのタイマー |
| 時刻 | **午前8時〜9時** |

→ 08:00 JST過ぎにチェック。Affiliate Cycle未起動なら即起動。

#### 夜のヘルスチェック
| 項目 | 値 |
|---|---|
| 実行する関数 | `eveningHealthCheck` |
| イベントのソース | 時間主導型 |
| タイプ | 日付ベースのタイマー |
| 時刻 | **午後11時〜深夜0時** |

→ 23:00 JST過ぎにチェック。Revenue Tracker / Auto-Measure未起動なら即起動。

---

### Step 3: 動作テスト

GAS エディタで関数を選択して「実行」：

```
morningHealthCheck
→ ログに「✅ 本日既にX件の実行あり」or「⚠️ 強制起動しました」が出ればOK
```

---

## 🛡️ これでどうなるか

### Before（今日4/23のケース）
```
05:37 JST cron → 遅延・スキップ（GitHub Actions無料枠）
→ 1日分の運用が止まる
→ 手動対応が必要
```

### After（明日以降）
```
05:37 JST cron → 遅延してもOK
06:26 JST cron → 2回目チャンス
07:51 JST cron → 3回目チャンス（YAMLに追加済み）
08:00 JST GAS → 全部失敗していたら自動起動（←NEW）
```

**4段階の冗長性**で、日中の運用止まりは実質ゼロに。

---

## 📊 対応マトリクス

| ワークフロー | cron段数 | GAS段数 | 合計 |
|---|---|---|---|
| Daily Threads Cycle | 3 | 1 | **4段** |
| **Affiliate Daily Cycle** | 3 | 1 | **4段** |
| Scheduled Post SLOT_2 | 2 | 1 | 3段 |
| Scheduled Post SLOT_3 | 2 | 1 | 3段 |
| Revenue Tracker | 3 | 1 | **4段** |
| Auto-Measure | 3 | 1 | **4段** |
| Weekly Monitor | 3 | - | 3段 |
| Refresh Token | 3 | - | 3段 |

→ クリティカルパス（Affiliate・収益・計測）は**4段の防御**。

---

## 🚨 緊急時の対応

それでも失敗した場合の診断：

1. GitHub Actions の UI で失敗ログ確認
2. GAS の実行ログ（表示 → ログ）を確認
3. Discord通知で異常ログを確認
4. 最悪、手動トリガー可能
