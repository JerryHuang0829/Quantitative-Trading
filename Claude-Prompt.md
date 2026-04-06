# Claude 交接 Prompt

最後更新：2026-04-07
請用中文回覆。

---

## 一. 專案現況總覽

### 策略設定

- 台股 long-only，月中再平衡，`tw_3m_stable` profile
- 三因子：`price_momentum`（55%）、`trend_quality`（20%）、`revenue_momentum`（25%）
- 已停用：`institutional_flow`（0%，rank IC 全期為負）、`quality`（0%，稀釋動能）
- `top_n=8`、`max_same_industry=3`、`caution exposure=0.70`

### 回測績效（P6，2026-04-07 乾淨 cache + backtest_mode）

| 回測 | Sharpe | Alpha | MDD | CVaR 95% | Tail Ratio | 偏態 | JB p | 性質 |
|------|--------|-------|-----|----------|------------|------|------|------|
| 6M（2024-H2） | 0.81 | +5.94% | -25.48% | -4.76% | 1.00 | -0.74 | 0.00 | IS |
| 4Y（2022-2025） | 1.41 | +25.68% | -28.09% | -3.60% | 0.98 | -0.50 | 0.00 | IS+OOS |
| **Walk-Forward 平均** | **1.22** | **+39.70%** | **-23.80%** | — | — | — | — | **11 段 OOS** |

注意：P5→P6 的 4Y Sharpe 1.44→1.41 差異來自不同電腦 cache 資料差異，選股邏輯未改動。

### 完成狀態

| 階段 | 狀態 |
|------|------|
| P0 Research Integrity | ✅ |
| P1 Grid Search（max_same_industry 2→3） | ✅ + Codex 驗證 |
| P2 因子/Exposure（IF 0%） | ✅ + Codex + Claude 雙重驗證 |
| P3 策略擴展（vol_weighted ❌、quality ❌） | ✅ + Codex 驗證 |
| P4.0-P4.4 / P4.8 / P4.9 工程化 | ✅ |
| P5 雙視角審查 + 工程修復（5 輪 + Codex） | ✅ 87 測試 |
| **P6 度量層 + Cache 機制** | **✅ 2026-04-07 完成** |
| Streamlit Dashboard（5 頁） | ✅ |
| 小額實盤追蹤工具 | ✅ `scripts/real_trade.py` |
| Claude Code Skills（5 commands + 1 agent） | ✅ `.claude/commands/` + `.claude/agents/` |

---

## 二. 2026-04-06~07 完成的工作（P6）

### P6 修改清單

| 項目 | 內容 | 檔案 |
|------|------|------|
| P6.1 | `slippage_bps` 5→10（中型股實際約 10-15bps/邊） | `config/settings.yaml` |
| P6.2 | CVaR 95% + Tail Ratio + Drawdown Duration（最大/平均水下天數 + 水下比例） | `src/backtest/metrics.py` |
| P6.3 | Skewness + Kurtosis + Jarque-Bera 常態性檢定（p<0.05 → Sharpe 不完全可信） | `src/backtest/metrics.py` |
| P6.4 | Bootstrap Sharpe 95% CI（10,000 次重抽，CI 含 0 → 策略不顯著） | `scripts/walk_forward.py` |
| P6.5 | 動能分散度（`score_dispersion`：eligible 分數 std + IQR） | `src/backtest/engine.py` |
| P6.6 | `backtest_mode`：回測時跳過所有 cache TTL，直接用 cache，0 API 呼叫 | `src/data/finmind.py` |
| P6.7 | `scipy>=1.11.0` 加入依賴 | `requirements.txt` |

### P6.6 backtest_mode 詳細說明

**問題**：`_DiskCache` 各資料集有 TTL（ohlcv 3 天、institutional 7 天、revenue 45 天等），過期後重打 FinMind API。但免費額度 600 req/hr 不夠用 → 部分股票 `Failed to fetch` → 候選股池每次不同 → 回測結果不可重現。

**解法**：`FinMindSource` 新增 `backtest_mode: bool = False` 參數。開啟後，所有 `fetch_*` 方法在 cache 存在時直接回傳，跳過 TTL 和增量更新邏輯。

**呼叫端修改**：
- `scripts/run_backtest.py`：`FinMindSource(token=token, backtest_mode=True)` ✅
- `scripts/walk_forward.py`：`FinMindSource(token=token, backtest_mode=True)` ✅
- `main.py`（Live 模式）：預設 `False`，不受影響
- `scripts/paper_trade.py`：預設 `False`，需要最新資料

**效果**：連續跑 3 次回測，數字完全一致。速度從幾分鐘（打 API）降到幾秒（純 cache 讀取）。

### Claude Code Skills（同日新增）

在 `Quantitative Trading/.claude/` 下建立 5 個 commands + 1 個 agent（已在 git repo 內）：

| 類型 | 名稱 | 用途 |
|------|------|------|
| Command | `/run-backtest` | Docker 回測 + 自動比對 baseline |
| Command | `/walk-forward` | Walk-Forward 驗證 + PASS/FAIL 判定 |
| Command | `/monthly-rebalance` | 月度 Paper Trading + 實盤指引 |
| Command | `/factor-research` | 因子研究（opus model） |
| Command | `/code-review-quant` | 雙視角程式碼審查（opus model） |
| Agent | `quant-analyst` | 多步策略分析子代理 |

### 文件整理（同日）

- `優化建議.md` 已合併進 `優化紀錄.md`（刪除重複檔案）
- `Codex-Prompt.md` 重寫為 P6 + 整體架構獨立驗證
- `CLAUDE.md` 新增 Skills 索引區塊
- 所有引用 `優化建議.md` 的檔案已更新指向 `優化紀錄.md`

### Cache 資料替換（04-07）

原本的 `data/cache/` 在 04-06 首次跑 P6 回測時被部分覆蓋（TTL 過期 → 重抓 API → 部分失敗 → 混合體）。已從另一台電腦匯入乾淨的 cache_backup 替換。

替換前後比較：
- ohlcv: 1955 → **2034** 支股票
- institutional: 134 → **527**
- revenue: 191 → **554**
- 舊的混合 cache 保留在 `data/cache_polluted/`（可刪除）

### 驗證結果

| 驗證項 | 結果 |
|--------|------|
| Docker 87 測試 | **87 passed** ✅ |
| 本機 29 測試 | **29 passed** ✅ |
| 6M 回測（乾淨 cache） | Sharpe 0.81, Alpha +5.94% ✅ |
| 4Y 回測（乾淨 cache） | Sharpe 1.41, Alpha +25.68% ✅ |
| backtest_mode 可重現性 | 連跑 3 次數字一致 ✅ |
| P6 新指標全部輸出 | CVaR/Tail Ratio/偏態/峰度/JB 全有 ✅ |

---

## 三. 關鍵檔案位置

| 檔案 | 用途 |
|------|------|
| `config/settings.yaml` | 策略參數 + `backtest:` + `slippage_bps: 10` |
| `src/backtest/engine.py` | 回測引擎 + `_DataSlicer` + `_compute_score_dispersion()` |
| `src/backtest/metrics.py` | KPI 計算 + CVaR/Tail Ratio/偏態/峰度/JB + `adjust_splits()` |
| `src/backtest/universe.py` | 歷史 Universe 管理 |
| `src/portfolio/tw_stock.py` | 核心選股邏輯（1293 行，不要動） |
| `src/data/finmind.py` | FinMind API + pickle cache + `backtest_mode` + CSV fallback |
| `src/data/twse_scraper.py` | TWSE/TPEX JSON API（成交金額排名，用於 universe 預篩） |
| `src/data/base.py` | DataSource 抽象介面 |
| `src/utils/constants.py` | 共用常數 |
| `scripts/run_backtest.py` | 回測 CLI（`backtest_mode=True`） |
| `scripts/walk_forward.py` | Walk-Forward（`backtest_mode=True` + Bootstrap Sharpe CI） |
| `scripts/paper_trade.py` | Paper trading 記錄器 |
| `scripts/real_trade.py` | 小額實盤追蹤 |
| `dashboard/` | Streamlit Dashboard（5 頁） |
| `tests/` | 87 個測試（8 個測試檔） |
| `.claude/commands/` | 5 個 Claude Code skills |
| `.claude/agents/quant-analyst.md` | 量化分析子代理 |
| `Codex-Prompt.md` | Codex 驗證 Prompt（P6 + 整體架構） |
| `data/cache/` | pickle 快取（.gitignore，不進 git） |
| `data/cache_polluted/` | 被汙染的舊 cache（可刪除） |
| `data/cache_backup/` | 空資料夾（backup 已移入 cache/，可刪除） |

---

## 四. 下一步行動清單（按優先度）

### 第一優先：Docker 執行

```bash
# 重跑 Walk-Forward（含 Bootstrap Sharpe CI + backtest_mode）
docker compose run --rm --entrypoint python portfolio-bot \
    scripts/walk_forward.py \
    --train-months 18 --test-months 6 \
    --start 2019-01-01 --end 2025-12-31 \
    --output-dir reports/walk_forward

# 驗證：summary.json 應包含 bootstrap_sharpe_ci_lo/hi/significant
```

### 第二優先：補測試覆蓋

| 項目 | 檔案 | 說明 |
|------|------|------|
| BacktestEngine 整合測試 | `tests/test_engine.py`（新建） | 用 mock data 跑 mini backtest |
| finmind.py 核心測試 | `tests/test_finmind.py`（新建） | cache hit/miss、backtest_mode |

### 第三優先：回測精度

| 項目 | 說明 |
|------|------|
| P4.5 Total Return Benchmark | 含配息，修正 Alpha 偏差 ~2-3%/年 |
| P4.6 Drift-aware 日報酬 | 持有期內權重隨股價更新 |

### Paper Trading 時間表

- 2026-03：第一筆 ✅
- 2026-04-14：執行第二筆
- 2026-04~06：累積數據
- 2026-10~：正式評估（對比 Walk-Forward Sharpe 1.22）
- **警戒線**：Sharpe < 0.7 或 Alpha 轉負

---

## 五. 不要做的事

- ❌ 調整 `score_weights` / `exposure` / `top_n` / `caution`（已 grid search + Codex 驗證）
- ❌ 把 `institutional_flow` 或 `quality` 拉回（已測試，績效下降）
- ❌ 把 AI 加進 ranking（AI 只做市場風向 + 事件風控）
- ❌ 同時改多個東西（一次改一項）
- ❌ 在 paper trading 累積 6 個月前投入實資金
- ❌ 刪除 `data/cache/`（回測依賴它，重建需 10+ 小時 API 額度）

---

## 六. 技術備註

- **Docker vs Windows**：回測/Walk-Forward/Paper Trading 在 Docker 跑；Dashboard 和 real_trade.py 在 Windows 本機
- **測試**：Docker 87 passed；Windows 本地 29 passed
- **Cache**：`data/cache/` 在 `.gitignore`，不進 git。換電腦需手動複製或重建
- **pickle 版本相容性**：backup cache 由較新版 numpy 建立，Windows 本機 Python 3.11 讀不了（`numpy._core` 錯誤），Docker 正常。如需本機跑回測，需升級 numpy
- **scipy**：P6.3 新增依賴，已加入 `requirements.txt`，Docker image 已重建
- **`--slippage-bps` CLI 參數**：`run_backtest.py` 預設值 5，`settings.yaml` 設 10。engine.py 會優先讀 yaml
- **`--label` 不存在**：`run_backtest.py` 沒有 `--label` 參數，用 `--output-dir` 指定輸出目錄

---

## 七. 文件索引

| 文件 | 內容 | 最後更新 |
|------|------|---------|
| `Claude-Prompt.md` | 本檔（Claude 交接用） | 2026-04-07 |
| `Codex-Prompt.md` | Codex 驗證 Prompt（P6 + 整體架構） | 2026-04-06 |
| `優化紀錄.md` | 完整修改歷程 + 路線圖 + 回測數據 + 雙視角評估 | 2026-04-07 |
| `策略研究.md` | P1-P3 因子研究結論 | 2026-04-01 |
| `教學進度.md` | 程式碼逐檔解析、觀念教學 | 2026-04-02 |
| `README.md` | 專案架構、Docker 操作 | 2026-04-02 |
| `CLAUDE.md` | Claude Code 指引 + Skills 索引 | 2026-04-06 |
