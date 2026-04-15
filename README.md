# 台股量化投組系統

台股 long-only 量化投資組合系統，採月度再平衡架構，以橫截面因子排名選出目標持股。涵蓋因子研究、回測引擎、資料工程、風險控制全流程。

## 功能特色

- **三因子選股**：價格動能（55%）、月營收動能（25%）、趨勢品質（20%）
- **市場風控**：以 0050 為市場代理，偵測 risk_on / caution / risk_off 狀態，動態調整曝險
- **Point-in-time 資料截斷**：`_DataSlicer` 確保回測中每個時間點只看到當時可得的資料，防止 look-ahead bias
- **Survivorship bias 防護**：回測 universe 包含已下市股票
- **Total return benchmark**：含配息再投資，使用 scale-invariant 公式調整
- **Drift-aware 日報酬**：持有期間權重隨股價自然漂移，消除固定權重回測的系統性高估
- **Stock split 自動前復權**：偵測 >40% 單日跌幅（正分割）與 >100% 單日漲幅（合股），自動校正
- **Rolling OOS 驗證**：11 個滾動樣本外視窗 + Bootstrap Sharpe 信賴區間（⚠️ 修正後 CI 跨 0，alpha 不顯著）
- **219 個自動化測試**：覆蓋回測引擎、因子排名、選股邏輯、配息調整、drift-aware、cache 路徑解析、backtest strict 模式等

## 架構

```text
config/settings.yaml           策略參數（唯一正式設定檔）
        |
        v
src/portfolio/tw_stock.py      核心選股引擎
  - 候選股池建構（close×volume 排序取前 80 名）
  - 單股因子分析（_analyze_symbol）
  - 橫截面排名（_rank_analyses）
  - 目標持股建構（_select_positions）
        |
        +--> src/data/finmind.py          FinMind API + pickle cache + TWSE fallback
        +--> src/data/twse_scraper.py     TWSE/TPEX 交易所資料爬蟲
        +--> src/backtest/engine.py       回測引擎 + _DataSlicer（point-in-time 截斷）
        +--> src/backtest/metrics.py      績效指標 + split/dividend 前復權
        +--> src/backtest/universe.py     歷史 universe（含下市股）
        +--> src/strategy/regime.py       市場狀態偵測（ADX + SMA）
        +--> src/utils/constants.py       共用常數
        +--> src/utils/paths.py           DATA_CACHE_DIR 路徑解析（resolve_cache_dir）
        +--> src/storage/database.py      SQLite 儲存
        +--> src/notify/telegram.py       Telegram 通知
```

## 策略邏輯

### 選股流程

1. **建立候選股池**：全市場股票以 close×volume（20 日均值）排序，取前 80 名
2. **因子分析**：對每支候選股計算價格動能、月營收動能、趨勢品質
3. **橫截面排名**：各因子分別排名後加權合成總分
4. **目標持股建構**：取前 8 名，考慮產業分散（同產業上限 3 支）、持倉緩衝、換手成本

### 市場風控

以 0050 的 ADX 和 SMA 判斷市場狀態：

| 狀態 | 條件 | 曝險 |
|------|------|------|
| risk_on | 上升趨勢 | 96% |
| caution | 盤整 | 70% |
| risk_off | 下降趨勢 | 35% |

### 因子設計決策

- `institutional_flow`（法人流量）經 IC 分析發現全期 rank IC 為負，主動移除
- `quality`（財務品質）回測顯示無法穩定提升績效，停用
- 選股池使用成交金額排序而非市值排序（回測驗證：市值排序 Sharpe 降 74%）

> ⚠️ 上述決策建立在 2026-04-15 之前的回測上，當時 pre-filter 對歷史日期失效（universe 退化為全市場 ~2000 支）。修復後策略結果大幅改變，這些因子結論需重新驗證。

## 回測結果

> 含交易成本（0.47% round-trip + 10bps 滑價）、total return benchmark、drift-aware 日報酬

> ⚠️ **2026-04-15 更新**：修正兩個隱藏 bug（`finmind.py` timezone error + pre-filter 對歷史日期失效）後，真實 Sharpe 大幅下降。過去表格數字是 pre-filter 失效時跑出的，**不符策略設計規格**。以下為修正後的結果。

| 回測期間 | 年化報酬 | Sharpe | Alpha | MDD | Beta | 性質 |
|---------|---------|--------|-------|-----|------|------|
| **2025** | **15.7%** | **0.66** | **-18.4%** | **-22.1%** | **0.53** | **Out-of-Sample** |
| 2024 單年 | 7.1% | 0.33 | -43.2% | -33.6% | 0.48 | IS+OOS |
| 2022-2025（4Y） | 15.5% | 0.64 | +3.4% | -34.1% | 0.51 | IS+OOS |
| Rolling OOS 平均 | — | 0.93 | +34.4% | — | — | 11 段 OOS |
| Rolling OOS 中位數 | — | **0.28** | — | — | — | ⚠️ 中位數遠低於平均 |
| Bootstrap 95% CI | — | [-0.05, 1.99] | — | — | — | ❌ 跨 0，不顯著 |

**修正後的觀察：**
- 策略在牛市年（2024、2025）顯著跑輸 0050
- 4Y Alpha 僅 +3.4%，接近 0（扣除換手成本後負貢獻）
- 2025 OOS 負 Alpha 表明策略無穩定選股優勢
- 過去「看似優秀」的表現來自 pre-filter 失效意外搶到中小型飆股

## 績效指標模組

自行實作的指標計算（`src/backtest/metrics.py`）：

- Sharpe Ratio / Sortino Ratio / Calmar Ratio
- Annualized Alpha / Beta（vs. 0050）
- Maximum Drawdown
- CVaR 95%（Conditional Value at Risk）
- Information Ratio / Tail Ratio
- Jarque-Bera 常態性檢定
- Bootstrap Sharpe 信賴區間

## 技術棧

| 類別 | 技術 |
|------|------|
| 語言 | Python 3.11+ |
| 容器化 | Docker + docker-compose |
| 資料庫 | SQLite |
| 資料來源 | FinMind API、TWSE/TPEX 交易所爬蟲 |
| 通知 | Telegram Bot |
| 測試 | pytest（219 tests） |

## 快速開始

```bash
# 安裝
pip install -r requirements.txt
cp .env.example .env  # 設定 FINMIND_TOKEN 與 DATA_CACHE_DIR（見下）

# 執行測試
python -m pytest tests/ -v

# Docker 回測
docker compose build
docker compose run --rm backtest --start 2022-01-01 --end 2025-12-31 --benchmark 0050

# Rolling OOS 驗證
docker compose run --rm --entrypoint python portfolio-bot scripts/walk_forward.py
```

### 環境變數

| 變數 | 必填 | 說明 |
|------|------|------|
| `FINMIND_TOKEN` | ✅ | FinMind API token（免費版 600 req/hr） |
| `DATA_CACHE_DIR` | ✅ | Cache 絕對路徑（例：`C:/Users/<user>/.../Quantitative-Trading/data/cache`）。避免 legacy Windows path 誤解析到 `C:\app\data\cache\` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 可選 | 再平衡通知 |

`src/utils/paths.py::resolve_cache_dir()` 會統一處理 `DATA_CACHE_DIR`，若未設則 fallback 到 `./data/cache`。

## 測試覆蓋

```bash
python -m pytest tests/ -v  # 219 passed
```

涵蓋績效指標（Sharpe/MDD/Alpha + known-answer）、回測引擎整合、FinMind cache/API、Point-in-time 資料截斷、再平衡日期、Universe 建構、選股門檻、因子排名、波動率加權、配息調整、零權重因子跳過、Drift-aware 日報酬、Data degradation、cache 路徑解析、backtest strict 模式、format_report None 安全、dividends strict 等。

## 限制

- **⚠️ 策略當前無顯著 alpha**：修正資料/程式 bug 後 4Y Sharpe 僅 0.64、Alpha +3.4%，2025 OOS 甚至 -18.4%，尚未驗證在大型股池中具備選股能力
- **過去看似優秀的回測數字（Sharpe 1.88、Walk-Forward 1.38）是 pre-filter 失效時跑出的**，不符策略設計規格
- 尚未串接券商自動下單
- FinMind 免費版 600 req/hr 配額限制
- Long-only 策略，Beta ≈ 0.5，部分報酬來自市場曝險
- 建議與被動投資（0050）對照後再決定是否實盤部署

## 免責聲明

本專案僅供學術研究與個人學習用途，不構成任何投資建議。
