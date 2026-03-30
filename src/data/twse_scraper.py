"""Free TWSE/TPEX daily turnover scraper for universe pre-filtering.

Uses the public TWSE STOCK_DAY_ALL endpoint (no API key required) to retrieve
transaction turnover (成交金額) for all listed stocks on a given date.
This is used to pre-filter the universe to the top-N most liquid stocks before
applying the cache-only OHLCV size proxy, ensuring large-caps like TSMC (2330)
are never excluded due to missing OHLCV cache.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
_TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailySummary"
_REQUEST_TIMEOUT = 15
_MAX_RETRY_DAYS = 7


def _prev_business_day(date: datetime, offset: int) -> datetime:
    """Return date shifted back by `offset` calendar days (simple approximation)."""
    return date - timedelta(days=offset)


def fetch_twse_turnover(as_of: datetime) -> dict[str, float]:
    """Return {stock_id: turnover_TWD} for all TWSE-listed stocks on or near as_of.

    Retries up to _MAX_RETRY_DAYS prior days to handle non-trading days.
    Returns empty dict on any unrecoverable error.
    """
    for delta in range(_MAX_RETRY_DAYS):
        date = _prev_business_day(as_of, delta)
        date_str = date.strftime("%Y%m%d")
        try:
            resp = requests.get(
                _TWSE_URL,
                params={"date": date_str, "response": "json"},
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                logger.debug("TWSE STOCK_DAY_ALL HTTP %d for date %s", resp.status_code, date_str)
                continue

            data = resp.json()
            if data.get("stat") != "OK":
                logger.debug("TWSE STOCK_DAY_ALL stat=%s for date %s", data.get("stat"), date_str)
                continue

            rows = data.get("data") or []
            if not rows:
                logger.debug("TWSE STOCK_DAY_ALL empty data for date %s", date_str)
                continue

            # Fields: 證券代號(0), 證券名稱(1), 成交股數(2), 成交金額(3), 開盤價(4), ...
            # 注意：成交金額在 index 3，不是 4（index 4 是開盤價）
            result: dict[str, float] = {}
            for row in rows:
                if len(row) < 4:
                    continue
                stock_id = str(row[0]).strip()
                if not stock_id:
                    continue
                try:
                    turnover = float(str(row[3]).replace(",", ""))
                except (ValueError, TypeError):
                    turnover = 0.0
                result[stock_id] = turnover

            if result:
                logger.info(
                    "TWSE turnover fetched: %d stocks for date %s (as_of %s)",
                    len(result), date_str, as_of.strftime("%Y-%m-%d"),
                )
                return result

        except Exception as exc:
            logger.debug("TWSE STOCK_DAY_ALL exception for date %s: %s", date_str, exc)

    logger.warning(
        "TWSE STOCK_DAY_ALL: could not fetch data near %s after %d retries",
        as_of.strftime("%Y-%m-%d"), _MAX_RETRY_DAYS,
    )
    return {}


def fetch_tpex_turnover(as_of: datetime) -> dict[str, float]:
    """Return {stock_id: turnover_TWD} for all TPEX-listed stocks on or near as_of.

    TPEX uses ROC (Republic of China) calendar: year = AD year - 1911.
    Retries up to _MAX_RETRY_DAYS prior days to handle non-trading days.
    Returns empty dict on any unrecoverable error.
    """
    for delta in range(_MAX_RETRY_DAYS):
        date = _prev_business_day(as_of, delta)
        # TPEX date format: YYY/MM/DD (ROC calendar)
        roc_year = date.year - 1911
        date_str = f"{roc_year}/{date.month:02d}/{date.day:02d}"
        try:
            resp = requests.get(
                _TPEX_URL,
                params={"date": date_str, "response": "json"},
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                logger.debug("TPEX dailySummary HTTP %d for date %s", resp.status_code, date_str)
                continue

            data = resp.json()
            # TPEX response structure varies; try common formats
            rows = None
            if isinstance(data, dict):
                rows = data.get("aaData") or data.get("data") or []
            elif isinstance(data, list):
                rows = data

            if not rows:
                logger.debug("TPEX dailySummary empty for date %s", date_str)
                continue

            result: dict[str, float] = {}
            for row in rows:
                if not row or len(row) < 5:
                    continue
                stock_id = str(row[0]).strip()
                if not stock_id or not stock_id.isdigit():
                    continue
                # Try column index 4 for turnover; may vary by TPEX format
                try:
                    turnover = float(str(row[4]).replace(",", ""))
                except (ValueError, TypeError):
                    turnover = 0.0
                result[stock_id] = turnover

            if result:
                logger.info(
                    "TPEX turnover fetched: %d stocks for date %s (as_of %s)",
                    len(result), date_str, as_of.strftime("%Y-%m-%d"),
                )
                return result

        except Exception as exc:
            logger.debug("TPEX dailySummary exception for date %s: %s", date_str, exc)

    # TPEX 失敗不影響核心大型股（台積電等全在 TWSE），降為 debug 等級
    logger.debug(
        "TPEX dailySummary: could not fetch data near %s after %d retries",
        as_of.strftime("%Y-%m-%d"), _MAX_RETRY_DAYS,
    )
    return {}


def fetch_combined_turnover(as_of: datetime) -> dict[str, float]:
    """Return merged TWSE + TPEX turnover for all Taiwan stocks on or near as_of.

    TPEX failure is non-fatal; TWSE alone is sufficient to identify the
    highest-turnover large-caps (which are all TWSE-listed).
    """
    twse = fetch_twse_turnover(as_of)
    tpex = fetch_tpex_turnover(as_of)
    combined = {**tpex, **twse}  # TWSE wins on duplicate keys
    logger.info(
        "Combined turnover: %d TWSE + %d TPEX = %d total stocks near %s",
        len(twse), len(tpex), len(combined), as_of.strftime("%Y-%m-%d"),
    )
    return combined
