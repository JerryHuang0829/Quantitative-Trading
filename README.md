# 台股量化投組系統

這個專案已從逐檔 `BUY/SELL` 訊號 bot，改成以 **台股 long-only 量化投組** 為核心的系統。主流程現在以「月度再平衡」為中心，而不是單檔即時訊號：

1. 讀取台股股票池
   - 可從 `symbols` 手動指定，也可由 FinMind `stock_info + market_value` 自動建池
2. 取得日線、法人與月營收資料
3. 做橫截面 ranking
4. 產生目標持股與目標權重
5. 將再平衡結果寫入 SQLite 並推送 Telegram

## 目前架構

```text
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
        +--> src/data/finmind.py
        +--> src/storage/database.py
        +--> src/notify/telegram.py
```

## 策略定位

- 市場：台股現貨
- 風格：long-only 短中線波段
- 節奏：月度再平衡
- 目前建議主線：`tw_3m_stable`
- 目標持有：平均約 3 個月，實際允許 2 到 4 個月自然流動
- 核心因子：
  - `price_momentum`
  - `trend_quality`
  - `revenue_momentum`
  - `institutional_flow`
- 市場風控：
  - 使用 `0050` 當市場代理
  - 將市場狀態切成 `risk_on / caution / risk_off`
  - 用總曝險而不是單純停機處理弱市

## 主要模組

- [main.py](./main.py)
  - 進入點，負責排程與月度再平衡觸發
- [src/portfolio/tw_stock.py](./src/portfolio/tw_stock.py)
  - 台股投組引擎，包含 universe 分析、排名與目標持股建構
- [src/data/finmind.py](./src/data/finmind.py)
  - 讀取日線、法人、月營收、stock info、market value
- [src/storage/database.py](./src/storage/database.py)
  - 儲存 `portfolio_rebalances` 與 `portfolio_positions`
- [src/notify/telegram.py](./src/notify/telegram.py)
  - 發送投組再平衡摘要

## 設定重點

核心設定在 [config/settings.yaml](./config/settings.yaml)。

```yaml
system:
  mode: tw_stock_portfolio

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

若 `use_auto_universe: true`，系統會先用 FinMind 的 `taiwan_stock_info` 與 `taiwan_stock_market_value` 建出全市場候選池，再套用市場別、ETF/ETN/權證排除與市值前段預篩。

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
docker compose run --rm backtest \
  --start 2021-01-01 \
  --end 2025-03-01 \
  --benchmark 0050
```

回測輸出會寫到：

- `reports/backtests/*_metrics.json`
- `reports/backtests/*_report.txt`
- `reports/backtests/*_snapshots.json`

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
- 已補回測模組骨架與 Docker backtest 入口，但尚未完成完整 point-in-time 驗證與 paper trading
- 月營收與法人資料依賴 FinMind 可用性
- auto-universe 依賴 FinMind `stock_info / market_value` 的回傳品質
- 台股交易日目前透過 `0050` 實際日線資料判斷，已不再硬編碼農曆假日；若 FinMind 查詢失敗，系統會 fail-closed，延後到下個週期再判斷

## 下一步建議

- 補回測器與交易成本模型
- 補產業中性 / 集中度限制
- 補 position sizing 與 exit framework
- 補 paper trading 與實單 reconciliation

這不是投資建議。請先用回測與 paper trading 驗證，再考慮實際資金部署。
