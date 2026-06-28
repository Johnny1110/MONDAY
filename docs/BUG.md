# BUG Tracker
Last updated: 2026-06-20 13:40 CST（週六維護）

## Open Bugs

### BUG-023: FinMind free tier 週末 rate-limit
- **發現**：2026-06-20，quant-researcher
- **症狀**：FinMind API "Requests reach the upper limit"，無法拉新資料
- **影響**：週末重訓/研究受限制，但 pipeline cache 可部分緩解
- **優先級**：P2（非 code bug，API tier 限制；考慮升級 Backer/Sponsor）
- **狀態**：觀測，等 UTC 午夜重置

### BUG-020: Portfolio 疊加殘留（53 open 含跨日期重複 symbol）
- **發現**：2026-06-18，risk-monitor
- **症狀**：finalize 後 35→53 open，同日標的雙重曝險
- **根因**：finalize append vs replace 模式
- **狀態**：code fixed（8755b35），歷史資料未清理。週一實戰驗證 replace 行為
- **commit**：8755b35

### BUG-019: Attribution by factor 回傳 flat 均值
- **發現**：2026-06-18，reviewer-calibrator
- **症狀**：三因子 attribution 完全相同
- **狀態**：code fixed（e4e806d），data snapshot 待更新後驗證
- **commit**：e4e806d

### BUG-018: 校準曲線 Bin 7-9 系統性 overconfidence
- **發現**：2026-06-16（synthetic），跨資料源確認
- **狀態**：觀測中（task #36 suspended），等 settled ≥30 後 calibmap.fit 自然修正
- **commit**：N/A（非 code bug，模型特性）

## Closed Bugs (recent)

### BUG-024: Pipeline 因 TPEx 不可用而整段失敗 ✅
- **發現**：2026-06-20，morgan/evva
- **修復**：49d585e — TPEx fetch 失敗 → graceful 降級 TWSE-only（log warning，不中斷 pipeline）
- **commit**：49d585e

### BUG-022: TPEx API 多重症狀（SSL + redirect + 週末空回應）✅
- **發現**：2026-06-20，quant-researcher + evva
- **修復**：49d585e（graceful degradation + SSL fallback in base.py）
- **commit**：49d585e

### BUG-021: PE 因子未出現在 feature snapshot ✅
- **發現**：2026-06-20
- **根因**：parquetio.py `Table.from_pylist()` 只從第一列推斷 schema → 舊 rows（無 pe_ratio）在前 → pe_ratio silent drop（PyArrow 24.0.0）
- **修復**：aa1fe98 — write_table 前先收集所有 keys 並標準化每個 dict
- **commit**：aa1fe98

### BUG-017: finalize 疊加 → 8755b35 ✅
### BUG-016: 1519 features 缺失（FinMind timeout）→ pipeline verify ✅
### BUG-015: 3008 entry price mismatch → 取價源問題 ✅
