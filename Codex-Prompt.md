# Codex 複核 Prompt — P5 第五輪修復驗證

最後更新：2026-04-02
用途：修復第四輪 Codex 回報的兩個問題（E8 cache hit 路徑缺 CSV、E2 walk_forward 需重跑）。

---

## 背景

第四輪 Codex 驗證結果：E6 PASS、回歸測試 PASS，但 E8 和 E2 有問題：
1. **E8**：`fetch_stock_info()` 命中有效 pickle cache 時直接 return，不會建立 CSV 備援
2. **E2**：`summary.json` 是舊資料，需要在 Docker 中實際重跑 `walk_forward.py`

本輪修正：

| 修正 | 檔案 | 內容 |
|------|------|------|
| E8 補丁 | `src/data/finmind.py` | cache hit 路徑加 `_ensure_stock_info_csv()` |
| E2 增強 | `scripts/walk_forward.py` | summary 新增 `degraded_periods` 欄位 |

---

## 修正 E8 補丁：cache hit 路徑補建 CSV

**根因分析**：
- `fetch_stock_info()` 在 pickle cache TTL 有效時（`< 7 天`）直接 `return cached`
- 如果使用者在「修復前」就有 pickle cache，CSV 永遠不會被建立
- 導致 CSV fallback 機制名存實亡

**修正方式**：
- 新增 `_ensure_stock_info_csv(df)` 方法：檢查 CSV 是否存在，不存在才寫入
- 在 cache hit 路徑（`return cached` 前）呼叫 `_ensure_stock_info_csv(cached)`
- 已存在時跳過，不會每次 cache hit 都寫磁碟

### 請驗證 A：程式碼結構

```bash
# 1. 確認 cache hit 路徑有呼叫 _ensure
grep -A 3 "days < 7" src/data/finmind.py
# 預期：
#   self._ensure_stock_info_csv(cached)
#   return cached

# 2. 確認 _ensure 方法存在且邏輯正確
grep -A 6 "def _ensure_stock_info_csv" src/data/finmind.py
# 預期：
#   csv_path = self._disk._dir / "stock_info" / "stock_info_snapshot.csv"
#   if not csv_path.exists():
#       ... _save_stock_info_csv_snapshot(df)

# 3. 共有 4 個方法涉及 CSV：_load / _save / _ensure / fetch_stock_info 中呼叫
grep -c "stock_info_csv" src/data/finmind.py
# 預期：7（_load 定義+使用x3, _save 定義+使用x2, _ensure 定義+使用x1 中呼叫 _save）
# 實際行數可能略有不同，重要的是確認 4 個方法都存在
```

### 請驗證 B：Docker 整合測試（關鍵驗證）

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import os
from pathlib import Path
from src.data.finmind import FinMindSource

token = os.getenv('FINMIND_TOKEN')
s = FinMindSource(token=token)

# 步驟 1：刪除 CSV 快照（模擬修復前的舊環境）
csv_path = s._disk._dir / 'stock_info' / 'stock_info_snapshot.csv'
if csv_path.exists():
    csv_path.unlink()
    print(f'Deleted existing CSV: {csv_path}')
else:
    print(f'No CSV existed (fresh state)')

# 步驟 2：呼叫 fetch_stock_info（應該 cache hit + 補建 CSV）
info = s.fetch_stock_info()
assert info is not None, 'fetch_stock_info returned None'
print(f'Stock info: {len(info)} rows')

# 步驟 3：檢查 CSV 是否被建立
assert csv_path.exists(), f'CSV NOT created at {csv_path} — _ensure failed!'
print(f'CSV snapshot created: OK ({csv_path})')

# 步驟 4：驗證 CSV 內容正確
import pandas as pd
csv_df = pd.read_csv(csv_path, dtype=str)
assert len(csv_df) == len(info), f'Row mismatch: CSV={len(csv_df)} vs pickle={len(info)}'
print(f'CSV content matches pickle: {len(csv_df)} rows — OK')

# 步驟 5：再次呼叫（CSV 已存在，不應重寫）
import time
mtime_before = csv_path.stat().st_mtime
time.sleep(0.1)
info2 = s.fetch_stock_info()
mtime_after = csv_path.stat().st_mtime
assert mtime_before == mtime_after, 'CSV was rewritten — _ensure should skip!'
print('CSV not rewritten on second call: OK')

print()
print('=== E8 CSV fallback: ALL CHECKS PASSED ===')
"
```

### 請驗證 C：fallback 讀取（模擬 pickle 損壞）

```bash
docker compose run --rm --entrypoint python portfolio-bot -c "
import os
from pathlib import Path
from src.data.finmind import FinMindSource

token = os.getenv('FINMIND_TOKEN')
s = FinMindSource(token=token)

# 先確保 CSV 存在
info = s.fetch_stock_info()
csv_path = s._disk._dir / 'stock_info' / 'stock_info_snapshot.csv'
assert csv_path.exists(), 'CSV must exist for this test'

# 測試 _load_stock_info_csv_fallback 可以讀取
fallback = s._load_stock_info_csv_fallback()
assert fallback is not None, 'CSV fallback returned None'
assert len(fallback) == len(info), f'Row mismatch: fallback={len(fallback)} vs original={len(info)}'
print(f'CSV fallback read: {len(fallback)} rows — OK')
"
```

---

## 修正 E2 增強：Walk-Forward summary 新增 degraded_periods

**修正內容**：`scripts/walk_forward.py` 的 `entry` dict 新增 `degraded_periods` 欄位。

原因：目前 summary 只記錄 `data_degraded: true/false`，無法區分「6 個月全部 degraded」和「只有 1 個月 degraded」。新增 `degraded_periods` 欄位（整數）讓使用者能判斷嚴重程度。

### 請驗證 A：程式碼

```bash
grep -n "degraded_periods" scripts/walk_forward.py
# 預期：1 行，在 entry dict 中
# "degraded_periods": metrics.get("degraded_periods", 0),
```

### 請驗證 B：Walk-Forward 重跑（需要 Docker + 較長時間）

```bash
# 重跑 Walk-Forward（約 30-60 分鐘）
docker compose run --rm --entrypoint python portfolio-bot \
    scripts/walk_forward.py \
    --train-months 18 --test-months 6 \
    --start 2019-01-01 --end 2025-12-31 \
    --output-dir reports/walk_forward

# 驗證結果
docker compose run --rm --entrypoint python portfolio-bot -c "
import json
with open('reports/walk_forward/summary.json') as f:
    s = json.load(f)
windows = s.get('windows', [])
print(f'Total windows: {len(windows)}')
print(f'Valid windows: {s[\"config\"].get(\"valid_windows\", \"?\")}')
print()
for w in windows:
    wid = w.get('window')
    degraded = w.get('data_degraded')
    dp = w.get('degraded_periods', '?')
    nr = w.get('n_rebalances', '?')
    sharpe = w.get('sharpe')
    period = f'{w[\"test_start\"]} → {w[\"test_end\"]}'
    print(f'  W{wid}: {period}  Sharpe={sharpe:.2f}  degraded={degraded}  ({dp}/{nr} periods)')

degraded_count = sum(1 for w in windows if w.get('data_degraded'))
print(f'')
print(f'Degraded windows: {degraded_count}/{len(windows)}')
if degraded_count < len(windows):
    print('改善：不再是全部 degraded — PASS')
elif all(w.get('degraded_periods', 0) < w.get('n_rebalances', 1) for w in windows if w.get('data_degraded')):
    print('部分改善：仍 degraded 但非全部月份 — CHECK degraded_periods')
else:
    print('未改善：可能是真實資料問題（早期 window 錯誤率較高）— INVESTIGATE')
"
```

**重要說明**：即使重跑後部分 window 仍然 `data_degraded=true`，不一定是 bug。早期 window（2019-2021）的 FinMind 資料確實可能有較高的分析錯誤率（股票下市、資料缺失等）。新增的 `degraded_periods` 欄位能區分「6/6 全部 degraded」和「1/6 偶發 degraded」，後者通常是可接受的。

---

## 整體回歸驗證

```bash
# 1. 單元測試
docker compose run --rm --entrypoint python portfolio-bot -m pytest tests/ -v
# 預期：87+ passed

# 2. finmind.py 語法
docker compose run --rm --entrypoint python portfolio-bot -c "
import ast
ast.parse(open('src/data/finmind.py').read())
print('finmind.py syntax: OK')
"

# 3. walk_forward.py 語法
docker compose run --rm --entrypoint python portfolio-bot -c "
import ast
ast.parse(open('scripts/walk_forward.py').read())
print('walk_forward.py syntax: OK')
"
```

---

## 回覆格式

```
### E8 補丁：cache hit CSV 備援
- [ ] _ensure_stock_info_csv 方法存在
- [ ] cache hit 路徑有呼叫 _ensure
- [ ] Docker 測試：刪除 CSV 後 fetch → CSV 自動建立
- [ ] Docker 測試：CSV 已存在時不重寫
- [ ] Docker 測試：_load_stock_info_csv_fallback 可讀取
結論：PASS / FAIL（原因）

### E2 增強：Walk-Forward
- [ ] walk_forward.py 有 degraded_periods 欄位
- [ ] Walk-Forward 已重跑（若時間允許）
- [ ] 重跑後 degraded 狀態描述
結論：PASS / FAIL（原因）

### 回歸測試
- [ ] 全部測試: 87+ passed
- [ ] 語法檢查通過
結論：PASS / FAIL

### 額外發現
（若有其他問題請列出）
```
