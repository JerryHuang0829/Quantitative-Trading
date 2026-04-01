# Claude 交接 Prompt

最後更新：2026-04-01

請用中文回覆。

---

## 一. 專案現況總覽

### 策略設定

- 台股 long-only，月中再平衡，`tw_3m_stable` profile
- 三因子：`price_momentum`（55%）、`trend_quality`（20%）、`revenue_momentum`（25%）
- 已停用：`institutional_flow`（0%，rank IC 全期為負）、`quality`（0%，稀釋動能）
- `top_n=8`、`max_same_industry=3`、`caution exposure=0.70`

### 回測績效

| 回測 | Sharpe | Alpha | MDD | 性質 |
|------|--------|-------|-----|------|
| 6M（2024-H2） | 1.08 | +13.52% | -21.50% | In-Sample |
| 3Y（2022-2024） | 1.85 | +48.43% | -21.50% | In-Sample |
| **2025 全年** | **1.81** | **+8.16%** | **-19.25%** | **Out-of-Sample** |
| **2019-2020** | **1.91** | **+27.03%** | **-17.41%** | **Out-of-Sample** |
| 4Y（2022-2025） | 1.44 | +27.40% | -29.40% | IS+OOS |
| **Walk-Forward 平均** | **1.22** | **+39.70%** | **-23.80%** | **11 段 OOS 平均** |

### 完成狀態

| 階段 | 狀態 |
|------|------|
| P0 Research Integrity | ✅ 全部完成 |
| P1 Grid Search（max_same_industry 2→3） | ✅ 落地 + Codex 驗證 |
| P2 因子/Exposure（IF 0%） | ✅ 落地 + Codex + Claude 雙重驗證 |
| P3 策略擴展（vol_weighted ❌、quality ❌） | ✅ 研究完成 + Codex 驗證 |
| 架構評估（Claude + Codex 交叉驗證） | ✅ 完成（6 項 Codex 發現全數確認） |
| P4.0 Paper trading 可審計性 | ✅ append-only + 讀取 DB |
| P4.1 Benchmark split 修復 | ✅ `adjust_splits()` 自動��復權 |
| P4.2 Known-answer test | ✅ 22 個 metrics 測試全通過 |
| 2025 OOS 回測（8 個區間） | ✅ 全部完成並記錄 |
| P4.3 Walk-Forward 驗證（11 個半年視��） | ✅ 平均 Sharpe 1.22，勝率 64% |
| 2019-2020 OOS 回測 | ✅ Sharpe 1.91，疫情防禦完美 |
| P4.8 主題集中風險指標 | ✅ `theme_concentration` 監控欄位 |
| P4.9 `data_degraded` false alarm 修復 | ✅ IF=0% 不再觸發 |
| Streamlit Dashboard | ✅ 5 個頁面（持股建議/績效走勢/Walk-Forward/模擬投資/實盤追蹤） |
| 小額實盤追蹤工具 | ��� `scripts/real_trade.py`（買賣記錄/月結/報告） |
| 日頻報酬序列輸出 | ✅ `run_backtest.py` 產出 `*_daily_returns.json` |

---

## 二. 本輪完成的工作（2026-04-01，第一台電腦）

### P4.9 `data_degraded` false alarm 修復

- 原因：IF weight=0 但 coverage=0 → 觸發 degraded
- 修法：`engine.py` degraded 判定只檢查 weight>0 的因子
- Walk-Forward 11 個視窗從全部 degraded=true → 正確的 false

### P4.8 主題集中風險指標

- `engine.py` 新增 `_compute_theme_concentration()`
- 每期 snapshot 自動計算科技供應鏈佔比（平均 56%，中位 70%）
- 純監控指標，不加硬性限制（限制 alpha 來源會傷害績效）
- `positions` 加入 `industry` 欄位

### P4.3 Walk-Forward 驗證框架

- 新增 `scripts/walk_forward.py`
- 11 個半年視窗（2020-H2 → 2025-H2）
- 平均 Sharpe 1.22，勝率 64%，最差 MDD -23.8%
- 趨勢市強、反轉市弱，獲利幅度大於虧損幅度

### 2019-2020 OOS 回測

- Sharpe 1.91���Alpha +27.03%��MDD -17.41%
- 疫情防禦完美：2020-02 即轉 risk_off（96%→35%），避開 3 月崩盤

### Streamlit Dashboard（5 頁）

- `dashboard/app.py`：主頁（策略白話說明）
- `dashboard/pages/1_持股建議.py`：本月該買什麼 + 小資族建議
- `dashboard/pages/2_績效走勢.py`：累積報酬曲線 + 回撤圖（需日頻資料）
- `dashboard/pages/3_WalkForward.py`：11 段成績單 + 白話解讀
- `dashboard/pages/4_PaperTrading.py`：模擬投資月度紀錄
- `dashboard/pages/5_實盤追蹤.py`：實際投資損益追蹤
- 啟動：`streamlit run dashboard/app.py`

### 小額實盤追��工具

- `scripts/real_trade.py`：buy/sell/status/close/report 指令
- 自動計算手續費（最低 20 元）和證交稅（0.3%）
- 月結功能：輸入各持股現價，計算月損益 vs paper trading 比較
- 資料存在 `reports/real_trading/`

### 日頻報酬序列輸出

- `run_backtest.py` 新增輸出 `*_daily_returns.json`
- 含 portfolio 和 benchmark 的每日報酬率
- Dashboard 績效頁用此資料畫累積報酬曲線和回撤圖
- 已產出：`dashboard_4y/`（2022-2025）和 `dashboard_6m/`（2024-H2）

---

## 三. 關鍵檔案位置

| 檔案 | 用途 |
|------|------|
| `config/settings.yaml` | 策略參數（唯一正式設定） |
| `src/backtest/engine.py` | 回測引擎 + `_compute_theme_concentration()` |
| `src/backtest/metrics.py` | KPI 計算 + `adjust_splits()` |
| `src/portfolio/tw_stock.py` | 核心選股邏輯 |
| `scripts/paper_trade.py` | Paper trading 記錄器（append-only） |
| `scripts/real_trade.py` | 小額實盤追蹤（buy/sell/status/close/report） |
| `scripts/walk_forward.py` | Walk-Forward 驗證腳本 |
| `scripts/run_backtest.py` | 回測 CLI（含日頻報酬輸出） |
| `dashboard/` | Streamlit Dashboard（5 頁） |
| `tests/test_metrics.py` | 22 個 metrics + split 測試 |
| `reports/backtests/dashboard_4y/` | 4Y 回測（含日頻資料） |
| `reports/walk_forward/summary.json` | Walk-Forward 匯總 |
| `reports/paper_trading/` | Paper trading 紀錄 |
| `reports/real_trading/` | 實盤追蹤紀錄 |

---

## 四. 下一步

### 當前最重要：累積 Paper Trading + 小額實盤數據

策略的 in-sample 優化（P1-P3）和驗證（P4.0-P4.9）全部完成。
繼續調參的 overfit 風險大於收益。現在需要的是時間。

時間表：
- 2026-04-14：執行第二筆 paper trading + 小額實盤開始
- 2026-04~06：累積數據，不做判斷
- 2026-07~09：初步趨勢觀察
- 2026-10：初步評估（對比 Walk-Forward 平均 Sharpe 1.22）
- 警戒線：Sharpe < 0.7 或 Alpha 轉負 → 觸發診斷

### P4 待做清單（不急）

| 編號 | 項目 | 建��� |
|------|------|------|
| P4.4 | Hardcoded 常數提到 config | 暫緩（參數不會再調） |
| P4.5 | Total return benchmark（含配息） | 低優先（同口徑比較已公平） |
| P4.6 | Drift-aware 日報酬 | 低優先（月頻影響小） |
| P4.7 | FinMind as_of plumbing | 低優先（未出問題） |
| P3.5 | 期中止損 | 值得研究但風險高 |
| P4.10 | 券商對接 | 等 paper trading 6 個月後 |
| P4.11 | AI 整合 | 最後 |

---

## 五. 目前不要做的事

- 調整 `caution/risk_off` exposure（overfit 風險太高）
- 把 `vol_weighted` 或 `quality` 拉回正式設定
- 改 `exposure` / `top_n`（已研究��，目前設定最佳）
- 把 AI 加進 ranking（AI 只做市場風向 + 事件風控）

---

## 六. 技術備註

- Dashboard 在 Windows 本機跑（`streamlit run dashboard/app.py`）
- 需要 FinMind 的指令在 Docker 跑（`docker compose run ...`）
- `real_trade.py` 在 Windows 本機跑（只讀寫 JSON）
- `data_degraded` false alarm 已修復（IF=0% 不再觸發）
- 65 個 pytest 測試全通過
- 日頻報酬 JSON 由 `run_backtest.py` 自動產出

---

## 七. 文件索引

| 文件 | 內容 |
|------|------|
| `Claude-Prompt.md` | 本檔（交接用） |
| `策略研究.md` | 因子研究結論、P1-P3 決策、OOS 結果、Walk-Forward |
| `優化建議.md` | 雙視角評估、P4 路線圖、架構評估 |
| `優化紀錄.md` | 所有修改的詳細紀錄 |
| `README.md` | 專案架構、Docker 操作 |
