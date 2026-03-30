# Backtest Artifacts

這些檔案是回測產出的結果，**僅供比對參考，不是唯一真相**。

## 使用原則

在新環境（另一台電腦）執行回測時：

1. **先重跑回測**，產出新的 artifact
2. **比對新舊數字差異**，可接受的差異範圍：
   - Sharpe / Alpha 差異 < 5%（因 TWSE 成交金額每次抓取略有不同）
   - 持股名單可能有 1-2 支邊際股票差異
   - `total_analyzed`、`n_rebalances` 應完全一致
3. **若差異超出預期**，優先排查：
   - FinMind token 是否正確（影響資料完整度）
   - TWSE 端點是否正常（影響 universe 排序）
   - `data/cache/` 是否從零開始重建（首次跑會比較慢）

## 目前 Artifact（2026-03-30 產出）

| 檔案 | 回測區間 | 關鍵數字 |
|------|---------|---------|
| `backtest_20220101_20241231_*` | 3Y | Sharpe 1.55, Alpha +35.34% |
| `backtest_20240601_20241231_*` | 6M | Sharpe 0.34, Alpha -10.92% |
| `backtest_20240601_20240630_*` | 1M（舊測試）| 可忽略 |

## 驗證命令

```bash
# 重跑 6M
docker compose run --rm backtest --start 2024-06-01 --end 2024-12-31

# 重跑 3Y
docker compose run --rm backtest --start 2022-01-01 --end 2024-12-31
```
