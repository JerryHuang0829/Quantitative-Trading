# CLAUDE.md

## 語言

所有回覆請用**繁體中文**。程式碼中的 comment 可用英文。

---

## 專案概述

台股 long-only 量化投組系統。月中再平衡，三因子橫截面排名選股。

- **策略**：`tw_3m_stable` profile — `price_momentum`(55%) + `revenue_momentum`(25%) + `trend_quality`(20%)
- **已停用因子**：`institutional_flow`(0%)、`quality`(0%)
- **核心參數**：`top_n=8`、`max_same_industry=3`、`caution=0.70`
- **唯一正式設定**：`config/settings.yaml`

---

## 快速指令

```bash
# 測試（Windows 本地，29/87 通過；完整 87 需 Docker）
python -m pytest tests/ -v

# 回測（需 Docker + FINMIND_TOKEN）
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31 --benchmark 0050

# Walk-Forward（需 Docker）
docker compose run --rm --entrypoint python portfolio-bot scripts/walk_forward.py --train-months 18 --test-months 6 --start 2019-01-01 --end 2025-12-31

# Dashboard（Windows 本機）
streamlit run dashboard/app.py

# Paper trading 記錄（Docker）
docker compose run --rm --entrypoint python portfolio-bot scripts/paper_trade.py

# 實盤追蹤（Windows 本機，只讀寫 JSON）
python scripts/real_trade.py buy 2330 100 580.0
```

---

## 架構

```
main.py                          Live 常駐程式（每 15 分鐘檢查再平衡條件）
├── src/portfolio/tw_stock.py    核心選股（1293 行，最大最重要的檔案）
│   ├── build_tw_stock_universe()    建立候選股池
│   ├── _analyze_symbol()            單股因子分析
│   ├── _rank_analyses()             橫截面排名
│   └── _select_positions()          選股 + 權重分配
├── src/data/finmind.py          FinMind API + pickle cache + CSV fallback
├── src/backtest/engine.py       回測引擎（BacktestEngine + _DataSlicer）
│   └── _DataSlicer                  point-in-time 資料截斷（防 look-ahead）
├── src/backtest/metrics.py      KPI 計算 + stock split 自動前復權
├── src/backtest/universe.py     HistoricalUniverse（含下市股，防 survivorship bias）
├── src/strategy/regime.py       大盤多空判斷（ADX + SMA → risk_on/caution/risk_off）
├── src/features/institutional.py 法人因子（目前 weight=0，已停用）
├── src/utils/constants.py       共用常數（TW_TZ、TECH_SUPPLY_CHAIN_KEYWORDS）
├── src/utils/config.py          YAML config 載入 + default_strategy 合併
├── src/storage/database.py      SQLite（portfolio_rebalances / positions）
└── src/notify/telegram.py       Telegram 通知
```

### Scripts

| 腳本 | 用途 | 環境 |
|------|------|------|
| `scripts/run_backtest.py` | 回測 CLI（preflight + multi-token fallback） | Docker |
| `scripts/walk_forward.py` | Walk-Forward 滾動驗證 | Docker |
| `scripts/paper_trade.py` | Paper trading 記錄（append-only） | Docker |
| `scripts/paper_trade_eval.py` | Paper trading 績效評估 | Docker |
| `scripts/real_trade.py` | 小額實盤追蹤（buy/sell/status/report） | Windows |
| `scripts/refresh_reports.sh` | 一鍵重跑 Walk-Forward + Dashboard | Docker |
| `dashboard/` | Streamlit Dashboard（5 頁） | Windows |
| `CTSwithPython/` | 中國信託 CTS 交易 API 範例（嘉實資訊，PyQt5） | 未整合，待 P4.10 |

---

## 關鍵設計模式

### Point-in-time（最重要的設計原則）

`_DataSlicer` 截斷所有資料到 `as_of` 日期，**嚴格禁止 look-ahead bias**。回測中每個月的分析只看到截止日之前的資料。修改任何資料取得邏輯時，必須確保經過 `_DataSlicer` 截斷。

### 資料快取

- `_DiskCache`（pickle）：首次抓取寬歷史（4000 天），之後只增量補最新
- 快取 TTL：3 天容忍度（跨週末/假日）
- `stock_info` 額外有 CSV fallback（`_ensure_stock_info_csv`）

### 市場 Regime

`detect_regime()`（regime.py）用 0050 的 ADX 和 SMA 判斷：
- `risk_on`：上升趨勢 → 96% 曝險
- `caution`：盤整 → 70% 曝險
- `risk_off`：下降趨勢 → 35% 曝險，放寬進場條件

### 因子跳過邏輯

`_rank_analyses()` 中，`weight <= 0` 的因子會被完全跳過（不 fetch、不進 `active_weights`）。`weight_sum` 只算 active 因子後 normalize。這是 `institutional_flow=0%` 生效的機制。

### Stock Split 處理

`adjust_splits()`（metrics.py）自動偵測並前復權：
- 正分割：單日跌幅 > 40%（如 1:4 分割 → 跌 75%）
- 合股：單日漲幅 > 100%（如 10:1 合股 → 漲 900%）

---

## Config 結構（settings.yaml）

```yaml
system:
  mode: tw_stock_portfolio

backtest:                              # P5 E6 新增
  benchmark_lookback_days: 3000
  ohlcv_min_fetch_days: 2000
  market_value_fetch_days: 2500
  institutional_fallback_days: 500
  error_rate_threshold: 0.2
  factor_coverage_threshold: 0.3

portfolio:
  profile: tw_3m_stable
  top_n: 8
  max_same_industry: 3
  score_weights:
    price_momentum: 0.55
    trend_quality: 0.20
    revenue_momentum: 0.25
    institutional_flow: 0.00            # 已停用
  exposure:
    risk_on: 0.96
    caution: 0.70
    risk_off: 0.35
```

`engine.py` 的 `BacktestEngine.__init__()` 從 `config["backtest"]` 讀取參數，所有值都有向後相容的預設值。

---

## 測試

87 個測試，分佈在 8 個檔案。Docker 全通過，Windows 本地只有 29 通過（5 個 tw_stock 依賴的檔案需 Docker）。

```bash
# Windows 可跑的測試
python -m pytest tests/test_metrics.py tests/test_universe.py -v      # 29 passed
# test_data_slicer.py 在 Windows 上會 skip（需要 _DataSlicer import）

# Docker 全部
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v
```

| 測試檔 | 數量 | 覆蓋 |
|--------|-----|------|
| test_metrics.py | 27 | Sharpe/MDD/Alpha + known-answer + split adjust |
| test_data_slicer.py | 15 | point-in-time 截斷 |
| test_ranking.py | 10 | 因子排名 |
| test_selection.py | 12 | 選股門檻 + hold buffer |
| test_vol_weighting.py | 9 | 波動率加權 |
| test_zero_weight_skip.py | 8 | IF=0% 跳過 |
| test_degradation.py | 4 | data_degraded |
| test_universe.py | 2 | edge case |

`tests/conftest.py` 提供共用 fixtures：`portfolio_config`、`market_view_*`、`ten_eligible_analyses`、`make_analysis()`。

### 未覆蓋

- `BacktestEngine.run()` 整合測試
- `finmind.py` 單元測試（cache TTL、CSV fallback）
- `main.py` / `telegram.py` / `database.py`

---

## 環境

- **Docker**（`docker-compose.yml`）：`portfolio-bot`（live 常駐）+ `backtest`（CLI 工具）
- **Python 3.12**（Dockerfile），本地 Windows 用 3.11
- **必要環境變數**：`FINMIND_TOKEN`（API）、`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`（通知，可選）
- **Volume 掛載**：src/, config/, data/, logs/, reports/, scripts/, tests/

---

## 修改守則

### 絕對不要

- **不要調整策略參數**（`score_weights`、`exposure`、`top_n`）— 已經過 P1-P3 grid search + Codex 雙重驗證
- **不要把 `institutional_flow` 或 `quality` 拉回正式設定** — 已測試，績效下降
- **不要改 `caution/risk_off` exposure** — overfit 風險極高（78% 回測期為 caution/risk_off）
- **不要在資料取得邏輯中繞過 `_DataSlicer`** — 會造成 look-ahead bias
- **不要修改 `.env` 內容或將密鑰寫入程式碼**

### 修改時注意

- `tw_stock.py` 是核心（1293 行）。修改前必須理解 `_analyze_symbol` → `_rank_analyses` → `_select_positions` 三步流程
- `engine.py` 的 `_DataSlicer` 用 `empty DataFrame` 作為 sentinel（已嘗試但失敗），不是 None
- 新增 config 參數時，在 `BacktestEngine.__init__()` 中加預設值以保持向後相容
- 共用常數放 `src/utils/constants.py`，不要在多個檔案重複定義
- `reports/` 在 git 中（供跨機器比對），但不是唯一真相 — 換機器後應重跑
- commit message 用中文，格式參考 git log

### 程式碼風格

- 無 type checker（不用 mypy）；用 type hints 但不強制
- 無 linter 設定；遵循現有格式（PEP 8 基本遵循）
- import 排序：stdlib → third-party → local，alphabetical within groups
- logging 用 `logger = logging.getLogger(__name__)`

---

## 文件索引

| 文件 | 用途 |
|------|------|
| `Claude-Prompt.md` | 跨 session 交接（今天做了什麼 + 下一步方向） |
| `Codex-Prompt.md` | Codex 交叉驗證 Prompt |
| `優化紀錄.md` | 完整修改歷程 + 路線圖 + 雙視角評估 + 測試框架 |
| `策略研究.md` | P1-P3 因子研究結論 |
| `教學進度.md` | 程式碼逐檔解析、觀念教學 |
| `README.md` | 專案架構、Docker 操作 |

---

## Claude Code Skills（自訂指令）

專案根目錄 `.claude/` 下有自訂 commands 和 agents：

### Commands（斜線指令）

| 指令 | 用途 | 環境 | Model |
|------|------|------|-------|
| `/run-backtest` | 執行 Docker 回測 + 自動比對 baseline | Docker | default |
| `/walk-forward` | Walk-Forward 滾動驗證 + 分析 | Docker | default |
| `/monthly-rebalance` | 月度 Paper Trading + 實盤交易指引 | Docker + Windows | default |
| `/factor-research` | 因子研究（可行性評估 + 回測 + 報告） | Docker | opus |
| `/code-review-quant` | 雙視角程式碼審查（投資人 + 量化主管） | 本地 | opus |

### Agents（子代理）

| Agent | 用途 |
|-------|------|
| `quant-analyst` | 多步策略分析（診斷 Walk-Forward 視窗、比較回測、因子評估） |

### 使用範例

```bash
# 回測 3 年
/run-backtest 2022-01-01 2024-12-31

# Walk-Forward 驗證
/walk-forward

# 本月再平衡
/monthly-rebalance 2026-04

# 研究新因子
/factor-research volume_accumulation "上漲日成交量/下跌日成交量比率，篩選法人吸貨股"

# 審查程式碼
/code-review-quant src/backtest/engine.py
```

---

## 目前狀態（2026-04-06）

**已完成**：P0-P3 策略研究 + P4.0-P4.4/P4.8/P4.9 工程化 + P5 五輪雙視角審查

**待做（按優先度）**：
1. Docker 重跑 Walk-Forward summary（`reports/walk_forward/summary.json` 是舊資料）
2. 補 `BacktestEngine.run()` 整合測試 + `finmind.py` 單元測試
3. P4.5 Total Return Benchmark（含配息）
4. P4.6 Drift-aware 日報酬
5. 持續累積 Paper Trading 數據（2026-10 正式評估）

**不急**：P4.7 FinMind as_of、tw_stock.py 策略層 hardcode、P4.11 AI 整合

**未來整合**：
- P4.10 券商對接 — `CTSwithPython/` 已有中國信託 CTS 交易 API 範例（嘉實資訊，PyQt5 測試程式）。Paper trading 累積 6 個月後，用此 API 實作自動下單
