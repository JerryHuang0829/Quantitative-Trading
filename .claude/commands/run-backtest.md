---
description: "執行 Docker 回測 + 自動比對 baseline（用法：/run-backtest 2022-01-01 2024-12-31 [--benchmark 0050]）"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "TodoWrite"]
---

# 回測執行 + 結果分析

你是台股量化投組系統的回測助手。請執行以下流程：

## 輸入參數

用戶輸入：$ARGUMENTS

解析參數：
- `--start` 或第一個日期：回測起始日（必要）
- `--end` 或第二個日期：回測結束日（必要）
- `--benchmark`：benchmark 代碼（預設 0050）
- `--label`：結果子目錄名稱（可選，用於 A/B 比較）

## 執行流程

### Step 1：驗證環境
- 執行 `docker info` 確認 Docker 運作中
- 若 Docker 未啟動，提醒用戶啟動 Docker Desktop

### Step 2：讀取 Baseline
- 根據回測期間長度選擇 baseline：
  - 期間 ≥ 3 年 → 讀取 `reports/backtests/dashboard_4y/backtest_20220101_20251231_metrics.json`
  - 期間 < 3 年 → 讀取 `reports/backtests/dashboard_6m/backtest_20240601_20241231_metrics.json`
- 若 baseline 不存在，跳過比對步驟

### Step 3：執行回測
工作目錄：`c:/Users/a0979/OneDrive/桌面/project/Quantitative Trading`

```bash
docker compose run --rm backtest --start <START> --end <END> --benchmark <BENCHMARK>
```

如果用戶指定了 `--label`：
```bash
docker compose run --rm backtest --start <START> --end <END> --benchmark <BENCHMARK> --label <LABEL>
```

### Step 4：讀取結果
- 用 Glob 找到最新的 `*_metrics.json`
- 讀取 metrics JSON
- 同時讀取對應的 `*_report.txt`（如有）

### Step 5：產出分析報告

用繁體中文產出以下表格：

#### 回測結果摘要

| 指標 | 本次結果 | Baseline | 差異 |
|------|---------|----------|------|
| 年化報酬 | | | |
| Sharpe Ratio | | | |
| Sortino Ratio | | | |
| Alpha | | | |
| MDD | | | |
| Beta | | | |
| 年化波動度 | | | |
| Calmar Ratio | | | |
| 換手率（每次再平衡） | | | |
| 交易成本 | | | |
| data_degraded | | | |

#### 自動警告（任一觸發即顯示）
- [ ] `data_degraded: true` → **資料品質問題**：部分期間資料不完整
- [ ] Sharpe < 0.7 → **績效偏低**：低於策略歷史均值
- [ ] MDD > -30% → **回撤過大**：超過歷史最大回撤
- [ ] Alpha < 0 → **負 Alpha**：未跑贏 benchmark
- [ ] `degraded_periods > 0` → **降級期間**：有 N 個月資料不足
- [ ] 交易成本 > 10% 年化報酬 → **成本過高**

#### 交易成本提醒
目前回測使用 `turnover_cost = 0.0047`（手續費+證交稅）。
實際交易需額外考慮滑價（0.05-0.15%/邊）+ 市場衝擊，真實 round-trip 約 0.55-0.65%。

### Step 6：如有 snapshots，提供持股分析
- 讀取 `*_snapshots.json`（如有）
- 報告：持股集中度、產業分佈、平均持有期間

## 重要提醒
- 所有回覆使用**繁體中文**
- 不要修改 `config/settings.yaml` 的策略參數
- 不要修改任何原始碼
- 如果回測失敗，顯示完整錯誤訊息並建議排查方向
