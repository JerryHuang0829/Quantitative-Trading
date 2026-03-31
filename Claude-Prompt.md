# Claude 交接 Prompt

最後更新：2026-03-31

請用中文回覆。  
這份檔案只保留兩類資訊：

1. Codex 已完成的複核結論  
2. Claude 下一輪需要驗證 / 處理的事項

---

## 一. Codex 已完成的複核

### 1. P3 baseline 與研究分支已核對

正式 baseline 應以這組 artifact 為準：

- `reports/backtests/p2_if0/backtest_20240601_20241231_metrics.json`
- `reports/backtests/p2_if0/backtest_20220101_20241231_metrics.json`

Codex 已確認其關鍵數字為：

- 6M：Sharpe `1.0834`、Alpha `+13.52%`、MDD `-21.50%`
- 3Y：Sharpe `1.8458`、Alpha `+48.43%`、MDD `-21.50%`

### 2. P3 結論方向大致合理

- `vol_weighted` 退步是合理的
  - 6M 對照：
    - baseline：Sharpe `1.0834`
    - `p3_vol_weighted`：Sharpe `0.4796`
  - 結論：目前這套動能策略不適合用 `1 / vol` 權重做正式配置

- `quality` 目前這版也不適合落地
  - 6M：
    - baseline：Sharpe `1.0834`
    - `p3_4factor`：Sharpe `0.6913`
  - 3Y：
    - baseline：Sharpe `1.8458`
    - `p3_4factor`：Sharpe `1.7932`

### 3. 正式設定目前仍未改動主策略

Codex 已確認：

- `config/settings.yaml`
  - `weight_mode: score_weighted`
  - `price_momentum: 0.55`
  - `trend_quality: 0.20`
  - `revenue_momentum: 0.25`
  - `institutional_flow: 0.00`

- `quality` 雖然出現在 `available_metrics`，但目前權重為 0，因此**不影響 ranking 結果**

### 4. 目前仍存在的問題

#### A. `quality` 有執行面副作用

雖然 `quality` 權重為 0，但 `_analyze_symbol()` 仍會無條件呼叫 `fetch_financial_quality()`。  
這代表：

- 不影響正式排名
- 但仍增加 API / cache / failure surface

#### B. artifact 路徑不一致

根目錄：

- `reports/backtests/backtest_20240601_20241231_metrics.json`
- `reports/backtests/backtest_20220101_20241231_metrics.json`

目前不是這輪正式 baseline。  
如果不整理，之後很容易讀錯結果。

#### C. benchmark 仍是 `price_only`

目前 `tests/test_metrics.py` 仍明確驗證 `benchmark_type == "price_only"`。  
所以現在的 alpha 不是 total-return benchmark 口徑。

#### D. 測試框架已建立，但未完全覆蓋 P3

目前 repo 內確實有 44 個測試，但 Codex 沒看到直接覆蓋：

- `fetch_financial_quality()`
- `quality_raw` 的財務語意
- `quality` 權重為 0 時應不抓資料

---

## 二. Claude 下一輪要做的事

### P0：先處理 `quality` 的關閉語意

請優先修正：

- 只有當 `score_weights["quality"] > 0` 時，才呼叫 `fetch_financial_quality()`

目標是讓：

- `quality=0`
  等於
- 不影響排序，也不增加執行成本與資料風險

### P1：整理 baseline artifact 路徑

請決定並落地一個正式規則：

方案 A：
- 把 `p2_if0` 升成 canonical root artifact

方案 B：
- 保留 `p2_if0/`，但在 README / md / prompt 明確寫死：
  - 正式 baseline 一律讀 `reports/backtests/p2_if0/`

不論選哪個方案，請同步更新：

- `Claude-Prompt.md`
- `優化紀錄.md`
- `優化建議.md`
- `策略研究.md`

### P2：對 `quality` 做更嚴格的結論

請把目前的敘述修正為：

- 可以說：`quality` 這一版不建議落地
- 不要直接寫成：品質因子永久無效

如果你要繼續保留研究路線，請補一段：

- 之後若重啟 quality 研究，應先修 ROE 定義
- 建議方向：
  - TTM net income / average equity
  - 或至少明確區分單季 / 累計 / 年化口徑

### P3：若時間夠，再補測試

建議新增測試：

1. `quality` 權重為 0 時，不應呼叫 `fetch_financial_quality()`
2. `fetch_financial_quality()` 回傳缺欄位時，`quality_raw` 應安全退化
3. `benchmark_type` 未來若改 total-return，測試要跟著更新

---

## 三. 目前不要做的事

在這一輪，先不要：

- 把 `vol_weighted` 拉回正式設定
- 直接刪掉 `quality` 整條研究分支
- 先改 exposure
- 先改 `top_n`
- 先把 AI 加進 ranking

---

## 四. Claude 回覆格式

請用這個格式回覆：

```text
1. Findings
2. Changes made
3. Validation
4. Residual risks
5. Next actions
```
