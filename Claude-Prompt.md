# Claude 交接 Prompt

最後更新：2026-04-08
請用中文回覆。

---

## 一. 專案現況總覽

### 策略設定

- 台股 long-only，月中再平衡，`tw_3m_stable` profile
- 三因子：`price_momentum`（55%）、`trend_quality`（20%）、`revenue_momentum`（25%）
- 已停用：`institutional_flow`（0%）、`quality`（0%）
- `top_n=8`、`max_same_industry=3`、`caution exposure=0.70`
- **候選股池**：close×volume（20日均值）排序取前 80 名，Live 和 Backtest 一致
- **benchmark**：`total_return`（含配息，P4.5）
- **日報酬**：drift-aware buy-and-hold within period（P4.6）

### 回測績效（P4.5+P4.6 修正後）

| 回測 | Sharpe | Alpha | MDD | 性質 |
|------|--------|-------|-----|------|
| 4Y（2022-2024） | 0.90 | +17.54% | -32.76% | IS+OOS |
| **Walk-Forward 平均** | **1.09** | **+45.63%** | **-26.74%** | **11 段 OOS** |
| Bootstrap 95% CI | [-0.13, 2.41] | — | — | ⚠️ 不顯著 |

### 完成狀態

| 階段 | 狀態 |
|------|------|
| P0-P3 策略研究 | ✅ |
| P4.0-P4.4/P4.8/P4.9 工程化 | ✅ |
| P5 雙視角審查 | ✅ |
| P6 度量層 + Cache 機制 | ✅ |
| P7 選股池正式化 + TWSE 資料完整性 | ✅ |
| P4.5 Total Return Benchmark（配息） | ✅ |
| P4.6 Drift-aware 日報酬 | ✅ |
| **Cache 全新重建** | **⏳ 已清除重來（修正 bug 後）** |

---

## 二. ⚠️ 正在進行的工作：Cache 全新重建

### 背景

現有 `data/cache/` 經歷多次 FinMind + TWSE 混合抓取，資料來源不一致。FinMind 免費版有 971 支股票永遠抓不到（其中 20+ 支超過 top-80 門檻），是策略盲區。

決定：**建立全新 cache（`data/cache_new/`），與舊 cache 完全分開。**

### 資料來源策略

| 資料 | 來源 | 備註 |
|------|------|------|
| OHLCV（上市 1,074 支） | **TWSE STOCK_DAY** | 100% 交易所原始資料，不用 FinMind |
| OHLCV（上櫃 881 支） | **FinMind** | TWSE 無上櫃個股歷史 JSON API |
| Revenue（全市場） | **FinMind** | TWSE 只有最新一期 |
| stock_info | **TWSE + TPEX OpenAPI** | 不依賴 FinMind |
| dividends | **TWSE TWT49U** | 已有實作 |
| market_value | **TWSE 計算** | 股本 × 收盤價 |
| institutional | **不抓** | weight=0% |

**FinMind 只用在：上櫃 OHLCV + 全市場 Revenue。其他全部 TWSE。**

### 重建腳本：`scripts/cache_rebuild.py`

```
Phase 0: 建立 data/cache_new/（空目錄）           ⏳ 需重新開始
Phase 1: stock_info + dividends（TWSE）           ⏳ 需重新開始
Phase 2: 上市股 OHLCV（TWSE STOCK_DAY）           ⏳ 需重新開始
Phase 3: 上櫃股 OHLCV（FinMind）                  ⏳ 需重新開始
Phase 4: Revenue（FinMind）                       ⏳ 需重新開始
Phase 5: market_value（TWSE 計算）                ⏳ 需重新開始
```

### 2026-04-08 重置原因

首次執行時發現兩個問題：
1. **Phase 2 和 Phase 3 同時跑時 progress 檔互相覆蓋**（已修正：每個 Phase 獨立 progress 檔）
2. **Phase 3（FinMind）抓的 TPEX pkl 有多餘欄位**（已修正：Phase 3 改為自己標準化到 5 欄）

已清除所有 `data/cache_new/` 和 progress 檔，從零開始。

### Phase 2 詳細

- 對 1,074 支上市股，逐月從 TWSE 抓 2019-01 ~ 2026-04（84 個月/支）
- 每次 API 間隔 1.5 秒
- 預估 ~38 小時（約 3.5 分鐘/支 × 1,074 支）
- **可中斷恢復**：進度存 `data/cache_rebuild_p2.json`（獨立檔案）
- Phase 2 和 Phase 3 可以**同時跑**（用不同 API，進度檔獨立）

### 查進度

```bash
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --status
```

### 如何接續

```bash
# 查進度
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --status

# 接續 Phase 2（自動從上次位置開始）
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --phase 2

# 跑 Phase 3（上櫃，可跟 Phase 2 分開跑）
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --phase 3

# 跑 Phase 4（Revenue）
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --phase 4

# 跑 Phase 5（market_value，最後跑）
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --phase 5
```

### 跨電腦接續

如果要換電腦繼續：
1. 複製 `data/cache_new/` + `data/cache_rebuild_progress.json` 到另一台
2. `git pull` 拿最新程式碼
3. 跑同樣的 `--phase N` 指令

### 完成後切換

```bash
mv data/cache data/cache_old       # 舊 cache 保留
mv data/cache_new data/cache       # 新 cache 上線
```

然後跑 `cache_health.py` 驗證，再跑回測確認結果合理。

---

## 三. 關鍵檔案位置

| 檔案 | 用途 |
|------|------|
| `config/settings.yaml` | 策略參數（唯一正式設定檔） |
| `src/portfolio/tw_stock.py` | 核心選股（close×volume 排序，~1200 行） |
| `src/backtest/engine.py` | 回測引擎 + `_DataSlicer` + drift-aware + 配息 |
| `src/backtest/universe.py` | 歷史 Universe（close×volume 排序） |
| `src/backtest/metrics.py` | KPI + adjust_splits + adjust_dividends |
| `src/data/finmind.py` | FinMind API + pickle cache + TWSE fallback |
| `src/data/twse_scraper.py` | TWSE/TPEX 全市場日線 + 個股歷史 + 月營收 + 股本 + 除息 |
| `src/strategy/regime.py` | 大盤多空判斷（ADX + SMA） |
| `scripts/cache_rebuild.py` | **Cache 全新重建腳本（進行中）** |
| `scripts/cache_health.py` | 資料完整性報告 |
| `scripts/cache_fill.py` | Cache 增量更新（舊版，重建完成後備用） |
| `scripts/run_backtest.py` | 回測 CLI |
| `scripts/walk_forward.py` | Walk-Forward + Bootstrap Sharpe CI |
| `scripts/paper_trade.py` | Paper Trading 記錄器 |
| `scripts/real_trade.py` | 小額實盤追蹤 |
| `tests/` | 161 個測試（14 個測試檔） |
| `data/cache/` | 現有 cache（舊，重建完成後改名 cache_old） |
| `data/cache_new/` | **新 cache（正在建立中）** |
| `data/cache_rebuild_progress.json` | 重建進度檔 |

---

## 四. 下一步行動清單

### 最高優先：完成 Cache 重建

1. Phase 2 跑完（上市 OHLCV，~38 小時）
2. Phase 3（上櫃 OHLCV FinMind，~1.5 小時）
3. Phase 4（Revenue FinMind，~3.3 小時）
4. Phase 5（market_value 計算，< 1 分鐘）
5. 驗證：cache_health + 回測比對
6. 切換：rename

### 之後：Paper Trading

- 2026-04-14：第 2 筆月度再平衡（用新 cache）
- 警戒線：Sharpe < 0.7 或 Alpha 轉負

### 未來

| 項目 | 說明 |
|------|------|
| P8 Size Factor | 市值大小當評分因子 |
| P4.10 券商對接 | CTS API 自動下單 |
| P4.11 AI 整合 | 市場風向 + 事件風控 |

---

## 五. 不要做的事

- ❌ 調整 `score_weights` / `exposure` / `top_n` / `caution`
- ❌ 把 `institutional_flow` 或 `quality` 拉回
- ❌ 用 market_value 做選股排序（實測 Sharpe 降 74%）
- ❌ 刪除 `data/cache/` 或 `data/cache_new/`（重建需要幾十小時）
- ❌ 在 cache 重建完成前跑正式回測
- ❌ 同時在兩台電腦跑同一個 Phase（進度檔會衝突）

---

## 六. 技術備註

### TWSE Fallback 架構

```
OHLCV:    FinMind → TWSE STOCK_DAY（不存 disk，避免混合來源）
Revenue:  FinMind → TWSE OpenData（不存 disk，只有 1 個月不夠 YoY）
```

TWSE fallback 回傳的資料只在當次 session 使用，不存進 disk cache。這確保 cache 永遠是單一來源（上市=TWSE，上櫃=FinMind）。

### Cache 重建的資料一致性

FinMind 免費版的 OHLCV = TWSE 原始價格（`TaiwanStockPriceAdj` 需付費，免費版 fallback 到 `TaiwanStockPrice`）。所以 TWSE 抓的資料跟 FinMind 免費版完全一致。

### 其他

- **`_DiskCache.load()`**：已改為 log-only，讀取失敗不刪除 pkl
- **Docker 測試**：161 passed, 0 failed
- **signals.db**：跨電腦不需複製
- **Skills 路徑**：已改為相對路徑

---

## 七. 數字變動歷程

| 時間點 | 4Y Sharpe | 原因 |
|--------|-----------|------|
| P6 原始 | 1.41 | price_only benchmark |
| P7（第二台） | 1.33 | cache 差異 |
| P4.5+P4.6 | **0.90** | drift-aware + total return（更真實） |
| Cache 重建後 | **待驗證** | 新 cache 可能略有變化 |

---

## 八. 文件索引

| 文件 | 內容 | 最後更新 |
|------|------|---------|
| `Claude-Prompt.md` | 本檔（交接用） | 2026-04-08 |
| `Codex-Prompt.md` | Codex 驗證（全架構 + P4.5/P4.6 + TWSE fallback） | 2026-04-08 |
| `優化紀錄.md` | 完整修改歷程 P0-P7 | 2026-04-08 |
| `策略研究.md` | P1-P3 因子研究結論 | 2026-04-01 |
| `CLAUDE.md` | Claude Code 指引 + Skills 索引 | 2026-04-08 |
| `README.md` | 專案架構、Docker 操作 | 2026-04-07 |
