# Claude 交接 Prompt

最後更新：2026-04-15
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

### 回測績效（新 Cache + Split Fix 後，2026-04-15）

| 回測 | Sharpe | Alpha | MDD | 性質 |
|------|--------|-------|-----|------|
| 4Y（2022-2025） | 0.97 | +4.91% | -32.19% | IS+OOS |
| 2025 OOS | 1.88 | +7.27% | -16.75% | Out-of-Sample |
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
| **Cache 全新重建** | **✅ 全部完成（Phase 1-5 done，資料到 2026-04-14，目錄已切換為 `data/cache`）** |
| **0050 Split Fix** | **✅ market_view 前復權修復（`tw_stock.py`，2025 Alpha -10%→+7.27%）** |
| **全專案盲點修正 Phase 1-4** | **✅ 20 項修正（S1-S5 + D1-D5 + O1-O3 + C1-C4）** |
| **雙視角全專案審查** | **✅ APPROVE — 無 P0 級問題** |

---

## 二. Cache 全新重建（已完成 ✅）

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
Phase 1: stock_info + dividends（TWSE）            ✅ 完成（1,962 筆 / 6,699 筆）
Phase 2: 上市股 OHLCV（TWSE STOCK_DAY）           ✅ v2 完成（1,077/1,081，99.6%；4 支疑似 DR/停牌）
Phase 3: 上櫃股 OHLCV（FinMind）                  ✅ 完成（881/881）
Phase 4: Revenue（FinMind）                       ✅ 完成（1,891/1,953，62 支新上市 <12mo，3 支 DR 無資料）
Phase 5: market_value（TWSE 計算）                ✅ 完成（1,952 支，157,375 筆）
validate_cache.py --fix --source twse             ✅ 完成（3,240/3,282 月，42 停牌/IPO 永久缺漏）
validate_cache.py --fix --source tpex             ✅ 完成（881/881）
data/cache_new → data/cache                       ✅ 完成（2026-04-14 17:37）
TWSE + TPEX 4/14 資料                             ✅ 完成（TWSE 533支 + fix順帶；TPEX 881支）
```

### 2026-04-09 事件時序

**早上**：驗證 `data_0409/cache_new/`，發現 1,074 支上市股 OHLCV 全部損壞（STOCK_DAY_ALL 不支援歷史）。清除重建，Phase 1 完成，Phase 2 v1 啟動。

**下午**：Phase 3/4 完成。Phase 2 v1 跑到 300/1081 時發現 150 支 ghost stocks（含 2330 台積電）— 標 done 但無 pkl。Codex 審計確認問題。

**傍晚**：盤點出 Phase 2 共 9 個 bug，重寫為 v2，清理 ghost 後重啟。

### Phase 2 的 9 個 bug（v1 → v2 修復）

| # | Bug | v1 行為 | v2 修復 |
|---|-----|--------|--------|
| 1 | Ghost stocks | 無資料也標 done | 只在 pkl 存成功後標 done |
| 2 | 307=空 | rate limit 與「未上市」混為一談 | 307 不算 consecutive_empty |
| 3 | 無 retry | 被 307 直接放棄 | fetch_twse_stock_day 有 30/60/120s retry |
| 4 | 進度粗 | 每 10 支存一次 | 每支成功就存 |
| 5 | 時間固定 | end_month 啟動時決定 | 每支股票取當下時間 |
| 6 | 不驗證 | 空 DataFrame 也存 | <20 rows 或常數資料跳過 |
| 7 | 無 proxy | 被 TWSE 封就卡住 | TwseProxyPool：直連遇 307 自動切免費 SOCKS5 proxy |
| 8 | IPO 誤判 | consecutive_empty>=12 跳過新上市股 | 用 stock_info 上市日期跳到正確起點，閾值提高到 24 |
| 9 | 空 pkl | dropna 後 0 rows 也存 | 驗證後才存，原子寫入（.tmp→rename） |

### 資料驗證腳本 `scripts/validate_cache.py`

全 Phase 驗證 + proxy 修復：
- Phase 1：stock_info 完整性、dividends 數值合理性
- Phase 2+3：交易日曆 consensus（10 支參考股票）→ 逐天比對每支股票
- Phase 4：revenue 負值、重複、格式
- Staleness：比對 pkl 最後日期 vs 日曆最後日期
- Look-ahead：偵測未來日期
- `--fix --source twse`：透過 proxy 自動補缺月

### Phase 2 詳細

- **1,081 支**（1,075 上市公司 + 6 ETF：0050/0051/0052/0053/0055/0056）
- 逐月從 TWSE 抓 2019-01 ~ 2026-04（88 個月/支）
- 每次 API 間隔 1.5 秒
- **95,128 次 API 呼叫，預估 ~40 小時**（~2.5 分鐘/支）
- **可中斷恢復**：每 10 支存一次 `data/cache_rebuild_p2.json`（存股票 ID）
- 2026-04-09 11:15 啟動，預計 04-11 完成

### Phase 3/4 FinMind Token 配置

3 個 FinMind 帳號（`.env`），全部 Free tier，600 calls/hr：

| 環境變數 | 帳號 | 綁定 IP |
|---------|------|--------|
| `FINMIND_TOKEN` | JerryHuang | 61.66.150.16 |
| `FINMIND_TOKEN2` | JerrySys | 61.66.150.16 |
| `FINMIND_TOKEN3` | jerry_liontravel | 61.66.150.16 |

Token 內嵌 IP（JWT），必須從該 IP 發 request。`TokenRotator` 自動輪替，每個 token 用 580 次後換下一個。全部用完等 65 分鐘後重來。

查 quota：`GET https://api.web.finmindtrade.com/v2/user_info?token=XXX` → `user_count` 欄位

備用 proxy 來源：`https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt`（~1600 個，成功率 ~30%，已測試可連 FinMind）

### 查進度 / 如何接續

```bash
# 本機跑（非 Docker）
cd Quantitative-Trading
PYTHONPATH=. python scripts/cache_rebuild.py --status
PYTHONPATH=. python scripts/cache_rebuild.py --phase N

# Docker 跑
docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --phase N
```

### 跨電腦接續

複製以下檔案到另一台：
1. `data/cache_new/` 整個目錄
2. `data/cache_rebuild_p*.json` 進度檔
3. `data/cache_rebuild_p*_done.flag` 完成標記
4. `git pull` 拿最新程式碼（含 `TokenRotator`）

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
| `scripts/cache_rebuild.py` | Cache 全新重建腳本（一次性，已完成） |
| `scripts/validate_cache.py` | Cache 資料驗證 + 自動修復（`--fix --source twse/tpex`） |
| `scripts/cache_health.py` | 資料完整性報告 |
| `scripts/cache_fill.py` | 日常 Cache 維護（`--daily` / `--daily-tpex` / `--revenue-only` / `--refresh-all`） |
| `scripts/run_backtest.py` | 回測 CLI |
| `scripts/walk_forward.py` | Rolling OOS 滾動驗證 + Bootstrap Sharpe CI |
| `scripts/regime_simulation.py` | Regime 改進模擬（研究用，不影響生產） |
| `scripts/paper_trade.py` | Paper Trading 記錄器 |
| `scripts/real_trade.py` | 小額實盤追蹤 |
| `tests/` | 161 個測試（14 個測試檔） |
| `data/cache/` | **正式 cache（TWSE 1,077支 + TPEX 881支，資料到 2026-04-15）** |
| `data/cache_old/` | 舊 cache 備份（2026-04-14 前的版本，可刪） |
| `data/validate_fix_list.json` | validate_cache.py 產生的修復清單 |
| `data/fix_twse_progress.json` | TWSE fix 月份級別進度（月份 key: `sym_yr_mo`） |
| `data_0409/` | 04-08 舊版資料備份（TWSE OHLCV 損壞，可刪） |

---

## 四. 下一步行動清單

### Cache 重建（✅ 全部完成）

1. ✅ Phase 1-5 全部完成
2. ✅ `validate_cache.py --fix --source twse`（3,240/3,282 月）
3. ✅ `validate_cache.py --fix --source tpex`（881/881）
4. ✅ `data/cache_new` → `data/cache`（2026-04-14 17:37）

### 日常維護指令

```bash
# 每天 15:00 後（TWSE 上市股，STOCK_DAY_ALL，2 requests，不消耗 FinMind）
PYTHONPATH=. python scripts/cache_fill.py --daily

# 每天 16:00 後（TPEX 上櫃股，FinMind 當月資料，881 支，~7-10 分鐘）
PYTHONPATH=. python scripts/cache_fill.py --daily-tpex

# 每月 1-10 號（更新月營收，~3hr FinMind）
PYTHONPATH=. python scripts/cache_fill.py --revenue-only

# 有缺漏時修補（失敗月份自動重試，中斷可恢復）
PYTHONPATH=. python scripts/validate_cache.py --fix --source twse
PYTHONPATH=. python scripts/validate_cache.py --fix --source tpex
```

### 回測驗證（✅ 已完成）

新 cache + 0050 split fix 後：4Y Sharpe 0.97、2025 OOS Sharpe 1.88、Alpha +7.27%。

### Paper Trading

- 下次再平衡：2026-05-15 左右（月中再平衡）
- 警戒線：Sharpe < 0.7 或 Alpha 轉負
- 2026-10：累積 6 個月後正式評估

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
- ❌ 刪除 `data/cache/`（重建需要幾十小時）
- ❌ 同時在兩台電腦跑 `--fix`（progress file 會衝突）
- ❌ 用 `STOCK_DAY_ALL` 建歷史 cache（只回最新一天，這是 04-08 損壞根因）

---

## 六. 技術備註

### TWSE Fallback 架構

```
OHLCV:    FinMind → TWSE STOCK_DAY（不存 disk，避免混合來源）
Revenue:  FinMind → TWSE OpenData（不存 disk，只有 1 個月不夠 YoY）
```

TWSE fallback 回傳的資料只在當次 session 使用，不存進 disk cache。這確保 cache 永遠是單一來源（上市=TWSE，上櫃=FinMind）。

### TWSE API 端點特性（重要！）

| 端點 | URL | 用途 | 歷史查詢 |
|------|-----|------|---------|
| `STOCK_DAY_ALL` | `twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL` | 全市場當日快照 | ❌ **不支援**（永遠回最新一天） |
| `STOCK_DAY` | `twse.com.tw/rwd/zh/afterTrading/STOCK_DAY` | 單股單月歷史 | ✅ 正確回傳指定月份 |
| `TWT49U` | `twse.com.tw/rwd/zh/exRight/TWT49U` | 除權息資料 | ✅ 支援年份範圍 |

**`STOCK_DAY_ALL` 只能查最新資料，不能建歷史 cache。** 這是 04-08 資料損壞的根因。

### Cache 重建的資料一致性

FinMind 免費版的 OHLCV = TWSE 原始價格（`TaiwanStockPriceAdj` 需付費，免費版 fallback 到 `TaiwanStockPrice`）。所以 TWSE 抓的資料跟 FinMind 免費版完全一致。

### 其他

- **`_DiskCache.load()`**：已改為 log-only，讀取失敗不刪除 pkl
- **Docker 測試**：161 passed, 0 failed
- **signals.db**：跨電腦不需複製
- **Skills 路徑**：已改為相對路徑
- **`TokenRotator`**（2026-04-09 新增）：Phase 3/4 FinMind multi-token 輪替，每 token 580 次自動切換

---

## 七. 數字變動歷程

| 時間點 | 4Y Sharpe | 原因 |
|--------|-----------|------|
| P6 原始 | 1.41 | price_only benchmark |
| P7（第二台） | 1.33 | cache 差異 |
| P4.5+P4.6 | 0.90 | drift-aware + total return（更真實） |
| Cache 重建後（舊 cache） | 0.84 | 新 cache + total return benchmark |
| **0050 Split Fix 後** | **0.97** | **修復 market_view 分割處理（+0.13）** |

---

## 八. Codex 實測調查報告（2026-04-09 16:25）

### 調查目標

驗證 `Codex-Prompt.md` 目前內容是否可被本機工作區**實際證明**為 2026-04-09 今天的修改重點，並區分：

1. **已證明**：可由檔案、diff、程式碼、腳本輸出直接支持
2. **未證明**：本機無法直接證明，只能合理推定
3. **文件錯誤**：`Codex-Prompt.md` 內已發現的明確錯誤或過度表述

### 調查方法

1. 檢查 `git status`、`git diff HEAD -- Codex-Prompt.md`
2. 檢查檔案時間戳：`Codex-Prompt.md`、`Claude-Prompt.md`、`CLAUDE.md`、`scripts/cache_rebuild.py`、`src/data/twse_scraper.py`、`scripts/validate_cache.py`
3. 比對今日相關程式碼是否真的存在：
   - `TokenRotator`
   - `REQUIRED_ETFS`
   - `fetch_twse_stock_day()` 的 307/403 retry
   - `validate_cache.py`
4. 實跑：
   - `python scripts/cache_rebuild.py --status`
   - PowerShell 等價的 `validate_cache.py`
5. 抽樣驗證 `data_0409/cache_new/ohlcv/*.pkl` 是否真有「TWSE 壞、TPEX 正常」現象

### 已證明事項

1. **`Codex-Prompt.md` 確實是今天大改，不是舊檔微調**
   - 檔案 `LastWriteTime`：`2026-04-09 16:19:11`
   - 相對 `HEAD` 的變更量：`1 file changed, 147 insertions(+), 231 deletions(-)`
   - 檔內明確寫 `最後更新：2026-04-09`

2. **`Codex-Prompt.md` 寫到的今日主題，與今天工作樹裡的程式碼變更一致**
   - `scripts/cache_rebuild.py` 已新增 `TokenRotator`
   - `scripts/cache_rebuild.py` Phase 2 已加入 `REQUIRED_ETFS = ["0050","0051","0052","0053","0055","0056"]`
   - `src/data/twse_scraper.py` 的 `fetch_twse_stock_day()` 已加入 HTTP `307/403` retry/backoff
   - `scripts/validate_cache.py` 確實存在，且可執行

3. **`Codex-Prompt.md` 提到的多個數字，與目前 cache 實際內容相符**
   - `stock_info`：1,962 筆
   - 4 位數股票：1,956 支
   - TWSE 4 位數股票：1,075 支
   - TPEX 4 位數股票：881 支
   - Phase 2 補入 6 支 ETF 後，TWSE OHLCV 目標數 = 1,081
   - `dividends/_global.pkl`：6,699 筆

4. **`data_0409` 舊資料損壞敘述有實證，不是空口描述**
   - 抽樣 `data_0409/cache_new/ohlcv/2330.pkl`：1,881 列，但 `close` 只有 2 個 unique 值
   - 抽樣 `2317.pkl`：`close` 只有 3 個 unique 值
   - 抽樣 `2454.pkl`：`close` 只有 4 個 unique 值
   - 對照 TPEX 樣本：`8080.pkl` 有 472 個 unique close，`6147.pkl` 有 295 個 unique close
   - 這與「TWSE 壞、TPEX 正常」的敘述一致

5. **目前 cache 重建進度與 prompt 的脈絡一致，但尚未完成**
   - 實跑 `python scripts/cache_rebuild.py --status`：
     - Phase 1 `done`
     - Phase 2 `270 stocks done`
     - Phase 3 `881 stocks done`
     - Phase 4 `1861 stocks done`
     - Phase 5 `pending`
     - FinMind tokens `3 available`

6. **`Codex-Prompt.md` 是審計清單，不是驗證通過證明**
   - 實跑 `validate_cache.py` 後，報告仍顯示：
     - `Total issues: 766`
     - `Structure errors: 530 stocks`
     - `Completeness issues: 197 stocks`
     - `OHLCV without revenue: 6`
   - 結論：目前狀態是「有驗證工具、可開始審計」，不是「已驗證通過」

### 無法直接證明的事項

1. **無法僅靠本機工作區 100% 證明這批未提交修改一定是「今天你和 Claude 協作完成」**
   - 原因：今天的改動尚未 commit
   - `.claude/` 目錄下只有設定檔，沒有可讀的會話紀錄或操作 log
   - 因此目前最多只能證明：
     - `Codex-Prompt.md` 今天有實際修改
     - 內容與今天其他程式/資料變更相互對應
     - 但**不能**在證據標準上斷言「這些修改一定由 Claude 參與完成」

2. **歷史 commit 只能證明過去多次提交曾標記 `Co-Authored-By: Claude`**
   - 例如 2026-04-08 以前的 commit message 多次出現 `Co-Authored-By: Claude`
   - 這能支持「專案過去確實常與 Claude 協作」
   - 但不能直接外推到今天這批未提交變更

### `Codex-Prompt.md` 已發現的明確錯誤

1. **測試檔數寫錯**
   - 檔案寫法：`161 個測試，13 個檔案`
   - 實際結果：`161` 個 `test_` 函式是對的，但 `tests/test_*.py` 實際有 `14` 個檔案

2. **PowerShell 指令寫法錯**
   - 檔案寫法：`PYTHONPATH=. python scripts/validate_cache.py`
   - 在目前 Windows PowerShell 會直接報錯
   - PowerShell 應改為：`$env:PYTHONPATH='.'; python scripts/validate_cache.py`

3. **文件語氣容易讓人誤讀為「已經驗證完成」**
   - 實際上它比較接近：
     - 獨立審計任務書
     - 驗證 checklist
     - 待執行的審核要求
   - 不應被引用成「目前系統已經通過 Codex 驗證」

### 對 Claude 的工作指示

1. **不要把 `Codex-Prompt.md` 當成驗證完成證明**
   - 正確解讀：它是 Codex 用來做獨立審計的任務書，不是審計結案報告

2. **文件同步時修正兩個明確錯誤**
   - `13 個檔案` → `14 個檔案`
   - PowerShell 指令改為 `$env:PYTHONPATH='.'; python scripts/validate_cache.py`

3. **若要對外或對下一位 agent 交接，必須附上目前真實狀態**
   - Cache 重建尚未完成
   - `validate_cache.py` 目前仍報 `766` 個 issue
   - 因此所有回測或品質判斷都應視為暫時結果

4. **若要保留「今天與 Claude 協作」這種說法，請降低措辭強度**
   - 可寫：`內容與 2026-04-09 今日工作樹變更一致`
   - 不要寫成：`已證明為今日與 Claude 協作完成`

5. **下一步優先順序**
   - 先完成 Phase 2
   - 跑 `validate_cache.py` 對 fix list 做收斂
   - 修正文檔中的事實錯誤後，再更新 `Codex-Prompt.md` / `Claude-Prompt.md`

---

## 九. 全專案盲點修正 + 雙視角審查（2026-04-15）

### 全專案盲點修正 Phase 1-4（20 項修正）

| 類別 | 修正 | 位置 |
|------|------|------|
| S1 | `_metric_ranks` NaN>50% 回傳 False | tw_stock.py |
| S2 | Hold buffer 排除 logging | tw_stock.py |
| S3 | `_cap_and_redistribute` 無 warning | tw_stock.py |
| S4 | Beta 零方差 fallback 改 0.0 | metrics.py |
| S5 | `score_weights` 合計驗證 | tw_stock.py |
| D1 | 空 sentinel 永久阻止重試 | finmind.py |
| D2 | `datetime.now()` 統一 TW_TZ | finmind.py |
| D4 | OHLCV schema 驗證 | cache_fill.py |
| D5 | TWSE/TPEX index name 統一（改用 stock_info CSV 偵測） | cache_fill.py |
| O1 | Token fallback timeout 30s | run_backtest.py |
| O3 | Walk-Forward 正名 Rolling OOS | walk_forward.py |
| C1 | 重複常數統一 constants.py（7 個新常數） | constants.py + tw_stock.py + engine.py |
| C2 | 刪除未使用 binance.py（77 行） | src/data/binance.py |
| C3 | 決策 logging（active factors + top-10 ranked + selection result） | tw_stock.py |
| C4 | Magic numbers 移至 constants.py | constants.py + tw_stock.py |

### 審查後額外修正

| # | 修正 | 位置 |
|---|------|------|
| 1 | Profile `tw_3m_stable` 殘留舊值對齊（max_same_industry 2→3, price_momentum 0.45→0.55, institutional_flow 0.10→0.00） | tw_stock.py |
| 2 | 停用因子加 as_of WARNING 註解（fetch_institutional, fetch_financial_quality） | tw_stock.py |
| 3 | `.env.example` 補齊 TOKEN2/TOKEN3 文件 | .env.example |
| 4 | TWSE STOCK_DAY_ALL 寫入加 `close > 0` 過濾（與 TPEX 統一） | cache_fill.py |

### 雙視角全專案審查結論（APPROVE ✅）

- **無 P0 級問題**
- Look-ahead bias 防護完整（`_DataSlicer` + 營收 35 天延遲 + split 前復權）
- Survivorship bias 防護到位（HistoricalUniverse + 下市股）
- 策略參數安全且有多層防護（config merge + 權重驗證 + CLAUDE.md 守則）
- 最大風險：測試覆蓋不足（tw_stock.py 1,259 行核心無直接單元測試）
- constants.py 新增 7 個常數：`TW_ROUND_TRIP_COST`、`MIN_OHLCV_BARS`、`MOMENTUM_PERIOD_3M/6M/12M`、`MOMENTUM_SKIP_DAYS`、`REVENUE_LAG_DAYS`

---

## 十. 文件索引

| 文件 | 內容 | 最後更新 |
|------|------|---------|
| `Claude-Prompt.md` | 本檔（交接用） | 2026-04-15 |
| `Codex-Prompt.md` | Codex 驗證（全架構 + P4.5/P4.6 + validate_cache.py 盲點修復 + Split Fix KPIs） | 2026-04-15 |
| `優化紀錄.md` | 完整修改歷程 P0-P7 + Cache 重建 + Split Fix + 全專案審查 | 2026-04-15 |
| `策略研究.md` | P1-P3 因子研究結論 | 2026-04-01 |
| `CLAUDE.md` | Claude Code 指引 + Skills 索引 | 2026-04-15 |
| `README.md` | 專案架構、Docker 操作 | 2026-04-15 |
