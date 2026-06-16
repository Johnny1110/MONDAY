# Monday 工作流程阻礙報告

**日期**：2026-06-16 | **作者**：morgan (CIO) | **版本**：v2.1（Day 2 累積，含對帳階段發現）

---

## 總覽

第二次 Production 運轉（2026-06-16 22:43→23:15），完成全流程閉環：Pipeline → 四方分析師覆蓋 → 20 檔定案 → 報告推送 → 逐日對帳。
過程累積發現 **7 項新障礙** + **5 項 Day 1 舊案持續**。

---

## 🆕 本日新發現（7 項）

### B14 — morgan cron（21:15）未觸發，每日自動流程斷鏈

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🔴 Critical |
| **影響** | 盤後 21:15 鬧鐘未喚醒 morgan，整個每日自動流程沒有自動啟動。22:43 才由外部 HTTP 手動觸發 pipeline，延遲 1.5 小時。若無人工介入，當日完全不會產出建議。 |
| **根因** | 不確定——可能 cron 未正確註冊、或 morgan 在 cron 時間點未 active。22:45 BOSS 手動發訊息後才喚醒 morgan。 |
| **重現** | 檢查 `list_members`：morgan 有 cron `15 21 * * 1-5` 已註冊，但 21:15 未觸發。watchdog 的 cron（`*/15 18-23`）正常運作，說明 cron infrastructure 本身正常。 |
| **建議** | ① 調查 morgan 的 cron 為何未觸發（timezone 問題？cron 在 morgan suspended 時是否會跳過？）；② 增加 watchdog 的「22:30 仍無當日 pipeline」警報（watchdog manifest 已定義此職責，確認是否確實執行）；③ 考慮雙保險：watchdog 在 21:20 檢查 morgan 是否已醒，未醒則主動 ping morgan |
| **責任** | evva（cron reliability）+ watchdog（雙保險機制） |

### B15 — Pipeline 被外部觸發時 post=false，無 webhook 通知

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🔴 Critical |
| **影響** | 今日第一條 pipeline（pipeline-20260616T144326）由外部 HTTP 觸發，參數 `post=false`。完成後沒有 webhook 通知 morgan，morgan 必須手動輪詢確認進度。 |
| **根因** | 外部觸發 pipeline 時未傳 `post=true`。morgan 自己的 cron 指令明確要求 `post=true`，但 cron 本身未觸發（見 B14）。 |
| **建議** | ① router `/api/system/run-pipeline` 將 `post` 預設值改為 `true`（swarm mode 的正確行為）；② pipeline 若 `finalize=false` 且 `post=false`，在 log 中加 warning |
| **責任** | evva（router default change） |

### B16 — a-chips 在無任務指派下自行執行並卡住

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟠 High |
| **影響** | a-chips 在未收到 task_assign 的情況下，自行啟動籌碼覆蓋（可能是殘留的 cron 或 stale message trigger）。bash call 卡住超過 10 分鐘。 |
| **根因** | 不確定。可能是 Day-1 的 stale message、或 signals_today 更新觸發。 |
| **建議** | ① 調查 a-chips 為何在無 task 下自行啟動；② swarm 成員應只在收到 message 或 task_assign 時才行動；③ 增加 message dedup/timeout 機制 |
| **責任** | evva（swarm message dispatch 可靠性） |

### B17 — Engine 板塊集中度閾值與憲法不一致（5 vs 6）

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟡 Medium |
| **影響** | POST /api/recommendations/finalize 回傳 `violations: [{sector_concentration: "電子零組件業: 6 > 5"}]`。但憲法明定「單一板塊 ≤30%（即 ≤6 檔）」。 |
| **根因** | Engine 的 sector concentration check 硬編碼為 5 檔（25%），而非讀取憲法的 30% 規則。 |
| **建議** | Engine 的 concentration limit 應可配置（env var `SECTOR_CONCENTRATION_PCT`，預設 30），或與 `/api/memory/morgan` 同步 |
| **責任** | evva（configurable concentration limit） |

### B18 — 資料庫未持久化 Day-1 投組，每次冷啟動

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🔴 Critical（校準基礎） |
| **影響** | 2026-06-15 Day 1 的 12 檔投組、報告、ADR-001 全部消失。核心信念「沒有帳本就沒有校準」無法實踐。 |
| **根因** | 可能是 DB reset、DB file 未被 volume mount、或 engine restart 時使用了不同的 data dir。 |
| **建議** | ① 確認 `data_dir` 配置是否指向持久化 volume；② `/health` response 中增加 `db_persisted: true/false` 欄位；③ engine startup 時若 DB 為空但存在 backup，自動 restore |
| **責任** | evva（DB persistence architecture） |

### 🆕 B19 — Entry price marks vs portfolio 跨表不一致

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🟠 High |
| **影響** | reviewer-calibrator 逐日對帳發現：/api/ledger/marks 反推的 entry price 與 /api/portfolio 記錄的 entry_price 有 ±1-3 點落差。首日僅差 2-3 點，但 20 天累積後會嚴重汙染歸因、命中率、IC 計算。 |
| **根因** | marks 計算 mtm 時的參考價與 portfolio finalize 寫入的 entry_price 取價源不同（可能是次日開盤價 vs 決策日收盤價）。 |
| **建議** | ① reconcile 的 mtm 基準價應與 finalize 寫入的 entry_price 使用同一取價源（統一為 FinMind close）；② portfolio entry_price 欄位增加 `price_source` metadata；③ 加入 cross-table consistency check |
| **責任** | evva（reconcile 取價修正 + consistency check） |

### 🆕 B20 — TP/SL trigger 未觸發（首日 7 檔穿越 ±8%）

| 屬性 | 內容 |
|------|------|
| **嚴重度** | 🔴 Critical（組合管理核心功能失效） |
| **影響** | 開倉首日（6/16）已有 7/20 標的 mtm 穿越 ±8% 邊界（5 檔越 TP、2 檔越 SL），但 tp_hit=0, sl_hit=0, settled=0。若 B19 的 entry price 不一致是根因，那 7 檔越線可能是假穿越（mtm 基於錯誤的 entry 計算）。 |
| **根因** | 兩種可能：① B19 的 entry price 不一致導致 mtm 計算錯誤（假穿越）；② TP/SL 判定邏輯有 bug。需 reviewer 進一步調查。 |
| **建議** | ① 優先修復 B19（統一取價源），修復後重新 reconcile；② TP/SL 判定邏輯加入 unit test；③ reconcile 回傳增加 `trigger_price` 欄位供追溯；④ 短期：暫停自動結算，改 reviewer 手動標記 + morgan 確認 |
| **責任** | reviewer-calibrator（調查根因）→ evva（修復） |

---

## 🔁 Day-1 舊案持續（5 項）

| # | 項目 | 今日狀態 |
|---|------|----------|
| B1 | mark_forward=1 預設值 | ⚠️ 仍未修。今日第一條 pipeline 仍用預設 `mark_forward=1`。手動第二條 pipeline 傳了 `mark_forward=0` 才正確。 |
| B5 | API 缺少 universe_size 參數 | ⚠️ 仍未修。今日 pipeline 的 `universe_size=null`，依賴 env var 預設 500。 |
| B6 | 因子退化/歷史深度 | ✅ 今日無退化，180 天歷史 + 500 檔全部因子 100% 覆蓋。但 baseline-0 的因子同質性問題（全動量無對沖）是新發現。 |
| B7 | Shell background spawn 失敗 | ⚠️ 仍未修。但今日未需要此功能（所有 pipeline 走 HTTP API）。 |
| B13 | Finalize 後 signal 被覆寫 | ⚠️ 仍未修。6/15 signals 被 6/16 pipeline 覆寫。無法追溯 6/15 的決策基礎。 |

---

## 優先級建議（更新）

| 優先級 | 項目 | 理由 |
|--------|------|------|
| **P0** | B14 (cron 未觸發) | 每日自動流程的起點，斷了就全停 |
| **P0** | B18 (DB 未持久化) | 沒有校準基礎 = Monday 核心信念崩壞 |
| **P0** | B15 (post 預設值) | webhook 是中樞神經，斷了 morgan 就瞎了 |
| **P0** | B20 (TP/SL trigger) | 組合管理核心功能失效 |
| **P0** | B1 (mark_forward 預設) | Day-1 已知，每次執行必撞 |
| **P1** | B19 (entry price 不一致) | 累積汙染歸因，且可能是 B20 根因 |
| **P1** | B16 (a-chips 自行啟動) | 干擾流程、消耗資源 |
| **P1** | B11 (pipeline mutex) | Day-1 已知，多 pipeline 競爭 SQLite |
| **P1** | B10 (async pipeline) | HTTP timeout 導致 API 不可靠 |
| **P2** | B17 (concentration threshold) | 功能可用但數值不一致 |
| **P2** | B13 (immutable signals) | 決策可追溯性 |
| **P2** | B5/B7/B8 (開發體驗) | 累積改善 |

---

## ✅ 本日正面發現

1. **webhook 機制可用**：第二條 pipeline（`post=true`）成功觸發 `pipeline_complete` webhook
2. **分析師覆蓋層有效**：四方分析師產出高品質報告，16 檔共識排除中有 11 檔來自人工判斷
3. **Watchdog 正常運作**：cron `*/15 18-23` 正常巡檢
4. **FinMind 配額今日健康**：1633 calls 未限速
5. **reviewer-calibrator 偵錯能力強**：首日對帳即發現 entry price 不一致 + TP/SL 未觸發

---

*Generated: 2026-06-16 23:16 CST | morgan / CIO*

---

## 🔧 evva 工程處理狀態（2026-06-16，逐項對照原始碼 + live 資料查證）

詳見 [`docs/adr/0002-live-pipeline-defaults.md`](../adr/0002-live-pipeline-defaults.md)。

| ID | 判定 | 處理 |
|----|------|------|
| **B1** | ✅ 真 bug（核心） | **已修**：`/run-pipeline` live 預設 `mark_forward=0`（as_of=最新收盤）；CLI 保留 1 給回測 |
| **B15** | ✅ 真問題（預設值） | **已修**：`post` 預設改 `true`；`post=false` 時記 warning |
| **B17** | ✅ 真（預設值與憲法不符） | **已修**：`max_per_sector` 5→6（憲法 ≤30%×20）；仍可 `MAX_PER_SECTOR` 覆寫 |
| **B3/as_of** | = B1 症狀 | 隨 B1 解決（6/16 本就存在，被 mark_forward 擋住） |
| **B19** | ❌ 反推誤差，非資料不一致 | 不需修：marks 的 mtm 是**扣成本淨值**，反推 entry 必差 ≈entry×0.6%。帳本正確。可選：marks 增列 entry_price 供對帳（待核可） |
| **B20** | ❌ 誤診 | 不需修：exits 是 **ATR 動態**（TP+20~28%/SL−13~15%），非 ±8%；無標的真的碰邊界，`tp/sl_hit=0` 正確 |
| **B18** | ❌ 維運（非 bug） | 不需修：Day-1 資料原本有持久化，被 `down -v` 清掉。`/api/system/status` 已露出各表筆數 |
| **B14** | ⚠️ 維運 + 架構缺口 | 短期：保持 swarm 長駐（已重啟）。長期：引擎側 cron 安全網 → **[PRD-001](../PRD/PRD-001-engine-cron-safety-net.md)** |
| **B16/B7** | evva 範圍 | 不在本專案修改範圍（evva runtime），請於 evva 開票 |
| **B5/B10/B11** | 已實作/已過時 | B5 參數已存在；B10 已 async；B11 已遷 Postgres + 有 single-flight lock |
| **B6** | 預期行為 | 冷啟動 baseline 同質性 → 訓練 GBDT 解決（roadmap），非 bug |
| **B13** | 已有防護 | finalize 後有 force-gated 防覆寫 + 逐日 `/api/signals/{date}` 封存 |

**測試**：114 passed / 5 skipped。**注意**：運行中的引擎需 **restart** 才會載入以上修正。

*evva 工程註記 | 2026-06-16*
