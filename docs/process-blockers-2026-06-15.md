# Production Day 1 — 流程阻礙報告

**日期**：2026-06-15 | **作者**：morgan (CIO) | **版本**：v1.0

---

## 總覽

首次 Production 運轉在 31 分鐘內完成閉環（22:49→23:20），產出 12 檔紙上投組。
過程中遭遇 **13 項流程阻礙**，其中 3 項已在運轉中修復、10 項需工程/流程改善。

已修復（Day 1 內）：
- [x] B1: mark_forward=1 導致 as_of 卡在前一交易日
- [x] B3a: /api/chips 500 crash → 503（evva committed 983da1f）
- [x] B2: 環境變數名稱 mismatch（UNIVERSE_SIZE vs MONDAY_UNIVERSE_SIZE）

待修復（10 項）：
- [ ] B3b: FinMind 免費配額耗盡 → 籌碼/法人資料無法取得
- [ ] B4: Engine 啟動時序：.env token 晚於 process start
- [ ] B5: Pipeline API endpoint 無 universe_size / symbols 參數
- [ ] B6: Pipeline 歷史深度不足導致因子退化（3/5 null）
- [ ] B7: 背景 shell 無法 spawn background process
- [ ] B8: Pipeline run 時無進度輸出、逾時無資訊
- [ ] B9: Cron 觸發與手動觸發的 universe 不同步
- [ ] B10: HTTP endpoint 同步執行長任務導致 client timeout
- [ ] B11: 多個 pipeline 進程同時競爭 SQLite lock
- [ ] B12: risk-monitor cron 在 universe 變更後才觸發
- [ ] B13: 推薦 finalize 後的 signal 被背景 pipeline 覆寫

---

## B1 — mark_forward=1 預設值導致 as_of 停在舊交易日

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🔴 Critical |
| **影響** | 整個 swarm 基於過期資料（6/12）做決策，watchdog 觸發異常警報 |
| **根因** | `pipeline.run()` 和 CLI `--mark-forward` 都預設為 1，保留最後交易日做 forward marking。Swarm mode（finalize=false）需要 mark_forward=0 來產出最新交易日訊號 |
| **檔案** | `engine/monday/pipeline.py:129`, `engine/monday/routers/system.py:30` |
| **修復** | 當日手動以 CLI `mark_forward=0` 繞過 |
| **建議** | ① router `/api/system/run-pipeline` default `mark_forward` 改為 0（swarm mode 的正確行為）；② CLI `--mark-forward` default 改為 0；③ 或讓 data-engineer cron 顯式傳 `mark_forward=0`；④ 文件 `/manual` 應說明此參數 |
| **責任** | evva（PRD → 實作） |

---

## B2 — 環境變數名稱 mismatch 導致 universe_size 無法覆蓋

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟠 High |
| **影響** | 嘗試用 `MONDAY_UNIVERSE_SIZE=30` 縮小 universe 失敗——pipeline 仍然拉 500 檔，浪費 FinMind 配額與時間 |
| **根因** | Pydantic `BaseSettings` 用欄位名稱（`universe_size`）匹配 env var，而非 `MONDAY_` prefix。正確 env var 是 `UNIVERSE_SIZE` |
| **檔案** | `engine/monday/config.py:46` |
| **修復** | 當日手動測試發現正確名稱為 `UNIVERSE_SIZE` |
| **建議** | ① 在 config.py 加入 `model_config = SettingsConfigDict(env_prefix="MONDAY_")` 使所有 env var 有統一的 `MONDAY_` prefix；② 或在 `.env.example` 中明確列出所有可覆蓋的 env var 名稱；③ 文件 `/manual` 應列出 pipeline 可控參數 |
| **責任** | evva（PRD → 實作） |

---

## B3a — /api/chips RateLimitError → 500 crash（已修復）

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟠 High |
| **影響** | a-chips 對 27 檔候選全部無法取得籌碼資料，被迫 stand down |
| **根因** | `routers/chips.py` 直接呼叫 `finmind.fetch_institutional/fetch_margin`，未捕獲 `RateLimitError`（HTTP 402），導致 FastAPI 回傳 500 |
| **檔案** | `engine/monday/routers/chips.py:29-30` |
| **修復** | ✅ evva committed 983da1f：try/except RateLimitError → HTTP 503 + JSON error body |
| **責任** | evva（已完成） |

---

## B3b — FinMind 免費配額耗盡（402 Payment Required / Requests reach upper limit）

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🔴 Critical（週期性） |
| **影響** | 今日 a-chips 完全無法取得法人/融資券資料。future：若 pipeline 在盤後高峰跑，可能連價格資料都拉不到 |
| **根因** | FinMind free tier 有每日請求上限。今日 pipeline（500 檔 × 價格 API）+ 多輪手動測試消耗完配額 |
| **建議** | ① pipeline ingest 應先檢查 cache 有效性，只在 TTL 過期時才打 API；② 實作 FinMind 配額用量追蹤（GET /api/system/quota）；③ 分時段補資料（收盤後一小時內先拉核心 100 檔，夜間慢慢補完）；④ 考慮 TWSE fallback 用於籌碼資料（TWSE 無 rate limit）；⑤ 長期：評估 FinMind 付費方案 |
| **責任** | data-engineer（配額管理策略）+ evva（配額追蹤 endpoint + cache 優化） |

---

## B4 — Engine 啟動時序：.env token 晚於 process start

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟠 High |
| **影響** | Engine（PID 5441）在 21:32 啟動，但 `.env` 的 FinMind token 在 22:09 才寫入。Engine 進程持有的 `settings.finmind_token` 為空字串——任何需要 token 的 API 呼叫（chips, stock_info）都會失敗 |
| **根因** | 部署流程：先啟動 engine，後設定 .env。Engine 不會 hot-reload .env |
| **建議** | ① 部署 script 確保 .env 在 engine start 前就緒；② engine 加入 `/api/system/reload-config` endpoint 支援 hot-reload；③ engine startup 時若 token 為空，log warning 並在 /health 中暴露狀態；④ data-engineer 派工流程中增加「確認 engine token 已載入」的 preflight check |
| **責任** | evva（engine hot-reload + health check）+ data-engineer（preflight check） |

---

## B5 — Pipeline API endpoint 缺少 universe_size / symbols / mark_forward 參數

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟡 Medium |
| **影響** | 無法透過 HTTP API 控制 universe 大小、指定股票清單、或調整 mark_forward——只能透過環境變數或 CLI |
| **根因** | `POST /api/system/run-pipeline` 只接受 `days, mark_forward, source, model, finalize, post, notify`，缺 `universe_size` 和 `symbols` 參數 |
| **檔案** | `engine/monday/routers/system.py:29-32`, `engine/monday/pipeline.py:129-131` |
| **建議** | ① router 增加 `universe_size: int | None = None` 和 `symbols: str | None = None` query params；② pipeline.run() 傳遞這些參數給 ingest layer；③ data-engineer cron 可以用 `universe_size=100` 做快速 preliminary run |
| **責任** | evva（PRD → 實作） |

---

## B6 — Pipeline 歷史深度不足導致因子退化

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🔴 Critical（資料品質） |
| **影響** | 初版 pipeline（days=10）只有 ~30 日曆天歷史，導致 mom_60d / mom_120d / dist_high_60d 全部 null。排名退化為 mom_20d 單因子（Spearman=1.0），失去交叉驗證能力 |
| **根因** | `days=10` 為手動測試參數，但 data-engineer cron 未指定 days（使用預設 180）卻因其他原因未執行。feature builder 需要至少 120 個交易日才能計算所有因子 |
| **建議** | ① feature builder 在因子不足時應 log warning + 在 signals envelope 中標記 `degraded_factors: [...]`；② pipeline 在 days < 120 時自動 warning；③ data-engineer cron 明確指定 `days=180`；④ 初次冷啟動時自動用較大 days 參數 |
| **責任** | quant（因子需求規格）+ evva（warning + envelope metadata）+ data-engineer（cron 參數） |

---

## B7 — Shell 環境無法 spawn background process

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟡 Medium（開發體驗） |
| **影響** | 多次嘗試 `nohup ... &`、`disown`、bash `run_in_background` 全部失敗——錯誤 `WaitDelay expired before I/O complete`。導致無法在背景擴充 universe、所有長期任務必須同步等待 |
| **根因** | macOS / zsh 環境下，evva 的 bash tool 在 spawn background process 時遇到 I/O 阻塞。可能與 process group / tty 控制有關 |
| **建議** | ① evva 開發團隊調查 bash tool 的 background spawn 在 macOS/zsh 下的行為；② 作為 workaround，所有長期任務改走 HTTP API endpoint（但需要先修復 B10 的 timeout 問題）；③ engine 提供 async pipeline endpoint（POST 觸發，GET 查狀態） |
| **責任** | evva 開發團隊（bash tool fix）+ evva（async pipeline endpoint） |

---

## B8 — Pipeline run 無進度輸出，逾時無法診斷

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟡 Medium（可觀測性） |
| **影響** | Pipeline 跑 3 分鐘無任何輸出，無法判斷是卡在 ingest / clean / features / inference 哪個階段。多次重試浪費 FinMind 配額 |
| **根因** | `pipeline.run()` 內部無 progress callback / logging。`logging.basicConfig(level=INFO)` 只對 ingest HTTP 層有效，pipeline 主體無結構化進度 |
| **建議** | ① pipeline 各階段（ingest/clean/snapshot/features/inference/signals）加入 `yield` 或 callback 報告進度；② router 回傳 `{stage, progress_pct, message}` 而非阻塞等待；③ CLI `--verbose` 輸出每階段耗時 |
| **責任** | evva（PRD → 實作 pipeline progress reporting） |

---

## B9 — Cron 觸發與手動觸發的 universe 不同步

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟠 High（流程一致性） |
| **影響** | Data-engineer cron（21:30）未執行。Morgan 手動觸發 pipeline 使用 UNIVERSE_SIZE=30。後來背景擴充 UNIVERSE_SIZE=200 覆寫了 signals_today。導致 risk-monitor 分析時看到的是 200 檔 universe 訊號，而非 morgan 定案時用的 30 檔訊號——出現「模型外選股」的假警報 |
| **根因** | ① cron 未執行（可能因 engine restart）；② signals_today KV store 被後續 pipeline 覆蓋；③ 無 immutable 的「daily snapshot」機制 |
| **建議** | ① signals_today 加上 version/timestamp，finalize 應鎖定特定 version；② pipeline 在 finalize=false 時不覆蓋已有 signals_today（或加 `--force` flag）；③ 實作 daily snapshot 機制（/api/signals/{date}）；④ watchdog 監控 cron 是否準時觸發 |
| **責任** | evva（immutable signals versioning）+ watchdog（cron monitoring） |

---

## B10 — HTTP endpoint 同步執行長任務導致 client timeout

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟠 High |
| **影響** | `POST /api/system/run-pipeline` 同步執行整個 pipeline（5s~300s），HTTP client 在 30-60s 後 timeout。Pipeline 可能仍在背景執行但 client 收到錯誤 |
| **根因** | FastAPI router 直接呼叫 `pipeline.run()` 並等待結果，無 async 包裝 |
| **建議** | ① 改為 async pattern：POST 觸發 → 回傳 `{task_id, status: "running"}` → GET `/api/system/tasks/{task_id}` 查狀態；② 短期 workaround：增加 HTTP timeout 設定；③ pipeline 執行期間定期寫入 KV store 讓 status endpoint 可查 |
| **責任** | evva（PRD → 實作 async pipeline） |

---

## B11 — 多個 pipeline 進程同時競爭 SQLite lock

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟠 High（資料安全） |
| **影響** | 3 個 pipeline CLI 進程 + 1 個 inline Python 同時寫入 `monday.db`。可能導致 SQLITE_BUSY、資料損壞、或 write-ahead log 膨脹 |
| **根因** | 多次手動觸發 pipeline（重試心態），加上 bash 的 `run_in_background` 失敗後殘留 orphan process。無 mutex / lock 機制防止 concurrent pipeline |
| **建議** | ① pipeline 啟動時檢查是否有其他 pipeline 在執行（KV store `pipeline_running` flag + TTL）；② engine 的 `POST /api/system/run-pipeline` 應檢查並回傳 409 Conflict 若已在執行中；③ 加入 process-level lock file（`/tmp/monday-pipeline.lock`）；④ CLI `--wait` flag 等待前一個 pipeline 完成 |
| **責任** | evva（PRD → 實作 pipeline mutex） |

---

## B12 — Risk-monitor cron 在 pipeline/universe 變更後才觸發

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟡 Medium（流程時序） |
| **影響** | Risk-monitor cron（22:45）在今日 pipeline 手動觸發（23:02）之前就過了，導致 risk-monitor 未參與第一次 finalize。即使在 finalize 收到訊息，universe 已從 30→200 檔，分析基礎與 morgan 不同 |
| **根因** | Cron 時間固定，但 pipeline 執行時間不固定（手動觸發延遲）。Swarm 模式下無 event-driven 的「pipeline 完成 → risk-monitor 喚醒」機制 |
| **建議** | ① pipeline 完成後透過 webhook event `pipeline_complete` 喚醒 downstream agents；② 或將 cron 鏈改為 event chain：data-engineer → quant → analysts → risk-monitor → morgan（每個完成後 notify 下一個）；③ 短期：morgan 手動派 task 給 risk-monitor（今日做法，可行但不自動化） |
| **責任** | evva（event-driven chain）+ morgan（流程設計） |

---

## B13 — 推薦 finalize 後的 signal 被背景 pipeline 覆寫

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟡 Medium（資料完整性） |
| **影響** | Morgan 基於 30 檔 universe 完成 finalize（12 檔）。隨後背景 pipeline（UNIVERSE_SIZE=200）覆寫了 `signals_today` KV store。任何人再查 `/api/signals/today` 會看到完全不同的 50 檔候選，無法追溯 morgan 當時的決策基礎 |
| **根因** | `signals_today` 是單一 mutable KV entry，沒有 versioning，也沒有 per-date 存檔 |
| **建議** | ① finalize 時將當時的 signals snapshot 存入 `/api/signals/{date}`（immutable）；② `signals_today` 改名為 `signals_latest`，明確語義；③ pipeline 在 finalize 已存在的情況下，預設不覆蓋當日 signals（需 `--force` 才會覆蓋）；④ recommendations 記錄中增加 `signals_version` 欄位 |
| **責任** | evva（PRD → 實作 immutable signals） |

---

## 優先級建議

| 優先級 | 項目 | 理由 |
|--------|------|------|
| **P0** | B1 (mark_forward), B4 (env timing), B11 (pipeline mutex) | 每次執行必撞 |
| **P0** | B10 (async pipeline) | HTTP timeout 導致無法透過 API 觸發 |
| **P1** | B3b (FinMind 配額), B6 (因子退化), B9 (universe sync) | 資料品質與一致性 |
| **P1** | B13 (immutable signals) | 決策可追溯性 |
| **P2** | B2 (env prefix), B5 (API params), B7 (shell bg), B8 (progress) | 開發體驗與可觀測性 |
| **P2** | B12 (event chain) | 自動化程度 |

---

*Generated: 2026-06-15 23:20 CST | morgan / CIO*
