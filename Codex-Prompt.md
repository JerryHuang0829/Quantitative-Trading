# Codex 複核 Prompt — 第十七輪（P0 完成後）

最後更新：2026-03-30
用途：Claude 完成 P0 修改後，交由 Codex 複核程式碼、artifact 與殘留風險。

---

## 本輪修改清單

### P0-1. Survivorship Bias — 驗證完成，無需修程式

實測結果：
- 107 支不在 stock_info 的已下市股票，全部是 **2001-2007 年** 下市
- **2015 年後下市的：0 支**
- FinMind TaiwanStockInfo 保留了所有近年下市股票記錄
- 結論：2022-2024 回測的 point-in-time universe **無 survivorship bias**

### P0-2. Benchmark Total-Return — 確認為 price-only，已標記

實測結果：
- 0050 在 2024-07-18 除息日，close 從 194.10 → 190.60（跌 3.50 元 = 除息金額）
- 確認 benchmark 為**未還原除息的原始價格**
- 但 FinMind `TaiwanStockPriceAdj` 在目前帳號不可用，**所有持倉股票也是 price-only**
- 組合 vs benchmark 同口徑，alpha 比較**大致公平**（差異約 0-1%/年，取決於殖利率差）
- `metrics.json` 已加入 `benchmark_type: "price_only"` 標記

### P0-3. Snapshot 診斷欄位 — 已補齊

新增 5 個 rejection 欄位到每月 snapshot：

```json
{
  "rejected_by_turnover": ["8021", "6830", "3026"],
  "rejected_by_price": ["3481", "2489", "1802", "2887"],
  "rejected_by_history": ["7769"],
  "rejected_by_trend": ["2313", "2408", ...],
  "rejected_by_industry": []
}
```

來源：
- `turnover` / `price` / `history` / `trend` → 從 `_analyze_symbol()` 的 `filters` 欄位提取
- `industry` → 從 `_select_positions()` 新增的 `rejected_by_industry` 回傳值

### P0-4. Degraded / Fail-Fast 重新定義

舊邏輯：只看 `analysis_errors > 20%`
新邏輯：
- `error_rate_high`：分析錯誤 > 20%
- `factor_coverage_low`：`revenue_momentum` 或 `institutional_flow` 覆蓋率 < 30%
- 任一觸發 → `data_degraded = true`
- snapshot 新增 `data_degraded_reasons` 陣列，明確列出降級原因

### P0-5. tw_stock.py 回傳產業拒絕名單

`_select_positions()` 新增：
- 初始化 `to_remove: set[str] = set()` 在函數頂部
- return dict 新增 `"rejected_by_industry": sorted(to_remove)`

---

## 修改的檔案

| 檔案 | 改動 |
|------|------|
| `src/backtest/engine.py` | snapshot 加 7 個欄位、degraded 邏輯改進 |
| `src/backtest/metrics.py` | 加 `benchmark_type: "price_only"` |
| `src/portfolio/tw_stock.py` | `_select_positions` 回傳 `rejected_by_industry` |

---

## Artifact 位置

```
reports/backtests/
  backtest_20240601_20241231_metrics.json    ← 6M KPI（含 benchmark_type）
  backtest_20240601_20241231_snapshots.json  ← 6M 月度快照（含新 rejection 欄位）
  backtest_20220101_20241231_metrics.json    ← 3Y KPI
  backtest_20220101_20241231_snapshots.json  ← 3Y 月度快照
```

---

## Codex 複核重點

### A. Snapshot 欄位驗證

請確認：
1. `rejected_by_turnover` 等欄位的股票確實符合 `min_avg_turnover` 等條件
2. `rejected_by_industry` 在有產業集中的月份是否正確觸發
3. `data_degraded_reasons` 在 coverage < 30% 時是否正確標記

### B. Benchmark 類型確認

請驗證：
1. `metrics.json` 中 `benchmark_type` 是否存在
2. 組合持倉是否也是 price-only（確認 alpha 比較公平性）
3. 0050 殖利率 ~3% vs 組合殖利率差異是否影響結論

### C. 殘留風險評估

| 風險 | 說明 | 影響 |
|------|------|------|
| Price-only benchmark | 組合與 benchmark 同口徑，alpha ±1%/年 | 低 |
| TWSE 端點穩定性 | STOCK_DAY_ALL URL 可能改版 | 低 |
| TPEX 無資料 | 上櫃股票依賴 FinMind，無 TWSE turnover | 低 |
| 2007 前下市股遺失 | 不影響 2022-2024 | 無 |

---

## Docker 驗證命令

```bash
cd "e:/Data/chongweihuang/Desktop/project/Quantitative-Trading"

# py_compile
docker compose run --rm --entrypoint python backtest -m py_compile \
  src/backtest/engine.py src/backtest/metrics.py src/portfolio/tw_stock.py

# 6M backtest
docker compose run --rm backtest --start 2024-06-01 --end 2024-12-31

# 3Y backtest
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31

# 驗證新 snapshot 欄位
docker compose run --rm --entrypoint python backtest -c "
import json
with open('reports/backtests/backtest_20240601_20241231_snapshots.json') as f:
    s = json.load(f)[0]
for k in ['rejected_by_turnover','rejected_by_price','rejected_by_history','rejected_by_trend','rejected_by_industry','data_degraded_reasons']:
    print(f'{k}: {s.get(k)}')
"
```

---

## Codex 回覆格式

```text
1. Findings
2. Snapshot review
3. Benchmark review
4. Degraded logic review
5. Residual risks
6. Suggestions
```
