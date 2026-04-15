"""Shared constants used across modules."""

from datetime import timedelta, timezone
from typing import Any

import pandas as pd

TW_TZ = timezone(timedelta(hours=8))


def to_utc_ts(value: Any) -> pd.Timestamp:
    """Convert any datetime-like value to a UTC-aware pd.Timestamp.

    Safe for both naive and tz-aware inputs. pandas 2.x raises if you pass
    `tz="UTC"` to a tz-aware value, so callers must branch — this helper
    centralizes that branching.
    """
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")

# 台股個股來回交易成本 ≈ 0.47%（手續費 0.1425% x2 + 證交稅 0.3% 賣出）
TW_ROUND_TRIP_COST = 0.0047

# OHLCV 最低歷史長度（交易日）— 252 天動能 + 22 天 SMA buffer
MIN_OHLCV_BARS = 274

# 動能計算期間（交易日）
MOMENTUM_PERIOD_3M = 63
MOMENTUM_PERIOD_6M = 126
MOMENTUM_PERIOD_12M = 252
MOMENTUM_SKIP_DAYS = 21  # 12-1 動能跳過最近 N 天

# 營收資料 look-ahead 延遲（日曆天）
# 台股月營收法定公告期限為次月 10 日前。舊值 35 天對早月再平衡（rebalance_day=5）
# 會把尚未公告的月營收納入因子（例：as_of=2026-03-05, cutoff=2026-01-29
# 會含 2026-02 營收，但該月營收要到 2026-03-10 才公告）。
# 45 天 = 次月 10 日最晚公告 + 5 天 publication buffer，確保 PIT 不洩漏。
REVENUE_LAG_DAYS = 45

# 廣義科技供應鏈關鍵字 — 用於 theme_concentration 監控
# engine.py 與 paper_trade.py 共用，避免兩處定義不一致
TECH_SUPPLY_CHAIN_KEYWORDS = frozenset([
    "電子", "半導體", "IC", "光電", "通信", "資訊", "電腦", "電機",
])
