# Claude 交接 Prompt

最後更新：2026-04-08
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
- **benchmark**：`total_return`（含配息，P4.5 修正）
- **日報酬計算**：drift-aware buy-and-hold within period（P4.6 修正）

### 回測績效（2026-04-08，P4.5+P4.6 修正後 + 權息修復）

| 回測 | Sharpe | Alpha | MDD | 性質 |
|------|--------|-------|-----|------|
| 4Y（2022-2024） | 0.90 | +17.54% | -32.76% | IS+OOS |
| **Walk-Forward 平均** | **1.09** | **+45.63%** | **-26.74%** | **11 段 OOS** |
| Walk-Forward 中位數 | 1.10 | — | — | — |
| Walk-Forward Bootstrap 95% CI | [-0.13, 2.41] | — | — | ⚠️ 不顯著（CI 包含 0） |

**P4.5+P4.6 修正影響**：Sharpe 1.33→0.90（drift-aware + total return），Alpha 23%→18%（benchmark 加回配息），Benchmark 年化 5.14%，benchmark_type `price_only`→`total_return`。數字更低但更真實。

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
| **P4.5 Total Return Benchmark（配息調整）** | **✅** |
| **P4.6 Drift-aware 日報酬** | **✅** |
| Streamlit Dashboard（5 頁） | ✅ |
| 小額實盤追蹤工具 | ✅ `scripts/real_trade.py` |
| Claude Code Skills（5 commands + 1 agent） | ✅ `.claude/commands/` |

---

## 二. P4.5+P4.6 完成的工作（2026-04-08）

### P4.5 Total Return Benchmark

| 項目 | 內容 | 檔案 |
|------|------|------|
| TWSE 除息爬蟲 | `fetch_twse_dividends()` — TWT49U 端點 | `src/data/twse_scraper.py` |
| `adjust_dividends()` | scale-invariant 公式 `1 - div/close_before` | `src/backtest/metrics.py` |
| DataSource 介面 | `fetch_dividends()` 新增 | `src/data/base.py` |
| FinMind 實作 + cache | pickle cache（非 DataFrame），TTL 7 天 | `src/data/finmind.py` |
| Engine 整合 | benchmark + portfolio 都套用配息調整 | `src/backtest/engine.py` |
| look-ahead 防護 | `as_of` 過濾：`ex_date <= end_date` | `src/backtest/engine.py` |
| 測試 | 9 個測試（含 split-safe 公式測試） | `tests/test_dividends.py` |

### P4.6 Drift-aware 日報酬

| 項目 | 內容 | 檔案 |
|------|------|------|
| drift-aware 算法 | buy-and-hold within period + cash drag | `src/backtest/engine.py` |
| 測試 | 5 個 known-answer 測試 | `tests/test_drift_aware.py` |

### 發現並修復的 bug（共 6 個，分兩批）

**第一批（P4.5+P4.6 開發期間）：**
1. **split-safe 配息公式**：0050 有 1:4 分割（2025-06-18），TWSE 配息金額是原始單位。改用 `1 - div/close_before`（scale-invariant）
2. **處理順序**：oldest-to-newest（非 newest-to-oldest），避免 fixed-amount dividend 的 compounding error
3. **cache 類型**：dividend 是 `list[dict]` 不是 DataFrame，改用 `pickle.dump/load`
4. **`self._dividends` 初始化**：加在 `__init__()` 避免 AttributeError

**第二批（W2 異常調查期間，2026-04-08 code review 發現）：**
5. **「權息」過濾 bug**（P1 嚴重）：`twse_scraper.py` 第 358 行 `"息" in div_type` 會同時匹配「息」和「權息」。「權息」的 `close_before - ref_price` 含股票股利（yield 15-30%），導致嚴重過度調整。**修復**：改為 `div_type != "息"` 精確匹配，只取純現金除息。
6. **Benchmark 配息年份範圍不足**（P1 嚴重）：`engine.py` 第 351 行 `fetch_dividends(start_date.year - 1, end_date.year)` 只回溯 1 年，但 benchmark 有 3000 天（~8 年）lookback。早期 benchmark 價格沒有配息調整 → benchmark total return 被低估 → Alpha 被高估。**修復**：改用 `(start_date - timedelta(days=self._benchmark_lookback)).year` 計算起始年份。

### 驗證結果

| 驗證項 | 結果 |
|--------|------|
| 本地測試（conda quant） | **161 passed, 0 failed** ✅ |
| Docker 測試 | **31 passed** ✅ |
| 4Y 回測 | Sharpe 0.90, Alpha +17.54%, Benchmark 年化 5.14% ✅ |
| Walk-Forward | 11/11 通過，mean Sharpe 1.09, median 1.10 ✅ |
| benchmark_type | `total_return` ✅ |

### 數據可信度說明

> **背景**：P4.5+P4.6 開發過程中數字變動多次（每修一個 bug 數字就變），用戶對數據可信度有合理的懷疑。

**目前數字的可信度根據**：
1. **JSON 原始檔交叉驗證**：`reports/backtests/backtest_20220101_20241231_metrics.json` 的原始浮點數與文件中的百分比完全吻合（Sharpe `0.8977`→0.90, Alpha `0.175426`→17.54%）
2. **Docker 環境確定性**：同一台電腦、同一份 cache、同一份程式碼，重跑回測結果應 100% 一致。如果不一致就是 bug。
3. **code review 通過**：`/code-review-quant` 雙視角審查，P0（look-ahead bias）全通過，修復了 2 個 P1。

**驗證方法（用戶可自行執行）**：
```bash
# 方法 A：直接看 JSON 原始檔（最快）
cat reports/backtests/backtest_20220101_20241231_metrics.json | python -m json.tool
cat reports/walk_forward/summary.json | python -m json.tool

# 方法 B：重跑回測確認可重現（最確定）
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31 --benchmark 0050

# 方法 C：Codex 獨立驗證（最嚴格）
# 把 Codex-Prompt.md 貼給 Codex，讓它從零讀程式碼、跑回測、比對數字
```

### 數字變動歷程（供追溯）

| 時間點 | 4Y Sharpe | 4Y Alpha | 原因 |
|--------|-----------|----------|------|
| P7 修正前 | 1.33 | +23.28% | baseline（`price_only` benchmark） |
| P4.5+P4.6 首版 | 0.98 | +16.13% | drift-aware + total return（含權息 bug） |
| **P4.5 bug fix 後（當前）** | **0.90** | **+17.54%** | 修復權息過濾 + benchmark 年份範圍 |

Alpha 從 16.13% 反而上升到 17.54%，原因：benchmark 年份範圍修復後，早期 benchmark 價格正確調整配息 → benchmark 基準線改變 → Alpha 計算方式更正確。

### 已知限制

1. **「權息」現金部分被跳過**：`div_type != "息"` 精確匹配排除了「權息」記錄，其中的現金股利部分也一併跳過。影響極小（年 ~0.1-0.3%），因為「權息」事件的現金部分通常很小。
2. **Bootstrap CI 包含 0**：WF 11 段 Sharpe CI [-0.13, 2.41]，統計上不顯著。需更多 OOS 數據（Paper Trading）。

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
| `tests/` | 161 個測試（14 個測試檔） |
| `data/cache/` | pickle 快取（.gitignore，跨電腦需整個複製） |
| `data/signals.db` | SQLite（Live/Paper Trading，跨電腦不需複製） |

---

## 四. 下一步行動清單

### 第一優先：Paper Trading

- 2026-04-14：執行第 2 筆月度再平衡
- 持續累積至 2026-10 正式評估
- 警戒線：Sharpe < 0.7 或 Alpha 轉負

### 第二優先：WF W2 異常（已調查完成，2026-04-08）

W2（2021H1）Alpha 428% — **非程式 bug**。原因：drift-aware 在 2021-H1 強趨勢市場（台股大牛市）放大集中持股漲幅，半年年化報酬 444%。調查過程中發現並修復了兩個真正的 bug（見上方「第二批」bug #5、#6）。

### 第三優先：Cache 管理（重要）

**背景**：用戶有兩台電腦，cache 已經同步過。

**Cache 分歧風險**：
- `paper_trade.py` / `main.py` 會觸發 FinMind API → 更新 cache
- `run_backtest.py`（`backtest_mode=True`）**不會**更新 cache
- 如果兩台都跑 Paper Trading / Live，cache 會各自增長 → 分歧

**建議做法**：
- 指定一台為「cache 主機」，只在該台跑 Paper Trading / Live
- 另一台只跑回測（`backtest_mode=True`，不打 API）+ Dashboard
- 定期從主機複製 `data/cache/` 到另一台

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
- **測試**：conda quant 161 passed, 0 failed；Docker 也全通過
- **Cache 同步**：`data/cache/` 不進 git。跨電腦需**複製整個資料夾**。用戶已完成同步，但注意 Paper Trading/Live 會更新 cache 造成分歧（見第四節 Cache 管理）
- **pickle 版本**：另一台建的 cache 在 Windows Python 3.13 可能讀不了（`StringDtype` 錯誤），Docker 正常
- **`_DiskCache.load()`**：已改為 log-only，讀取失敗不再刪除 pkl 檔案
- **scipy**：P6 新增依賴，Docker image 需含 scipy（已重建）
- **signals.db**：Live/Paper Trading 的 SQLite，跨電腦不需複製
- **TWSE vs TPEX**：TWSE = 上市（1080 家），TPEX = 上櫃（881 家），FinMind = 兩者整合的第三方 API
- **benchmark**：`total_return`（P4.5 已修復，含配息調整），Benchmark 0050 年化 5.14%
- **Skills 路徑**：已改為相對路徑，兩台電腦都能用

---

## 七. 文件索引

| 文件 | 內容 | 最後更新 |
|------|------|---------|
| `Claude-Prompt.md` | 本檔（Claude 交接用） | 2026-04-08 |
| `Codex-Prompt.md` | Codex 驗證 Prompt（P4.5+P4.6 配息 + drift-aware + 權息修復） | 2026-04-08 |
| `優化紀錄.md` | 完整修改歷程 P0-P7 + 路線圖 + 雙視角評估 | 2026-04-08 |
| `策略研究.md` | P1-P3 因子研究結論 | 2026-04-01 |
| `教學進度.md` | 程式碼逐檔解析、觀念教學 | 2026-04-02 |
| `README.md` | 專案架構、Docker 操作 | 2026-04-07 |
| `CLAUDE.md` | Claude Code 指引 + Skills 索引 | 2026-04-08 |
