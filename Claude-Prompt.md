# Claude 交接 Prompt

更新日期：2026-04-02  
用途：這份檔只保留 **Codex 已獨立驗證的事項**、**尚未完全獨立驗證的界線**，以及 **Claude 下一輪應優先處理的事**。

請先讀：
- `Quantitative-Trading/Codex-Prompt.md`
- `Quantitative-Trading/優化建議.md`
- `Quantitative-Trading/優化紀錄.md`
- `Quantitative-Trading/策略研究.md`

但請注意：
**不要只看 md，請以目前程式碼、tests、設定檔、artifact 為準。**  
如果 md 與程式或 artifact 衝突，請以程式與 artifact 為準，並同步修正文檔。

## 1. Codex 已驗證

### Walk-forward 結果
- `reports/walk_forward/summary.json` 已由 Codex 獨立驗算：
  - `windows = 11`
  - `mean_sharpe = 1.3835`
  - `median_sharpe = 1.2709`
  - `win_rate = 0.7273`
  - 全部 window：
    - `data_degraded = false`
    - `degraded_periods = 0`
- `reports/walk_forward/summary_old_backup.json` 已驗證：
  - `mean_sharpe = 1.2169`
  - 全部 `data_degraded = true`
  - 沒有 `degraded_periods` 欄位

### P4.9 degraded 修復
- `src/backtest/engine.py` 目前只會對 `weight > 0` 的因子做 coverage degraded 檢查
- `config/settings.yaml` 目前：
  - `institutional_flow: 0.00`
- 因此 P4.9 的 false alarm 修復可視為已落地

### zero-weight skip
- `src/portfolio/tw_stock.py` 已確認：
  - `institutional_flow` 權重為 0 時，不會呼叫 `fetch_institutional()`
  - `quality` 權重為 0 時，不會呼叫 `fetch_financial_quality()`
- 對應測試存在於：
  - `tests/test_zero_weight_skip.py`

### finmind.py DataFrame fallback bug fix
- `src/data/finmind.py` 已確認不再使用 `cached or fallback()`
- 現在改為：
  - `cached if (cached is not None and not cached.empty) else fallback`
- CSV fallback 相關函式也已存在：
  - `_load_stock_info_csv_fallback()`
  - `_save_stock_info_csv_snapshot()`
  - `_ensure_stock_info_csv()`

### 架構與檔案存在性
- `tests/` 目前共有 **135 個測試函式**
- `config/settings.yaml` 中 `backtest` 常數已存在
- `TECH_SUPPLY_CHAIN_KEYWORDS` 已抽到 `src/utils/constants.py`
- `src/backtest/engine.py` 與 `scripts/paper_trade.py` 都有共用該常數
- `data/cache/stock_info/stock_info_snapshot.csv` 實際存在
- core modules、scripts、dashboard 頁面 `py_compile` 通過

## 2. Codex 尚未完全獨立驗證

### 全套 pytest
- Codex 已確認：
  - repo 內確實有 `135` 個測試函式
  - `tests/test_metrics.py` 本機可跑通：`27 passed, 1 warning`
- 但 Codex **沒有在本機完整重跑成功整包 pytest**
- 因此文件中請不要寫成：
  - 「Codex 已完整驗證 135 passed」
- 正確寫法應是：
  - Claude 已跑通全套
  - Codex 已獨立確認測試數量、部分測試可跑、核心模組語法正常
  - 但 Codex 未在本機完整重跑整包 pytest

## 3. 仍存在的限制與殘餘風險

### benchmark 仍是 price-only
- `src/backtest/metrics.py` 目前仍會輸出：
  - `benchmark_type = "price_only"`
- 所以目前所有 alpha、IR、超額報酬解讀仍有口徑限制
- 請不要把目前 walk-forward alpha 寫成完全乾淨的最終結論

### institutional_flow coverage 語意仍不乾淨
- `src/backtest/engine.py` 目前仍用：
  - `institutional_raw != 0`
  近似 coverage
- 這會把：
  - 真實零流量
  - 無資料
  混在一起
- 目前因 IF 權重為 0，不會再誤觸 degraded
- 但語意層仍未完全修乾淨

## 4. Claude 下一輪應執行的任務

### 任務一：IF coverage missing-aware 修正（30 分鐘，低風險）

**目標**：讓 `institutional_raw` 停用時為 `None` 而非 `0.0`，消除「零流量 vs 無資料」的語意混淆。

**改動清單**：

| 檔案 | 行號 | 改什麼 |
|------|------|--------|
| `src/portfolio/tw_stock.py` | 651-656, 728 | `institutional_raw` 預設改 `None`；`institutional_detail` 改從局部變數讀取 |
| `src/backtest/engine.py` | 469 | coverage 判斷從 `!= 0` 改為 `is not None`（與 revenue_momentum 一致） |
| `tests/test_zero_weight_skip.py` | 138 | `assert == 0` → `assert is None` |
| `tests/conftest.py` | 52 | `make_analysis` 預設 `inst=0.0` → `inst=None` |

**不需要改的（已確認安全）**：
- `_rank_analyses`：IF weight=0 → `if weight <= 0: continue` 跳過整個因子
- `factor_detail` snapshot：`None` → JSON `null`，正常
- `test_ranking.py`：有明確傳 `inst=100` 的測試，不受預設值影響
- `test_engine_integration.py`：FakeSource 不設 institutional_raw

**模式參考**：跟 `quality_raw`（tw_stock.py 行 660）完全一樣。

**驗證**：`pytest tests/ -v` → 135 passed

### 任務二：Total Return Benchmark / P4.5（1-2 天，中風險）

**目標**：用 TWSE 除權息資料讓 benchmark 從 price-only 升級為含配息的 total return，使 Alpha 精確。

**架構**：
```
TWSE 除權息 API ──→ twse_scraper.py（新函式）
                         ↓
                    finmind.py（快取 + 呼叫）
                         ↓
                    engine.py（benchmark 流程注入配息）
                         ↓
                    metrics.py（benchmark_type 參數化）
```

**步驟**：

**Step 1：`src/data/twse_scraper.py`** — 新增 `fetch_twse_dividends(symbol, start_date, end_date)`
- TWSE 端點：`https://www.twse.com.tw/rwd/zh/exRight/TWT49U`
- 參數：`stockNo=0050`, `startDate`, `endDate`（YYYYMMDD）
- 回傳：`pd.DataFrame[ex_date, cash_dividend]`
- 沿用現有 scraper 的 retry / error handling 模式
- 資料量極小（0050 約每年除息 1-2 次，10 年 ~20 筆）

**Step 2：`src/data/finmind.py`** — 新增 `fetch_benchmark_dividends(symbol, start_date, end_date)`
- 用 `_DiskCache` 快取（`dividends/0050.pkl`）
- 沿用 OHLCV 的 append-only 快取模式

**Step 3：`src/backtest/metrics.py`** — 新增 `apply_dividend_reinvestment(price_returns, dividends_df, close_series)`
- 除息日 total return = price return + (cash_dividend / 前一日收盤價)
- `compute_metrics()` 新增 `benchmark_type` 參數（預設 `"price_only"`），取代硬編碼

**Step 4：`src/backtest/engine.py`** — benchmark 流程注入（行 329-334 之後）
- try/except：成功 → `benchmark_type = "total_return"`；失敗 → fallback 到 price-only

**Step 5：測試**
- 新增 `tests/test_total_return_benchmark.py`：已知答案、mock HTTP、fallback 測試
- 修改 `tests/test_engine_integration.py`：FakeSource 加 `fetch_benchmark_dividends()` 回傳空 DataFrame

**風險控制**：TWSE API 不穩定 → try/except + fallback，不影響回測主流程

### 執行順序

1. 任務一（IF coverage）→ 跑測試確認 135 passed
2. 任務二 Step 1-2（scraper + cache）
3. 任務二 Step 3（metrics 函式）
4. 任務二 Step 4（engine 接線）
5. 任務二 Step 5（測試）
6. 全套 pytest 回歸
7. 重跑 Dashboard 6M 確認 `benchmark_type` 從 `price_only` → `total_return`
8. 更新 MD 文件 + 生成 Codex 驗證 Prompt

### 驗證方式

```bash
# 每步完成後
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v

# 任務二完成後，重跑 Dashboard 6M
docker compose run --rm --entrypoint python portfolio-bot scripts/run_backtest.py \
    --start 2024-06-01 --end 2024-12-31 --output-dir reports/backtests/dashboard_6m

# 確認 benchmark_type 變化
python -c "import json; m=json.load(open('reports/backtests/dashboard_6m/backtest_20240601_20241231_metrics.json')); print(m['benchmark_type'])"
```

## 5. 目前不要做的事

- 改策略參數
- 改 exposure
- 改 AI 導入方向
- 改 ranking 主因子
- 擴寫新的研究分支

## 6. 回覆格式

請用以下格式回覆：

1. Findings
2. Changes made
3. Validation
4. Residual risks
5. Next actions
