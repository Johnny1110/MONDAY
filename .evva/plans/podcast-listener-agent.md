# Plan: podcast-listener agent

## 問題診斷

目前 podcast（股癌）分析由 a-catalyst 和 strategy-researcher **各自獨立重複做**，產出只停在 swarm 對話層，沒有結構化接入 workflow。分析師覆蓋在引擎中沒有接口（`contributing_analysts` 永遠為 `[]`），無法被校準或歸因。User 認為 podcast 分析很準，但當前架構無法讓它有效影響選股權重。

## 目標

1. 建立單一 **podcast-listener** agent，每天抓取並分析股癌 podcast
2. 將分析結果結構化發送給 morgan + 三位分析師（a-tech, a-chips, a-catalyst）
3. 從 a-catalyst 和 strategy-researcher 的職責中移除 podcast 抓取任務
4. 調整 morgan 的流程，讓 podcast 分析在選股決策中權重更高

## 實作步驟

### Step 1: 創建 podcast-listener agent 目錄與配置

新 agent 定位：**每日 podcast 情報中樞** — 在 pipeline 前先跑，產出方向判斷與標的權重建議，分發給指揮官與分析師。

- `agents/sub/podcast-listener/system_prompt.md` — persona + 職責
- `agents/sub/podcast-listener/profile.yml` — model/effort
- `agents/sub/podcast-listener/tools/active.yml` — 工具清單

### Step 2: 註冊到 evva-swarm.yml

- 新增 `podcast-listener` worker，schedule 設為 `0 17 * * 1-5`（盤前下午 5 點，podcast 已出，比 21:15 pipeline 早 4 小時）
- morgan 的 nightly cron prompt 加入「先讀 podcast-listener 的方向判斷與標的關注清單」
- a-catalyst 的 when_to_use 移除 podcast 職責
- strategy-researcher 的 when_to_use 移除 podcast 職責

### Step 3: 更新現有 agent 的 system_prompt

- **a-catalyst**: 移除「找 podcast 逐字稿」的職責，改為「讀 podcast-listener 的主題/地雷摘要作為覆蓋素材」
- **strategy-researcher**: 移除「找 podcast 逐字稿」的職責，改為「讀 podcast-listener 的結構性主題摘要作為前瞻素材」

### Step 4: 驗證

- 檢查 YAML 語法
- 確認不與現有 agent 衝突
- 確認 schedule 時間合理（在 pipeline 之前，不與其他 cron 重疊）
