# Claude 接手 Prompt — 台股量化投組系統

最後更新：2026-03-31

請用中文回覆。你是這個專案的研究主導（Claude），負責策略研究、回測分析、overfit 判斷。Codex 是工程驗證者，負責複現回測和程式碼審查。

---

## 專案現況

台股 long-only 月度再平衡量化投組系統，使用 `tw_3m_stable` profile。

### 已完成的里程碑

| 階段 | 內容 | 狀態 |
|------|------|------|
| P0 | Survivorship bias、benchmark 口徑、snapshot 診斷、degraded 定義、跨機器驗證 | ✅ 全部完成 |
| P1 | `max_same_industry` 2→3（台股電子業主導，2 太嚴格） | ✅ 已落地 + Codex/Claude 雙重驗證 |
| P2 | `institutional_flow` 10%→0%（rank IC 全期為負 -0.053） | ✅ 已落地 + Codex/Claude 雙重驗證 |
| P2 | caution exposure 0.70→0.80/0.85 研究 | ✅ 研究完成，**不落地**（overfit） |

### 目前正式設定（`config/settings.yaml`）

```yaml
max_same_industry: 3
score_weights:
  price_momentum: 0.55
  trend_quality: 0.20
  revenue_momentum: 0.25
  institutional_flow: 0.00
exposure:
  risk_on: 0.96
  caution: 0.70
  risk_off: 0.35
```

### 目前 Artifact

| 回測 | 年化報酬 | Sharpe | Alpha | MDD |
|------|---------|--------|-------|-----|
| 6M（2024-H2） | 31.78% | 1.08 | +13.52% | -21.50% |
| 3Y（2022-2024） | 53.57% | 1.85 | +48.43% | -21.50% |

---

## 2026-03-31 的改動摘要

### 參數落地
- `settings.yaml`：`institutional_flow` 權重 10%→0%，`price_momentum` 45%→55%

### P2 回測完成
- 6 組 6M grid：baseline / if5 / if0 / caution80 / caution85 / combo_if5_c80 / combo_if0_c80
- Top 4 的 3Y 驗證：if0 / caution85 / combo_if0_c80 / combo_if5_c80
- Overfit 分析：caution 調高的改善來自加槓桿（vol +7%, beta +3.4%），不是選股改善
- trend_quality 連續化評估：ROI 過低（二元項僅佔總分 3%），跳過

### Codex 驗證（由使用者提交 Codex 執行）
- IF=0% fresh rerun：6M/3Y 所有指標與 Claude artifact 差異 0.0%
- `_rank_analyses` 邏輯審查：IF=0 時跳過 active_weights，語義正確
- market signal 分布確認：caution+risk_off = 77.8%

### Claude 獨立複核
- 逐欄位比對 Claude vs Codex metrics JSON，差異 0.00%
- `_rank_analyses` 語義審查通過，備註 graceful degradation 行為
- `6805` coverage warning 評估：IF=0% 後無影響，低優先修復（歸 P4）
- **P2 正式通過雙重驗證**

### md 檔更新
- `優化紀錄.md`：新增 P2 全部 section（P2.1-P2.6）含 Claude 複核
- `優化建議.md`：重寫為 P2 完成狀態，加入雙重驗證結果
- `策略研究.md`：更新 artifact、標記 P1/P2 已落地、研究態度新增方法論
- `README.md`：回測結果更新為 P2 數據、核心因子標註 IF 已移除

### 回測報告位置
- `reports/backtests/new_baseline/` — ind3 baseline（IF10%）
- `reports/backtests/p2_*/` — P2 各組 6M/3Y
- `reports/backtests/codex_verify/p2_if0/` — Codex fresh rerun

---

## 接下來要做的事

### 最高優先：P4.1 Paper Trading 框架

P1+P2 的 in-sample 優化已完成，**最重要的下一步是開始累積 out-of-sample 數據**。

需要做的：
1. 確認 Docker bot 的 live 再平衡流程能正常跑（`docker compose up -d portfolio-bot`）
2. 建立 paper trading 記錄機制：每月 12 號記錄策略建議的持股/權重，追蹤模擬績效
3. 累積至少 6 個月 out-of-sample 數據後，比較與回測預期是否一致
4. 若 paper trading 績效與回測差異過大（Sharpe 差 > 50%），需診斷原因

### P3 研究（可與 paper trading 並行）

按優先順序：

1. **P3.1 revenue_momentum 覆蓋率**（快速確認）
   - 查 snapshot 中 `revenue_raw=None` 的股票是否主要是金融業
   - 若是，79% 覆蓋率可接受，不需修改

2. **P3.2 產業權重限制**（中等工作量）
   - 目前 `max_same_industry=3` 是檔數限制
   - 測試加入單一產業總權重 ≤ 30% 的限制
   - 需修改 `_select_positions` 或 weighting 邏輯

3. **P3.3 position sizing — risk parity lite**（中等工作量）
   - 目前是 `score_weighted`
   - 測試波動率倒數加權（ATR 或 rolling std）
   - 回測對照 6M + 3Y

4. **P3.4 exit framework**（較大工作量）
   - 期中止損：單檔回撤 > 20% 強制退出
   - 需修改 engine 支援期中事件
   - 回測驗證止損是否在波動市場頻繁觸發

### P4 工程化（Paper trading 通過後）

1. `6805` coverage warning 修復（IF=0% 時跳過 institutional fetch）
2. 券商對接
3. AI 整合（限定市場風向 + 事件風控，不進 ranking）

---

## 重要研究原則

1. **一次改一項參數**，每項都要回測 6M + 3Y 對照
2. **Codex 複核**：每個要落地的變更都需 Codex fresh rerun 驗證
3. **區分「選股改善」和「加槓桿」**：看 vol 和 beta 是否變化。IF 移除是前者（vol 不變），caution 調高是後者（vol +7%）
4. **不要碰 caution/risk_off exposure**：78% 回測期為 caution/risk_off，任何調整都有嚴重 overfit 風險
5. **回測命令格式**：
   ```bash
   docker compose run --rm --entrypoint python portfolio-bot scripts/run_backtest.py \
     --start 2024-06-01 --end 2024-12-31 \
     --output reports/backtests/<name>/ \
     --config config/<config>.yaml
   ```

---

## 跨機器注意事項

### 另一台電腦操作步驟

```bash
cd Quantitative-Trading
git pull

# 確認 .env 已設定 FINMIND_TOKEN
cat .env

# 如果從未 build 過：
docker compose build

# 驗證當前設定的回測結果：
docker compose run --rm --entrypoint python portfolio-bot scripts/run_backtest.py \
  --start 2024-06-01 --end 2024-12-31 \
  --output reports/backtests/verify/
docker compose run --rm --entrypoint python portfolio-bot scripts/run_backtest.py \
  --start 2022-01-01 --end 2024-12-31 \
  --output reports/backtests/verify/
```

注意：
- 首次跑 3Y 需要較長時間（FinMind 快取從零建立，~15-30 分鐘）
- `docker-compose.override.yml` 已刪除，內容已合併進主檔
- 跨機器差異 < 5% 為正常（OHLCV cache cold/warm start 差異）

---

## 關鍵檔案

| 檔案 | 用途 |
|------|------|
| `config/settings.yaml` | 正式設定（已含 P1+P2 變更） |
| `src/portfolio/tw_stock.py` | 選股核心（ranking、selection、weighting） |
| `src/backtest/engine.py` | 回測引擎（point-in-time） |
| `scripts/run_backtest.py` | 回測 CLI 入口 |
| `scripts/analyze_institutional_ic.py` | rank IC 離線分析腳本 |
| `優化紀錄.md` | 完整研究歷程與驗證記錄 |
| `優化建議.md` | 當前建議與待辦路線圖 |
| `策略研究.md` | 研究結論與方法論 |
