# Codex 複核 Prompt — P7 全架構獨立驗證

更新日期：2026-04-02
用途：Claude 本輪新增 48 個測試（87→135）、修復 finmind.py bug、重跑 Dashboard 6M、更新 Walk-Forward 數據。
**請獨立驗證。不要依賴 Claude 或任何 MD 檔的說法。以程式碼、tests、artifact 為準。**

---

## 專案簡介

台股 long-only 量化選股系統，月頻再平衡，三因子排名選前 8 檔。

| 因子 | 權重 | 來源 |
|------|------|------|
| price_momentum | 55% | OHLCV（FinMind） |
| trend_quality | 20% | SMA + regime detection |
| revenue_momentum | 25% | 月營收（FinMind） |
| institutional_flow | **0%**（已停用） | — |

市場風向機制：0050 SMA 位置 → risk_on(96%) / caution(70%) / risk_off(35%)

---

## 本輪變更清單

| 項目 | 檔案 | 變更類型 |
|------|------|---------|
| 1 | `tests/test_rebalance_dates.py`（新建） | 14 個測試：`_generate_rebalance_dates` 基礎 + 假日對齊 |
| 2 | `tests/test_engine_integration.py`（新建） | 17 個測試：`BacktestEngine.run()` 端對端整合測試 |
| 3 | `tests/test_finmind.py`（新建） | 17 個測試：DiskCache + CSV fallback + fetch_stock_info 流程 |
| 4 | `src/data/finmind.py` | Bug fix：3 處 `cached or fallback()` → 安全的 if/else |
| 5 | `src/backtest/engine.py` | 4 行註釋：標記 IF coverage 為近似值 |
| 6 | `reports/backtests/dashboard_6m/` | Dashboard 6M 用修復後引擎重跑 |
| 7 | `reports/walk_forward/summary.json` | Walk-Forward 用修復後引擎重跑 |
| 8 | `reports/walk_forward/summary_old_backup.json`（新建） | 修復前的舊 Walk-Forward 備份 |
| 9 | 多個 MD 檔 | 日期修正（4/14 → 4/13）+ Walk-Forward 數據更新 |

---

## 驗證一：測試完整性

### A. 測試數量（請自己數）

```bash
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ --collect-only -q 2>&1 | tail -3
```

### B. 逐檔獨立跑通

```bash
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/test_rebalance_dates.py -v 2>&1 | tail -3
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/test_engine_integration.py -v 2>&1 | tail -3
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/test_finmind.py -v 2>&1 | tail -3
```

### C. 全套 pytest

```bash
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v 2>&1
```

記錄：passed / failed / warning / 耗時

---

## 驗證二：test_rebalance_dates.py

```bash
# 確認測試的是 engine.py 靜態方法
grep "BacktestEngine" tests/test_rebalance_dates.py

# 確認 4/12 週日對齊到 4/13 週一
grep -A 3 "sunday_aligns" tests/test_rebalance_dates.py

# 自己驗算 2026-04-12 是星期幾
docker compose run --rm --entrypoint python portfolio-bot -c "
import datetime
d = datetime.date(2026, 4, 12)
print(f'2026-04-12 is {d.strftime(\"%A\")}')
"

# 確認有 timezone-aware 測試
grep "tz" tests/test_rebalance_dates.py
```

---

## 驗證三：test_engine_integration.py

```bash
# FakeSource 提供了哪些方法
grep "def fetch_" tests/test_engine_integration.py

# 確認合成資料是上升趨勢（否則所有股票都不會 eligible）
grep "daily_return" tests/test_engine_integration.py

# 確認 fixture 真的呼叫了 engine.run()
grep -A 5 "def result" tests/test_engine_integration.py

# 確認覆蓋了哪些面向
grep "def test_" tests/test_engine_integration.py
```

---

## 驗證四：test_finmind.py

```bash
# 三個測試類
grep "class Test" tests/test_finmind.py

# 確認使用 tmp_path（不碰真實 cache）
grep "tmp_path" tests/test_finmind.py | head -5

# 確認測了哪些場景
grep "def test_" tests/test_finmind.py
```

---

## 驗證五：finmind.py bug 修復

這是本輪發現的真實 bug。請獨立驗證：

### A. 確認 bug 存在

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import pandas as pd
df = pd.DataFrame({'a': [1, 2, 3]})
try:
    result = df or 'fallback'
    print('No error')
except ValueError as e:
    print(f'Bug confirmed: {e}')
"
```

### B. 確認修復後程式碼

```bash
# 應該有 3 行 if/else 模式
grep -n "cached if (cached" src/data/finmind.py

# 不應該有殘留的 "cached or"
grep -n "cached or" src/data/finmind.py
```

### C. 驗證修復邏輯正確

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import pandas as pd

# Case 1: cached 有資料 → 回傳 cached
cached = pd.DataFrame({'a': [1]})
result = cached if (cached is not None and not cached.empty) else 'fallback'
assert isinstance(result, pd.DataFrame)
print('Case 1 (cached exists): OK')

# Case 2: cached 是 None → 回傳 fallback
cached = None
result = cached if (cached is not None and not cached.empty) else 'fallback'
assert result == 'fallback'
print('Case 2 (cached is None): OK')

# Case 3: cached 是空 DataFrame → 回傳 fallback
cached = pd.DataFrame()
result = cached if (cached is not None and not cached.empty) else 'fallback'
assert result == 'fallback'
print('Case 3 (cached is empty): OK')

print('=== Bug fix verified ===')
"
```

### D. 影響範圍

觸發條件：pickle cache 存在 + TTL 過期 + API 失敗。
請評估這在回測 / paper trading / 實盤中是否可能觸發。

---

## 驗證六：engine.py IF coverage 註釋

```bash
# 只加了註釋，邏輯沒改
grep -B 1 -A 6 "NOTE.*非零值" src/backtest/engine.py

# 原始邏輯仍在
grep "institutional_raw.*or 0.*!= 0" src/backtest/engine.py
```

---

## 驗證七：Walk-Forward summary.json

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import json, statistics

with open('reports/walk_forward/summary.json') as f:
    s = json.load(f)

# 自己算，不信 aggregate
sharpes = [w['sharpe'] for w in s['windows']]
my_mean = round(statistics.mean(sharpes), 4)
my_median = round(statistics.median(sharpes), 4)
my_win = round(sum(1 for x in sharpes if x > 0) / len(sharpes), 4)

agg = s['aggregate']
print(f'Windows: {len(s[\"windows\"])}')
print(f'mean_sharpe:   reported={agg[\"mean_sharpe\"]}  computed={my_mean}  match={abs(my_mean - agg[\"mean_sharpe\"]) < 0.01}')
print(f'median_sharpe: reported={agg[\"median_sharpe\"]}  computed={my_median}  match={abs(my_median - agg[\"median_sharpe\"]) < 0.01}')
print(f'win_rate:      reported={agg[\"win_rate\"]}  computed={my_win}  match={abs(my_win - agg[\"win_rate\"]) < 0.01}')
print()

for w in s['windows']:
    print(f'  W{w[\"window\"]:2d}: {w[\"test_start\"]} → {w[\"test_end\"]}  Sharpe={w[\"sharpe\"]:+.2f}  degraded={w[\"data_degraded\"]}  dp={w.get(\"degraded_periods\",\"?\")}')

print()
print(f'All degraded=false: {all(not w[\"data_degraded\"] for w in s[\"windows\"])}')
print(f'All dp=0: {all(w.get(\"degraded_periods\",-1)==0 for w in s[\"windows\"])}')
"
```

---

## 驗證八：Dashboard 6M 結果

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import json
with open('reports/backtests/dashboard_6m/backtest_20240601_20241231_metrics.json') as f:
    m = json.load(f)

print(f'Sharpe:           {m[\"sharpe_ratio\"]:.4f}')
print(f'Alpha:            {m[\"annualized_alpha\"]*100:.2f}%')
print(f'MDD:              {m[\"max_drawdown\"]*100:.2f}%')
print(f'data_degraded:    {m[\"data_degraded\"]}')
print(f'degraded_periods: {m[\"degraded_periods\"]}')
print(f'benchmark_type:   {m[\"benchmark_type\"]}')
print(f'n_rebalances:     {m[\"n_rebalances\"]}')
"
```

---

## 驗證九：全架構掃描

### A. 核心模組可 import

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import importlib
for mod in ['src.backtest.engine', 'src.backtest.metrics', 'src.backtest.universe',
            'src.portfolio.tw_stock', 'src.data.finmind', 'src.data.twse_scraper',
            'src.utils.constants']:
    importlib.import_module(mod)
    print(f'  {mod}: OK')
print('=== All imports OK ===')
"
```

### B. Config 完整性

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import yaml
with open('config/settings.yaml') as f:
    cfg = yaml.safe_load(f)

bt = cfg.get('backtest', {})
for k in ['benchmark_lookback_days','ohlcv_min_fetch_days','market_value_fetch_days',
          'institutional_fallback_days','error_rate_threshold','factor_coverage_threshold']:
    print(f'  backtest.{k} = {bt[k]}')

p = cfg['portfolio']
sw = p['score_weights']
print(f'  IF weight = {sw[\"institutional_flow\"]}')
print(f'  rebalance_day = {p[\"rebalance_day\"]}')
print(f'  max_same_industry = {p[\"max_same_industry\"]}')
print(f'  top_n = {p[\"top_n\"]}')
"
```

### C. 共用常數未分裂

```bash
# 定義應該只在 constants.py
grep -rn "TECH_SUPPLY_CHAIN_KEYWORDS" src/ scripts/
```

### D. data_degraded 只查 weight > 0

```bash
grep -B 2 -A 3 "weight > 0" src/backtest/engine.py
```

### E. split 測試覆蓋

```bash
grep -c "def test_.*split" tests/test_metrics.py
grep "REVERSE_SPLIT" src/backtest/metrics.py
```

### F. 檔案結構

```bash
find src/ -name "*.py" | sort
find scripts/ -name "*.py" | sort
find tests/ -name "*.py" | sort
find dashboard/ -name "*.py" | sort
find reports/ -type f | sort
```

---

## 驗證十：MD 交叉比對

**用程式碼 / artifact 的數字去比對 MD，不要反過來。**

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import json, yaml, subprocess

# 1. 測試數量
r = subprocess.run(['python','-m','pytest','tests/','--collect-only','-q'], capture_output=True, text=True)
print(f'Test count: {[l for l in r.stdout.split(chr(10)) if \"test\" in l][-1]}')

# 2. Walk-Forward
with open('reports/walk_forward/summary.json') as f:
    wf = json.load(f)
print(f'WF mean_sharpe: {wf[\"aggregate\"][\"mean_sharpe\"]}')
print(f'WF win_rate: {wf[\"aggregate\"][\"win_rate\"]}')

# 3. Dashboard 6M
with open('reports/backtests/dashboard_6m/backtest_20240601_20241231_metrics.json') as f:
    d = json.load(f)
print(f'6M Sharpe: {d[\"sharpe_ratio\"]}')
print(f'6M benchmark_type: {d[\"benchmark_type\"]}')

# 4. Config
with open('config/settings.yaml') as f:
    cfg = yaml.safe_load(f)
print(f'IF weight: {cfg[\"portfolio\"][\"score_weights\"][\"institutional_flow\"]}')
print(f'rebalance_day: {cfg[\"portfolio\"][\"rebalance_day\"]}')
"
```

將以上輸出與 `Claude-Prompt.md`、`優化建議.md`、`優化紀錄.md`、`策略研究.md` 比對。
**如果有不一致，以程式碼 / artifact 為準，列出差異。**

---

## 回覆格式

```
### 驗證一：測試完整性
- [ ] collected X tests
- [ ] test_rebalance_dates.py: X passed
- [ ] test_engine_integration.py: X passed
- [ ] test_finmind.py: X passed
- [ ] 全套: X passed / X failed / X warning / 耗時 Xs
結論：PASS / FAIL

### 驗證二：test_rebalance_dates.py
- [ ] 測試 _generate_rebalance_dates 靜態方法
- [ ] 4/12 週日 → 4/13 週一
- [ ] timezone-aware 測試存在
結論：PASS / FAIL

### 驗證三：test_engine_integration.py
- [ ] FakeSource 介面完整
- [ ] fixture 呼叫了 engine.run()
- [ ] 涵蓋 metrics / snapshot / positions / 邊界
結論：PASS / FAIL

### 驗證四：test_finmind.py
- [ ] DiskCache 測試
- [ ] CSV fallback 測試
- [ ] fetch_stock_info 流程
- [ ] 使用 tmp_path
結論：PASS / FAIL

### 驗證五：finmind.py bug
- [ ] bug 存在已確認（DataFrame or → ValueError）
- [ ] 3 處修復完成
- [ ] 無殘留 "cached or"
- [ ] 影響範圍評估
結論：PASS / FAIL

### 驗證六：engine.py 註釋
- [ ] 只加註釋，邏輯未改
結論：PASS / FAIL

### 驗證七：Walk-Forward
- [ ] aggregate 可驗算
- [ ] 全部 degraded=false, dp=0
結論：PASS / FAIL

### 驗證八：Dashboard 6M
- [ ] data_degraded=false
- [ ] benchmark_type=price_only
結論：PASS / FAIL

### 驗證九：全架構
- [ ] 核心模組可 import
- [ ] Config 完整
- [ ] 共用常數未分裂
- [ ] degraded 只查 weight > 0
- [ ] split 測試覆蓋
結論：PASS / FAIL

### 驗證十：MD 交叉比對
- [ ] 測試數量一致
- [ ] WF 數字一致
- [ ] 6M 數字一致
- [ ] config 數字一致
結論：PASS / FAIL / 有差異（列出）

### 額外發現
（任何問題、建議、或不同意的判斷）
```
