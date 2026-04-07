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
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
                verify=False,
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
                verify=False,
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


# ---------------------------------------------------------------------------
# Market value (市值) computation from TWSE issued capital + close prices
# ---------------------------------------------------------------------------

_TWSE_COMPANY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
_TPEX_COMPANY_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


def _parse_company_profile(data: list[dict]) -> dict[str, int]:
    """Parse TWSE/TPEX company profile JSON into {stock_id: shares_outstanding}.

    Both TWSE and TPEX use the same field structure — field names are matched
    by substring to avoid encoding issues on some platforms.
    """
    if not data:
        return {}

    sample = data[0]
    stock_id_key = None
    shares_key = None
    capital_key = None
    for k in sample.keys():
        kl = k.lower()
        if "公司代號" in k or "securitiescompanycod" in kl:
            stock_id_key = k
        elif "已發行" in k or k == "IssueShares":
            shares_key = k
        elif "實收資本額" in k or "paidin.capital" in kl:
            capital_key = k

    if not stock_id_key:
        return {}

    result: dict[str, int] = {}
    for row in data:
        sid = str(row.get(stock_id_key, "")).strip()
        if not sid:
            continue
        try:
            # Prefer direct shares outstanding field
            if shares_key and row.get(shares_key):
                shares = int(str(row[shares_key]).replace(",", ""))
                if shares > 0:
                    result[sid] = shares
                    continue
            # Fallback: issued capital / 10 (par value)
            if capital_key and row.get(capital_key):
                capital = int(float(str(row[capital_key]).replace(",", "")))
                if capital > 0:
                    result[sid] = capital // 10
        except (ValueError, TypeError):
            continue
    return result


def fetch_twse_issued_capital() -> dict[str, int]:
    """Return {stock_id: shares_outstanding} for all TWSE + TPEX stocks.

    Fetches company profile data from both TWSE (上市) and TPEX (上櫃)
    OpenAPI endpoints.  TPEX failure is non-fatal.
    Returns empty dict on any error.
    """
    result: dict[str, int] = {}

    # TWSE (上市)
    try:
        resp = requests.get(
            _TWSE_COMPANY_URL,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
            verify=False,
        )
        if resp.status_code == 200:
            twse = _parse_company_profile(resp.json())
            result.update(twse)
            logger.info("TWSE issued capital: %d companies", len(twse))
        else:
            logger.warning("TWSE company profile HTTP %d", resp.status_code)
    except Exception as exc:
        logger.warning("TWSE issued capital fetch failed: %s", exc)

    # TPEX (上櫃) — non-fatal
    try:
        resp = requests.get(
            _TPEX_COMPANY_URL,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
            verify=False,
        )
        if resp.status_code == 200:
            tpex = _parse_company_profile(resp.json())
            result.update(tpex)
            logger.info("TPEX issued capital: %d companies", len(tpex))
        else:
            logger.debug("TPEX company profile HTTP %d", resp.status_code)
    except Exception as exc:
        logger.debug("TPEX issued capital fetch failed: %s", exc)

    if result:
        logger.info("Total issued capital fetched: %d companies (TWSE + TPEX)", len(result))
    return result


# ---------------------------------------------------------------------------
# Ex-dividend data (除權息) for total-return price adjustment (P4.5)
# ---------------------------------------------------------------------------

_TWSE_EX_DIVIDEND_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"


def _parse_roc_date(roc_str: str) -> str | None:
    """Convert ROC date like '112年07月18日' to '2023-07-18'.

    Returns None if parsing fails.
    """
    import re
    m = re.match(r"(\d+)\D+(\d+)\D+(\d+)", roc_str)
    if not m:
        return None
    year = int(m.group(1)) + 1911
    month = int(m.group(2))
    day = int(m.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def fetch_twse_dividends(start_year: int, end_year: int) -> list[dict]:
    """Fetch ex-dividend records from TWSE for the given year range.

    Queries TWT49U endpoint year-by-year (TWSE limits range to ~1 year).
    Returns list of dicts with keys:
        stock_id, ex_date, cash_dividend, close_before, ref_price

    Only returns cash dividend (息) records, not stock dividend (權).
    Stock dividends are similar to splits and are already handled by
    adjust_splits() in metrics.py.
    """
    import time

    all_records: list[dict] = []

    for year in range(start_year, end_year + 1):
        year_start_str = f"{year}0101"
        year_end_str = f"{year}1231"

        try:
            resp = requests.get(
                _TWSE_EX_DIVIDEND_URL,
                params={
                    "startDate": year_start_str,
                    "endDate": year_end_str,
                    "response": "json",
                },
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
                verify=False,
            )
            if resp.status_code != 200:
                logger.warning("TWSE TWT49U HTTP %d for year %d", resp.status_code, year)
                continue

            data = resp.json()
            rows = data.get("data", [])
            if not rows:
                logger.debug("TWSE TWT49U: no data for year %d", year)
                continue

            year_count = 0
            for row in rows:
                if len(row) < 7:
                    continue

                # [6] = 權/息 type: "息" = cash only, "權" = stock only, "權息" = both
                # Only include pure cash dividend ("息").  "權息" records have
                # close_before - ref_price that includes stock dividend value
                # (10-30% yield vs actual cash ~1-3%), causing massive over-
                # adjustment.  Stock dividends are already handled by
                # adjust_splits() in metrics.py.
                div_type = str(row[6]).strip()
                if div_type != "息":
                    continue

                stock_id = str(row[1]).strip()
                ex_date = _parse_roc_date(str(row[0]))
                if not ex_date or not stock_id:
                    continue

                # [3] = close before ex-date, [4] = reference price after
                # cash_dividend = close_before - ref_price (for pure cash div)
                try:
                    close_before = float(str(row[3]).replace(",", ""))
                    ref_price = float(str(row[4]).replace(",", ""))
                except (ValueError, TypeError):
                    continue

                cash_dividend = round(close_before - ref_price, 6)
                if cash_dividend <= 0:
                    continue

                all_records.append({
                    "stock_id": stock_id,
                    "ex_date": ex_date,
                    "cash_dividend": cash_dividend,
                    "close_before": close_before,
                    "ref_price": ref_price,
                })
                year_count += 1

            logger.info(
                "TWSE dividends %d: %d cash-dividend records from %d rows",
                year, year_count, len(rows),
            )

        except Exception as exc:
            logger.warning("TWSE TWT49U failed for year %d: %s", year, exc)

        # Rate limit between years
        if year < end_year:
            time.sleep(1.0)

    logger.info(
        "TWSE dividends total: %d records across %d-%d",
        len(all_records), start_year, end_year,
    )
    return all_records
