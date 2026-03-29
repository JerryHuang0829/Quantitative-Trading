"""Institutional flow scoring for Taiwan stocks.

Extracted from src/strategy/signals.py so that both the portfolio
engine and the legacy signal path can share the same implementation
without private-function coupling.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def score_institutional(institutional_df: pd.DataFrame | None, days: int = 3) -> dict:
    """Score institutional investor activity over the last *days* trading days.

    FinMind format:
        date | stock_id | buy | name | sell
        name: Foreign_Investor, Investment_Trust, Dealer_self, ...

    Scoring:
    - Foreign investors net-buy for *days* consecutive days  → +80
    - Foreign + Investment Trust both net-buy                → +90
    - Foreign investors net-sell for *days* consecutive days  → -80
    - Foreign + Investment Trust both net-sell                → -90
    """
    if institutional_df is None or institutional_df.empty:
        return {"score": 0, "detail": "no_data", "icon": "➖"}

    if not {"name", "buy", "sell", "date"}.issubset(institutional_df.columns):
        return {"score": 0, "detail": "bad_columns", "icon": "⚠️"}

    try:
        df = institutional_df.copy()
        df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
        df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
        df["net"] = df["buy"] - df["sell"]

        dates = sorted(df["date"].unique())
        if len(dates) < days:
            return {"score": 0, "detail": "insufficient_days", "icon": "➖"}
        recent_dates = dates[-days:]
        df = df[df["date"].isin(recent_dates)]

        # Foreign investor daily net
        foreign = df[df["name"] == "Foreign_Investor"]
        if foreign.empty:
            return {"score": 0, "detail": "no_foreign", "icon": "➖"}

        foreign_daily = foreign.groupby("date")["net"].sum()
        all_buy = all(foreign_daily > 0)
        all_sell = all(foreign_daily < 0)

        # Investment trust direction (bonus)
        trust = df[df["name"] == "Investment_Trust"]
        trust_daily = trust.groupby("date")["net"].sum() if not trust.empty else pd.Series(dtype=float)
        trust_buy = len(trust_daily) >= days and all(trust_daily.tail(days) > 0)
        trust_sell = len(trust_daily) >= days and all(trust_daily.tail(days) < 0)

        if all_buy:
            if trust_buy:
                return {"score": 90, "detail": f"foreign+trust_buy_{days}d", "icon": "🔥"}
            return {"score": 80, "detail": f"foreign_buy_{days}d", "icon": "✅"}
        if all_sell:
            if trust_sell:
                return {"score": -90, "detail": f"foreign+trust_sell_{days}d", "icon": "🔥"}
            return {"score": -80, "detail": f"foreign_sell_{days}d", "icon": "🔻"}

        return {"score": 0, "detail": "neutral", "icon": "➖"}

    except Exception as exc:
        logger.warning("Institutional scoring error: %s", exc)
        return {"score": 0, "detail": "error", "icon": "⚠️"}
