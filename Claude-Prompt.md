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
| 4Y（2022-2025） | 1.47 | +26.34% | -31.07% | IS+OOS |

OOS Sharpe 1.81 vs IS 1.85，衰減僅 2%。

### 完成狀態

| 階段 | 狀態 |
|------|------|
| P0 Research Integrity | ✅ 全部完成 |
| P1 Grid Search（max_same_industry 2→3） | ✅ 落地 + Codex 驗證 |
| P2 因子/Exposure（IF 0%） | ✅ 落地 + Codex + Claude 雙重驗證 |
| P3 策略擴展（vol_weighted ❌、quality ❌） | ✅ 研究完成 + Codex 驗證 |
| 架構評估（Claude + Codex 交叉驗證） | ✅ 完成（6 項 Codex 發現全數確認） |
| P4.0 Paper trading 可審計性 | ✅ append-only + 讀取 DB |
| P4.1 Benchmark split 修復 | ✅ `adjust_splits()` 自動前復權 |
| P4.2 Known-answer test | ✅ 22 個 metrics 測試全通過 |
| 2025 OOS 回測（8 個區間） | ✅ 全部完成並記錄 |

---

## 二. 本輪完成的修復（2026-04-01）

### P4.0：Paper Trading 可審計性

- `paper_trade.py` 改為 append-only + 讀取 DB（`get_latest_rebalance()`）
- `paper_trade_eval.py` 只使用正式紀錄（`is_rerun=false`）
- `database.py` 新增 `get_latest_rebalance()` 方法
- 7 個 E2E 測試通過

### P4.1：Benchmark Stock Split 自動前復權

- `metrics.py` 新增 `adjust_splits()`：偵測單日跌幅 >40% → 前復權
- `engine.py:272`：benchmark 日報酬前先經過 split 調整
- 2025 全年 benchmark 從 -71.52%（失真）修正為 +34.17%（正確）
- Alpha 從虛高 +113.85% 修正為真實 +8.16%
- 8 個 `TestAdjustSplits` 測試全通過

### P4.2：Known-Answer Test

- 5 個精確值測試（Sharpe、MDD -20%、Alpha/Beta、波動率、總報酬）
- 22 個 metrics 測試全通過（Windows 本機可跑）

---

## 三. 關鍵檔案位置

| 檔案 | 用途 |
|------|------|
| `config/settings.yaml` | 策略參數（唯一正式設定） |
| `src/backtest/metrics.py` | KPI 計算 + `adjust_splits()` |
| `src/backtest/engine.py` | 回測引擎（point-in-time 月度再平衡） |
| `src/portfolio/tw_stock.py` | 核心選股邏輯 |
| `scripts/paper_trade.py` | Paper trading 記錄器（append-only） |
| `scripts/paper_trade_eval.py` | Paper trading 績效評估 |
| `tests/test_metrics.py` | 22 個 metrics + split 測試 |
| `reports/backtests/split_fix/` | 修復後的 OOS 回測結果 |
| `reports/paper_trading/history.json` | Paper trading 歷史紀錄 |

---

## 四. 下一輪最高優先事項

### P4.3：Walk-Forward 驗證框架（3-5 天）

**問題：** 目前只有單次 IS/OOS 比對（2022-2024 vs 2025），缺乏系統化滾動驗證。

**修復方案：** 在 engine.py 新增 `walk_forward_backtest()`：
- 滾動視窗：18 個月訓練 + 6 個月測試
- 自動產出多段 OOS 績效曲線
- 參數穩定性報告（各 window 的 Sharpe/Alpha 分布）

**為什麼重要：** 單次 OOS 可能只是運氣好。多段滾動 OOS 能確認策略在不同市場環境下都有效。

### P4.4-P4.11 待做清單

| 優先度 | 項目 | 工作量 |
|--------|------|--------|
| P4.4 | Hardcoded 常數提到 config | 半天 |
| P4.5 | Total return benchmark（含配息） | 1-2 天 |
| P4.6 | Drift-aware 日報酬 | 1-2 天 |
| P4.7 | FinMind as_of plumbing | 2-3 天 |
| P4.8 | 主題集中風險指標 | 研究題 |
| P4.9 | `data_degraded` false alarm 修復 | 低優先 |
| P4.10 | 券商對接 | paper trading 通過後 |
| P4.11 | AI 整合（市場風向 + 事件風控） | 最後 |

---

## 五. 目前不要做的事

- 調整 `caution/risk_off` exposure（in-sample overfit 風險太高）
- 把 `vol_weighted` 或 `quality` 拉回正式設定
- 先改 `exposure` / `top_n`（已研究過，目前設定最佳）
- 把 AI 加進 ranking（AI 只做市場風向 + 事件風控，不進選股）
- 在 paper trading 累積 6 個月之前投入實資金

---

## 六. 已知技術限制

- `pandas_ta` 只裝在 Docker，Windows 本機只能跑 `test_metrics.py`
- 完整測試需在 Docker 跑：`docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v`
- FinMind 免費版 600 req/hr，3Y 回測需 ~400-500 次呼叫
- MarketValue API 免費版不可用，fallback 到 size proxy
- `data_degraded: true` 在 2025 回測是 false alarm（IF coverage=0 因為 IF weight=0）

---

## 七. 文件索引

| 文件 | 內容 |
|------|------|
| `README.md` | 專案架構、模組說明、Docker 操作 |
| `教學進度.md` | 給專案擁有者的學習筆記（白話解說所有概念） |
| `策略研究.md` | 因子研究結論、P1-P3 決策記錄、OOS 結果 |
| `優化建議.md` | 雙視角評估（投資人+工程主管）、P4 路線圖 |
| `優化紀錄.md` | 所有修改的詳細紀錄（P4.1/P4.2 修復、OOS 回測、交叉驗證） |
| `Claude-Prompt.md` | 本檔（交接用） |

---

## 八. Claude 回覆格式

請用這個格式回覆：

```text
1. Findings（發現了什麼）
2. Changes made（做了什麼改動）
3. Validation（如何驗證）
4. Residual risks（殘餘風險）
5. Next actions（下一步）
```
