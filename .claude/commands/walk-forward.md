---
description: "執行 Walk-Forward 滾動驗證 + 分析（用法：/walk-forward [--start 2019-01-01 --end 2025-12-31]）"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "TodoWrite"]
---

# Walk-Forward 滾動驗證

你是台股量化投組系統的 Walk-Forward 驗證助手。請執行以下流程：

## 輸入參數

用戶輸入：$ARGUMENTS

解析參數（均有預設值）：
- `--start`：起始日（預設 2019-01-01）
- `--end`：結束日（預設 2025-12-31）
- `--train-months`：訓練期月數（預設 18）
- `--test-months`：測試期月數（預設 6）

## 執行流程

### Step 1：讀取舊結果
- 讀取 `Quantitative Trading/reports/walk_forward/summary.json` 作為比對基準
- 記錄舊的 `aggregate` 欄位

### Step 2：驗證環境
- 執行 `docker info` 確認 Docker 運作中

### Step 3：執行 Walk-Forward
工作目錄：`c:/Users/a0979/OneDrive/桌面/project/Quantitative Trading`

```bash
docker compose run --rm --entrypoint python portfolio-bot scripts/walk_forward.py \
  --train-months <TRAIN> --test-months <TEST> \
  --start <START> --end <END>
```

### Step 4：讀取新結果
- 讀取新的 `reports/walk_forward/summary.json`

### Step 5：產出分析報告（繁體中文）

#### 全視窗概覽表

| 視窗 | 測試期間 | Sharpe | 年化報酬 | Alpha | MDD | Beta | data_degraded |
|------|---------|--------|---------|-------|-----|------|--------------|
| W1 | ... | | | | | | |
| ... | | | | | | | |

#### 市場環境分類
根據每個視窗的 Sharpe 和 benchmark 走勢分類：
- **牛市**（benchmark 年化 > 15%）：列出視窗
- **盤整**（benchmark 年化 -5% ~ 15%）：列出視窗
- **熊市**（benchmark 年化 < -5%）：列出視窗

#### 匯總統計

| 統計量 | 新結果 | 舊結果 | 差異 |
|--------|-------|-------|------|
| 平均 Sharpe | | | |
| 中位數 Sharpe | | | |
| Sharpe 標準差 | | | |
| 最佳 Sharpe | | | |
| 最差 Sharpe | | | |
| 勝率（Sharpe>0） | | | |
| 平均 Alpha | | | |
| 最大 MDD | | | |

#### 判定結果

根據以下規則判定：
- **PASS** ✅：平均 Sharpe ≥ 0.7 且勝率 ≥ 50%
- **BORDERLINE** ⚠️：平均 Sharpe 0.3-0.7 或勝率 40-50%
- **FAIL** ❌：平均 Sharpe < 0.3 或勝率 < 40%

額外警告：
- 若 Sharpe 標準差 > 2.0 → 警告「策略穩定性偏低」
- 若最差視窗 Sharpe < -2.0 → 警告「存在極端虧損期」
- 若連續 2+ 個視窗 Sharpe < 0 → 警告「可能有 regime 適應性問題」
- 若 data_degraded 視窗 > 50% → 警告「資料品質影響可信度」

#### 動能崩盤風險分析（Daniel & Moskowitz 2016）
- 找出 Sharpe 最差的視窗
- 描述當時的市場環境（熊市反轉？高波動？）
- 評估策略的 regime 防護是否足夠

#### Bootstrap Sharpe 建議
如果匯總 Sharpe 的標準差很大，建議：
> 考慮對整體回測序列做 Bootstrap 重抽（10,000 次），計算 Sharpe 95% CI。若 CI 包含 0，則策略統計顯著性不足。

## 重要提醒
- 所有回覆使用**繁體中文**
- 不要修改 `config/settings.yaml` 的策略參數
- Walk-Forward 是驗證工具，不是優化工具 — 不要建議根據結果調參
- 如果執行失敗，顯示完整錯誤並建議排查方向
