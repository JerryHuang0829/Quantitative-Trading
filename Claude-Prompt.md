# Claude 交接 Prompt

最後更新：2026-03-30
用途：Codex 完成第十七輪複核後，交由 Claude 依目前程式碼與既有 artifact 繼續修正與回測。

## 工作分工

- Claude 負責：
  - 實際執行 6M / 3Y backtest
  - 管理 FinMind quota / token
  - 產出新的 artifact、log、snapshot
  - 依交接內容修正程式碼與文件
- Codex 負責：
  - 讀碼複核
  - 檢查 artifact 是否支持結論
  - 指出殘留風險與下一步建議

## 目前已驗證的狀態

### 1. Universe reconstruction — 已修好

- `src/backtest/universe.py`：移除 `date <= as_of`、加 `drop_duplicates`
- `src/data/twse_scraper.py`：TWSE 成交金額排序（免費端點）
- `auto_universe_pre_filter_size=400` 已在程式碼落地

### 2. Market signal look-ahead — Codex 確認無明顯問題

- `slicer.set_as_of(rebal_date)` 在前
- `market_view` 之後才算
- `_compute_daily_returns()` 不含 rebal 當天報酬

### 3. Survivorship bias — 已驗證對 2022-2024 無影響

- 107 支缺失的已下市股票全部是 2001-2007 年下市的
- 2015 年後下市且不在 stock_info 的：**0 支**
- FinMind TaiwanStockInfo 保留了所有 2007 年後下市的股票記錄

### 4. Benchmark — 確認為 price-only

- FinMind `TaiwanStockPriceAdj` 在目前帳號不可用，所有股票均為未還原除息
- 組合和 benchmark 同口徑（都是 price-only），alpha 比較大致公平
- 但雙方都低估約 2-3% 年化殖利率
- `metrics.json` 已加入 `benchmark_type: "price_only"` 標記

### 5. Snapshot 診斷欄位 — 已補齊

新增欄位：
- `rejected_by_turnover`：成交金額不足
- `rejected_by_price`：股價低於門檻
- `rejected_by_history`：歷史資料不足
- `rejected_by_trend`：趨勢/動能不合格
- `rejected_by_industry`：產業集中度限制
- `data_degraded_reasons`：降級原因（`error_rate_high` / `factor_coverage_low`）

### 6. Degraded 定義 — 已改進

新邏輯：
- `error_rate_high`：分析錯誤 > 20%
- `factor_coverage_low`：revenue_momentum 或 institutional_flow 覆蓋率 < 30%
- 任一觸發 → `data_degraded = true`

## 目前 Artifact 結果

### 6M（2024-06-01 → 2024-12-31）

- 年化報酬：7.34%，Sharpe：0.34，Alpha：-10.92%
- Beta：0.58，data_degraded：false
- benchmark_type：price_only

### 3Y（2022-01-01 → 2024-12-31）

- 年化報酬：~40%，Sharpe：~1.55，Alpha：~+35%
- Beta：~0.52，data_degraded：false
- （3Y 正在重跑中，精確數字待最終 artifact 為準）

## 跨機器回測比對

`reports/backtests/` 裡的 artifact 已加入 git，但**不是唯一真相**。
在新環境（另一台電腦）時：

1. **必須先重跑** 6M 和 3Y backtest
2. **比對新舊數字**：
   - Sharpe / Alpha 差異 < 5% → 正常（TWSE 成交金額每次略有差異）
   - `total_analyzed`、`n_rebalances` 應完全一致
   - 持股名單可能有 1-2 支邊際股票差異
3. **若差異 > 5%** → 排查 FinMind token、TWSE 端點、cache 是否從零重建

### Docker 環境改動（第十七輪）

**重要：`docker-compose.override.yml` 已刪除**，其內容（volume mount、PYTHONPATH）
已合併進 `docker-compose.yml` 主檔。`git pull` 後如果另一台電腦還有舊的 override 檔，
需刪除或確認 pull 已同步刪除。

### 另一台電腦操作步驟

```bash
cd Quantitative-Trading
git pull

# 確認 override 已刪除
ls docker-compose.override.yml  # 應該 not found

# 確認 .env 已設定 FINMIND_TOKEN
cat .env

# 如果從未 build 過：
docker compose build

# 跑回測並與 reports/ 裡的基準數字比對：
docker compose run --rm backtest --start 2024-06-01 --end 2024-12-31
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31
```

注意：
- 首次跑 3Y 需要較長時間（FinMind 快取從零建立，~15-30 分鐘）
- `src/data/twse_scraper.py` 是新增檔案，用 `requests`（已在 requirements.txt），不需 rebuild image

### 第十七輪新增 / 修改的檔案

| 檔案 | 類型 | 說明 |
|------|------|------|
| `src/data/twse_scraper.py` | 新增 | TWSE 成交金額 scraper |
| `src/backtest/universe.py` | 修改 | 移除 date 過濾、加 dedup、加 TWSE 預篩 + 排序 |
| `src/backtest/engine.py` | 修改 | inf 過濾、snapshot 擴充（7 個 rejection 欄位）、degraded 改進 |
| `src/backtest/metrics.py` | 修改 | 加入 benchmark_type 標記 |
| `src/portfolio/tw_stock.py` | 修改 | _select_positions 回傳 rejected_by_industry |
| `.gitignore` | 修改 | 取消排除 reports/ |
| `docker-compose.override.yml` | 刪除 | 內容合併進主檔 |

## Claude 下一步

### P1：策略層分析（look-ahead 已確認無問題）

- 分析 6M 負 alpha 根因（台積電不被選入 top-8 的因子分數）
- 評估 `top_n=8` 是否太集中
- 評估 `institutional_flow` 在大盤強勢期的效果

### P2：因子調參（需基於 P1 分析結論）

- `trend_quality` scaling 校準
- `hold_buffer` 是否過於保守
- exposure 是否需要調整

## 回覆格式

```text
1. Findings
2. Changes made
3. Validation
4. Residual risks
5. Next actions
```
