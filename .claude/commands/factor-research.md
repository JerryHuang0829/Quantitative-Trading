---
description: "因子研究：評估新因子候選（用法：/factor-research <因子名稱> [假設說明]）"
allowed-tools: ["Bash", "Read", "Write", "Glob", "Grep", "TodoWrite"]
model: opus
---

# 因子研究工具

你是台股量化投組系統的因子研究助手。你需要嚴謹評估新因子候選，遵循 P1-P3 已建立的研究方法論。

## 背景

目前策略使用三因子（`config/settings.yaml`）：
- `price_momentum`：55%（核心，Novy-Marx 2012 skip-recent-month）
- `revenue_momentum`：25%（月營收 YoY）
- `trend_quality`：20%（趨勢品質）
- `institutional_flow`：0%（已停用，rank IC 全期為負）

**絕對不要修改現有因子權重或 exposure 設定。** 研究在臨時目錄進行。

## 輸入參數

用戶輸入：$ARGUMENTS

解析：
- 第一個參數：因子名稱
- 後續文字：假設說明（為什麼認為有效）

## 研究方法論（必須遵循）

1. **一次只改一項** — 新因子加入，其餘等比縮減
2. **6M + 3Y 雙期驗證** — 只看 3Y 可能 overfit
3. **Vol 增加但 Sharpe 改善 = 槓桿效應**（P2 的教訓）— 需仔細區分
4. **Rank IC** — 因子預測力的核心指標，IC_IR > 0.5 為穩健
5. **不要追求最高 Sharpe** — 追求穩定性和可解釋性

## 執行流程

### Step 1：研究前準備
- 讀取 `策略研究.md` 了解已有研究結論
- 讀取 baseline 結果：
  - 3Y：`reports/backtests/dashboard_4y/backtest_20220101_20251231_metrics.json`
  - 6M：`reports/backtests/dashboard_6m/backtest_20240601_20241231_metrics.json`
- 確認該因子是否已被研究過（避免重複）

### Step 2：因子可行性評估（不需 Docker）
在執行回測前，先回答：
1. **資料來源**：FinMind 是否有對應 API？資料頻率？歷史可追溯到何時？
2. **Point-in-time**：能否通過 `_DataSlicer` 截斷？有無 look-ahead 風險？
3. **覆蓋率**：台股 universe 80 檔中預計有多少有數據？（< 30% 不建議繼續）
4. **理論基礎**：學術文獻或市場邏輯支持？
5. **與現有因子相關性**：是否與 PM/RM/TQ 高度相關？（相關性 > 0.6 則邊際貢獻有限）

如果可行性評估為「不建議」，直接跳到 Step 6 產出報告。

### Step 3：設計權重方案
產出 3 組候選權重（新因子取 10%/15%/20%，其餘等比縮減）：

**方案 A**（保守，10%）：
| 因子 | 原權重 | 新權重 |
|------|-------|-------|
| price_momentum | 55% | 49.5% |
| revenue_momentum | 25% | 22.5% |
| trend_quality | 20% | 18.0% |
| 新因子 | 0% | 10.0% |

**方案 B**（中等，15%）和 **方案 C**（積極，20%）類推。

### Step 4：執行回測（需 Docker）
對每個方案，分別跑 6M 和 3Y 回測。

⚠️ **注意**：如果新因子尚未在 `tw_stock.py` 中實作，則此步驟無法執行。需先確認：
- 因子計算邏輯是否已存在於 `_analyze_symbol()` 中
- 如不存在，此 command 只做 Step 1-2 的可行性評估，不執行回測

若可執行：
```bash
# 臨時修改 config（不要動正式的 settings.yaml）
# 在 reports/backtests/ 下建立研究子目錄
docker compose run --rm backtest --start 2024-06-01 --end 2024-12-31 --label research_<因子名>_a
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31 --label research_<因子名>_a
```

### Step 5：結果分析

#### 比對表

| 指標 | Baseline 6M | A 6M | B 6M | C 6M | Baseline 3Y | A 3Y | B 3Y | C 3Y |
|------|------------|------|------|------|------------|------|------|------|
| Sharpe | | | | | | | | |
| Alpha | | | | | | | | |
| MDD | | | | | | | | |
| 波動度 | | | | | | | | |
| Beta | | | | | | | | |

#### 關鍵檢查
- [ ] Sharpe 改善是否伴隨 Vol 等比增加？（若是 → 槓桿效應，非真實改善）
- [ ] 6M 和 3Y 方向是否一致？（不一致 → 可能 overfit）
- [ ] Alpha 是否改善？（Sharpe 改善但 Alpha 不變 → 只是承擔更多 Beta）
- [ ] MDD 是否惡化？（MDD 明顯惡化 → 尾部風險增加）

#### Deflated Sharpe Ratio 提醒
如果包含本次在內已測試 N 組參數，最佳 Sharpe 需打折：
> DSR 修正：測試 N 組後，期望最佳 Sharpe 約 sqrt(2×ln(N))。
> 需確認改善幅度超過此閾值才有統計意義。

### Step 6：產出研究報告

判定結果（三級）：
- **ADOPT** ✅：6M+3Y 均改善，Vol 不等比增加，理論基礎充足
- **REJECT** ❌：改善不顯著或有明顯副作用
- **NEEDS-MORE-DATA** ⚠️：資料不足或結果不一致，需更長回測期

報告格式：
```
## <因子名稱> 研究報告
日期：YYYY-MM-DD
研究者：Claude（/factor-research command）

### 假設
[用戶提出的假設]

### 可行性評估
[Step 2 結果]

### 回測結果
[Step 5 比對表]

### 結論：ADOPT / REJECT / NEEDS-MORE-DATA
[理由，包含具體數據]

### 後續建議
[如果 ADOPT：建議的權重配置和下一步驗證]
[如果 REJECT：為什麼不行，是否有修改版本值得嘗試]
```

### Step 7：追加到策略研究.md
將報告追加到 `策略研究.md` 末尾。

## 重要提醒
- 所有回覆使用**繁體中文**
- **絕對不要修改** `config/settings.yaml` 的正式設定
- **絕對不要修改** `tw_stock.py` 的原始碼
- 研究結果只寫入 `reports/` 和 `策略研究.md`
- 用 opus model 以確保深度推理
