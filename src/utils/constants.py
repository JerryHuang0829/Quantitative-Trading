"""Shared constants used across modules."""

from datetime import timedelta, timezone

TW_TZ = timezone(timedelta(hours=8))

# 廣義科技供應鏈關鍵字 — 用於 theme_concentration 監控
# engine.py 與 paper_trade.py 共用，避免兩處定義不一致
TECH_SUPPLY_CHAIN_KEYWORDS = frozenset([
    "電子", "半導體", "IC", "光電", "通信", "資訊", "電腦", "電機",
])
