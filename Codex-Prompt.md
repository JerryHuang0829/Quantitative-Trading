# Codex 獨立驗證 Prompt — 全架構 + P7 + P4.5/P4.6 + 資料完整性

最後更新：2026-04-08
用途：對整個專案做完整的獨立驗證。涵蓋架構、選股邏輯、回測引擎、資料層、TWSE fallback、配息調整、drift-aware。

**⚠️ 重要：請完全獨立驗證，不要依賴 Claude 的任何結論或數字。你需要自己讀程式碼、自己算數學、自己跑測試、自己判斷。Claude 可能犯錯、可能遺漏、可能自圓其說。你的工作是找到 Claude 沒發現的問題。**

---

## 一、專案概述

台股 long-only 量化投組系統。月中再平衡，三因子橫截面排名選股：
- `price_momentum`（55%）、`revenue_momentum`（25%）、`trend_quality`（20%）
- `top_n=8`、`max_same_industry=3`、`caution=0.70`
- 已停用：`institutional_flow=0%`、`quality=0%`
- 候選股池：close×volume（20 日均值）排序取前 80 名
- benchmark：`total_return`（含配息，P4.5）
- 日報酬：drift-aware buy-and-hold within period（P4.6）

---

## 二、完整架構驗證

### 2.1 選股池一致性（P7 核心）

**Live 路徑**（`tw_stock.py:build_tw_stock_universe`）和**回測路徑**（`universe.py:get_universe_at`）必須用相同排序：

驗證：
1. `tw_stock.py` 是否只呼叫 `_prepare_auto_universe_by_size_proxy()`？不呼叫 `fetch_market_value()`？
2. `_prepare_auto_universe()` 函式是否已刪除？（P7.13）
3. `universe.py` 是否只用 close×volume 排序？不用 market_value 或 TWSE turnover？
4. 兩條路徑在相同資料下是否選出相同候選股？

### 2.2 Point-in-time 完整性

1. `_DataSlicer`（engine.py）是否正確截斷所有資料到 `as_of` 日期？
2. `fetch_ohlcv()` / `fetch_institutional()` / `fetch_month_revenue()` 都有 `_truncate_by_date_col()` 嗎？
3. Revenue 有 35 天 lag 保護嗎？（tw_stock.py `_monthly_revenue_momentum()`）
4. 除息資料的 look-ahead 防護：`ex_date <= end_date` cutoff（engine.py）

### 2.3 因子跳過邏輯

1. `institutional_flow` weight=0 → 完全不打 API？（tw_stock.py）
2. `quality` weight=0 → 完全不打 API？
3. `revenue_momentum` weight=0 → 也跳過？（P7.14 新增 `rm_weight > 0` guard）
4. 確認 `_rank_analyses()` 中 weight <= 0 因子不參與排名

### 2.4 交易成本模型

1. `turnover` 是 one-way（engine.py）
2. `round_trip_cost` = 0.0047（手續費×2 + 證交稅）
3. `slippage_bps` 從 yaml 讀取（預設 10）
4. `slippage_cost = turnover * 2 * (slippage_bps / 10000)`

### 2.5 Stock Split 處理

1. `adjust_splits()`（metrics.py）：-40% 門檻、+100% 門檻
2. 不會誤判台股 ±10% 漲跌停
3. 處理順序：newest-to-oldest

### 2.6 Market Regime

1. `detect_regime()`（regime.py）：ADX + SMA 判斷 risk_on/caution/risk_off
2. 對應曝險：96%/70%/35%

---

## 三、P4.5 配息調整驗證

### 3.1 TWSE 除息爬蟲（`twse_scraper.py`：`fetch_twse_dividends()`）

1. TWT49U 端點：正確解析「息」vs「權」？
2. `div_type != "息"` 精確匹配 — 排除「權息」（P4.5 bug fix #5）
3. `cash_dividend = close_before - ref_price`
4. ROC 日期解析 `_parse_roc_date()` 是否 robust？

### 3.2 配息調整公式（`metrics.py`：`adjust_dividends()`）

1. Scale-invariant：`factor = 1 - cash_div / close_before`
2. Fallback：`factor = price_on_ex / (price_on_ex + cash_div)`
3. 處理順序：oldest-to-newest（配息是固定金額，非比率）
4. Guard conditions：empty、no match、ex_date not in index、factor 範圍
5. 0050 的 1:4 split + 配息是否正確處理？

### 3.3 Cache 層（`finmind.py`：`fetch_dividends()`）

1. 用 `pickle.dump/load`（不是 `_DiskCache`），因為 `list[dict]` 不是 DataFrame
2. TTL 7 天
3. `backtest_mode=True` → 直接回傳 cache

### 3.4 引擎整合（`engine.py`）

1. look-ahead 防護：`ex_date <= end_date`
2. 順序：先 `adjust_splits` 再 `adjust_dividends`
3. `benchmark_type` 從 `price_only` 覆蓋為 `total_return`
4. Benchmark 配息年份範圍涵蓋 3000 天 lookback（P4.5 bug fix #6）

---

## 四、P4.6 Drift-aware 日報酬驗證

### 4.1 數學公式（`engine.py`：`_compute_daily_returns()`）

1. `values = w.copy()` → 初始 dollar value = 目標權重
2. `cash = 1.0 - w_sum` → 未投資部位
3. 每日：`values = values * (1.0 + day_rets)`
4. 日報酬：`port_ret = (values.sum() + cash) / total_before - 1.0`

### 4.2 手算驗證

2 支股票各 50%，持有 2 天：A +10%/-5%，B -3%/+8%
- Day 1：drift = fixed = 3.5%
- Day 2：drift = 1.09%，fixed = 1.5%（差異 0.41%）
- **請自行驗算。**

---

## 五、P7 選股池正式化 + 資料完整性

### 5.1 選股池（P7.1-P7.15）

1. `_prepare_auto_universe()` 已刪除（P7.13）
2. `preload_reference_data()` 已改為 `pass`（P7.15）
3. `_DiskCache.load()` 改為 log-only 不刪檔（P7.10）
4. `revenue_momentum` weight=0 時跳過 API（P7.14）
5. Live/Backtest 都用 close×volume（P7.9 統一）

### 5.2 TWSE 資料來源（P7.16-P7.22）

| 函式 | 端點 | 驗證 |
|------|------|------|
| `fetch_twse_daily_all(as_of)` | STOCK_DAY_ALL + TPEX OpenAPI | 回傳 > 2,500 支？含 close/volume/turnover？ |
| `fetch_twse_stock_day(symbol, year, month)` | TWSE STOCK_DAY | OHLCV 格式正確？ROC 日期解析？ |
| `fetch_twse_monthly_revenue()` | TWSE t187ap05_L + TPEX mopsfin_t187ap05_O | > 1,900 家？單位千元→TWD？ |
| `fetch_twse_issued_capital()` | TWSE t187ap03_L + TPEX mopsfin_t187ap03_O | > 1,900 家？TWSE 中文 + TPEX 英文欄位？ |

### 5.3 Fallback 整合（`finmind.py`）

1. **OHLCV fallback**：`fetch_ohlcv()` → FinMind 失敗 → `_fetch_ohlcv_from_twse()` → 逐月補
   - 只在 `not backtest_mode` 時觸發
   - **不存 disk cache**（只回傳當次使用）— 避免混入非 FinMind 資料影響回測
   - DataFrame 格式與 FinMind 一致（UTC index）
2. **Revenue fallback**：`fetch_month_revenue()` → FinMind 失敗 → `_fetch_revenue_from_twse()`
   - **不存 disk cache**（只回傳，不 persist）— 避免 1 個月陷阱
   - sentinel（空 DataFrame）也不存 — 讓下次重試 FinMind
3. **market_value**：TWSE 計算（監控用，不影響選股）

### 5.4 Cache 品質控制

1. **`cache_fill.py --refresh-all`**：
   - OHLCV：檢查 max_date > stale_cutoff 才記 done（不被 API 失敗欺騙）
   - Revenue：需 >= 12 個月才記 done（不被 TWSE 1 個月 fallback 欺騙）
   - 20 次連續失敗自動停止
   - 進度可中斷恢復
2. **`cache_health.py`**：
   - 用 OHLCV cache 20 日均值排名（與策略一致）
   - 不用 TWSE daily_all（避免假警報）

---

## 六、測試覆蓋驗證

| 測試檔 | 數量 | 覆蓋 |
|--------|------|------|
| test_metrics.py | 27 | Sharpe/MDD/Alpha/CVaR/Tail Ratio + known-answer + split adjust |
| test_engine_integration.py | 17 | 端到端回測（FakeSource） |
| test_finmind.py | 17 | DiskCache + CSV fallback + stock_info |
| test_data_slicer.py | 15 | point-in-time 截斷 |
| test_rebalance_dates.py | 14 | 月曆 + 交易日對齊 |
| test_selection.py | 12 | 選股門檻 + hold buffer + 產業限制 |
| test_p7_universe.py | 12 | TWSE 解析 + 市值計算 + size proxy 路徑 |
| test_ranking.py | 10 | 因子排名 + 百分位 |
| test_vol_weighting.py | 9 | 波動率加權 |
| test_dividends.py | 9 | 配息調整 + split-safe + TWSE 日期 |
| test_zero_weight_skip.py | 8 | weight=0 跳過邏輯 |
| test_drift_aware.py | 5 | drift-aware known-answer |
| test_degradation.py | 4 | data_degraded 判定 |
| test_universe.py | 2 | stock_id 缺失 edge case |
| **合計** | **161** | |

**缺失的測試**（Codex 應指出）：
- `fetch_twse_daily_all()` 無測試
- `fetch_twse_stock_day()` 無測試
- `fetch_twse_monthly_revenue()` 無測試
- `_fetch_ohlcv_from_twse()` 無測試
- `cache_fill.py` 的 stale 檢測邏輯無測試
- `cache_health.py` 無測試

---

## 七、執行驗證步驟

```bash
# 1. 全部測試（Docker）
docker compose build portfolio-bot
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v
# 預期：161 passed, 0 failed

# 2. 選股池驗證
docker compose run --rm --entrypoint python portfolio-bot -c "
import inspect
from src.portfolio.tw_stock import build_tw_stock_universe
source = inspect.getsource(build_tw_stock_universe)
assert 'fetch_market_value' not in source, 'Still calls fetch_market_value!'
assert '_prepare_auto_universe_by_size_proxy' in source
from src.portfolio import tw_stock
assert not hasattr(tw_stock, '_prepare_auto_universe'), 'Dead code still exists!'
print('PASS: Universe uses size proxy only')
"

# 3. TWSE fallback 驗證
docker compose run --rm --entrypoint python portfolio-bot -c "
from src.data.twse_scraper import fetch_twse_daily_all, fetch_twse_monthly_revenue
from datetime import datetime
daily = fetch_twse_daily_all(datetime.now())
assert len(daily) > 2500, f'Expected >2500, got {len(daily)}'
tsmc = daily.get('2330', {})
assert tsmc.get('close', 0) > 0, 'TSMC close missing!'
print(f'PASS: daily_all = {len(daily)} stocks')

rev = fetch_twse_monthly_revenue()
assert len(rev) > 1900, f'Expected >1900, got {len(rev)}'
print(f'PASS: monthly_revenue = {len(rev)} companies')
"

# 4. Revenue fallback 不存 disk 驗證
docker compose run --rm --entrypoint python portfolio-bot -c "
import inspect
from src.data.finmind import FinMindSource
src = inspect.getsource(FinMindSource.fetch_month_revenue)
# TWSE fallback 不應該有 disk.save
assert 'return twse_result  # 回傳但不存 disk' in src or 'return twse_result  # Return for this session only' in src, \
    'TWSE revenue fallback might be saving to disk!'
print('PASS: TWSE revenue fallback does not persist to disk')
"

# 5. _DiskCache 不刪檔驗證
docker compose run --rm --entrypoint python portfolio-bot -c "
import inspect
from src.data.finmind import _DiskCache
src = inspect.getsource(_DiskCache.load)
assert 'unlink' not in src, '_DiskCache.load still deletes files!'
assert 'warning' in src.lower() or 'Warning' in src, 'Should log warning on failure'
print('PASS: _DiskCache.load is log-only, no file deletion')
"

# 6. cache_health 報告
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_health.py

# 7. Drift-aware 手算驗證
docker compose run --rm --entrypoint python portfolio-bot -c "
import pandas as pd
dates = pd.bdate_range('2024-01-02', periods=2, tz='UTC')
ret_df = pd.DataFrame({'A': [0.10, -0.05], 'B': [-0.03, 0.08]}, index=dates)
w = pd.Series({'A': 0.5, 'B': 0.5})
values = w.copy().astype(float)
cash = 0.0
d1_before = values.sum() + cash
values = values * (1.0 + ret_df.iloc[0])
d1 = (values.sum() + cash) / d1_before - 1.0
d2_before = values.sum() + cash
values = values * (1.0 + ret_df.iloc[1])
d2 = (values.sum() + cash) / d2_before - 1.0
assert abs(d1 - 0.035) < 1e-10, f'Day1 wrong: {d1}'
assert abs(d2 - 0.0109) < 0.001, f'Day2 wrong: {d2}'
print(f'PASS: drift Day1={d1:.4f}, Day2={d2:.4f}')
"

# 8. 4Y 回測（比對數字）
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31 --benchmark 0050
# Claude 聲稱：Sharpe 0.90, Alpha +17.54%

# 9. Walk-Forward
docker compose run --rm --entrypoint python portfolio-bot scripts/walk_forward.py \
    --train-months 18 --test-months 6 --start 2019-01-01 --end 2025-12-31
# Claude 聲稱：mean Sharpe 1.09, median 1.10
```

---

## 八、判斷標準

| 項目 | PASS 條件 |
|------|----------|
| Docker 測試 | 161 passed, 0 failed |
| 選股池 | tw_stock.py + universe.py 都用 close×volume，不用 market_value |
| `_prepare_auto_universe` | 已刪除，不存在 |
| `_DiskCache.load()` | 不刪檔，只 log warning |
| TWSE daily_all | > 2,500 支，含 close/volume |
| TWSE monthly_revenue | > 1,900 家 |
| Revenue fallback 不存 disk | TWSE 結果不 persist |
| Drift-aware 數學 | 手算一致 |
| Scale-invariant 公式 | close_before 路徑正確 |
| look-ahead | 除息資料不在 price index 外生效 |
| benchmark_type | `total_return` |
| cache_fill OHLCV | 只有真正更新的才記 done |
| cache_fill Revenue | >= 12 個月才記 done |
| 4Y Sharpe | ~0.8-1.0（cache 差異允許 ±0.1） |
| WF mean Sharpe | > 0 |

---

## 九、Claude 聲稱的 KPI（請自行驗證）

| 指標 | P7（price_only） | P4.5+P4.6（total_return） | 你跑出來的 |
|------|------------------|--------------------------|-----------|
| 4Y Sharpe | 1.33 | 0.90 | ？ |
| 4Y Alpha | +23.28% | +17.54% | ？ |
| 4Y MDD | -31.09% | -32.76% | ？ |
| Benchmark 年化 | ~1% | 5.14% | ？ |
| WF mean Sharpe | 1.15 | 1.09 | ？ |
| benchmark_type | price_only | total_return | ？ |

---

## 十、重要提醒

- **不要修改任何原始碼** — 這是驗證任務
- **不要修改策略參數** — `score_weights`/`exposure`/`top_n` 已 grid search 驗證
- **不要相信 Claude 的行號** — 自己搜尋函式名
- **不要相信 Claude 的數字** — 自己跑回測比對
- 如果發現問題，明確指出：檔案、函式名、問題描述、嚴重度（P0/P1/P2/P3）
- 特別注意：
  1. Revenue fallback 是否真的不存 disk？有沒有漏洞？
  2. cache_fill stale 檢測是否可靠？
  3. Live 和 Backtest 選股池是否真的一致？
  4. 「權息」過濾是否足夠嚴格？
