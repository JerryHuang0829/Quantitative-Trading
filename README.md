# 台股量化投組系統

這個專案已從逐檔 `BUY/SELL` 訊號 bot，改成以 **台股 long-only 量化投組** 為核心的系統。主流程現在以「月度再平衡」為中心，而不是單檔即時訊號：

1. 讀取台股股票池
   - 可從 `symbols` 手動指定，也可由 FinMind `stock_info` + 成交金額排序（close×volume）自動建池
2. 取得日線、法人與月營收資料
3. 做橫截面 ranking
4. 產生目標持股與目標權重
5. 將再平衡結果寫入 SQLite 並推送 Telegram

## 目前架構

```text
=== Live 月度再平衡 ===

config/settings.yaml
        |
        v
main.py
        |
        v
src/portfolio/tw_stock.py
  - auto universe builder
  - market proxy filter
  - universe analysis
  - cross-sectional ranking
  - target portfolio construction
        |
        +--> src/data/finmind.py        (FinMind API + 磁碟快取)
        +--> src/data/twse_scraper.py   (TWSE/TPEX 成交金額)
        +--> src/features/institutional.py (法人連續淨流量因子)
        +--> src/storage/database.py
        +--> src/notify/telegram.py

=== 回測 + Walk-Forward ===

scripts/run_backtest.py              (回測 CLI + preflight + multi-token)
scripts/walk_forward.py              (Rolling OOS 滾動驗證)
scripts/refresh_reports.sh           (一鍵重跑所有報告)
        |
        v
src/backtest/engine.py
  - BacktestEngine: 月度再平衡回測 (config 驅動)
  - _DataSlicer: point-in-time 資料截斷
        |
        +--> src/backtest/universe.py   (TWSE turnover 排序 + size proxy)
        +--> src/backtest/metrics.py    (KPI 計算 + split adjust)
        +--> src/portfolio/tw_stock.py  (共用選股邏輯)
        +--> src/utils/constants.py     (共用常數：TW_ROUND_TRIP_COST、MIN_OHLCV_BARS 等)

=== Paper / Real Trading ===

scripts/paper_trade.py               (Paper Trading 記錄 + 集中度顯示)
scripts/real_trade.py                (小額實盤追蹤)
scripts/paper_trade_eval.py          (Paper Trading 績效評估)
```

## 策略定位

- 市場：台股現貨
- 風格：long-only 短中線波段
- 節奏：月度再平衡
- 目前建議主線：`tw_3m_stable`
- 目標持有：平均約 3 個月，實際允許 2 到 4 個月自然流動
- 核心因子（P2 後）：
  - `price_momentum`（55%）
  - `revenue_momentum`（25%）
  - `trend_quality`（20%）
  - ~~`institutional_flow`~~（已移除，rank IC 全期為負）
- 市場風控：
  - 使用 `0050` 當市場代理
  - 將市場狀態切成 `risk_on / caution / risk_off`
  - 用總曝險而不是單純停機處理弱市

## 主要模組

### Live

- [main.py](./main.py) — 進入點，排程與月度再平衡觸發
- [src/portfolio/tw_stock.py](./src/portfolio/tw_stock.py) — 台股投組引擎（universe 分析、排名、目標持股建構）
- [src/data/finmind.py](./src/data/finmind.py) — FinMind API 介接 + 磁碟持久化快取
- [src/data/twse_scraper.py](./src/data/twse_scraper.py) — TWSE/TPEX 成交金額爬蟲（universe 預篩）
- [src/features/institutional.py](./src/features/institutional.py) — 法人連續淨流量因子（70% 外資 + 30% 投信）
- [src/storage/database.py](./src/storage/database.py) — SQLite 儲存（portfolio_rebalances / positions）
- [src/notify/telegram.py](./src/notify/telegram.py) — Telegram 再平衡摘要通知

### 回測

- [scripts/run_backtest.py](./scripts/run_backtest.py) — 回測 CLI 入口（preflight check + multi-token fallback）
- [scripts/walk_forward.py](./scripts/walk_forward.py) — Rolling OOS 驗證（滾動 18M 訓練 + 6M 測試，非真正 Walk-Forward）
- [scripts/refresh_reports.sh](./scripts/refresh_reports.sh) — 一鍵重跑 Walk-Forward + Dashboard 6M
- [src/backtest/engine.py](./src/backtest/engine.py) — 回測引擎（point-in-time 月度再平衡 + _DataSlicer 資料截斷 + config 驅動）
- [src/backtest/universe.py](./src/backtest/universe.py) — 回測 universe 管理（TWSE turnover 排序 + size proxy fallback）
- [src/backtest/metrics.py](./src/backtest/metrics.py) — KPI 計算（Sharpe / Alpha / MDD 等）+ 報告生成 + stock split 自動前復權（含 reverse split）
- [src/utils/constants.py](./src/utils/constants.py) — 共用常數（TW_TZ、TW_ROUND_TRIP_COST、MIN_OHLCV_BARS、MOMENTUM_*、REVENUE_LAG_DAYS、TECH_SUPPLY_CHAIN_KEYWORDS）

## 設定重點

核心設定在 [config/settings.yaml](./config/settings.yaml)。

```yaml
system:
  mode: tw_stock_portfolio

backtest:
  benchmark_lookback_days: 3000
  ohlcv_min_fetch_days: 2000
  market_value_fetch_days: 2500        # 監控用，不用於選股排序
  institutional_fallback_days: 500
  error_rate_threshold: 0.2
  factor_coverage_threshold: 0.3

portfolio:
  profile: tw_3m_stable
  rebalance_frequency: monthly
  rebalance_day: 12
  top_n: 8
  hold_buffer: 3
  max_position_weight: 0.12
  market_proxy_symbol: "0050"
  use_auto_universe: true
  auto_universe_size: 80
  min_price: 20
  min_avg_turnover: 50000000
```

若 `use_auto_universe: true`，系統會先用 FinMind 的 `taiwan_stock_info` 建出全市場候選池，再以**成交金額（close×volume 20日均值）**排序篩選前 80 名，套用市場別、ETF/ETN/權證排除等條件。market_value 資料僅供 dashboard 監控用，不影響選股排序。

`profile: tw_3m_stable` 代表目前推薦的主版本，偏向「較高且較穩的淨利」取向：

- 較分散的持股數
- 較低的單檔上限
- 較高的換倉門檻
- 價格動能為核心，月營收動能為次核心
- 月中再平衡，優先吃到較完整的最新月營收
- `risk_on` 先保留約 `4%` 現金緩衝，主打較穩而非滿曝險

此時 `symbols` 的角色會變成：

- 手動 override 名稱與策略
- 強制納入特定股票
- 強制排除特定股票（把該 symbol 設為 `enabled: false`）

## 啟動

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py
```

`.env` 至少建議設定：

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
FINMIND_TOKEN=...
```

## Docker 操作

專案已整理成可用的 Docker 工作流，包含：

- `portfolio-bot`
  - 跑 live 月度再平衡主程式
- `backtest`
  - 跑容器內回測 CLI

### 建置

```bash
docker compose build
```

### 啟動 live bot

```bash
docker compose up -d portfolio-bot
```

### 查看 log

```bash
docker compose logs -f portfolio-bot
```

### 停止

```bash
docker compose down
```

### 執行回測

```bash
# 3Y 回測
docker compose run --rm backtest \
  --start 2022-01-01 \
  --end 2024-12-31 \
  --benchmark 0050

# 6M 回測
docker compose run --rm backtest \
  --start 2024-06-01 \
  --end 2024-12-31 \
  --benchmark 0050
```

回測輸出會寫到：

- `reports/backtests/*_metrics.json` — Sharpe / Alpha / MDD 等量化指標
- `reports/backtests/*_report.txt` — 可讀的績效報告
- `reports/backtests/*_snapshots.json` — 每期再平衡的選股快照與診斷資訊

備註：

- `.env` 不會被打包進 image，會透過 `docker compose` 在 runtime 掛入
- `config/`、`data/`、`logs/`、`reports/` 都會掛載到容器內，方便保留結果
- 若你在 WSL 使用 Docker，需先啟用 Docker Desktop 的 WSL integration

## 資料庫

SQLite 檔案預設在 `data/signals.db`。現在除了舊的 `signal_history` 之外，新增兩張和投組相關的表：

- `portfolio_rebalances`
  - 每次月度再平衡的快照
- `portfolio_positions`
  - 最新目標持股與目標權重

## Telegram 內容

再平衡通知會包含：

- 再平衡日期
- 市場狀態與總曝險
- 候選數 / 合格數 / 入選數
- 目標持股與權重
- 新進與移出
- 前幾名 ranking 預覽

## 舊模組狀態

舊的 `src/strategy/engine.py`、`signals.py`、`regime.py`、`indicators.py` 仍保留，原因是：

- `indicators.py` 與 `regime.py` 仍被投組引擎使用
- 舊的單檔 alert 邏輯可作為研究參考

但現在主流程不再以逐檔訊號通知為核心。

## 限制

- 尚未接券商 / 下單執行
- Paper trading 已啟動（`scripts/paper_trade.py`），已修復為 append-only + 讀取 DB
- 2025 OOS 驗證已完成（新 Cache + Split Fix 後，Sharpe 1.88，Alpha +7.27%）
- Benchmark 為 **total_return**（P4.5，含配息 + stock split 自動前復權）
- FinMind 免費版 600 req/hr 配額限制（3Y 回測需 ~400-500 次呼叫）
- MarketValue API 在免費版不可用，需 fallback 到 close × volume size proxy
- 月營收與法人資料依賴 FinMind 可用性
- 台股交易日透過 `0050` 實際日線資料判斷；若 FinMind 查詢失敗，系統 fail-closed

## 目前回測結果（2026-04-15 更新，新 Cache + Split Fix + 全專案審查）

> ℹ️ 以下數字為新 Cache + 0050 split fix 後結果（drift-aware + total return benchmark）。Cache 全新重建已於 2026-04-14 完成（`data/cache/`，TWSE 1,077 支 + TPEX 881 支）。2026-04-15 完成全專案盲點修正 Phase 1-4（20 項）+ 雙視角審查（APPROVE ✅）。

| 回測期間 | 年化報酬 | Sharpe | Alpha | MDD | Beta | 性質 |
|---------|---------|--------|-------|-----|------|------|
| **2025 OOS** | **44.61%** | **1.88** | **+7.27%** | **-16.75%** | **0.49** | **Out-of-Sample** |
| 4Y（2022-2025）| 20.84% | 0.97 | +4.91% | -32.19% | 0.48 | IS+OOS |
| Walk-Forward 平均 | — | 1.09 | — | — | — | 11 段 OOS |
| Bootstrap 95% CI | — | [-0.13, 2.41] | — | — | — | ⚠️ 不顯著 |

Benchmark（0050）含 stock split 自動前復權 + 配息調整（total return）。詳見 `優化紀錄.md`。

## 下一步建議

- ~~**P0** Research Integrity~~ ✅ 全部完成
- ~~**P1** 6M 負 alpha 根因分析~~ ✅ 已完成（`max_same_industry` 2→3）
- ~~**P2** 因子調整~~ ✅ 已完成（`institutional_flow` 移除）
- ~~**P3** 策略擴展~~ ✅ 已完成（vol_weighted ❌、quality ❌、revenue 覆蓋率 ✅）
- ~~**P4.0** Paper trading 可審計性~~ ✅ 已修復（append-only + 讀取 DB）
- ~~**P4.1** Benchmark split 修復~~ ✅ 已修復（自動前復權 + reverse split）
- ~~**P4.2** Known-answer test~~ ✅ 已修復（27 個 metrics 測試）
- ~~**P4.3** Walk-forward 驗證框架~~ ✅ 已完成（11 視窗，平均 Sharpe 1.09）
- ~~**P4.4** Hardcoded 常數提到 config~~ ✅ 已完成（engine.py 6 個值）
- ~~**P4.8** 主題集中風險指標~~ ✅ 已完成（theme_concentration）
- ~~**P4.9** data_degraded false alarm~~ ✅ 已修復
- ~~**P5** 雙視角審查 + 工程修復~~ ✅ 5 輪完成（CSV fallback、constants 共用）
- ~~**P7** 測試擴充 + Bug 修復~~ ✅ 完成（161 測試、finmind bug fix、Dashboard 6M 重跑）
- ~~**P4.5** Total return benchmark（含配息再投資）~~ ✅ 已完成（2026-04-08）
- ~~**P4.6** Drift-aware 日報酬計算~~ ✅ 已完成（2026-04-08）
- ~~**Split Fix** 0050 市場代理前復權修復~~ ✅ 已完成（2026-04-14）
- ~~**全專案盲點修正** Phase 1-4（S1-S5 + D1-D5 + O1-O3 + C1-C4）~~ ✅ 已完成（2026-04-15）
- ~~**雙視角全專案審查** APPROVE — 無 P0 級問題~~ ✅ 已完成（2026-04-15）
- **P4.10** 券商對接

詳見 `優化紀錄.md`。

**架構評估結論（2026-04-15，全專案雙視角審查 APPROVE ✅）：** 策略方向正確、研究有紀律、工程品質中上。161 個測試覆蓋核心模組（含 BacktestEngine 整合測試、finmind 單元測試、drift-aware、配息調整），benchmark 為 total_return，新 Cache + 0050 split fix 後 4Y Sharpe 0.97、2025 OOS Alpha +7.27%。全專案盲點修正 Phase 1-4 已完成 20 項修正（S1-S5 + D1-D5 + O1-O3 + C1-C4），含常數統一、決策 logging、profile 對齊等。詳見 `優化紀錄.md`。

這不是投資建議。請先完成更長期驗證與 paper trading，再考慮實際資金部署。
