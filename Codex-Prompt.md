# Codex 獨立驗證 Prompt — P4.5 Total Return Benchmark + P4.6 Drift-aware 日報酬

最後更新：2026-04-08
用途：驗證 P4.5+P4.6 修改的正確性 + 數學邏輯 + 資料流完整性。

**⚠️ 重要：請完全獨立驗證，不要依賴 Claude 的任何結論或數字。你需要自己讀程式碼、自己算數學、自己跑測試、自己判斷。Claude 可能犯錯、可能遺漏、可能自圓其說。你的工作是找到 Claude 沒發現的問題。**

---

## 一、專案概述（請自行讀 CLAUDE.md 和 README.md 確認）

台股 long-only 量化投組系統。月中再平衡，三因子橫截面排名選股：
- `price_momentum`（55%）
- `revenue_momentum`（25%）
- `trend_quality`（20%）

核心設定：`top_n=8`、`max_same_industry=3`、`caution=0.70`
已停用因子：`institutional_flow=0%`、`quality=0%`
候選股池：以成交金額（close×volume）排序取前 80 名

---

## 二、P4.5+P4.6 修改範圍（2026-04-08）

### Claude 聲稱的修改摘要

| 項目 | Claude 說的 | 你需要驗證的 |
|------|-----------|------------|
| P4.6 Drift-aware | 日報酬從固定權重改為 buy-and-hold within period | 數學公式是否正確？cash 部位處理是否正確？ |
| P4.5 除息爬蟲 | TWSE TWT49U 端點，年度查詢 | 是否正確解析「息」vs「權」？日期格式？ |
| P4.5 配息調整 | scale-invariant 公式 `1 - div/close_before` | 數學推導是否正確？處理順序是否正確？ |
| P4.5 Cache | pickle 格式，TTL 7 天 | 為什麼不用 `_DiskCache`？是否有 race condition？ |
| P4.5 look-ahead | `as_of` 過濾 `ex_date <= end_date` | 是否真的防住了？有沒有其他洩漏路徑？ |
| benchmark_type | `price_only` → `total_return` | 哪裡設定的？會不會被其他地方覆蓋？ |

---

## 三、逐項驗證清單

### 3.1 P4.6 Drift-aware 日報酬（`engine.py` lines 716-731）

**請自己讀 `src/backtest/engine.py` 的 `_compute_daily_returns()` 方法。**

驗證重點：

1. **數學正確性**：
   - `values = w.copy()` — 初始 dollar value = 目標權重
   - `cash = 1.0 - w_sum` — 未投資部位
   - 每日更新：`values = values * (1.0 + day_rets)`
   - 日報酬：`port_ret = (values.sum() + cash) / total_before - 1.0`
   - **自行推導**：用 2 支股票、3 天的簡單例子手算，確認公式正確
   - **邊界條件**：`w_sum = 1.0` 時 `cash = 0`，是否行為正確？`w_sum < 1.0`（caution 模式）呢？

2. **NaN 處理**：
   - `fillna(0.0)` — 停牌股當日報酬視為 0%
   - 這是否合理？停牌期間價值不變，但復牌後可能跳空

3. **與舊邏輯的差異**：
   - 舊：每天用固定 `w` 乘 `daily_ret`，等於「每日收盤隱含再平衡」
   - 新：dollar value 隨股價漂移，贏家權重增加
   - **Claude 聲稱 4Y 年化報酬從 53.6% 降到 25.3%**。這個降幅合理嗎？一般 drift vs fixed 差異不會這麼大。但台股月度再平衡（~20 交易日），如果動能策略持股波動大，差異可能放大。**請自行判斷**。

4. **測試**（`tests/test_drift_aware.py`，5 個測試）：
   - 自行讀測試，確認 known-answer 是手算的正確值
   - 特別注意 `test_drift_diverges_from_fixed_weight` — 漲跌不對稱的情況

### 3.2 P4.5 TWSE 除息爬蟲（`twse_scraper.py` lines 287-398）

**請自己讀 `src/data/twse_scraper.py` 的 `fetch_twse_dividends()` 函式。**

驗證重點：

1. **TWSE TWT49U 端點**：
   - URL：`https://www.twse.com.tw/rwd/zh/exRight/TWT49U`
   - 參數：`startDate`、`endDate`（格式 YYYYMMDD，西元年不是民國年）
   - 回傳 JSON：`data` 陣列，每列代表一個除權息事件

2. **「息」vs「權」過濾**（line 353）：
   - `if "息" not in div_type: continue`
   - 「息」= 現金股利（cash dividend）
   - 「權」= 股票股利（stock dividend），由 `adjust_splits()` 處理
   - **「權息」**（同時有現金+股票股利）：`"息" in "權息"` = True，會被納入
   - **Claude 承認的已知限制**：「權息」的 `close_before - ref_price` 含股票股利分量，會高估 cash_dividend
   - **你自己判斷**：這個限制有多嚴重？是否可能觸發 `adjust_splits` 的 -40% 門檻？

3. **ROC 日期解析**（`_parse_roc_date()`）：
   - `"112年07月18日"` → `"2023-07-18"`
   - 驗證：regex 是否 robust？非標準格式（如缺少「年月日」字元）是否安全 fail？

4. **cash_dividend 計算**（line 369）：
   - `cash_dividend = round(close_before - ref_price, 6)`
   - 這不是 TWSE 直接提供的配息金額，而是「收盤價 - 參考價」的差值
   - **問題**：如果是「權息」，這個差值包含股票股利的價值。這是 Claude 承認的限制。

### 3.3 P4.5 配息調整公式（`metrics.py` lines 84-172）

**請自己讀 `src/backtest/metrics.py` 的 `adjust_dividends()` 函式。**

驗證重點：

1. **Scale-invariant 公式**：
   - 有 `close_before` 時：`factor = 1 - cash_div / close_before`
   - 沒有時（fallback）：`factor = price_on_ex / (price_on_ex + cash_div)`
   - **數學等價性**：`1 - div/P = (P - div)/P = ref_price/close_before`。TWSE 提供 `close_before` 和 `ref_price`。兩者是否一致？
   - **為什麼需要 scale-invariant**：0050 有 1:4 分割（2025-06-18）。分割後 prices 除以 4，但 TWSE 配息金額仍是原始單位。`$3.20 / $35.97 = 8.9%` vs `$3.20 / $143.88 = 2.2%`。**自行確認 0050 的分割日期和比率**。

2. **處理順序**（line 130）：
   - `reverse=False` → oldest-to-newest
   - 為什麼不是 newest-to-oldest（跟 `adjust_splits` 一樣）？
   - **Claude 的解釋**：配息是固定金額（$3.20），不是比率。如果先處理最新的，早期 ex-date 的 `price_on_ex`（fallback 路徑）會被之前的調整縮小，導致 factor 偏離。
   - **但是**：有 `close_before` 時，TWSE 提供的是原始值，不受前次調整影響。那 oldest-to-newest 有差嗎？**自行推導：當所有 dividends 都有 `close_before` 時，處理順序是否無關？**

3. **Guard conditions**（lines 112, 120, 146-147, 163）：
   - empty dividends → return copy
   - no matching symbol → return copy
   - ex_date not in index → skip
   - loc == 0（ex-date 是第一天）→ skip
   - factor <= 0 or >= 1 → skip
   - **自行確認**：有沒有遺漏的 edge case？

4. **測試**（`tests/test_dividends.py`，9 個測試）：
   - 自行讀測試，特別注意：
   - `test_close_before_split_safe_formula` — 模擬 1:4 split 情境
   - `test_splits_then_dividends_compose` — 先 split 再 dividend 是否正確疊加
   - `test_multiple_dividends_same_stock` — 同一年兩次配息

### 3.4 P4.5 Cache 層（`finmind.py` lines 784-829）

**請自己讀 `src/data/finmind.py` 的 `fetch_dividends()` 方法。**

驗證重點：

1. **為什麼用 `pickle.dump/load` 而不是 `_DiskCache`**：
   - `_DiskCache.save()` 呼叫 `df.to_pickle()`，但 dividends 是 `list[dict]` 不是 DataFrame
   - 直接用 `_pkl.dump/load` 是合理的 workaround
   - **但是**：`_DiskCache` 的 meta 管理（TTL 檢查）仍然可用嗎？確認 `self._disk.meta("dividends")` 和 `self._disk.save_meta()` 是否正常運作

2. **backtest_mode**（line 806）：
   - `backtest_mode=True` 且 cache 存在 → 直接回傳，不查 TTL，不打 API
   - 這跟其他 dataset 的 backtest_mode 行為一致嗎？

3. **TTL = 7 天**（line 811）：
   - 除息日程變動不頻繁，7 天合理
   - **但是**：`datetime.now()` 沒有指定時區。跟 `_DiskCache` 的其他 TTL 邏輯一致嗎？

### 3.5 P4.5 引擎整合（`engine.py` lines 351-373）

**請自己讀 `src/backtest/engine.py` 的 `run()` 方法中的除息整合區塊。**

驗證重點：

1. **look-ahead 防護**（lines 358-361）：
   - `cutoff = end_date.strftime("%Y-%m-%d")`
   - `self._dividends = [d for d in self._dividends if d["ex_date"] <= cutoff]`
   - **問題**：這是回測期間的 `end_date`，不是每個月的 `as_of`。在月度 replay 中，第 1 個月能看到最後一個月的除息資料嗎？
   - **Claude 的立場**：除息日期和金額是事後已知的公開資訊，不構成 look-ahead bias。因為 `adjust_dividends()` 只用 `ex_date` 在 price index 內的記錄，而 `_DataSlicer` 已截斷 price。
   - **你自己判斷**：如果 stock A 在 2024-12 除息 $5，但回測 period 是 2024-06，`adjust_dividends()` 會不會用到這筆資料？（提示：price index 在 2024-06 結束，所以 2024-12 的 ex_date 不在 index 中，會被 skip）

2. **Benchmark 配息調整**（lines 370-372）：
   - `adjusted_close = adjust_splits(bench_df["close"])`
   - `if self._dividends: adjusted_close = adjust_dividends(...)`
   - 順序：先 split 再 dividend。**是否正確**？`adjust_dividends` 的 `close_before` 是 TWSE 原始值（未 split-adjusted）。在 split-adjusted 的 series 上用原始 `close_before` 計算 factor，數學上是否等價？

3. **Portfolio 個股配息調整**（lines 678-680，在 `_compute_daily_returns()` 內）：
   - 每個持倉期的 close series 都做 `adjust_splits` + `adjust_dividends`
   - **跟 benchmark 同邏輯**。確認 `self._dividends` 在 `__init__()` 有初始化為 None（line 304）

4. **`benchmark_type` 設定**（line 613）：
   - `metrics["benchmark_type"] = "total_return"`
   - 這是在 `run()` 最後覆蓋 `compute_metrics()` 的預設值
   - 確認 `compute_metrics()` 不會在其他地方設定回 `"price_only"`

### 3.6 DataSource 介面（`base.py`）

- 新增 `fetch_dividends(self, start_year, end_year) -> list[dict] | None`
- 預設回傳 None
- 確認 `engine.py` 在 `fetch_dividends()` 回傳 None 時不 crash

---

## 四、數學驗證（手算）

### 4.1 Drift-aware 簡單例子

假設 2 支股票，初始權重各 50%，持有 2 天：
- Stock A：Day 1 +10%, Day 2 -5%
- Stock B：Day 1 -3%, Day 2 +8%

**固定權重**（舊方法）：
- Day 1 ret = 0.5 × 10% + 0.5 × (-3%) = 3.5%
- Day 2 ret = 0.5 × (-5%) + 0.5 × 8% = 1.5%

**Drift-aware**（新方法）：
- 初始：A=0.5, B=0.5, cash=0
- Day 1：A=0.55, B=0.485, total=1.035, ret=3.5%（與固定相同）
- Day 2：A=0.55×0.95=0.5225, B=0.485×1.08=0.5238, total=1.0463, ret=1.0463/1.035-1=1.09%
- 固定 Day 2 = 1.5%，drift Day 2 = 1.09%

**差異 = 0.41%**。因為 drift 讓 A（Day 2 虧損）的權重更高。**請自行驗算。**

### 4.2 Scale-invariant 配息公式

0050 配息 $3.20（原始單位），close_before = $143.88（原始），split ratio 1:4。
- Split-adjusted close = $143.88 / 4 ≈ $35.97
- Scale-invariant factor = 1 - 3.20 / 143.88 = 0.9778
- Fallback factor = 35.97 / (35.97 + 3.20) = 0.9183 ← **錯誤！**

**0.9778 vs 0.9183，差異 6%。** 這就是為什麼需要 `close_before`。**請自行確認 0050 的 2024 年除息記錄。**

---

## 五、執行驗證步驟

```bash
# 1. 讀取關鍵原始碼（自己判斷，不要相信上面的行號）
cat src/backtest/engine.py | head -n 740 | tail -n 50   # _compute_daily_returns drift-aware
cat src/backtest/metrics.py | head -n 175 | tail -n 95  # adjust_dividends
cat src/data/twse_scraper.py | tail -n 120              # fetch_twse_dividends
cat src/data/finmind.py | tail -n 50                    # fetch_dividends cache

# 2. 執行測試（161 個應全通過）
conda run -n quant python -m pytest tests/ -v

# 3. 單獨跑新增的測試
conda run -n quant python -m pytest tests/test_dividends.py tests/test_drift_aware.py -v

# 4. 驗證 adjust_dividends 的 split-safe 行為
conda run -n quant python -c "
import pandas as pd
from src.backtest.metrics import adjust_dividends

# 模擬 1:4 split 後的價格（原始 ~200，split 後 ~50）
dates = pd.bdate_range('2023-07-17', periods=4, tz='UTC')
prices = pd.Series([50.0, 50.0, 48.0, 48.0], index=dates)

# 有 close_before（正確）
div_with = [{'stock_id': 'T', 'ex_date': '2023-07-19', 'cash_dividend': 4.0, 'close_before': 200.0}]
adj_with = adjust_dividends(prices, div_with, 'T')

# 沒有 close_before（fallback，會出錯）
div_without = [{'stock_id': 'T', 'ex_date': '2023-07-19', 'cash_dividend': 4.0}]
adj_without = adjust_dividends(prices, div_without, 'T')

print(f'With close_before: factor = {1 - 4.0/200.0:.4f}, prior prices = {adj_with.iloc[0]:.2f}')
print(f'Without close_before: factor = {48.0/(48.0+4.0):.4f}, prior prices = {adj_without.iloc[0]:.2f}')
print(f'Difference: {abs(adj_with.iloc[0] - adj_without.iloc[0]):.2f}')
assert abs(adj_with.iloc[0] - 49.0) < 0.01, f'Expected ~49.0, got {adj_with.iloc[0]}'
print('Split-safe formula verification PASSED')
"

# 5. 驗證 drift-aware 的數學
conda run -n quant python -c "
import pandas as pd
import numpy as np

# 2 stocks, 2 days, 手算驗證
dates = pd.bdate_range('2024-01-02', periods=2, tz='UTC')
ret_df = pd.DataFrame({'A': [0.10, -0.05], 'B': [-0.03, 0.08]}, index=dates)
w = pd.Series({'A': 0.5, 'B': 0.5})

# Fixed weight
fixed_d1 = (ret_df.iloc[0] * w).sum()
fixed_d2 = (ret_df.iloc[1] * w).sum()
print(f'Fixed: Day1={fixed_d1:.4f}, Day2={fixed_d2:.4f}')

# Drift-aware
values = w.copy().astype(float)
cash = 0.0
d1_before = values.sum() + cash
values = values * (1.0 + ret_df.iloc[0])
d1_ret = (values.sum() + cash) / d1_before - 1.0
d2_before = values.sum() + cash
values = values * (1.0 + ret_df.iloc[1])
d2_ret = (values.sum() + cash) / d2_before - 1.0
print(f'Drift:  Day1={d1_ret:.4f}, Day2={d2_ret:.4f}')
print(f'Day1 same? {abs(d1_ret - fixed_d1) < 1e-10}')
print(f'Day2 diff = {abs(d2_ret - fixed_d2):.4f} (expected ~0.004)')
assert abs(d1_ret - fixed_d1) < 1e-10, 'Day 1 should be identical'
assert abs(d2_ret - fixed_d2) > 0.001, 'Day 2 should diverge'
print('Drift-aware math verification PASSED')
"

# 6. 驗證 benchmark_type 是 total_return
conda run -n quant python -c "
import inspect
from src.backtest.engine import BacktestEngine
source = inspect.getsource(BacktestEngine.run)
assert 'total_return' in source, 'benchmark_type not set to total_return!'
assert 'benchmark_type' in source, 'benchmark_type not found in run()!'
print('benchmark_type = total_return: CONFIRMED')
"

# 7. 驗證 look-ahead 防護
conda run -n quant python -c "
import inspect
from src.backtest.engine import BacktestEngine
source = inspect.getsource(BacktestEngine.run)
assert 'ex_date' in source and 'cutoff' in source, 'as_of cutoff not found!'
print('look-ahead cutoff for dividends: CONFIRMED')
"

# 8. Docker 全部測試（如果可用）
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v

# 9. Docker 4Y 回測（比對 Claude 聲稱的數字）
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31 --benchmark 0050
# Claude 聲稱：Sharpe 0.90, Alpha +17.54%, MDD -32.76%
# 你自己跑出來的數字是什麼？

# 10. Docker Walk-Forward
docker compose run --rm --entrypoint python portfolio-bot scripts/walk_forward.py --train-months 18 --test-months 6 --start 2019-01-01 --end 2025-12-31
# Claude 聲稱：mean Sharpe 1.09, median 1.10, 11 windows
```

---

## 六、你的判斷標準

| 項目 | PASS 條件 |
|------|----------|
| 測試 | 161 passed, 0 failed |
| Drift-aware 數學 | 手算與程式碼結果一致 |
| Scale-invariant 公式 | 有 close_before 時 factor 正確；fallback 在 split 情境下會出錯（這是預期的） |
| 處理順序 | oldest-to-newest 對固定金額配息是正確的（自行推導確認） |
| look-ahead | 除息資料不會在 price index 範圍外生效 |
| Cache | `backtest_mode=True` 不打 API；TTL 7 天 |
| benchmark_type | `"total_return"` 在 `run()` 最後被設定 |
| 4Y 回測 | 能完成、數字與 Claude 聲稱的大致一致（Sharpe ~0.8-1.0） |
| WF | 11 windows 全完成、mean Sharpe > 0 |

---

## 七、Claude 聲稱的 KPI 前後比對（請自行驗證）

| 指標 | P7 修正前（Claude 聲稱） | P4.5+P4.6 修正後（Claude 聲稱） | 你跑出來的 |
|------|------------------------|-------------------------------|-----------|
| 4Y Sharpe | 1.33 | 0.90 | ？ |
| 4Y Alpha | +23.28% | +17.54% | ？ |
| 4Y MDD | -31.09% | -32.76% | ？ |
| Benchmark 年化 | ~1% | 5.14% | ？ |
| WF mean Sharpe | 1.22 | 1.09 | ？ |
| WF median Sharpe | 0.98 | 1.10 | ？ |
| benchmark_type | price_only | total_return | ？ |

**如果你跑出來的數字與 Claude 聲稱的有顯著差異（Sharpe 差 > 0.1 或 Alpha 差 > 5%），請深入調查原因。**

---

## 八、重要提醒

- **不要修改 `score_weights`、`exposure`、`top_n`** — 這些是策略參數，已經過 P1-P3 grid search + Codex 雙重驗證
- **不要修改任何原始碼** — 這是驗證任務，不是修復任務
- **不要相信 Claude 的行號** — 行號可能因為後續編輯而偏移，自己搜尋函式名
- **不要相信 Claude 的數字** — 自己跑回測，自己比對
- 如果發現問題，請明確指出：檔案、函式名、問題描述、嚴重度（P0/P1/P2/P3）
- 特別注意：
  1. **「權息」問題**：Claude 承認這是已知限制。你自己評估它的嚴重性
  2. **Drift-aware 報酬降幅**：53.6% → 25.3% 是否合理？還是有 bug？
  3. **處理順序**：oldest-to-newest 在所有情境下都正確嗎？

---

## 九、架構變更摘要（供快速定位用）

### 新增檔案
| 檔案 | 用途 |
|------|------|
| `tests/test_dividends.py` | 9 個測試：配息調整 + TWSE 日期解析 |
| `tests/test_drift_aware.py` | 5 個測試：drift-aware 日報酬 |

### 修改檔案
| 檔案 | 修改範圍 |
|------|---------|
| `src/backtest/engine.py` | `__init__`（+self._dividends）、`run()`（+除息整合）、`_compute_daily_returns()`（drift-aware + 配息調整） |
| `src/backtest/metrics.py` | 新增 `adjust_dividends()` + 更新 stale comment |
| `src/data/twse_scraper.py` | 新增 `_parse_roc_date()`、`fetch_twse_dividends()` |
| `src/data/finmind.py` | 新增 `fetch_dividends()` + pickle cache |
| `src/data/base.py` | 新增 `fetch_dividends()` 介面（預設回傳 None） |

### 未修改的關鍵檔案（確認它們沒被動過）
- `config/settings.yaml` — 策略參數不應變動
- `src/portfolio/tw_stock.py` — 選股邏輯不應變動
- `src/backtest/universe.py` — 選股池邏輯不應變動
- `src/strategy/regime.py` — Regime 判斷不應變動
