# Monday — 台股預測實驗室 白皮書 (v0.1 draft)

> **這是什麼**：一份把「用 evva swarm 打造台股每日選股 + 自我回歸校準實驗室」的構想，grill 成
> 可落地 spec 的白皮書。它是 [Sunday](../../README.md) 的**姊妹專案**——沿用 Sunday 已驗證的
> 工程 DNA（無狀態平台持金鑰、agent 只走 HTTP、webhook 喚醒、cron 安全網、決策權集中），
> 但資產類別換成**台股**、產出換成**每日 20 檔月線價差標的建議 + 紙上投組 + 校準帳本**。
>
> **狀態**：v0.1，已鎖定 4 個架構岔路（見 §0.1），仍有若干待定決策（見 §11）。
> **命名**：專案暫名 **Monday**（台股週一開盤之意，對應 Sunday）；平台引擎暫名 **Monday engine**；
> swarm leader 暫名 **morgan**（CIO/PM）。全部是 placeholder，最後由 User 定。

---

## 0. 摘要（一頁讀懂）

**目標**：一支長壽（≥1 年）的 evva swarm，每個交易日盤後跑一次完整分析流程，於隔日盤前向 User
推薦**最多 20 檔、持有窗口 ≤1 個月的價差交易標的**，每檔附「方向 / 進場參考價 / 期望停利價 /
建議停損 / 信心度 / 理由（動能・籌碼・題材催化）/ 風險點」。所有建議寫進一個**紙上投組**並
**逐日對帳真實價格**，累積命中率 / 報酬 / 預測誤差，**持續做回歸校準與策略優化**——而且**不是
固定回圈**：內建分層復盤 SOP 與觸發式調整機制，能動態調整因子權重、agent 工作方向、甚至組織編制。

**預測引擎 = 量化為主、LLM 為輔的混合制**（§0.1 鎖定）：

```
真實資料 ──► 特徵庫 ──► 量化 ML 模型（排名+機率+期望報酬）──► LLM 質化覆蓋層（題材/籌碼/地雷/敘事）
                                                                      │
                                                          CIO 整合 + 組合風控 ──► 20 檔建議 + 紙上投組
                                                                      │
                                            逐日對帳 ──► 校準帳本 ──► 分層復盤 ──► 動態調整（回到上游）
```

**成功衡量（雙軌，誠實版）**：
1. **能力 oracle（主）**：一支只靠通用 HTTP 工具 + 平台手冊的 swarm，能不能把「爬蟲→清洗→ML
   →質化→選股→對帳→回歸校準→自我調整」這條長鏈**自主跑滿一年並持續改善自己**。這延續 Sunday 的
   multi-agent completeness 命題。
2. **預測品質（副）**：紙上投組相對大盤（加權報酬指數 TAIEX TR）的超額報酬、命中率、期望停利達成率、
   模型 IC（information coefficient）是否隨校準上升而非衰減。

**為什麼這個設計可信**：它把「不可信的 LLM 直接報明牌」換成「**可校準的統計模型**做排名、LLM 只做
人類擅長的質化覆蓋與敘事」——模型每一筆預測都有版本、特徵快照、機率，才能逐日回歸、算 calibration
curve、做因子歸因。沒有帳本就沒有校準；沒有可校準的模型就沒有優化。

### 0.1 已鎖定的四個架構決策（2026-06-13 與 User 敲定）

| # | 岔路 | 決策 | 後果 |
| --- | --- | --- | --- |
| 1 | 「ML/DL」誰是模型 | **量化為主、LLM 輔助**：agent 訓練真實 ML 模型輸出排名/機率，LLM 只做質化覆蓋與選股理由 | 需要 ML 工程 + MLOps 編制與訓練基礎設施；LLM **不直接預測股價** |
| 2 | 產出邊界 | **建議 + 紙上投組 + 逐日對帳校準帳本** | 平台需內建 portfolio/ledger 子系統；校準是核心，非附屬 |
| 3 | 資料層 | **免費核心源**（TWSE/TPEx OpenAPI・FinMind・Yahoo TW）**+ 另類/情緒源**（新聞・法說・PTT/Dcard・Google Trends）**+ CMoney 免費版**（1 年歷史、日價量、三大法人明細） | **日線級**、無盤中即時、無付費 point-in-time → look-ahead 風險須自建快照緩解（§4.2） |
| 4 | 選股風格 | **動能 + 題材催化（主軸）+ 多因子混合（模型自選 regime 權重）** | 因子集偏動能/籌碼/事件；regime-aware ensemble 是模型設計核心（§5.3） |

---

## 1. 設計原則與不變量（沿用 Sunday DNA）

Monday 直接繼承 Sunday 的 8 條不變量精神，改寫成台股 lab 語境。**動工前先確認沒違反：**

1. **資料 = 唯讀外部源（持帳號/金鑰在平台）；產出 = 平台內部狀態。** agent 永遠只用通用 HTTP 工具
   打 Monday engine，**看不到任何資料源 API key / CMoney 帳密**（延續 Sunday 不變量 2）。
2. **所有 Monday engine API 免 token。** 平台持金鑰，agent 只持 HTTP。
3. **回大量資料的 list 一律分頁**（沿用 Sunday `pagination.paginate` 的 `{items,page,page_size,total,has_more}` 信封）。
4. **API prefix 依模組劃分**：`/api/universe` `/api/prices` `/api/factors` `/api/features` `/api/models`
   `/api/signals` `/api/recommendations` `/api/portfolio` `/api/ledger` `/api/calibration` `/api/news`
   `/api/sentiment` `/api/memory` `/api/journal` `/api/reports` `/api/system` `/api/admin`，各自一個 router 模組。
5. **無 Postgres/Redis。** 持久狀態 = sqlite（recommendations / paper_portfolio / ledger / calibration /
   model_registry / memory / journal / reports / kv）+ 特徵/行情大表用 **parquet 檔**（唯讀分析友善）。
   sqlite wrapper 沿用 **RLock 寫鎖 + WAL/busy_timeout**（Sunday `store.py` 模式，多執行緒寫不死鎖）。
6. **純邏輯 stdlib-only、可單元測試**：因子計算 / 指標 / 分頁 / 校準數學（IC、calibration curve、命中率、
   歸因）/ 訊號規則 / 紙上投組對帳。**重依賴（pandas/numpy/lightgbm/ccxt/fastapi）惰性 import**，
   不在模組頂層。
7. **校準觸發用 webhook + cron 安全網**：平台偵測到「值得 agent 注意的時刻」（投組回撤破線、校準漂移、
   pipeline 失敗、因子 IC 翻負）→ webhook 喚醒對應 agent；cron 是 webhook 失靈的保底，**不是輪詢**。
8. **對外通道**：(a) **swarm webhook**（agent-facing：Monday engine → evva swarm 事件）；
   (b) **User 通道**（Telegram + dashboard：每日 20 檔建議、復盤日誌、重大快訊推 User 手機）。
   兩者 fire-and-forget、永不 raise；金鑰只在引擎側。

> **與 Sunday 的關鍵差異**：Sunday 的 swarm 是去**操作一個既有交易所代理**；Monday 的 swarm 要去
> **操作一個資料/建模/校準平台**，而這個平台本身得先蓋出來。所以 Monday 比 Sunday 多一個明確的
> 「平台層 vs swarm 層」分工（§3），以及一個常駐工程師 agent 來建/養平台（§7 的 `lab-engineer`）。

---

## 2. 不變量的延伸：為什麼「平台 / swarm」要分層

把資料源金鑰、特徵計算、模型訓練、回測、紙上投組帳本，全部塞進 agent 的 prompt/工具裡是**反模式**：
不可重現、不可單元測試、燒 token、且金鑰外洩給 LLM。Sunday 的成功正是因為它把「**確定性、可測試、
持金鑰的重活**」收進 Python 平台，讓 agent 只做**判斷與敘事**。Monday 照搬：

| 屬於**平台**（Monday engine，Python，確定性、可測試、持金鑰） | 屬於**swarm**（evva agents，判斷、敘事、調度） |
| --- | --- |
| 爬蟲拉取 + rate-limit + 重試 + 快取（TWSE/FinMind/CMoney/Yahoo/Google Trends） | 決定**今天要不要相信**模型的某個排名 |
| 資料清洗、還原權值、point-in-time 對齊、品質閘 | 讀最新法說/新聞，判斷題材是**新鮮**還是**利多出盡** |
| 特徵庫計算（動能/籌碼/基本面/事件/情緒/regime 因子） | 抓出模型看不到的**地雷**（增資/訴訟/財報難產/借殼） |
| ML 模型訓練、walk-forward 驗證、版本化、每日推論 | 把 20 檔建議寫成**人能讀的理由**與風險點 |
| 紙上投組對帳、校準指標計算（IC/命中率/calibration/歸因） | 復盤時**決定**要重訓、換因子、改 agent 方向、還是動組織 |
| webhook 觸發、Telegram 推播、dashboard | 與 User 對話、回應臨時指令 |

**判準**：凡是「同樣輸入必須得到同樣輸出、且要寫單元測試」的——進平台。凡是「需要判斷、權衡、敘事、
對外溝通」的——進 swarm。模型**訓練腳本**由 `quant`/`quant-researcher` agent 撰寫並用平台的
`repl`/`bash` 跑，但**訓練流程與產物（model registry）落在平台**，不是落在 agent 的對話裡。

---

## 3. 系統架構

```
   ┌─────────────────── 決策平面：evva swarm（:8888, Go, .vero）─────────────────────┐
   │                                                                                  │
   │   User ──(evva web / Telegram)──►  morgan（leader = CIO / PM / 唯一定案者）        │
   │                            │  ① 每日整合：量化排名 + 分析覆蓋 + 組合風控 → 定案 20 檔 │
   │                            │  ② 主持分層復盤、據校準結果動態調整（schedule_set/提案）  │
   │          ┌─────────┬───────┼────────┬─────────┬──────────┬─────────┬──────────┐   │
   │          ▼         ▼       ▼        ▼         ▼          ▼         ▼          ▼   │
   │  data-engineer  quant  quant-rsrch a-tech  a-chips  a-catalyst risk-mon  reviewer │
   │   (爬蟲/清洗/   (每日   (新因子/    (技術/  (籌碼/   (題材/新聞/ (組合風控/(復盤校準/ │
   │    特徵庫)      推論)   重訓/regime) 動能)   法人)    情緒/地雷)  流動性)  回歸引擎) │
   │          │   strategy-researcher(策略前瞻)   watchdog(pipeline健康)  lab-engineer(建平台)│
   │          └───────────────────── send_message / task ──────────────► morgan        │
   └──────────┼───────────────────────────────────────────────────────────────────────┘
          ▲ webhook（校準漂移/回撤/pipeline失敗）   │ http_request（全部免 token）+ 未來可加 typed MCP
          │                                            ▼
   ┌──────┴───────────────────── 平台平面：Monday engine（:7790, Python, FastAPI）──────┐
   │  routers/*（universe prices factors features models signals recommendations         │
   │            portfolio ledger calibration news sentiment memory journal reports system）│
   │  ingest（爬蟲 + rate-limit + 快取）→ clean（還原權值/PIT 對齊/品質閘）              │
   │  featurestore（parquet）→ model_registry（版本化）→ daily inference                  │
   │  paper-portfolio + ledger（逐日對帳）→ calibration（IC/命中率/歸因）                 │
   │  triggers（回撤/漂移/失敗）─► events.post ─► swarm webhook；reports ─► telegram      │
   │  sqlite（唯一交易型持久狀態：recs/portfolio/ledger/calibration/registry/memory/kv）  │
   └───────────────────────────────────┬──────────────────────────────────────────────┘
                   資料 adapters         │（帳號/金鑰只在這層）
        TWSE/TPEx OpenAPI · FinMind · CMoney(free) · Yahoo TW · 新聞/法說 · Google Trends · PTT/Dcard
```

**HTTP 邊界**（其餘不准跨）：
1. **swarm → Monday engine**：agent 走通用 `http_request` 打 `:7790/api/*`（完整合約 `GET /manual`）。
   全部免 token。（成熟後可比照 Sunday milestone-9 加一層 typed MCP sidecar，但**非 MVP**。）
2. **Monday engine → swarm**：webhook `POST :8888/api/swarm/monday/event`，payload `{title,body,data,to}`，
   事件 `calibration_drift` / `portfolio_drawdown` / `pipeline_failed` / `factor_decay`，自帶 `suggested_action`。
3. **Monday engine → User**：Telegram 推播（每日建議 / 復盤摘要 / 重大快訊）+ 自服 `/dashboard`。

**信任模型邊界**（誠實版，同 Sunday）：「只有 morgan 定案」是 **prompt 紀律**，不是技術強制——API 免 token，
任何 worker 技術上都打得到。各 agent system prompt 明文劃界，且**這是紙上投組、不碰真錢**，是能接受
該邊界的原因（延續 Sunday testnet 假錢的邏輯）。

---

## 4. 資料層

### 4.1 來源盤點（User 已選）

| 層 | 來源 | 取得內容 | 頻率/限制 |
| --- | --- | --- | --- |
| **核心價量** | TWSE/TPEx OpenAPI、Yahoo TW、FinMind | 上市櫃日 K（開高低收量）、還原權值、指數、成分股 | 盤後 EOD；免費有 rate limit |
| **籌碼** | CMoney 免費版、FinMind、TWSE T86 | 三大法人買賣超明細（外資/投信/自營分開）、融資融券餘額、借券、主力 | 法人 ~15:00、融資券 ~21:00（盤後） |
| **基本面** | FinMind、公開資訊觀測站、CMoney | 月營收、季財報（EPS/毛利/營收）、本益比/股價淨值比、除權息、股本 | 月營收每月 10 日前；季報有公告時點 |
| **事件/題材** | 公開資訊觀測站重訊、法說會行事曆、新聞 | 法說/財報/除權息日程、重大訊息、產業政策 | 日內滾動 |
| **另類/情緒** | 新聞 RSS、Google Trends、PTT Stock/Dcard 股票板 | 新聞情緒、搜尋熱度、散戶討論量與情緒 | 日內滾動 |

**universe（標的池）**：上市 + 上櫃約 ~1,800 檔，但**硬過濾**到可交易子集：剔除全額交割股、處置股、
注意股（題材熱但無法穩定進出）、日均成交額低於門檻（流動性陷阱——User 月線價差出得掉才有意義）、
即將下市/變更交易、興櫃。預估**可分析池 ~800–1,000 檔**。過濾規則是**硬閘**（風險旗標），不是 alpha 因子。

### 4.2 ⚠️ 頭號風險：look-ahead bias（未來函數）與緩解

User 選了免費源、**沒有付費 point-in-time（PIT）資料庫（如 TEJ）**。這是本實驗**最大的科學性威脅**：
免費源給的是「現在這一刻的最新值」，歷史回測時很容易不小心用到「當時還沒公布的財報/法人/還原權值」，
讓回測虛胖、上線即破功。緩解策略（**必做**）：

1. **自建 PIT 快照（治本）**：從 Day 1 起，平台**每日盤後把當天能看到的全部原始資料原樣存檔**
   （append-only parquet，戳 `as_of` 日期）。**上線後累積的每一天都是天然 PIT 正確的**——這是 Monday
   最重要的資產，越早開機越值錢。校準與「上線後 walk-forward」一律只用快照重建的 PIT 視圖。
2. **歷史回測誠實降級**：用 CMoney 免費 1 年歷史 + FinMind 做**初版模型冷啟動**時，明確標註其
   look-ahead 限制（財報用公告日對齊、月營收延到 10 日後生效、還原權值只回溯不前視），**並把冷啟動
   回測的結論視為「假設」而非「已驗證」**——真正的驗證來自上線後的 PIT 紙上投組。
3. **purged + embargo 時序驗證**（§5.4）：1 個月持有窗口會讓相鄰樣本的標籤期重疊，必須 purge/embargo
   防洩漏。
4. **資料品質閘**：缺值、停牌、跳空、還原權值斷點、來源不一致（CMoney vs FinMind 對不上）→ 標記並
   隔離，不靜默餵進模型。watchdog 監測爬取成功率與來源延遲。

> **一句話**：免費源讓我們**能立刻開工**，代價是歷史回測不可全信；解法是**每日存快照、用上線後的真
> PIT 資料做為校準與優化的權威依據**。這也正好呼應 §0 的成功衡量——重點是「上線後一年的自我改善」，
> 不是「冷啟動回測多漂亮」。

### 4.3 特徵庫（feature store）

平台每日盤後計算並落 parquet（每檔每日一列），分群（純函式、stdlib/numpy 可測）：

- **動能/技術**：1/3/6/12 月報酬、距 52 週高低、均線排列（5/20/60/120）、RSI、MACD、ADX、ATR、乖離率、
  量能（爆量、量價背離）、相對強度（vs 加權 / vs 同產業）。
- **籌碼**：三大法人連續買賣超天數/金額/占股本比（外資・投信・自營分開）、投信作帳季節性、融資增減與
  維持率、融券/借券、主力買賣超、大戶持股比（週）、董監持股。
- **基本面（當特徵）**：月營收 YoY/MoM/累計與連續成長月數、EPS、毛利率趨勢、本益比/股價淨值比的
  歷史與同業 percentile、殖利率。
- **事件/題材**：距下次法說/財報/除權息天數、近期重訊旗標、產業題材熱度（新聞計數 + Google Trends）、
  ETF 成分異動。
- **情緒/另類**：新聞情緒分數、PTT/Dcard 提及量與情緒、討論熱度變化率。
- **市場/regime（全市場共用）**：加權指數趨勢與位階、漲跌家數 breadth、成交量、外資期貨未平倉、
  美股隔夜（費半 SOX / Nasdaq）、USD/TWD、VIX。

**風險旗標**（硬過濾，不進 alpha）：處置/注意/全額交割、流動性門檻、即將下市、財報難產。

---

## 5. 預測引擎（量化主幹 + LLM 覆蓋）

### 5.1 問題框定：**橫斷面排名**，不是「猜某檔會漲多少」

每個交易日，對可分析池 ~800–1,000 檔做**橫斷面排名**：預測未來 ~20 個交易日（≈1 月）的相對表現，
取頂部候選交給 LLM 覆蓋。這是 equity factor model 的標準框架，比「逐檔回歸絕對報酬」穩健得多。

### 5.2 模型選型（誠實版）

- **主力 = 梯度提升樹（LightGBM / XGBoost）**，三個並行頭：
  1. **Ranker（LambdaMART）**：輸出橫斷面排名分數（選股主依據）。
  2. **Regressor**：預測 1 月期望報酬（用來推導**期望停利價**）。
  3. **Classifier（校準機率）**：P(未來 1 月觸及 +X% 停利目標)（用來給**信心度**並做 calibration curve）。
  - 為何 GBDT 為主：表格型橫斷面因子上，GBDT 幾乎總是打敗 DL；快、穩、可用 SHAP 做**因子歸因**
    （直接餵校準與復盤）。
- **DL 為輔、且要自己掙到位子（Phase 2+）**：序列模型（LSTM/GRU/**Temporal Fusion Transformer**）吃
  價量序列；但每年僅 ~250 個交易日、樣本稀薄，DL **極易過擬合**。紀律：**DL 只有在 walk-forward 的
  out-of-sample IC 穩定贏過 GBDT 才納入 ensemble**，否則不上。（這條本身就是「不固定回圈、用證據決定」
  的體現。）
- **情緒/文本**：新聞與法說的情緒分數可由輕量模型或 LLM 批次打分後**當成特徵**進 GBDT（不是讓 LLM 直接選股）。

### 5.3 regime-aware ensemble（實現「多因子混合、模型自選權重」）

User 要的「不預設主軸、模型用歷史回測自學各因子在不同盤勢下的權重」具體化為：

1. **regime 分類器**：用市場層特徵（指數趨勢/breadth/VIX/外資期貨/美股隔夜）把每天打成
   regime 標籤（如：多頭趨勢 / 盤整 / 系統性下殺 / 高波動）——用 HMM 或簡單規則 + 分類器。
2. **per-style 子模型**：分別訓練「動能模型」「籌碼模型」「題材/事件模型」「價值模型」。
3. **regime 條件加權**：ensemble 權重**依當前 regime** 由驗證集學出（多頭給動能/籌碼高權、下殺給
   防禦/低 beta 高權）。權重不是寫死的，是**校準迴圈會持續調整的對象**（§6）。

> User 已選「動能 + 題材催化」為**主軸**：冷啟動時動能/籌碼/事件子模型給較高基礎權重；但最終權重交給
> regime ensemble 與校準迴圈決定，避免人為過度自信。

### 5.4 訓練與驗證紀律（防自欺的命脈）

- **walk-forward / purged time-series CV + embargo**：因 1 月持有窗口造成標籤重疊，相鄰 fold 之間
  **purge** 掉重疊期、加 **embargo** 間隔，否則 IC 虛高、上線崩。
- **主要模型指標 = IC（rank IC）**：預測排名與實際報酬的等級相關；附 calibration curve（70% 信心的
  那批是否真的 ~70% 命中）、turnover / 因子衰減、分 regime 的分層 IC。
- **冷啟動 → PIT 接管**：冷啟動用歷史資料拿初版模型；上線後**每月用累積的 PIT 快照重訓並做真 OOS 驗證**
  （§4.2、§6）。

### 5.5 期望停利價 / 停損 / 信心度 的推導（讓建議可校準）

- **期望停利價** `TP = entry × (1 + max(model_E[ret], k · ATR_1m))`，再依信心度微調；`k` 起始給保守值，
  **由校準迴圈用實際停利達成率回歸調整**（達成率太低就調低乘數）。
- **建議停損** `SL = entry × (1 − j · ATR)` 或固定風險預算（如單檔 −8%）；`j` 同樣可校準。
- **信心度** = classifier 校準後機率 × LLM 覆蓋調整（題材新鮮度/地雷扣分）。
- **持有窗口** ≤20 交易日；到期未觸 TP/SL 即「到期平倉」記帳。

### 5.6 LLM 質化覆蓋層（量化之後、定案之前）

模型排出**頂部 ~40–60 檔候選**後，三位分析師 agent 做人類擅長、模型做不到的事：

- **a-tech（技術/動能）**：驗證候選的技術結構（突破有效性、量價、關鍵支撐壓力、相對強度），標出
  進場區間與技術停損位。
- **a-chips（籌碼/法人）**：三大法人連續性與品質（是真進駐還是當沖對敲）、融資券結構、主力動向、
  投信季底作帳。台股散戶市場**籌碼是 alpha 大宗**，單獨設位。
- **a-catalyst（題材/新聞/情緒/地雷）**：讀最新法說語氣、新聞、產業題材——判斷題材**新鮮 vs 利多出盡**，
  並**抓地雷**（增資、訴訟、財報難產、借殼、董監質押爆倉風險、即將解禁）。可對個股**否決/降權**並附理由。

**分工本質**：模型負責**廣度與客觀排名**，LLM 負責**深度、時效、敘事與否決權**。LLM **不發明**沒進
候選的標的（避免 LLM 報明牌的不可校準性），只在模型候選內做覆蓋——但若 a-catalyst 發現模型完全漏掉的
重大催化，可走 `task_propose` 提案讓 morgan 裁決（留痕、可校準）。

### 5.7 定案與組合（morgan）

morgan 整合「量化排名 × LLM 覆蓋分數 × 組合風控約束」選出**最多 20 檔**，並由 **risk-monitor** 過組合閘：
**單一產業 ≤ N 檔、因子曝險不過度集中（不能 20 檔都是 AI 伺服器）、相關性分散、單檔流動性可進出、
總曝險符合風格**。產出**每日建議信封**（§附錄 C 的 JSON 契約），寫進 recommendations + paper-portfolio，
並推 User（Telegram + dashboard）。

---

## 6. ⭐ 回歸優化工作流（本實驗的核心——「不是固定回圈」）

User 最強調的需求：小組不能死循環重複同樣的工作，要有**復盤與調整 SOP**，能**動態調整組織或單一 agent
的工作方向**。這一節是 Monday 與「普通每日選股 bot」的根本差別。

### 6.1 校準帳本（calibration ledger）——一切優化的地基

每筆建議在**出生時**就完整記錄（沒有這些欄位就無法回歸）：

```
rec_id, as_of_date, symbol, name, direction,
entry_ref_price, predicted_return, predicted_prob_tp, conviction,
model_version, feature_snapshot_id, regime_label,
take_profit_price, stop_loss_price, holding_window_days,
contributing_factors[], contributing_analysts[], rationale, risk_notes
```

**逐日對帳**（reviewer-calibrator 每日盤後）追加：

```
rec_id, mark_date, close_price, mtm_return, max_favorable, max_adverse,
tp_hit?, sl_hit?, days_held
```

**到期結算**（觸 TP/SL 或滿 20 日）：

```
rec_id, exit_date, exit_price, realized_return, hit?(>0), tp_hit?, sl_hit?,
exit_reason(tp|sl|timeout), error = realized_return − predicted_return
```

有了它就能算：命中率、期望停利達成率、平均賺賠比、**IC（predicted vs realized）**、**calibration curve**、
**分因子/分 regime/分分析師歸因**、相對大盤超額、最大回撤、turnover。

### 6.2 分層節奏（calendar-driven）——四個迴圈，越外層越慢越結構性

| 迴圈 | 頻率 | 誰主跑 | 做什麼 | 可動到什麼 |
| --- | --- | --- | --- | --- |
| **Ops（日）** | 每交易日盤後 | 全隊 | 爬蟲→清洗→特徵→量化排名→LLM 覆蓋→定案 20→推 User→對帳開倉建議 | 當日選股 |
| **復盤（週）** | **每週五**（盤後對帳後） | reviewer-calibrator → morgan | reviewer 跑回歸 scorecard（命中率/IC/calibration/分因子衰減/分析師採納率）+ 讀全隊本週 journal，產 1–3 條**具體提案**（`task_propose`）；morgan 裁決並**派工**（程式→evva、找料補特徵→data-engineer、策略→憲法），每案一條 ADR | **cheap 調整**：因子權重微調、agent cadence（`schedule_set`）、候選池大小、分析師關注重點 |
| **重校準（月）** | 每月 1 日 | quant-researcher + morgan | 用累積 PIT 快照**重訓模型**、walk-forward 真 OOS 驗證、因子增刪、TP/SL 乘數回歸校正；上月建議全數到期 → 乾淨 OOS scorecard | **模型/策略級**：換模型版本、增/退因子、改 regime 權重、改停利停損公式 |
| **組織盤整（季）** | 每季 | morgan（+ User） | 結構性檢視：整套方法在賺錢嗎？相對大盤有超額嗎？哪個 agent/子模型沒貢獻？ | **組織級**：增聘/凍結 agent、改 universe、改風格權重、重訂目標 |

### 6.3 觸發式調整（event-driven）——不等行事曆，壞了立刻修

平台持續監測，達標即 webhook 喚醒，強制**off-cycle** 復盤（這是「動態」的關鍵，避免一週的傷害累積）：

| 觸發 | 條件（起始值，可校準） | 喚醒 | 動作 |
| --- | --- | --- | --- |
| `portfolio_drawdown` | 紙上投組回撤 > 8% | morgan + risk-monitor | 緊急復盤、降曝險/暫停新建議直到診斷 |
| `calibration_drift` | 預測 vs 實際 IC 連 3 週 < 門檻 | quant-researcher | 強制提前重訓、查資料/regime 是否變了 |
| `factor_decay` | 某因子 IC 連 N 期翻負 | quant-researcher | 該因子降權/退役提案 |
| `regime_shift` | regime 分類器偵測盤勢翻轉 | morgan | 切換 ensemble 權重 / 風格 |
| `hitrate_collapse` | 滾動命中率跌破基線 | morgan | 召集 off-cycle 復盤、歸因 |
| `pipeline_failed` | 爬蟲/特徵/推論失敗 | watchdog → morgan | 修復、必要時當日不發建議（誠實 > 硬發） |

### 6.4 復盤 SOP（reviewer-calibrator + morgan 的決策規則）

每次復盤照這張**決策樹**走，產出**可執行**而非空泛的結論：

1. **歸因賺賠**：贏的單靠什麼因子/分析師/regime？輸的單錯在**模型排錯**還是**LLM 覆蓋判錯**還是
   **執行價/停利公式**？（決策錯 vs 校準錯，分開記——這直接決定下一步動誰。）
2. **校準健檢**：classifier 的機率準不準（calibration curve 偏了就 recalibrate）？TP 達成率對不對得上
   乘數 `k`（不對就調 `k`）？
3. **因子健檢**：哪些因子 IC 還活著、哪些在衰減？衰減的降權/退役；strategy-researcher 有沒有新因子候選。
4. **agent 健檢**：哪個分析師的覆蓋**真的改變了結果**（採納且事後證明對）？哪個只是噪音？據此
   **`schedule_set` 調 cadence、改 prompt 關注重點、或凍結**。
5. **決策規則（決定動到哪一層）**：
   - 只是雜訊波動 → **不動**（過度調整 = 過擬合校準集，明確記「本週不調整」也是合法輸出）。
   - 參數偏移 → **cheap 調整**（權重/乘數/cadence）。
   - 模型結構性失準 → **重訓/換模型**（升到月迴圈）。
   - 整個方法對某 regime 無效 → **組織級**（升到季迴圈，可能增聘專責該 regime 的 agent）。
6. **留痕**：每個調整寫進**決策日誌（ADR）**——這個 repo 已有 `memory/DECISIONS.md` + `init-memory`/
   `continue-develop`/`shutdown-develop` 的 ADR 機制，Monday **直接沿用**：每次策略/組織調整 = 一條 ADR
   （決策、理由、預期效果、何時回看驗證）。校準的可信來自「每個改動都可追溯、可回測是否真的有效」。

### 6.5 動態調整「組織」具體怎麼發生（對應 evva primitives）

- **改 agent 工作方向 / 節奏**：morgan 用 `schedule_set` 在 runtime 改任何 worker 的 cron 與 prompt
  （Sunday friday 的「方向盤」，動前先 `list_members` 看儀表板）。例：發現籌碼面貢獻度上升 → 提高
  a-chips cadence、擴充其關注清單。
- **增聘**：`evva swarm add <space> <name>` 熱加入新 worker（目錄先備好）。例：季復盤發現需要專責
  「ETF 資金流 / 當沖結構」的分析師 → 新增一位。
- **凍結/暫停**：Web 花名册凍結貢獻度低或燒 token 兇的 agent（被凍結者不再被派任務，解凍即回歸）。
- **立案深挖**：worker 可 `task_propose` 提議跨多次喚醒的研究課題（如「驗證投信作帳季節性因子」），
  morgan 裁決後上看板、有驗收與留痕。
- **記憶分三本**（前兩本沿用 Sunday）：**公告板**（morgan 的策略憲法 + researcher 研究日誌，`/api/memory/*`，
  User 在 dashboard 可讀）+ **私人工作記憶**（evva 原生 `agents/*/<name>/memory/`，每 agent 寫自己的教訓與
  校準筆記，喚醒先讀）+ **團隊工作日誌**（`/api/journal`，每位排程成員每班寫一句、`author` 標記自己；
  watchdog 只在異常時寫）——這本是週復盤的反思素材，reviewer 以 `?since=<本週一>` 讀整週。**長線運行靠
  這三本累積，不讓校準心得隨對話視窗消失。**

---

## 7. 成員編制（要招募哪些 agents）

對應 evva 結構：leader 放 `agents/main/`，worker 放 `agents/sub/`，每個含 `system_prompt.md`（只寫人設）
+ `profile.yml`（model/effort/schedule/...）+ 選填 `tools/active.yml`（**只列一般工具，協作工具由角色
自動注入、不可重列**）。

### 7.1 目標編制（1 leader + 11 workers）

| # | 角色（目錄名） | 層 | 喚醒源 | 做什麼 | **不做** | model/effort（建議） |
| --- | --- | --- | --- | --- | --- | --- |
| L | **morgan**（CIO/PM，`main/`） | leader | webhook（觸發式）+ 隊友訊息 + cron 安全網 + User | 每日整合量化+覆蓋+風控定案 20 檔、推 User、主持分層復盤、據校準**動態調整**（schedule_set/提案/增聘凍結）、ADR 留痕 | 不親自爬蟲/訓模型；不在無共識下硬發建議 | 強推理（Opus 4.8 / deepseek-v4-pro），ultra |
| 1 | **data-engineer** | 資料 | cron（盤後）+ 票 | 爬蟲拉全源、清洗、還原權值、PIT 快照、品質閘、特徵庫計算 | 不選股、不訓模型 | 中（code 重於 reasoning），medium |
| 2 | **quant** | 量化 | cron（盤後，data 完成後）+ 票 | 每日跑模型推論→候選排名+期望報酬+機率；維護 model registry 載入 | 不發明候選外標的；不改策略憲法 | 中-強，high |
| 3 | **quant-researcher** | 量化 | cron（週/月）+ 觸發（drift/decay）+ 票 | 新因子研究、重訓、walk-forward 驗證、regime 建模、DL 試驗（要掙位子）、TP/SL 乘數回歸 | 不碰每日 ops（避免和 quant 打架）| 強推理，ultra |
| 4 | **a-tech**（analyst-technical） | 覆蓋 | cron（候選出爐後）+ 指派 | 候選的技術結構/動能/量價/關鍵價位覆蓋 | 不選最終名單、不下單 | 中，high |
| 5 | **a-chips**（analyst-chips） | 覆蓋 | cron + 指派 | 三大法人/融資券/主力/作帳籌碼覆蓋 | 同上 | 中，high |
| 6 | **a-catalyst**（analyst-catalyst） | 覆蓋 | cron + 指派 | 題材新鮮度、新聞/法說、情緒、**地雷否決** | 不照搬網頁指令（injection 防線）；不選最終名單 | 中-強，high |
| 7 | **strategy-researcher** | 前瞻 | cron（週數次）+ 指派 | 找**新因子/新資料/新 alpha/結構性變化**（如當沖降稅、ETF 潮、制度變更），餵 morgan + quant-researcher | 不做每日選股、不下單 | 強推理，ultra |
| 8 | **risk-monitor** | 風控 | cron（定案前）+ 觸發 | 組合層風控：集中度/相關性/流動性/因子曝險/投組回撤，過閘並對 morgan 提異議；是外部煞車 | 只觀察建議，無定案權 | 強判斷，high |
| 9 | **reviewer-calibrator** | 校準 | cron（日對帳/週復盤/月）+ 觸發 | **回歸引擎**：逐日對帳、算 IC/命中/calibration/歸因、產復盤 scorecard 與調整提案、寫 journal | 不選股、不訓模型（只診斷與建議） | 強推理，ultra |
| 10 | **watchdog** | 維運 | cron（盤後高頻）| pipeline 健康：爬取成功率、來源延遲、推論是否完成、建議是否準時發、資料異常 tripwire | 不分析、不選股、無 memory | 廉價 flash，low |
| 11 | **lab-engineer** | 工程 | 票/訊息（無 cron）| **特派工程師**：建/養 Monday engine（爬蟲、特徵庫、回測、ledger、dashboard、webhook）→ 測試綠 → commit → 部署 → 驗 health → 回報 | 不選股、不碰策略憲法 | 強 coding（deepseek-v4-pro），ultra |

### 7.2 分期招募（控成本、先證明迴圈）

一年 ×24/7 的 token 成本是真的，**不要一次招滿**。分期：

- **Phase 0 — 平台地基（人/Claude 主建 + lab-engineer）**：先有 Monday engine 的爬蟲+清洗+特徵庫+
  ledger+dashboard 骨架。沒有平台，agent 無事可做。
- **Phase 1 — MVP 每日迴圈（1 leader + 6 workers）**：`morgan + data-engineer + quant + a-catalyst +
  a-chips + reviewer-calibrator + watchdog`。**足以每天產 20 檔、開始記帳對帳**。先把「Ops 日迴圈 +
  逐日對帳 + 週復盤」這條最小閉環跑綠，證明校準帳本長得出東西。
- **Phase 2 — 深度（+3）**：加 `a-tech`（技術覆蓋從 quant 分離）、`risk-monitor`（組合風控）、
  `quant-researcher`（R&D 從 quant 分離，啟動月重訓與 regime 建模）。
- **Phase 3 — 優化/前瞻（+1 與精修）**：加 `strategy-researcher`（新因子前瞻）、開季組織盤整、視
  校準結果增聘專責 agent（如 ETF 資金流、當沖結構、產業專家）。

> **編制哲學**：Phase 1 刻意把「技術+量化」「風控」先合進既有角色，先證明**閉環**；待校準帳本顯示
> 「哪裡最缺判斷」再分化角色——**讓組織演化由數據驅動**，本身就是 §6 的體現。

---

## 8. 日常時間軸（cron，host TZ = Asia/Taipei）

台股 09:00 開、13:30 收；三大法人 ~15:00、融資券餘額 ~21:00 才齊。故主流程**晚間跑**，隔日盤前推 User。
（evva cron 是 5 欄、系統本地牆鐘、分鐘精度；`1-5` = 週一到週五。）

| 時間 | agent | 動作 |
| --- | --- | --- |
| `30 21 * * 1-5` | data-engineer | 拉齊全源（含融資券）→ 清洗 → PIT 快照 → 特徵庫 |
| `0 22 * * 1-5` | quant | 載入模型 → 推論 → 候選排名（含期望報酬/機率）|
| `15 22 * * 1-5` | a-tech / a-chips / a-catalyst | 對候選平行覆蓋（quant 完成時也可 `send_message` 觸發）|
| `45 22 * * 1-5` | risk-monitor | 組合層過閘（集中度/相關/流動性）|
| `0 23 * * 1-5` | **morgan** | 整合定案 20 檔 → 寫 recommendations + paper-portfolio → 推 User |
| `0 14 * * 1-5` | reviewer-calibrator | 盤後對帳：開倉建議 mark-to-market、更新 ledger、檢查觸發條件 |
| `*/15 18-23 * * 1-5` | watchdog | pipeline 健康巡檢（只在異常時通報 morgan）|
| `0 14 * * 5`（併入當日對帳喚醒） | reviewer-calibrator → morgan | **週復盤**（每週五）scorecard + `task_propose` 提案；morgan 當日清佇列、裁決派工、留 ADR |
| `0 9 * * 6` | quant-researcher | 週末重訓/驗證/因子健檢 |
| `0 10 1 * *` | quant-researcher + morgan | **月重校準**（PIT 重訓 + 乾淨 OOS scorecard）|
| `0 11 * * 1,3,5` | strategy-researcher | 前瞻找新因子/新 alpha |

morgan 另有 webhook（觸發式）即時喚醒，cron 只是安全網。盤前 `0 8 * * 1-5` 可再加一輪 morgan 輕巡檢：
對昨日建議在美股隔夜後做最終確認 + reconcile，再推 User。

---

## 9. 風險、限制與誠實聲明

1. **不是合格投資建議**：這是個人實驗，morgan 產出的是「研究意見」，**真實下單由 User 自行決定與負責**。
   全程紙上投組，無自動下單。
2. **過擬合**：最大科學風險。緩解 = purged walk-forward、OOS 才算數、**校準集上的過度調整本身被視為錯誤**
   （§6.4 決策規則）、ADR 記錄每次改動以便事後驗證是否真有效。
3. **look-ahead / 資料品質**：見 §4.2——免費源無 PIT，靠自建每日快照治本，冷啟動回測明確降級為「假設」。
4. **存活者偏誤**：universe 要含已下市/變更交易標的的歷史，否則回測虛胖。
5. **台股微結構**：漲跌幅 ±10%、處置股、全額交割、流動性斷層、除權息跳價——硬過濾 + 還原權值處理，
   且 1 月窗口要假設 User **真的進得出**（risk-monitor 的流動性閘）。
6. **regime 依賴**：模型在訓練 regime 外會失準——這正是 regime-aware ensemble + 觸發式 `regime_shift`
   復盤要對付的。
7. **成本**：一年 ×24/7 的 LLM token 是實際支出；用 evva 的 `daily_budget_tokens` 熔絲 + 分期招募
   + 廉價模型跑 watchdog（同 Sunday）控制。

---

## 10. 落地路線圖

> **現況（2026-06-15 PRODUCTION CUTOVER）**：已正式上線——real FinMind（token 已設）為主源、TWSE fallback、
> **synthetic 已移除**；P0–P2 平台地基完成並合併 main。**全編制（1 leader + 11 workers）一次性啟動**（User
> 拍板，刻意 override §7.2 分期招募，留 ADR）。下一個閘：讓 live PIT 校準帳本連續長出東西、誠實長期運行。

| 階段 | 交付 | 完成閘（gate）|
| --- | --- | --- |
| **P0 平台地基** | Monday engine：ingest + clean + PIT 快照 + featurestore + ledger + recommendations/portfolio API + dashboard + webhook + Telegram；evva-swarm.yml 骨架 + lab-engineer | 能手動觸發跑出一次「資料→特徵→空模型→寫一筆假建議→對帳」全鏈路；單元測試綠（因子/校準數學/分頁/對帳）|
| **P1 MVP 迴圈** | 冷啟動 GBDT 模型 + 1 leader + 6 workers；每日自動產 20 檔 + 逐日對帳 + 週復盤 scorecard | 連續 ≥4 週每日自動產出、帳本完整、週復盤能產出**具體**調整提案並留 ADR |
| **P2 深度** | +a-tech/risk-monitor/quant-researcher；月重訓 + regime ensemble + 組合風控閘 | 首次月重校準完成、OOS scorecard 出爐、至少一次因子退役/權重調整有 ADR |
| **P3 優化** | +strategy-researcher；季組織盤整；觸發式調整全開 | 跑滿一季、季盤整產出組織級調整（增聘/凍結/換 universe 之一）並驗證 |
| **長期** | 持續一年以上 | 雙軌成功衡量（§0）：自我改善可見 + 紙上投組相對大盤有可解釋的超額或可解釋的失敗 |

---

## 11. 待定決策（請 User 拍板）

1. **專案/平台/leader 命名**：暫名 Monday / Monday engine / morgan，是否沿用？或要 Sunday/friday 那種
   day-name persona 風格？
2. **冷啟動歷史深度**：CMoney 免費版只給 1 年歷史。要不要我同時接 FinMind（更長歷史、免費）把冷啟動
   訓練窗口拉到 3–5 年？（強烈建議要——1 年歷史橫跨不到一個完整多空循環，模型學不到 regime 多樣性。）
3. **universe 範圍**：上市+上櫃全納（過硬閘後 ~800–1,000）？還是先鎖**上市 + 流動性前 500** 把 MVP
   做小做快？
4. **建議純做多 vs 可融券做空**：MVP 建議**純做多**（台股散戶主場、放空成本與限制高）；之後再加空方？
5. **平台寄居何處**：這份白皮書先放在 `sunday/docs/twlab/`。要不要我直接 `git init` 一個**獨立
   sibling repo `~/lab/monday/`**（比照 Sunday 結構），把平台與 swarm 分目錄起底？
6. **Telegram / dashboard**：每日 20 檔要推 Telegram + 自服 dashboard（沿用 Sunday telegram.py / web）嗎？

---

## 附錄 A：evva-swarm.yml 草案（Phase 1）

```yaml
name: monday              # webhook: POST /api/swarm/monday/event
workdir: .

leader:
  agent: morgan
  budget_tokens: -1       # 永不凍結指揮官（workers 個別設上限）
  schedule:
    cron: "0 23 * * 1-5"  # 盤後整合定案 + 推 User
    prompt: "每日定案：讀策略憲法(GET /api/memory/morgan) → 取量化候選(GET /api/signals/today)
             與三位分析師覆蓋 → 過 risk-monitor 組合閘 → 選 ≤20 檔寫進 /api/recommendations
             與 /api/portfolio → 推 User(reports/telegram)。檢查觸發式事件未閉環者。"

workers:
  - agent: data-engineer
    schedule: { cron: "30 21 * * 1-5", prompt: "拉全源→清洗→PIT 快照→特徵庫；品質閘異常通報 morgan。" }
  - agent: quant
    schedule: { cron: "0 22 * * 1-5", prompt: "載入 registry 模型→推論→寫 /api/signals/today 候選排名。" }
  - agent: a-chips
    schedule: { cron: "15 22 * * 1-5", prompt: "對候選做籌碼覆蓋(三大法人/融資券/主力)，回報 morgan。" }
  - agent: a-catalyst
    schedule: { cron: "15 22 * * 1-5", prompt: "對候選做題材/新聞/情緒覆蓋 + 地雷否決，回報 morgan。" }
  - agent: reviewer-calibrator
    budget_tokens: -1
    schedule:
      cron: "0 14 * * 1-5"            # 每日對帳
      prompt: "逐日對帳開倉建議→更新 ledger→檢查觸發條件；逢週五對帳後加跑週復盤 scorecard + task_propose 提案。"
  - agent: watchdog
    schedule: { cron: "*/15 18-23 * * 1-5", prompt: "pipeline 健康巡檢，只在異常時通報 morgan。" }
  - persona: lab-engineer            # 特派工程師，無 cron，純票/訊息驅動
    model: deepseek-v4-pro
    effort: ultra
    when_to_use: "特派工程師——建/養 Monday engine：實作→測試綠→commit→部署→驗 health→回報。"

settings:
  permission_mode: bypass            # 無人值守 7×24（operator 確認；紙上投組、無真錢）
  max_iterations: 99
  daily_budget_tokens: 2000000       # 每成員每日上限（lab-engineer/morgan/reviewer 用 -1 豁免）
  stall_hard_timeout: "2h"           # 長訓練/長 code run 的硬超時（同 Sunday）
  task_stale_threshold: "24h"
  mailbox_stale_threshold: "30m"
  retention_days: 90                 # ledger/journal 久存（校準要長歷史），event log 90 天後歸檔
```

## 附錄 B：calibration ledger DDL（sqlite，草案）

```sql
CREATE TABLE recommendations (
  rec_id TEXT PRIMARY KEY, as_of_date TEXT, symbol TEXT, name TEXT, direction TEXT,
  entry_ref_price REAL, predicted_return REAL, predicted_prob_tp REAL, conviction REAL,
  model_version TEXT, feature_snapshot_id TEXT, regime_label TEXT,
  take_profit_price REAL, stop_loss_price REAL, holding_window_days INTEGER,
  contributing_factors TEXT, contributing_analysts TEXT, rationale TEXT, risk_notes TEXT
);
CREATE TABLE ledger_marks (        -- 逐日對帳，每筆建議每日一列
  rec_id TEXT, mark_date TEXT, close_price REAL, mtm_return REAL,
  max_favorable REAL, max_adverse REAL, tp_hit INTEGER, sl_hit INTEGER, days_held INTEGER,
  PRIMARY KEY (rec_id, mark_date)
);
CREATE TABLE outcomes (            -- 到期結算
  rec_id TEXT PRIMARY KEY, exit_date TEXT, exit_price REAL, realized_return REAL,
  hit INTEGER, tp_hit INTEGER, sl_hit INTEGER, exit_reason TEXT, error REAL
);
CREATE TABLE model_registry (
  model_version TEXT PRIMARY KEY, trained_at TEXT, train_window TEXT, cv_ic REAL,
  factor_set TEXT, regime_weights TEXT, notes TEXT
);
CREATE TABLE calibration_runs (   -- 每次復盤的 scorecard 快照
  run_id TEXT PRIMARY KEY, run_date TEXT, window TEXT, hit_rate REAL, tp_hit_rate REAL,
  avg_win REAL, avg_loss REAL, ic REAL, excess_vs_taiex REAL, attribution TEXT, adjustments TEXT
);
```

## 附錄 C：每日建議信封（JSON 契約，草案）

```json
{
  "as_of_date": "2026-06-15",
  "model_version": "gbdt-2026.06.01",
  "regime": "多頭趨勢",
  "recommendations": [
    {
      "symbol": "2330", "name": "台積電", "direction": "long",
      "entry_ref": 1085.0, "take_profit": 1180.0, "tp_pct": 8.8,
      "stop_loss": 1020.0, "holding_window_days": 20, "conviction": 0.72,
      "factors": ["momentum_3m", "foreign_net_buy_5d", "earnings_catalyst"],
      "analysts": ["a-tech:強勢突破", "a-chips:外資連7買", "a-catalyst:法說前卡位"],
      "rationale": "...", "risk_notes": "..."
    }
  ]
}
```

---

*v0.1 — 待 User 對 §11 拍板後收斂為 v1.0，並啟動 Phase 0 平台地基。*
