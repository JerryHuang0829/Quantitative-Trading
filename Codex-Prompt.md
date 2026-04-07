# Codex 獨立驗證 Prompt — P7 選股池正式化 + TWSE 市值監控 + 整體架構審查

最後更新：2026-04-07
用途：驗證 P7 修改的正確性 + 對整體專案架構做獨立審查。

**重要：請完全獨立驗證，不要依賴 Claude 的任何結論。你需要自己讀程式碼、自己跑測試、自己判斷。**

---

## 一、專案概述（請自行讀 CLAUDE.md 和 README.md 確認）

台股 long-only 量化投組系統。月中再平衡，三因子橫截面排名選股：
- `price_momentum`（55%）
- `revenue_momentum`（25%）
- `trend_quality`（20%）

核心設定：`top_n=8`、`max_same_industry=3`、`caution=0.70`
已停用因子：`institutional_flow=0%`、`quality=0%`
**候選股池**：以成交金額（close×volume）排序取前 80 名（P7 正式化）

---

## 二、P7 修改範圍（2026-04-07）

### P7.3 `.dockerignore` 修復
- **檔案**：`.dockerignore`
- **變更**：新增 `.pytest_tmp/` 和 `pytest-cache-files-*/` 排除
- **驗證**：確認 Docker build 不會因 pytest 暫存資料夾的權限問題失敗

### P7.4 TWSE+TPEX 股本抓取
- **檔案**：`src/data/twse_scraper.py`
- **新增函式**：
  - `_parse_company_profile(data)` — 解析 TWSE/TPEX 公司基本資料 JSON
  - `fetch_twse_issued_capital()` — 抓取 TWSE + TPEX 合計 1961 家公司的已發行股數
- **API 端點**：
  - TWSE：`https://openapi.twse.com.tw/v1/opendata/t187ap03_L`（中文欄位名）
  - TPEX：`https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O`（英文欄位名）
- **驗證**：
  1. `fetch_twse_issued_capital()` 回傳 >= 1900 家公司
  2. 台積電（2330）的股數約為 259 億（25,932,524,521）
  3. TPEX 股票（如 5274、6547）也有資料
  4. `_parse_company_profile()` 能同時處理中文和英文欄位名（substring matching）
  5. API 失敗時回傳空 dict，不 crash

### P7.5 `fetch_market_value()` 重構（監控用途）
- **檔案**：`src/data/finmind.py`
- **變更**：
  - `fetch_market_value()` 改為 TWSE 優先（監控用途，不影響選股）
  - 新增 `_compute_market_value_from_twse()` — 用 TWSE 股本 × OHLCV cache 歷史收盤價計算市值
  - 舊的 FinMind 邏輯提取為 `_fetch_market_value_finmind()` 作為 fallback
  - TTL 從 1 天改為 3 天
- **驗證**：
  1. `_compute_market_value_from_twse()` 回傳 DataFrame 含 `stock_id`、`date`、`market_value` 三欄
  2. `date` 欄位為 timezone-naive（不是 UTC-aware）
  3. 使用 `pd.read_pickle()` 直接讀取，**不經過 `_DiskCache.load()`**（因為後者在讀取失敗時會刪除 pkl 檔案，Windows pickle 版本不相容時會誤刪 cache）
  4. `backtest_mode=True` 且 cache 存在時直接回傳，不打 API
  5. TWSE 失敗 → 嘗試 FinMind → 全部失敗 → 回傳舊 cache

### P7.6 選股池正式化（最重要的變更）
- **檔案**：`src/portfolio/tw_stock.py`
- **變更**：
  - 移除 `market_value = source.fetch_market_value()` 呼叫
  - 移除 `_prepare_auto_universe(stock_info, market_value, portfolio_config)` 呼叫
  - 直接呼叫 `_prepare_auto_universe_by_size_proxy(stock_info, source, portfolio_config)`
- **驗證**：
  1. `build_tw_stock_universe()` 不再呼叫 `fetch_market_value()`
  2. 候選股池的排序方式為 close×volume 20 日均值（`_prepare_auto_universe_by_size_proxy`）
  3. `_prepare_auto_universe()` 函式仍存在但不被 `build_tw_stock_universe()` 呼叫（保留供未來參考）

### P7.7 回測引擎移除 market_value 排序
- **檔案**：`src/backtest/universe.py`
- **變更**：
  - 移除「嘗試 1: 使用 TaiwanStockMarketValue」整個區塊（約 15 行）
  - 原「嘗試 1.5: TWSE 成交金額」改為「嘗試 1」
  - 原「嘗試 2: close×volume」保持不變
  - `market_value` 欄位改用 `row.get()` 避免 KeyError
- **驗證**：
  1. `get_universe_at()` 不再呼叫 `source.fetch_market_value()`
  2. 排序優先順序：TWSE turnover → close×volume → stock_info 順序
  3. 回傳的 dict 中 `market_value` 欄位為 `None`（因為不再 merge market_value）
  4. `_twse_turnover` 為空時（`pre_filter_size=0`），正確 fallback 到 close×volume

---

## 三、整體架構審查（獨立於 P7）

### 3.1 選股池一致性（最重要）
- **Live 路徑**（`tw_stock.py:build_tw_stock_universe()`）和**回測路徑**（`universe.py:get_universe_at()`）的候選股池排序方式是否一致？
  - 兩者都應該使用 close×volume，**不使用 market_value**
  - 確認兩條路徑在相同資料下會選出相同的候選股
- **`_prepare_auto_universe()` 函式**（tw_stock.py:423）仍然存在且使用 market_value。確認它不會被任何地方呼叫到
- **`fetch_market_value()`**（finmind.py）仍然可以被呼叫。確認它只被 preflight check 和 dashboard 使用，不影響選股

### 3.2 Point-in-time 完整性
- `_DataSlicer` 是否正確截斷所有資料到 `as_of` 日期？
- 有沒有任何路徑能在 `as_of` 之前看到未來資料？
- `_compute_market_value_from_twse()` 使用「現在的」TWSE 股本數據。這只用於監控，不影響回測選股。但確認 `_DataSlicer.fetch_market_value()` 的 `_truncate_by_date_col()` 是否正確截斷

### 3.3 TWSE 資料安全性
- `fetch_twse_issued_capital()` 使用 `verify=False`。確認這是否與既有 TWSE scraper 一致
- TPEX API 失敗時不應影響 TWSE 結果（TPEX failure is non-fatal）
- 確認 `_parse_company_profile()` 的 substring matching 不會在未來 API 格式變更時靜默出錯

### 3.4 `_DiskCache.load()` 危險行為
- `finmind.py:73-74`：`except Exception: path.unlink(missing_ok=True)`
- 這會在讀取失敗時**刪除** pickle 檔案。在 Windows 上因 pandas 版本不相容會觸發
- 確認 `_compute_market_value_from_twse()` 不使用 `_DiskCache.load()` 而是直接 `pd.read_pickle()`
- 評估：`_DiskCache.load()` 的刪除行為是否應該修改為 log warning 而非刪除？

### 3.5 交易成本模型（P6 沿用）
- `slippage_bps: 10` 是否從 yaml 正確傳遞到 `BacktestEngine`？
- 確認 `turnover` 是 one-way，`round_trip_cost` 乘一次正確
- 確認 slippage 乘 2（進出各一次）正確

### 3.6 因子跳過邏輯
- `_rank_analyses()` 中 `weight <= 0` 因子是否完全跳過？
- IF=0% 時完全不增加 API 呼叫？

### 3.7 測試覆蓋
- Docker 129 passed, 6 failed（6 個是 `test_finmind.py::TestFetchStockInfo`，另一台電腦新增）
- 確認 6 個失敗的測試是否因為程式碼版本不同步（另一台電腦有 P7 bug fix 但本台未拉取）
- **缺失的測試**：
  - `fetch_twse_issued_capital()` 無測試
  - `_compute_market_value_from_twse()` 無測試
  - `build_tw_stock_universe()` 的 size proxy 路徑無直接測試

---

## 四、執行驗證步驟

```bash
# 1. 本機測試（Windows）
python -m pytest tests/test_metrics.py tests/test_universe.py -v

# 2. 驗證 TWSE 股本抓取
python -c "
from src.data.twse_scraper import fetch_twse_issued_capital
result = fetch_twse_issued_capital()
print(f'Total: {len(result)} companies')
assert len(result) >= 1900, f'Expected >= 1900, got {len(result)}'
assert result.get('2330', 0) > 25_000_000_000, 'TSMC shares too low'
assert result.get('5274', 0) > 0, 'TPEX stock missing'
print('PASS: TWSE+TPEX issued capital')
"

# 3. 驗證選股池不使用 market_value
python -c "
import ast, inspect
from src.portfolio import tw_stock
source = inspect.getsource(tw_stock.build_tw_stock_universe)
assert 'fetch_market_value' not in source, 'build_tw_stock_universe still calls fetch_market_value!'
assert '_prepare_auto_universe_by_size_proxy' in source, 'size proxy not used!'
print('PASS: build_tw_stock_universe uses size proxy, not market_value')
"

# 4. 驗證 universe.py 不使用 market_value 排序
python -c "
import inspect
from src.backtest.universe import HistoricalUniverse
source = inspect.getsource(HistoricalUniverse.get_universe_at)
assert 'TaiwanStockMarketValue' not in source, 'universe.py still references TaiwanStockMarketValue'
# fetch_market_value should NOT be called for ranking
lines = [l.strip() for l in source.split('\n') if 'fetch_market_value' in l and not l.startswith('#')]
assert len(lines) == 0, f'universe.py still calls fetch_market_value: {lines}'
print('PASS: universe.py does not rank by market_value')
"

# 5. Docker 全部測試
docker compose build backtest
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v

# 6. Docker 6M 回測
docker compose run --rm backtest --start 2024-06-01 --end 2024-12-31 --benchmark 0050

# 7. Docker 4Y 回測
docker compose run --rm backtest --start 2022-01-01 --end 2025-12-31 --benchmark 0050
```

---

## 五、你的判斷標準

| 項目 | PASS 條件 |
|------|----------|
| 本機測試 | 16+ passed（13 個 scipy 相關 fail 為既有問題） |
| TWSE 股本 | >= 1900 家，含 TWSE + TPEX |
| 選股池 | `tw_stock.py` 和 `universe.py` 都不使用 market_value 做排序 |
| Docker 測試 | 129+ passed（6 個 stock_info fail 為既有問題） |
| 6M 回測 | 能完成、不 crash、無 "Market value dataset unavailable" 警告影響選股 |
| market_value cache | 存在且含 `stock_id`、`date`、`market_value` 三欄（監控用） |
| `_DiskCache` 安全 | `_compute_market_value_from_twse()` 不使用 `_DiskCache.load()` |
| Point-in-time | 無 look-ahead bias |
| 因子跳過 | IF=0 完全不 fetch |
| Config 相容 | 無 settings.yaml → 全部有預設值，不 crash |

---

## 六、重要提醒

- **不要修改 `score_weights`、`exposure`、`top_n`** — 這些是策略參數，已經過 P1-P3 grid search + Codex 雙重驗證
- **不要用 market_value 做選股排序** — P7 實測 Sharpe 從 0.81 降到 0.21，動能策略不適合大市值股池
- **不要修改任何原始碼** — 這是驗證任務，不是修復任務
- 如果發現問題，請明確指出檔案、行號、問題描述、嚴重度
- 特別注意：Live 路徑（`tw_stock.py`）和回測路徑（`universe.py`）的選股池一致性

---

## 七、P7 架構決策背景（供理解用）

### 為什麼不用 market_value 做選股？

| 排序方式 | 6M Sharpe | 說明 |
|---------|-----------|------|
| 真實市值（TWSE 計算） | 0.21 | 大市值股池，偏保守 |
| 成交金額（close×volume） | 0.45 | 高流動性股池，動能策略表現更好 |

動能策略的 alpha 來自高交易量的活躍股票。用市值排序會納入「大但不活躍」的股票（如部分金控、傳產龍頭），稀釋動能效果。

### market_value 的正確用途

1. **Dashboard 顯示**：每支持股的市值規模
2. **風控監控**：持倉的大/中/小型股分布
3. **P8 研究候選**：未來可能作為第 4 因子（size premium），需經過與 P2 相同的嚴格測試流程
