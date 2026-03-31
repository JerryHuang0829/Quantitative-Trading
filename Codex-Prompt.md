# Codex 複核 Prompt — P3 研究完成後

最後更新：2026-03-31
用途：Claude 完成 P3 研究後，交由 Codex 複核程式碼與研究結論。

---

## 本輪改動摘要（第一台電腦，2026-03-31）

### 1. P3.3 波動率加權 — 測試完成，不落地

- 新增 `vol_weighted` 模式到 `_calculate_position_weights()`
- 新增 `volatility_20d` 欄位到 `_analyze_symbol()`
- 6M Sharpe 1.08→0.48（-56%），Alpha +13.52%→-6.43%
- 原因：動能策略 alpha 來自高波動強勢股，波動率降權等於自廢武功
- **設定不改（仍為 score_weighted），程式碼保留**

### 2. P3.4 四因子（+quality）— 測試完成，不落地

- 新增 `fetch_financial_quality()` 到 `finmind.py`（ROE + 毛利率，季報快取 90 天）
- 新增 `quality_raw` 欄位到 `_analyze_symbol()`
- 新增 `quality` 到 `_rank_analyses()` 的 `available_metrics`
- 6M Sharpe 1.08→0.69（-36%），3Y Sharpe 1.85→1.79（-3%）
- 原因：品質因子偏好穩定公司，稀釋動能權重
- **設定不改（quality 權重=0），程式碼保留**

### 3. pytest 測試框架 — 已建立

- 新增 `tests/` 目錄（5 個測試檔，44 個測試）
- 覆蓋：ranking、selection、metrics、degradation、vol_weighting
- 全部通過，2 秒完成
- `docker-compose.yml` 加入 `./tests:/app/tests` volume mount
- `requirements.txt` 加入 `pytest>=7.0.0`

### 4. Paper Trading Bug 修復

- 重跑 Docker 產出乾淨 `2026-03.json`（中文正常、ranking 無重複）
- `paper_trade.py` 加入 Windows 環境警告

---

## Codex 複核重點

### A. P3 研究結論是否合理

1. 波動率加權在動能策略中表現差 — 是否符合 Codex 的理解？
2. 品質因子稀釋動能 → 績效下降 — 邏輯是否成立？
3. 「三因子已是最佳」的結論是否過早？是否有其他值得測試的因子？

### B. 程式碼品質

1. `_calculate_position_weights` 的 `vol_weighted` 分支邏輯是否正確
2. `fetch_financial_quality()` 的 ROE 計算是否正確（單季 × 4 年化）
3. `quality_raw = roe_score * 0.6 + gm_score * 0.4` 的權重是否合理
4. pytest 測試覆蓋率是否足夠

### C. 新增程式碼對現有策略的影響

**所有新增功能都是「設定關閉」的狀態，不應影響現有策略。** 請確認：
1. `settings.yaml` 的 `score_weights` 是否仍為 `PM 0.55 / TQ 0.20 / RM 0.25 / IF 0.00`
2. `weight_mode` 是否仍為 `score_weighted`
3. 新增的 `quality` 在 `available_metrics` 中，但權重=0 → 不進 `active_weights` → 不影響排序

---

## 目前正式設定（不變）

```yaml
score_weights:
  price_momentum: 0.55
  trend_quality: 0.20
  revenue_momentum: 0.25
  institutional_flow: 0.00
  # quality: 0.00  (未加入 settings.yaml，_rank_analyses 中 available_metrics 有但權重=0)
weight_mode: score_weighted
max_same_industry: 3
exposure:
  risk_on: 0.96
  caution: 0.70
  risk_off: 0.35
```

## 目前最佳 Artifact（不變）

| 回測 | Sharpe | Alpha | MDD |
|------|--------|-------|-----|
| 6M | 1.08 | +13.52% | -21.50% |
| 3Y | 1.85 | +48.43% | -21.50% |

---

## 驗證命令

```bash
# pytest
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v

# 確認現有策略不受影響（應與 p2_if0 結果一致）
docker compose run --rm --entrypoint python portfolio-bot scripts/run_backtest.py \
  --start 2024-06-01 --end 2024-12-31 --output-dir reports/backtests/verify/
```

---

## Codex 回覆格式

```text
1. Findings
2. P3 研究結論複核
3. 程式碼品質審查
4. 現有策略影響確認
5. Suggestions
```
