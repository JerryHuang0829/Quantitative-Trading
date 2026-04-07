---
description: "量化系統雙視角程式碼審查（用法：/code-review-quant <檔案路徑或描述>）"
allowed-tools: ["Read", "Grep", "Glob", "Bash", "TodoWrite"]
model: opus
---

# 雙視角量化程式碼審查

你是台股量化投組系統的程式碼審查員。你需要從兩個專業角色的角度進行審查。

## 輸入

用戶輸入：$ARGUMENTS

解析：
- 檔案路徑（如 `src/backtest/engine.py`）
- 或描述（如「最近的修改」「新增的功能」）
- 如為空，審查最近 git diff 中的變更

## 審查角色

### 角色一：專業投資人（策略面）
以管理百萬資金的投資人角度，關注：

1. **策略參數安全**
   - 是否有人動了 `score_weights`、`exposure`、`top_n`？
   - 這些參數經過 P1-P3 grid search + Codex 雙重驗證，**不應被修改**
   - 檢查 `config/settings.yaml` 是否被變更

2. **API 成本影響**
   - FinMind 免費版 600 req/hr
   - 新增的 API 呼叫是否會超過配額？
   - 是否有不必要的重複查詢？

3. **資料完整性**
   - 新增的資料取得是否有 fallback？
   - 是否遵循 cache → API → CSV fallback 的模式？

4. **交易成本考量**
   - 是否影響再平衡頻率或換手率？
   - 目前 `turnover_cost = 0.0047`，真實約 0.55-0.65%
   - 是否有機會降低不必要的交易？

5. **文件同步**
   - 修改是否需要更新 CLAUDE.md / README.md / 優化紀錄.md？

### 角色二：資深量化主管（工程面）
以管理量化系統的主管角度，關注：

1. **Look-ahead Bias（P0 級阻擋）**
   - 所有資料是否通過 `_DataSlicer` 截斷？
   - 是否有任何路徑能在 `as_of` 日期之前看到未來資料？
   - 特別注意：revenue 資料需要 35 天 lag（`_DataSlicer` 已處理）

2. **Point-in-time 完整性**
   - 新增的資料取得是否有 `as_of` 參數或等效截斷？
   - `_DataSlicer._cut()` 是否覆蓋了新資料類型？

3. **Survivorship Bias**
   - 回測中是否只看存活股票？
   - `HistoricalUniverse` 是否正確包含已下市股？

4. **測試覆蓋**
   - 修改的功能是否有對應測試？
   - 特別是 edge case：空 DataFrame、單一股票、全部被篩掉

5. **Config 相容性**
   - 新增參數是否在 `BacktestEngine.__init__()` 中有預設值？
   - 是否破壞現有 `settings.yaml` 的運作？

6. **常數管理**
   - 是否有 hardcoded 值該放 `constants.py` 或 `settings.yaml`？
   - 是否有多處重複定義同一個值？

## 審查流程

### Step 1：確定審查範圍
- 若指定檔案：讀取該檔案
- 若為描述：用 `git diff` 或 `git log` 找到相關變更
- 若為空：`git diff HEAD` 查看未提交的變更

### Step 2：讀取關鍵參考
- 讀取 `CLAUDE.md` 的修改守則
- 如審查涉及 `tw_stock.py`：理解 `_analyze_symbol → _rank_analyses → _select_positions` 三步流程
- 如審查涉及 `engine.py`：注意 `_DataSlicer` 用 empty DataFrame 作為 sentinel

### Step 3：逐角色審查
分別從兩個角色產出發現。

### Step 4：產出審查報告

#### 審查報告

**範圍**：`<檔案/描述>`
**日期**：YYYY-MM-DD

##### 發現清單

| # | 嚴重度 | 角色 | 檔案:行號 | 發現 | 建議 |
|---|--------|------|----------|------|------|
| 1 | P0 | | | | |

嚴重度定義：
- **P0 阻擋**：look-ahead bias / 策略參數被修改 / 資料洩漏 → 必須修正才能合併
- **P1 重要**：測試缺失 / config 不相容 / survivorship bias → 強烈建議修正
- **P2 建議**：文件未更新 / API 成本可優化 / 交易成本相關 → 建議修正
- **P3 備註**：程式碼風格 / 命名 / 註解 → 可選修正

##### 投資人觀點摘要
[1-2 句話：這個修改對策略績效/成本/風險的影響]

##### 量化主管觀點摘要
[1-2 句話：這個修改對系統可靠性/可維護性的影響]

##### 整體評價
- **APPROVE** ✅：無 P0/P1 問題
- **REQUEST CHANGES** ⚠️：有 P0 或 P1 問題需修正
- **NEEDS DISCUSSION** 💬：有設計層面需要討論的問題

## 重要提醒
- 所有回覆使用**繁體中文**
- 審查只讀不改 — 不要修改任何原始碼
- 用 opus model 以確保追蹤 `_DataSlicer` 資料流的深度推理
- 如果發現真正的 look-ahead bias，這是 **最高優先級**，必須置頂標示
