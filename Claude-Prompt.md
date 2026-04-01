# Claude 交接 Prompt

最後更新：2026-04-02
請用中文回覆。

---

## 一. 專案現況總覽

### 策略設定

- 台股 long-only，月中再平衡，`tw_3m_stable` profile
- 三因子：`price_momentum`（55%）、`trend_quality`（20%）、`revenue_momentum`（25%）
- 已停用：`institutional_flow`（0%，rank IC 全期為負）、`quality`（0%，稀釋動能）
- `top_n=8`、`max_same_industry=3`、`caution exposure=0.70`

### 回測績效

| 回測 | Sharpe | Alpha | MDD | 性質 |
|------|--------|-------|-----|------|
| 6M（2024-H2） | 1.08 | +13.52% | -21.50% | In-Sample |
| 3Y（2022-2024） | 1.85 | +48.43% | -21.50% | In-Sample |
| **2025 全年** | **1.81** | **+8.16%** | **-19.25%** | **Out-of-Sample** |
| **2019-2020** | **1.91** | **+27.03%** | **-17.41%** | **Out-of-Sample** |
| 4Y（2022-2025） | 1.47 | +26.34% | -31.07% | IS+OOS |
| **Walk-Forward 平均** | **1.22** | **+39.70%** | **-23.80%** | **11 段 OOS 平均** |

### 完成狀態

| 階段 | 狀態 |
|------|------|
| P0 Research Integrity | ✅ 全部完成 |
| P1 Grid Search（max_same_industry 2→3） | ✅ 落地 + Codex 驗證 |
| P2 因子/Exposure（IF 0%） | ✅ 落地 + Codex + Claude 雙重驗證 |
| P3 策略擴展（vol_weighted ❌、quality ❌） | ✅ 研究完成 + Codex 驗證 |
| 架構評估（Claude + Codex 交叉驗證） | ✅ 完成 |
| P4.0 Paper trading 可審計性 | ✅ append-only + 讀取 DB |
| P4.1 Benchmark split 修復 | ✅ `adjust_splits()` 正分割 + 合股偵測 |
| P4.2 Known-answer test | ✅ 27 個 metrics 測試 |
| P4.3 Walk-Forward 驗證（11 個半年視窗） | ✅ 平均 Sharpe 1.22，勝率 64% |
| P4.4 Hardcoded 常數提到 config | ✅ engine.py 6 個值 → `settings.yaml` |
| P4.8 主題集中風險指標 | ✅ `theme_concentration` + `constants.py` 共用 |
| P4.9 `data_degraded` false alarm 修復 | ✅ IF=0% 不再觸發 |
| P5 雙視角審查 + 工程修復（5 輪 + Codex） | ✅ 87 測試、CSV fallback、reverse split |
| Streamlit Dashboard（5 頁） | ✅ 完成 |
| 小額實盤追蹤工具 | ✅ `scripts/real_trade.py` |
| 日頻報酬序列輸出 | ✅ `*_daily_returns.json` |

---

## 二. 2026-04-02 完成的工作（P5 雙視角審查）

### P5 概述

以**專業投資人**和**資深量化主管**兩個視角對整個專案做程式碼審查。
共 5 輪修復，每輪完成後產生 Codex Prompt 讓 Codex 獨立交叉驗證。

### 5 輪修復明細

**第一輪 — 核心缺陷修復：**
- R1：`metrics.py` 新增合股偵測（reverse split ≥100% 暴漲 → 自動前復權）
- E1：`tests/test_data_slicer.py` 新增 15 個測試，覆蓋 `_DataSlicer` point-in-time 截斷
- R2：`real_trade.py` paper 比對改為持股清單重疊度
- R3：`paper_trade.py --status` 新增科技供應鏈佔比

**第二輪 — 工程穩健性：**
- E3：`tests/test_universe.py` 新增 2 個 edge case 測試
- E4：`engine.py` NaN 高比例（>50%）加 logger.warning
- E7：`universe.py` stock_id 缺失 guard + `tw_stock.py` 寫入順序修正

**第三輪 — 程式碼品質：**
- 未使用 import 清理（`test_data_slicer.py`）
- `TECH_SUPPLY_CHAIN_KEYWORDS` 提取到 `src/utils/constants.py` 共用
- `engine.py` import 排序修正（`import hashlib` 移至頂部）

**第四輪 — Config 提取 + CSV Fallback：**
- E6：`engine.py` 6 個 hardcoded 值提取到 `config/settings.yaml` 的 `backtest:` section
- E8：`finmind.py` 新增 `_load_stock_info_csv_fallback()`、`_save_stock_info_csv_snapshot()`
- E2：新增 `scripts/refresh_reports.sh` 一鍵重跑 Walk-Forward + Dashboard

**第五輪 — Cache Hit 修復 + degraded_periods：**
- E8 補丁：`finmind.py` cache hit 路徑（TTL < 7 天）加 `_ensure_stock_info_csv()` 呼叫
- E2 增強：`walk_forward.py` entry dict 新增 `degraded_periods` 欄位

### Codex 驗證狀態

- 第 1-4 輪：全部 PASS（回歸 87 tests 通過）
- 第 5 輪：已產生 `Codex-Prompt.md`（P5 驗證 Prompt），**待回報結果**

### 測試覆蓋（P5 後）

| 測試檔 | 數量 | 覆蓋 |
|--------|-----|------|
| `test_metrics.py` | 27 | Sharpe/MDD/Alpha/split adjust（含 reverse split） |
| `test_data_slicer.py` | 15 | point-in-time 截斷（OHLCV/營收/法人/市值） |
| `test_ranking.py` | 10 | 因子排名、percentile |
| `test_selection.py` | 12 | 選股門檻、hold buffer、產業分散 |
| `test_vol_weighting.py` | 9 | 波動率加權模式 |
| `test_zero_weight_skip.py` | 8 | IF=0% 跳過邏輯 |
| `test_degradation.py` | 4 | data_degraded 判定 |
| `test_universe.py` | 2 | stock_id 缺失 edge case |
| **合計** | **87** | Docker 全通過；Windows 本地 29 通過 |

### 文件更新

四個 .md 檔已同步更新至 2026-04-02：
- `優化紀錄.md`：新增 P5 完整章節（5 輪修復 + 測試覆蓋表 + 檔案總覽）
- `優化建議.md`：P4.3/P4.4/P4.8/P4.9 標記已完成；測試數 52→87；Claude 額外發現標記已修復
- `README.md`：架構圖 + config 範例 + 下一步全面更新
- `教學進度.md`：檔案地圖新增 6 個檔案；測試數 52→87

---

## 三. 關鍵檔案位置

| 檔案 | 用途 |
|------|------|
| `config/settings.yaml` | 策略參數 + `backtest:` section（6 個提取的常數） |
| `src/backtest/engine.py` | 回測引擎 + `_DataSlicer` + config 驅動 + NaN 警告 |
| `src/backtest/metrics.py` | KPI 計算 + `adjust_splits()`（含 reverse split） |
| `src/backtest/universe.py` | 歷史 Universe 管理 + stock_id guard |
| `src/portfolio/tw_stock.py` | 核心選股邏輯 |
| `src/data/finmind.py` | FinMind API + pickle cache + CSV fallback（3 個方法） |
| `src/utils/constants.py` | 共用常數（`TW_TZ`、`TECH_SUPPLY_CHAIN_KEYWORDS`） |
| `scripts/paper_trade.py` | Paper trading 記錄器（append-only + 集中度顯示） |
| `scripts/real_trade.py` | 小額實盤追蹤（buy/sell/status/close/report） |
| `scripts/walk_forward.py` | Walk-Forward 驗證（含 `degraded_periods`） |
| `scripts/refresh_reports.sh` | 一鍵重跑 Walk-Forward + Dashboard 6M |
| `scripts/run_backtest.py` | 回測 CLI（含日頻報酬輸出） |
| `dashboard/` | Streamlit Dashboard（5 頁） |
| `tests/` | 87 個測試（8 個測試檔） |
| `Codex-Prompt.md` | Codex 驗證 Prompt（目前為 P5 第五輪） |
| `reports/walk_forward/summary.json` | Walk-Forward 匯總（⚠️ 舊資料，需重跑） |
| `reports/paper_trading/` | Paper trading 紀錄（目前 1 個月：2026-03） |

---

## 四. 兩個角色的現況評估

### 視角一：專業投資人（風險/報酬/實盤信心）

**已建立的信心：**

1. **OOS 驗證紮實** — 2025 全年 Sharpe 1.81（IS 衰減僅 2%）、2019-2020 Sharpe 1.91、Walk-Forward 11 段平均 1.22
2. **策略邏輯可解釋** — 三因子（動能+趨勢+營收）不是黑箱，過去 6 年跨越牛熊都有正期望值
3. **風控機制運作** — 2020 疫情即轉 risk_off 避開崩盤；2022 熊市 MDD 控制在 -21%
4. **研究紀律好** — 能拒絕漂亮的 in-sample 數字（caution 85%、vol-weighted、quality）

**仍存在的風險：**

| 風險 | 嚴重度 | 說明 |
|------|--------|------|
| Alpha 高估 ~2-3%/年 | 中 | Benchmark 是 price-only（不含配息），3Y 累計偏差約 9% |
| 科技供應鏈集中 | 中 | 持股平均 56% 科技類，台股大盤特性但遇科技反轉會同跌 |
| Paper trading 數據不足 | 中 | 僅 1 個月（2026-03），無法判斷實盤表現 |
| 月頻無止損 | 中 | 單檔一個月內跌 30% 只能硬扛到再平衡日 |
| 小型股流動性 | 低 | `min_avg_turnover=5000 萬` 已篩掉流動性差的標的 |

**投資人視角的下一步建議：**

1. **最重要：讓 Paper Trading 自然累積** — 不要再調參。策略已充分驗證，現在需要的是時間
2. **2026-04-14 執行第二筆 paper trading** — 檢查系統是否正常出單
3. **每月檢查重點**：持股是否合理、集中度是否異常、系統是否正常運作
4. **P4.5（Total Return Benchmark）** — 值得做，能讓 Alpha 估計更準確，但不影響策略決策
5. **6 個月後（2026-10）正式評估** — 對比 Walk-Forward 平均 Sharpe 1.22
6. **警戒線**：累計 Sharpe < 0.7 或 Alpha 持續為負 → 觸發診斷

### 視角二：資深量化主管（工程/測試/穩健性）

**已達到的工程水準：**

1. **87 個測試** — 覆蓋選股排名、metrics 精確值、_DataSlicer point-in-time、split adjust、degradation
2. **Config 驅動** — engine.py 6 個常數提取到 settings.yaml，可調不改 code
3. **備援機制** — finmind.py 有 pickle cache + CSV fallback + adjusted→unadjusted API fallback
4. **可重現性** — Walk-Forward 框架 + universe fingerprint（MD5 hash）
5. **程式碼品質** — 共用常數抽到 constants.py、import 排序、無 dead code

**仍存在的工程缺口：**

| 缺口 | 嚴重度 | 說明 |
|------|--------|------|
| `BacktestEngine.run()` 零整合測試 | 中高 | 核心方法無自動化測試，只靠手動 Docker 跑驗證 |
| `finmind.py` 零單元測試 | 中 | CSV fallback、cache TTL、API error handling 都沒測試 |
| Walk-Forward summary 是舊資料 | 中 | 全部 11 個 `data_degraded=true`（修復前產生的），無 `degraded_periods` 欄位 |
| Dashboard 6M 可能過期 | 低 | 需確認是否用修復後的 engine 產生 |
| `tw_stock.py` 策略層 hardcode | 低 | `0.85`(risk_off discount)、`-0.15`(momentum threshold)、動能時間加權 `0.20/0.35/0.45` 等約 15 個常數未進 config |
| Codex P5 驗證結果未回 | 低 | 已產生 Prompt，等待執行 |

**量化主管視角的下一步建議：**

1. **立即可做（Docker）**：執行 `scripts/refresh_reports.sh` 重跑 Walk-Forward summary + Dashboard 6M
2. **短期（1-2 天）**：補 `BacktestEngine.run()` 整合測試 — 用 mock data 跑 mini backtest，驗證輸出結構
3. **短期（半天）**：補 `finmind.py` 核心測試 — cache hit/miss、CSV fallback 讀寫
4. **中期**：P4.5 Total Return Benchmark — 爬 TWSE 除權息資料，修正 Alpha 偏差
5. **低優先**：P4.6 Drift-aware 日報酬、P4.7 FinMind as_of plumbing、tw_stock.py 策略層 hardcode 提取

---

## 五. 下一步行動清單（按優先度）

### 第一優先：Docker 執行（耗時但簡單）

```bash
# 1. 重跑 Walk-Forward（約 30-60 分鐘）
# 修復後的 engine 會正確計算 data_degraded，且 summary 會有 degraded_periods 欄位
docker compose run --rm --entrypoint python portfolio-bot \
    scripts/walk_forward.py \
    --train-months 18 --test-months 6 \
    --start 2019-01-01 --end 2025-12-31 \
    --output-dir reports/walk_forward

# 2. 重跑 Dashboard 6M
docker compose run --rm --entrypoint python portfolio-bot \
    scripts/run_backtest.py \
    --start 2024-06-01 --end 2024-12-31 \
    --output-dir reports/backtests/dashboard_6m

# 或直接用一鍵腳本：
# ./scripts/refresh_reports.sh
```

重跑後驗證：
- `summary.json` 的 `data_degraded` 不應全部為 true（IF=0% 修復後）
- `summary.json` 的每個 window 應有 `degraded_periods` 欄位

### 第二優先：補測試覆蓋

| 項目 | 檔案 | 工作量 | 說明 |
|------|------|--------|------|
| BacktestEngine 整合測試 | `tests/test_engine.py`（新建） | 2-3hr | 用 mock data 跑 mini backtest，驗證輸出結構和日報酬序列 |
| finmind.py 核心測試 | `tests/test_finmind.py`（新建） | 1-2hr | cache hit/miss、CSV fallback 讀寫、stock_info 流程 |

### 第三優先：回測精度提升

| 項目 | 說明 | 工作量 |
|------|------|--------|
| P4.5 Total Return Benchmark | 爬 TWSE 除權息資料，benchmark 改為含息報酬 | 1-2 天 |
| P4.6 Drift-aware 日報酬 | 持有期內權重隨股價 drift 更新 | 1-2 天 |

### 不急 / 暫緩

| 項目 | 原因 |
|------|------|
| P4.7 FinMind as_of plumbing | `_DataSlicer` 已在輸出端截斷，未出過問題 |
| tw_stock.py 策略層 hardcode | 策略不會再調，提取到 config 的 ROI 低 |
| P3.5 期中止損 | 需大幅修改 engine 支援期中事件，風險高 |
| P4.10 券商對接 | 等 paper trading 6 個月後 |
| P4.11 AI 整合 | 最後，AI 只做市場風向 + 事件風控 |

### Paper Trading 時間表

- 2026-03：第一筆紀錄（已存在 `reports/paper_trading/2026-03.json`）
- 2026-04-14：執行第二筆 paper trading
- 2026-04~06：累積數據，不做判斷
- 2026-07~09：初步趨勢觀察
- 2026-10~：正式評估（對比 Walk-Forward 平均 Sharpe 1.22）
- **警戒線**：Sharpe < 0.7 或 Alpha 轉負 → 觸發診斷

---

## 六. 目前不要做的事

- ❌ 調整 `caution/risk_off` exposure（overfit 風險太高，78% 的回測期為 caution/risk_off）
- ❌ 把 `vol_weighted` 或 `quality` 拉回正式設定（已測試，績效下降）
- ❌ 改 `exposure` / `top_n`（已 grid search，目前設定最佳）
- ❌ 把 AI 加進 ranking（AI 只做市場風向 + 事件風控）
- ❌ 同時改多個東西（一次改一項，方便歸因）
- ❌ 在 paper trading 累積 6 個月前投入實資金

---

## 七. 技術備註

- **Docker vs Windows**：需要 FinMind API 的指令在 Docker 跑（`docker compose run ...`）；Dashboard 和 real_trade.py 在 Windows 本機跑
- **測試環境**：87 測試在 Docker 全通過；Windows 本地只有 29 通過（5 個 tw_stock.py 依賴的測試檔需 Docker 環境）
- **Walk-Forward summary.json 是舊資料**：全部 `data_degraded=true`、無 `degraded_periods` 欄位 — 這是 P5 修復前產生的，需重跑更新
- **Codex P5 驗證**：`Codex-Prompt.md` 已準備好 P5 第五輪驗證 Prompt，尚未執行
- **real_trading 目錄不存在**：尚未開始實盤操作
- **config/settings.yaml 結構**：`system:` → `backtest:` → `portfolio:` → ...，`backtest:` section 是 P5 E6 新增

---

## 八. 文件索引

| 文件 | 內容 | 最後更新 |
|------|------|---------|
| `Claude-Prompt.md` | 本檔（Claude 交接用） | 2026-04-02 |
| `Codex-Prompt.md` | Codex 驗證 Prompt（P5 第五輪） | 2026-04-02 |
| `優化紀錄.md` | 所有修改的詳細紀錄（P5→P4.3→P2→P1→P0） | 2026-04-02 |
| `優化建議.md` | 雙視角評估、P4 路線圖、架構評估、測試框架 | 2026-04-02 |
| `策略研究.md` | P1-P3 因子研究結論、OOS 結果、Walk-Forward | 2026-04-01 |
| `教學進度.md` | 程式碼逐檔解析、觀念教學、檔案地圖 | 2026-04-02 |
| `README.md` | 專案架構、Docker 操作、回測績效、下一步 | 2026-04-02 |
