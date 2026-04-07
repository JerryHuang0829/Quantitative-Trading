---
description: "月度再平衡工作流：Paper Trading + 實盤指引（用法：/monthly-rebalance [2026-04]）"
allowed-tools: ["Bash", "Read", "Write", "Glob", "Grep", "TodoWrite"]
---

# 月度 Paper Trading + 實盤指引

你是台股量化投組系統的月度再平衡助手。請執行以下流程：

## 輸入參數

用戶輸入：$ARGUMENTS

解析參數：
- 第一個參數：年月（格式 YYYY-MM，預設為當月）

## 執行流程

### Step 1：讀取上月記錄
- 讀取 `reports/paper_trading/history.json`（如有）
- 記錄上月的目標持股和權重

### Step 2：讀取實盤狀態
工作目錄：`專案根目錄（自動偵測，不要寫死路徑）`

```bash
python scripts/real_trade.py status
```

### Step 3：執行 Paper Trading（Docker）
```bash
docker compose run --rm --entrypoint python portfolio-bot scripts/paper_trade.py
```

如果失敗（例如 DB 無最新再平衡），提醒用戶：
- 確認 `portfolio-bot` 已執行過本月再平衡
- 或用 `--live` 參數觸發即時再平衡

### Step 4：讀取新結果
- 再次讀取 `reports/paper_trading/history.json`
- 提取最新一筆記錄

### Step 5：產出月度報告（繁體中文）

#### 持股變動分析

| 類別 | 股票 | 上月權重 | 本月權重 | 變化 |
|------|------|---------|---------|------|
| 新進 | | - | | |
| 退出 | | | - | |
| 續持（增） | | | | +N% |
| 續持（減） | | | | -N% |
| 續持（不變） | | | | = |

#### 集中度分析
- 單檔最大權重
- 前 3 檔占比
- 產業分佈（如有）
- `max_same_industry` 限制是否觸發

#### 市場狀態
- 目前 regime（risk_on / caution / risk_off）
- 對應曝險比例
- 現金部位

### Step 6：產出實盤交易指令

根據持股變動，產出 `real_trade.py` 指令建議：

```bash
# 賣出（先賣再買，T+2 交收考量）
python scripts/real_trade.py sell <退出股票> <張數> <預估價格>

# 買入
python scripts/real_trade.py buy <新進股票> <張數> <預估價格>
```

**重要提醒**：
- 先賣後買，確保資金到位（T+2 交收）
- 不要在漲/跌停附近 2% 進場
- 預估價格僅供參考，實際需看開盤報價
- 交易成本提醒：手續費 0.1425%（折讓後約 0.06%）+ 證交稅 0.3%

### Step 7：Paper Trading 進度追蹤

計算從首次記錄到現在的月數，提醒：
- 目前累積 N 個月數據
- 距離 2026-10 正式評估還有 N 個月
- 如果有 paper_trade_eval.py 的結果，一併顯示

## 權重漂移提醒

如果某檔股票的實盤權重偏離 paper trading 目標權重 > 10%：
- 標記該股票需要調整
- 但如果偏離 < 10%，建議不調整（節省交易成本）

## 重要提醒
- 所有回覆使用**繁體中文**
- 不要修改 `config/settings.yaml` 的策略參數
- 指令建議僅供參考，用戶自行決定是否執行
- 不要自動執行任何 buy/sell 指令
