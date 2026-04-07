# Claude 交接 Prompt

最後更新：2026-04-07
請用中文回覆。

---

## 一. 專案現況總覽

### 策略設定

- 台股 long-only，月中再平衡，`tw_3m_stable` profile
- 三因子：`price_momentum`（55%）、`trend_quality`（20%）、`revenue_momentum`（25%）
- 已停用：`institutional_flow`（0%，rank IC 全期為負）、`quality`（0%，稀釋動能）
- `top_n=8`、`max_same_industry=3`、`caution exposure=0.70`
- **候選股池**：以 close×volume（20日均值）排序取前 80 名 — 正式規格，Live 和 Backtest 完全一致
- **market_value**：已退出選股排序，僅供 dashboard 監控用（TWSE 股本 × OHLCV 收盤價計算）
- **benchmark**：仍為 `price_only`（不含配息），Alpha 有 ~2-3%/年系統性高估

### 回測績效（2026-04-07，第二台電腦）

| 回測 | Sharpe | Alpha | MDD | 性質 |
|------|--------|-------|-----|------|
| 6M（2024-H2） | 0.45 | -7.15% | -23.81% | IS |
| 4Y（2022-2025） | 1.33 | +23.28% | -31.09% | IS+OOS |
| **Walk-Forward 平均** | **1.15** | **+33.60%** | **-24.60%** | **11 段 OOS** |
| Walk-Forward Bootstrap 95% CI | [-0.18, 2.48] | — | — | ⚠️ 不顯著（CI 包含 0） |

另一台電腦數字不同（4Y Sharpe 1.41、WF 1.22），原因是 OHLCV cache 內容差異。選股邏輯完全相同。要一致需複製整個 `data/cache/`。

### 完成狀態

| 階段 | 狀態 |
|------|------|
| P0 Research Integrity | ✅ |
| P1 Grid Search（max_same_industry 2→3） | ✅ + Codex 驗證 |
| P2 因子/Exposure（IF 0%） | ✅ + Codex + Claude 雙重驗證 |
| P3 策略擴展（vol_weighted ❌、quality ❌） | ✅ + Codex 驗證 |
| P4.0-P4.4 / P4.8 / P4.9 工程化 | ✅ |
| P5 雙視角審查 + 工程修復（5 輪 + Codex） | ✅ |
| P6 度量層 + Cache 機制 | ✅ |
| **P7 選股池正式化 + TWSE 市值監控 + 全面審查** | **✅** |
| Streamlit Dashboard（5 頁） | ✅ |
| 小額實盤追蹤工具 | ✅ `scripts/real_trade.py` |
| Claude Code Skills（5 commands + 1 agent） | ✅ `.claude/commands/` |

---

## 二. P7 完成的工作（2026-04-07，第二台電腦）

### P7 修改清單（共 15 項）

| 項目 | 內容 | 檔案 |
|------|------|------|
| P7.1 | Walk-Forward 重跑（含 Bootstrap Sharpe CI） | `reports/walk_forward/summary.json` |
| P7.2 | Docker image 重建（修復 scipy 缺失） | Dockerfile |
| P7.3 | `.dockerignore` 修復（加入 pytest 暫存） | `.dockerignore` |
| P7.4 | TWSE+TPEX 股本抓取（1961 家） | `src/data/twse_scraper.py` |
| P7.5 | `fetch_market_value()` 改為 TWSE 計算（監控用） | `src/data/finmind.py` |
| P7.6 | 選股池正式化：close×volume 為正式規格 | `src/portfolio/tw_stock.py` |
| P7.7 | 回測引擎移除 market_value 排序 | `src/backtest/universe.py` |
| P7.8 | 清理 pytest 暫存資料夾 | 已刪除 |
| P7.9 | 統一 Live/Backtest 排序為 close×volume | `src/backtest/universe.py` |
| P7.10 | `_DiskCache.load()` 改為 log-only 不刪檔 | `src/data/finmind.py` |
| P7.11 | 修正 test fixture 缺 `_backtest_mode` | `tests/test_finmind.py` |
| P7.12 | 新增 12 個 P7 直接測試 | `tests/test_p7_universe.py` |
| P7.13 | 刪除死碼 `_prepare_auto_universe()`（87 行） | `src/portfolio/tw_stock.py` |
| P7.14 | revenue_momentum weight=0 時跳過 API | `src/portfolio/tw_stock.py` |
| P7.15 | 移除無用的 `preload_reference_data()` market_value 呼叫 | `src/backtest/engine.py` |

### 關鍵決策：為什麼不用 market_value 做選股

實測結果：用真實市值排序 → 6M Sharpe 從 0.81 降到 0.21（-74%）。

原因：動能策略的 alpha 來自高交易量的活躍股票。用市值排序會納入「大但不活躍」的股票，稀釋動能效果。close×volume 排序是策略的正確規格，不是退而求其次。

### market_value 目前的角色

| 位置 | 用途 | 影響選股？ |
|------|------|-----------|
| `finmind.py:fetch_market_value()` | TWSE 股本 × OHLCV 收盤價計算市值 | ❌ |
| `run_backtest.py` preflight | 顯示 `[OK] MarketValue (monitoring)` | ❌ |
| `engine.py:_DataSlicer.fetch_market_value()` | 可被外部呼叫（dashboard） | ❌ |
| `tw_stock.py` / `universe.py` | **不再呼叫** | — |

### 驗證結果

| 驗證項 | 結果 |
|--------|------|
| Docker 測試 | **147 passed, 0 failed** ✅ |
| Windows 本機 | 16 passed, 13 failed（缺 scipy，非程式問題） |
| 6M 回測 | Sharpe 0.45 ✅ |
| 4Y 回測 | Sharpe 1.33, Alpha +23.28% ✅ |
| Walk-Forward | 11/11 通過，Sharpe 1.15 ✅ |
| Live/Backtest 路徑一致 | ✅ 兩者都用 close×volume |

---

## 三. 關鍵檔案位置

| 檔案 | 用途 |
|------|------|
| `config/settings.yaml` | 策略參數（唯一正式設定檔） |
| `src/portfolio/tw_stock.py` | 核心選股（close×volume 排序，~1200 行） |
| `src/backtest/engine.py` | 回測引擎 + `_DataSlicer`（point-in-time） |
| `src/backtest/universe.py` | 歷史 Universe（close×volume 排序，與 tw_stock.py 一致） |
| `src/backtest/metrics.py` | KPI（含 CVaR/Tail Ratio/JB/Bootstrap CI） |
| `src/data/finmind.py` | FinMind API + pickle cache + TWSE 市值計算 |
| `src/data/twse_scraper.py` | TWSE/TPEX 成交金額 + 股本抓取 |
| `src/strategy/regime.py` | 大盤多空判斷（ADX + SMA） |
| `scripts/run_backtest.py` | 回測 CLI（`backtest_mode=True`） |
| `scripts/walk_forward.py` | Walk-Forward + Bootstrap Sharpe CI |
| `scripts/paper_trade.py` | Paper Trading 記錄器 |
| `scripts/real_trade.py` | 小額實盤追蹤 |
| `tests/` | 147 個測試（12 個測試檔） |
| `data/cache/` | pickle 快取（.gitignore，跨電腦需整個複製） |
| `data/signals.db` | SQLite（Live/Paper Trading，跨電腦不需複製） |

---

## 四. 下一步行動清單

### 第一優先：Paper Trading

- 2026-04-14：執行第 2 筆月度再平衡
- 持續累積至 2026-10 正式評估
- 警戒線：Sharpe < 0.7 或 Alpha 轉負

### 第二優先：回測精度

| 項目 | 說明 |
|------|------|
| P4.5 Total Return Benchmark | 含配息，修正 Alpha 偏差 ~2-3%/年 |
| P4.6 Drift-aware 日報酬 | 持有期內權重隨股價更新 |

### 第三優先：Cache 同步

兩台電腦的 `data/cache/` 內容不同。要讓回測結果一致，需挑一台當主機，複製整個 `data/cache/` 到另一台。「兩台都更新到最新日期」不能解決（只補已有股票的新資料，不會補從未抓過的股票）。

### 未來研究（P8+）

| 項目 | 說明 |
|------|------|
| P8 Size Factor | 市值大小當評分因子（需經 P2 同等嚴格測試） |
| P4.10 券商對接 | Paper Trading 通過後用 CTS API 自動下單 |
| P4.11 AI 整合 | AI 只做市場風向 + 事件風控，不進選股排名 |

---

## 五. 不要做的事

- ❌ 調整 `score_weights` / `exposure` / `top_n` / `caution`（已 grid search + Codex 驗證）
- ❌ 把 `institutional_flow` 或 `quality` 拉回（已測試，績效下降）
- ❌ 把 AI 加進 ranking
- ❌ 同時改多個東西（一次改一項）
- ❌ 在 paper trading 累積 6 個月前投入實資金
- ❌ 刪除 `data/cache/`（重建需 10+ 小時 API 額度）
- ❌ **用 market_value 做選股排序**（實測 Sharpe 降 74%，動能策略不適合大市值股池）

---

## 六. 技術備註

- **Docker vs Windows**：回測/Walk-Forward/Paper Trading 在 Docker；Dashboard/real_trade 在 Windows
- **測試**：Docker 147 passed, 0 failed；Windows 16 passed / 13 failed（缺 scipy）
- **Cache 同步**：`data/cache/` 不進 git。跨電腦需**複製整個資料夾**（不是更新到最新日期）
- **pickle 版本**：另一台建的 cache 在 Windows Python 3.13 可能讀不了（`StringDtype` 錯誤），Docker 正常
- **`_DiskCache.load()`**：已改為 log-only，讀取失敗不再刪除 pkl 檔案
- **scipy**：P6 新增依賴，Docker image 需含 scipy（已重建）
- **signals.db**：Live/Paper Trading 的 SQLite，跨電腦不需複製
- **TWSE vs TPEX**：TWSE = 上市（1080 家），TPEX = 上櫃（881 家），FinMind = 兩者整合的第三方 API
- **benchmark**：目前 `price_only`，Alpha 有 ~2-3%/年高估（需 P4.5 修復）
- **Skills 路徑**：已改為相對路徑，兩台電腦都能用

---

## 七. 文件索引

| 文件 | 內容 | 最後更新 |
|------|------|---------|
| `Claude-Prompt.md` | 本檔（Claude 交接用） | 2026-04-07 |
| `Codex-Prompt.md` | Codex 驗證 Prompt（P7 + 整體架構） | 2026-04-07 |
| `優化紀錄.md` | 完整修改歷程 P0-P7 + 路線圖 + 雙視角評估 | 2026-04-07 |
| `策略研究.md` | P1-P3 因子研究結論 | 2026-04-01 |
| `教學進度.md` | 程式碼逐檔解析、觀念教學 | 2026-04-02 |
| `README.md` | 專案架構、Docker 操作 | 2026-04-07 |
| `CLAUDE.md` | Claude Code 指引 + Skills 索引 | 2026-04-07 |
