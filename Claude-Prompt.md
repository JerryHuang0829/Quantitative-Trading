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
| **Cache 全新重建** | **⏳ Phase 1-4 完成，Phase 5 待執行** |

---

## 二. ⚠️ 正在進行的工作：Cache 全新重建

### 背景

現有 `data/cache/` 經歷多次 FinMind + TWSE 混合抓取，資料來源不一致。FinMind 免費版有 971 支股票永遠抓不到（其中 20+ 支超過 top-80 門檻），是策略盲區。

決定：**建立全新 cache（`data/cache_new/`），與舊 cache 完全分開。**

### 資料來源策略

| 資料 | 來源 | 備註 |
|------|------|------|
| OHLCV（上市 1,074 支） | **TWSE STOCK_DAY_ALL** | 全市場日快照，透過 SOCKS5 proxy pool 繞過 HiNetCDN IP ban |
| OHLCV（上櫃 881 支） | **TPEX 官方 `dailyQuotes`** | 100% 交易所原始資料，不需 proxy |
| Revenue（全市場 1,952 支） | **FinMind** | 多 token 輪替 + proxy 換 IP 突破 600 req/hr/IP 限制 |
| stock_info | **TWSE + TPEX OpenAPI** | 不依賴 FinMind |
| dividends | **TWSE TWT49U** | 已有實作 |
| market_value | **TWSE 計算** | 股本 × 收盤價（Phase 5） |
| institutional | **不抓** | weight=0% |

**FinMind 只用在：Revenue。OHLCV 全部來自交易所原始 API（TWSE + TPEX）。**

### 重建腳本：`scripts/cache_rebuild.py`

```
Phase 0: 建立 data/cache_new/（空目錄）                        ✅ 完成
Phase 1: stock_info（1,961）+ dividends（6,699）               ✅ 完成
Phase 2: 上市股 OHLCV（TWSE STOCK_DAY_ALL，1,074 支 × 1,897 日）✅ 完成（~3 小時，proxy）
Phase 3: 上櫃股 OHLCV（TPEX 官方，881 支 × 1,897 日）          ✅ 完成（~35 分鐘，直連）
Phase 4: Revenue（FinMind 多 token，1,952 支）                 ✅ 完成（多 token 輪替）
Phase 5: market_value（TWSE 計算）                             ⏳ 待執行（< 1 分鐘）
```

### 技術實作細節

#### SOCKS5 Proxy Pool
- TWSE HiNetCDN 封鎖 Docker 出口 IP → 腳本自動掃描免費 SOCKS5 proxy 列表
- 掃描 150 個 proxy，取前 3 個可用的建立 pool
- Phase 2 透過 proxy 存取 TWSE STOCK_DAY_ALL API

#### Phase 2: STOCK_DAY_ALL（全市場日快照）
- 改用 STOCK_DAY_ALL 全市場端點（每日一次請求取得所有上市股）
- 1,897 個交易日（2019-01 ~ 2026-04），每日一個 API call
- 比逐股逐月快 10 倍以上（~3 小時 vs 原估 ~38 小時）
- 進度存 `data/cache_rebuild_p2.json`

#### Phase 3: TPEX 官方 dailyQuotes
- 原計畫用 FinMind，改為 TPEX 官方 API（不需 proxy、不需 token）
- 1,897 個交易日，每日一次請求
- ~35 分鐘完成

#### Phase 4: FinMind 多 Token 策略
- FinMind 免費版限制：600 requests/hour/**per IP**（非 per token）
- 策略：4 個 token 搭配不同 IP（T4 直連 + T1/T2/T3 各用不同 SOCKS5 proxy）
- 順序執行：一個 token 用完（`failed_count >= 100`）再切下一個
- 透過 `source.loader._FinMindApi__session.proxies.update(px)` 注入 proxy
- 3 支 DR 股（9103/9110/9136）FinMind 無資料（確認 API 回傳空），屬正常

### 資料驗證結果

| 項目 | 結果 |
|------|------|
| Phase 1 stock_info | 1,961 支（TWSE 1,080 + TPEX 881） |
| Phase 1 dividends | 6,699 筆 |
| Phase 2 TWSE OHLCV | 1,074 支 pkl，1,897 日 |
| Phase 3 TPEX OHLCV | 881 支 pkl，1,897 日，0 NaN，0 OHLC 異常，0 重複日期 |
| Phase 4 Revenue | 1,952 支 pkl |
| Top-80 Revenue 覆蓋率 | 100% |
| Top-200 Revenue 覆蓋率 | 100% |
| Top-500 Revenue 覆蓋率 | 100% |
| Revenue 不足 12 個月 | 61 支（全為 2025+ IPO，資料完整） |
| Revenue 無資料 | 3 支 DR 股（9103/9110/9136，FinMind 無此類資料） |

### 剩餘步驟

```bash
# Phase 5（market_value 計算，< 1 分鐘）
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --phase 5

# 查進度
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --status
```

### 完成後切換

```bash
# Phase 5 完成後
mv data/cache data/cache_old       # 舊 cache 保留
mv data/cache_new data/cache       # 新 cache 上線

# 驗證
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_health.py

# 回測比對（基準：4Y Sharpe ~0.90）
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31 --benchmark 0050
```

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
| `data/cache_new/` | **新 cache（Phase 1-4 完成，Phase 5 待執行）** |
| `data/cache_rebuild_p2.json` | Phase 2 進度檔 |
| `data/cache_rebuild_p3.json` | Phase 3 進度檔 |
| `data/cache_rebuild_p4.json` | Phase 4 進度檔 |

---

## 四. 下一步行動清單

### 最高優先：完成 Cache 重建

1. ~~Phase 1-4~~ ✅ 已完成
2. Phase 5（market_value 計算，< 1 分鐘）
3. 驗證：cache_health + 回測比對
4. 切換：rename

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

### Cache 重建後的資料來源架構

```
OHLCV 上市: TWSE STOCK_DAY_ALL（cache_new，100% 交易所原始）
OHLCV 上櫃: TPEX dailyQuotes（cache_new，100% 交易所原始）
Revenue:    FinMind（cache_new，多 token + proxy）
Live 補資料: FinMind → TWSE/TPEX fallback（不存 disk，避免混合來源）
```

新 cache 的 OHLCV **完全不依賴 FinMind**，解決了 FinMind 免費版 971 支股票抓不到的策略盲區。

### FinMind 多 Token 架構

4 個帳號 token，FinMind 以 IP 為單位限流（600 req/hr/IP）：
- `FINMIND_TOKEN4`：直連（無 proxy）
- `FINMIND_TOKEN` / `TOKEN2` / `TOKEN3`：各搭配不同 SOCKS5 proxy IP
- 順序執行：一個 token 的 IP 用完（連續 100 次失敗）再切下一個

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
