# Codex 獨立驗證 Prompt — P6 度量層 + 整體架構審查

最後更新：2026-04-06
用途：驗證 P6 新增程式碼的正確性 + 對整體專案架構做獨立審查。

**重要：請完全獨立驗證，不要依賴 Claude 的任何結論。你需要自己讀程式碼、自己跑測試、自己判斷。**

---

## 一、專案概述（請自行讀 CLAUDE.md 和 README.md 確認）

台股 long-only 量化投組系統。月中再平衡，三因子橫截面排名選股：
- `price_momentum`（55%）：12M 報酬跳過最近 1M（Novy-Marx 2012）
- `revenue_momentum`（25%）：月營收 YoY
- `trend_quality`（20%）：趨勢品質

核心設定：`top_n=8`、`max_same_industry=3`、`caution=0.70`
已停用因子：`institutional_flow=0%`、`quality=0%`

---

## 二、P6 修改範圍（2026-04-06）

### P6.1 滑價調整
- **檔案**：`config/settings.yaml`
- **變更**：新增 `slippage_bps: 10`（原預設 5bps，在 `engine.py:26`）
- **驗證**：確認 `BacktestEngine.__init__()` 會讀取 yaml 的 `slippage_bps`，覆蓋預設值

### P6.2 + P6.3 新增風險指標
- **檔案**：`src/backtest/metrics.py`
- **新增指標**（在 `compute_metrics()` 中，位於 MDD 之後、Sharpe 之前）：

| 指標 | key | 驗證方式 |
|------|-----|---------|
| CVaR 95% | `cvar_95` | = `mean(returns[returns <= percentile(5%)])`，必須 < 0 對正常策略 |
| Tail Ratio | `tail_ratio` | = `abs(P95) / abs(P5)`，>1 表示上行尾巴較大 |
| 最大水下天數 | `max_drawdown_duration_days` | 從 drawdowns 序列計算連續 <0 的最長天數 |
| 平均水下天數 | `avg_drawdown_duration_days` | 所有水下期間的平均長度 |
| 水下時間比例 | `underwater_pct` | 水下天數 / 總天數 |
| 偏態 | `skewness` | `scipy.stats.skew()`，負偏態 = 左尾肥 |
| 峰度 | `kurtosis` | `scipy.stats.kurtosis()`（excess kurtosis），>0 = 肥尾 |
| Jarque-Bera | `jarque_bera_stat` + `jarque_bera_pvalue` | p<0.05 表示非常態分佈 |

- **驗證方式**：
  1. `python -m pytest tests/test_metrics.py -v` — 29 個測試必須全通過
  2. 手動呼叫 `compute_metrics()` 確認新 key 都存在
  3. 檢查 `format_report()` 是否正確顯示新指標

### P6.4 Bootstrap Sharpe CI
- **檔案**：`scripts/walk_forward.py`
- **新增函式**：`_bootstrap_sharpe_ci(sharpes, n_bootstrap=10000, ci=0.95)`
- **邏輯**：
  - 對視窗級 Sharpe 做有放回重抽 10,000 次
  - 取 2.5% 和 97.5% percentile 作為 95% CI
  - CI 不含 0 → `bootstrap_sharpe_significant: true`
  - 固定 seed `rng = np.random.default_rng(42)` 確保可重現
- **驗證**：
  1. 用已知 sharpes = [1.0, 1.5, 2.0, 0.5, 1.2] 呼叫，確認 CI > 0
  2. 用 sharpes = [1.0, -1.0, 0.5, -0.5, 0.2] 呼叫，確認 CI 包含 0
  3. `summary.json` 的 `aggregate` 是否包含 `bootstrap_sharpe_ci_lo/hi/significant`

### P6.5 動能分散度
- **檔案**：`src/backtest/engine.py`
- **新增函式**：`_compute_score_dispersion(ranked)`
- **邏輯**：
  - 從 `ranked` 中取 `eligible=True` 且 `portfolio_score is not None` 的分數
  - 回傳 `{"std": float, "iqr": float, "n_eligible": int}`
  - `< 5` 個 eligible → 回傳 None
- **驗證**：
  - 在 snapshot 中確認 `score_dispersion` 欄位存在
  - std 和 iqr 計算公式正確

---

## 三、整體架構審查（獨立於 P6）

請對以下核心模組做**獨立**程式碼審查，不需要依賴 Claude 之前的任何結論。

### 3.1 Point-in-time 完整性
- `src/backtest/engine.py` 的 `_DataSlicer` 是否正確截斷所有資料到 `as_of` 日期？
- 有沒有任何路徑能在 `as_of` 之前看到未來資料？
- `finmind.py` 的 4 處 `datetime.now()` 是否被 `_DataSlicer` 正確緩解？

### 3.2 交易成本模型
- `engine.py:406-411` 的成本計算邏輯：
  - `rebalance_cost = turnover * round_trip_cost`（0.47%）
  - `slippage_cost = turnover * 2 * (slippage_bps / 10000)`
  - 確認 `turnover` 是 one-way，所以 round-trip cost 乘一次是正確的
  - 確認 slippage 乘 2（進出各一次）是正確的
  - **新增**：確認 `settings.yaml` 的 `slippage_bps: 10` 是否被正確讀取覆蓋預設值 5

### 3.3 因子跳過邏輯
- `tw_stock.py` 的 `_rank_analyses()` 中 `weight <= 0` 因子是否完全跳過？
- `_analyze_symbol()` 中 `inst_weight > 0` guard 和 `quality > 0` guard 是否正確？
- 確認 IF=0% 時完全不增加 API 呼叫

### 3.4 Stock Split 處理
- `metrics.py:adjust_splits()` 的閾值 `-40%` 是否安全（不會誤判台股 ±10% 漲跌停）？
- Reverse split 閾值 `+100%` 是否合理？
- 從新到舊處理的順序是否正確？

### 3.5 Walk-Forward 框架
- `walk_forward.py` 的視窗滾動邏輯是否正確（無重疊洩漏）？
- 新增的 Bootstrap CI 使用固定 seed 42，確認可重現
- `degraded_periods` 欄位是否從 BacktestEngine 正確傳遞？

### 3.6 測試覆蓋
- 87 個測試（Docker 全通過，Windows 29 通過）
- 確認 `tests/test_metrics.py` 覆蓋新指標（CVaR/Tail Ratio/Drawdown Duration/Skew/Kurt）
  - **注意**：目前 test_metrics.py 的既有測試不直接測新指標，但 `compute_metrics()` 被呼叫時會計算它們。如果你認為需要專門測試，請指出。

### 3.7 Config 向後相容
- `engine.py:276-282` 的 backtest section 預設值是否完整？
- 新增的 `slippage_bps` 在 yaml 中是否有對應的讀取邏輯？（注意：`slippage_bps` 目前在 `tw_stock.py:996` 讀取 portfolio config，但 `BacktestEngine.__init__()` 使用 constructor 參數。請確認 yaml 的值能否正確傳遞到 engine。）

---

## 四、執行驗證步驟

```bash
# 1. 本機測試（Windows）
python -m pytest tests/test_metrics.py tests/test_universe.py -v

# 2. 手動驗證新指標
python -c "
import pandas as pd, numpy as np
from src.backtest.metrics import compute_metrics
np.random.seed(42)
rets = pd.Series(np.random.normal(0.001, 0.02, 252))
bench = pd.Series(np.random.normal(0.0005, 0.015, 252))
m = compute_metrics(rets, bench)
new_keys = ['cvar_95','tail_ratio','max_drawdown_duration_days','avg_drawdown_duration_days',
            'underwater_pct','skewness','kurtosis','jarque_bera_stat','jarque_bera_pvalue']
for k in new_keys:
    print(f'{k}: {m.get(k)}')
"

# 3. Bootstrap CI 驗證
python -c "
import sys; sys.path.insert(0,'scripts')
from walk_forward import _bootstrap_sharpe_ci
# Case 1: 全正 → CI 應 > 0
print(_bootstrap_sharpe_ci([1.0, 1.5, 2.0, 0.5, 1.2]))
# Case 2: 混合 → CI 可能包含 0
print(_bootstrap_sharpe_ci([1.0, -1.0, 0.5, -0.5, 0.2]))
"

# 4. Docker 全部測試（87 個）
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v

# 5. Docker 回測（產出含新指標的 metrics JSON）
docker compose run --rm backtest --start 2024-06-01 --end 2024-12-31 --benchmark 0050 --label p6_verify

# 6. Docker Walk-Forward（產出含 Bootstrap CI 的 summary）
docker compose run --rm --entrypoint python portfolio-bot scripts/walk_forward.py
```

---

## 五、你的判斷標準

| 項目 | PASS 條件 |
|------|----------|
| 本機測試 | 29 passed, 0 failed |
| Docker 測試 | 87 passed, 0 failed |
| 新指標 | 8 個新 key 全部出現且數值合理 |
| Bootstrap CI | 全正 sharpes → CI > 0；混合 sharpes → CI 含 0 |
| P6.1 slippage | yaml 10bps → 回測 trade_cost 比之前高（因為滑價從 5→10） |
| Point-in-time | 無 look-ahead bias |
| 因子跳過 | IF=0 完全不 fetch |
| Split 處理 | 不誤判正常漲跌停 |
| Config 相容 | 無 settings.yaml → 全部有預設值，不 crash |

---

## 六、重要提醒

- **不要修改 `score_weights`、`exposure`、`top_n`** — 這些是策略參數，已經過 P1-P3 grid search + Codex 雙重驗證
- **不要修改任何原始碼** — 這是驗證任務，不是修復任務
- 如果發現問題，請明確指出檔案、行號、問題描述、嚴重度
- 特別注意：`slippage_bps` 的傳遞路徑（yaml → tw_stock.py vs engine.py constructor）是否有斷裂
