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

import pandas as pd
import requests
import urllib3

from src.utils.constants import TW_TZ

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


def _cache_based_turnover(
    as_of: datetime,
    stock_ids: list[str] | None,
    ohlcv_source,
    lookback_days: int = 20,
) -> dict[str, float]:
    """從 OHLCV cache 計算歷史 turnover（close × volume 的近 N 日平均）。

    用於回測時的 pre-filter：STOCK_DAY_ALL 只回當日快照，歷史日期必失敗，
    改用每支股票的 cache 直接計算即可得到任意歷史日期的 turnover。

    Parameters
    ----------
    as_of : datetime
        查詢日（回測的 rebalance 日期）
    stock_ids : list[str] | None
        候選股票 ID 清單。若為 None 則跳過（無法掃）
    ohlcv_source : Callable
        可接受 (symbol, timeframe, limit) 的函式，通常是 source.fetch_ohlcv
    lookback_days : int
        計算均值的日數（預設 20 個交易日）
    """
    if not stock_ids or ohlcv_source is None:
        return {}

    as_of_ts = pd.Timestamp(as_of)
    if as_of_ts.tz is None:
        as_of_ts = as_of_ts.tz_localize("UTC")
    else:
        as_of_ts = as_of_ts.tz_convert("UTC")

    result: dict[str, float] = {}
    # 抓每支股票足夠的歷史資料（lookback_days × 2 天的日曆日 buffer，對應 ~lookback_days 交易日）
    fetch_limit = max(60, lookback_days * 3)

    for sid in stock_ids:
        try:
            df = ohlcv_source(str(sid), "D", fetch_limit)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        if "close" not in df.columns or "volume" not in df.columns:
            continue
        # 截到 as_of 日 (含)
        df_slice = df[df.index <= as_of_ts]
        if len(df_slice) < 5:
            continue
        recent = df_slice.tail(lookback_days)
        turnover = (recent["close"] * recent["volume"]).mean()
        if pd.notna(turnover) and turnover > 0:
            result[str(sid)] = float(turnover)

    return result


def fetch_combined_turnover(
    as_of: datetime,
    ohlcv_source=None,
    stock_ids: list[str] | None = None,
) -> dict[str, float]:
    """Return merged TWSE + TPEX turnover for all Taiwan stocks on or near as_of.

    對 as_of 接近今天（< 2 天）時，優先打 TWSE/TPEX 當日 API（跟 live 模式一致）。
    對歷史日期（回測使用），直接從 OHLCV cache 計算近 20 日平均 close×volume。

    TPEX failure is non-fatal; TWSE alone is sufficient to identify the
    highest-turnover large-caps (which are all TWSE-listed).
    """
    # 判斷是否為歷史日期（相對今天 >= 2 天前視為歷史）
    now = datetime.now(TW_TZ)
    as_of_tz = as_of if as_of.tzinfo else as_of.replace(tzinfo=TW_TZ)
    days_ago = (now - as_of_tz).days

    # 歷史日期：從 cache 計算
    if days_ago >= 2 and ohlcv_source is not None and stock_ids:
        cached = _cache_based_turnover(as_of, stock_ids, ohlcv_source)
        if cached:
            logger.info(
                "Combined turnover (from OHLCV cache): %d stocks near %s",
                len(cached), as_of.strftime("%Y-%m-%d"),
            )
            return cached
        # cache 全空才 fallback 到 API（理論上不會發生）

    # 接近今天 或 沒有 cache source：打 API
    twse = fetch_twse_turnover(as_of)
    tpex = fetch_tpex_turnover(as_of)
    combined = {**tpex, **twse}  # TWSE wins on duplicate keys
    logger.info(
        "Combined turnover (from API): %d TWSE + %d TPEX = %d total stocks near %s",
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
            logger.warning("TPEX company profile HTTP %d — TPEX stocks will have no market_value", resp.status_code)
    except Exception as exc:
        logger.warning("TPEX issued capital fetch failed: %s — TPEX stocks will have no market_value", exc)

    if result:
        logger.info("Total issued capital fetched: %d companies (TWSE + TPEX)", len(result))
    return result


# ---------------------------------------------------------------------------
# Full-market daily snapshot (全市場日線快照)
# ---------------------------------------------------------------------------

_TPEX_DAILY_QUOTES_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def fetch_twse_daily_all(as_of: datetime) -> dict[str, dict]:
    """Return {stock_id: {open, high, low, close, volume, turnover}} for ALL TWSE+TPEX stocks.

    Uses TWSE STOCK_DAY_ALL + TPEX OpenAPI to get a single-day snapshot
    of the entire market in 2 API calls.  Far more efficient than
    per-stock OHLCV queries for universe ranking.

    Returns empty dict on any unrecoverable error.
    """
    result: dict[str, dict] = {}

    # --- TWSE (上市) ---
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
                continue
            data = resp.json()
            if data.get("stat") != "OK":
                continue
            rows = data.get("data") or []
            if not rows:
                continue

            # Fields: [0]代號 [1]名稱 [2]成交股數 [3]成交金額 [4]開盤 [5]最高 [6]最低 [7]收盤 [8]漲跌 [9]筆數
            for row in rows:
                if len(row) < 8:
                    continue
                stock_id = str(row[0]).strip()
                if not stock_id:
                    continue
                try:
                    close = float(str(row[7]).replace(",", ""))
                    volume = int(str(row[2]).replace(",", ""))
                    turnover = float(str(row[3]).replace(",", ""))

                    def _safe_price(val: str, fallback: float) -> float:
                        s = str(val).replace(",", "").strip()
                        return float(s) if s not in ("", "--", "---") else fallback

                    open_ = _safe_price(row[4], close)
                    high  = _safe_price(row[5], close)
                    low   = _safe_price(row[6], close)

                    result[stock_id] = {
                        "open": open_, "high": high, "low": low,
                        "close": close, "volume": volume, "turnover": turnover,
                    }
                except (ValueError, TypeError):
                    continue

            logger.info(
                "TWSE daily_all: %d stocks for %s", len(result), date_str,
            )
            break
        except Exception as exc:
            logger.debug("TWSE STOCK_DAY_ALL exception for %s: %s", date_str, exc)

    # --- TPEX (上櫃) ---
    try:
        resp = requests.get(
            _TPEX_DAILY_QUOTES_URL,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
            verify=False,
        )
        if resp.status_code == 200:
            data = resp.json()
            tpex_count = 0
            for row in data:
                stock_id = str(row.get("SecuritiesCompanyCode", "")).strip()
                if not stock_id or not stock_id.isdigit():
                    continue
                try:
                    close = float(str(row.get("Close", "0")).replace(",", ""))
                    volume = int(str(row.get("TradingShares", "0")).replace(",", ""))
                    turnover = float(str(row.get("TransactionAmount", "0")).replace(",", ""))
                    if close > 0 and stock_id not in result:  # TWSE wins on duplicates
                        result[stock_id] = {
                            "close": close, "volume": volume, "turnover": turnover,
                        }
                        tpex_count += 1
                except (ValueError, TypeError):
                    continue
            logger.info("TPEX daily_all: %d stocks", tpex_count)
    except Exception as exc:
        logger.debug("TPEX daily quotes failed: %s", exc)

    if result:
        logger.info("Combined daily_all: %d total stocks", len(result))
    return result


# ---------------------------------------------------------------------------
# Per-stock historical OHLCV from TWSE/TPEX (個股歷史日線)
# ---------------------------------------------------------------------------

_TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
_TPEX_STOCK_DAY_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingInfo"


def fetch_twse_stock_day(symbol: str, year: int, month: int) -> list[dict]:
    """Fetch one stock's daily OHLCV for a given month from TWSE.

    Returns list of dicts: {date, open, high, low, close, volume}.
    Retries on HTTP 307 (TWSE rate-limit redirect) up to 3 times with backoff.
    Returns empty list only when TWSE genuinely has no data for this stock-month.
    """
    import time as _time

    date_str = f"{year}{month:02d}01"
    max_retries = 3

    for attempt in range(max_retries):
        try:
            resp = requests.get(
                _TWSE_STOCK_DAY_URL,
                params={"date": date_str, "stockNo": symbol, "response": "json"},
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
                verify=False,
            )

            if resp.status_code == 307 or resp.status_code == 403:
                # TWSE rate-limit redirect — wait longer each retry
                wait = [30, 60, 120][attempt]
                logger.warning(
                    "TWSE rate-limited (HTTP %d) for %s %d-%02d, retry %d/%d in %ds",
                    resp.status_code, symbol, year, month, attempt + 1, max_retries, wait,
                )
                _time.sleep(wait)
                continue

            if resp.status_code != 200:
                logger.debug("TWSE STOCK_DAY HTTP %d for %s %d-%02d",
                             resp.status_code, symbol, year, month)
                return []

            data = resp.json()
            if data.get("stat") != "OK":
                return []

            rows = data.get("data") or []
            records: list[dict] = []
            for row in rows:
                if len(row) < 7:
                    continue
                date_parsed = _parse_roc_date(str(row[0]))
                if not date_parsed:
                    continue
                try:
                    records.append({
                        "date": date_parsed,
                        "open": float(str(row[3]).replace(",", "")),
                        "high": float(str(row[4]).replace(",", "")),
                        "low": float(str(row[5]).replace(",", "")),
                        "close": float(str(row[6]).replace(",", "")),
                        "volume": int(str(row[1]).replace(",", "")),
                    })
                except (ValueError, TypeError):
                    continue
            return records

        except Exception as exc:
            logger.debug("TWSE STOCK_DAY failed for %s %d-%02d: %s", symbol, year, month, exc)
            if attempt < max_retries - 1:
                _time.sleep(3)

    logger.warning("TWSE STOCK_DAY exhausted retries for %s %d-%02d", symbol, year, month)
    return []


# ---------------------------------------------------------------------------
# MOPS monthly revenue (公開資訊觀測站月營收)
# ---------------------------------------------------------------------------

_TWSE_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
_TPEX_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"


def fetch_twse_monthly_revenue() -> dict[str, dict]:
    """Fetch the latest monthly revenue for ALL TWSE+TPEX companies.

    Uses TWSE/TPEX OpenData (free, no auth, JSON format).
    Returns only the **latest month** — use FinMind for historical data.

    Returns {stock_id: {"date": "YYYY-MM-01", "revenue": float_twd}} or empty dict.
    Revenue unit: 千元 (thousands of TWD) from TWSE, converted to TWD.
    """
    result: dict[str, dict] = {}

    for url, label in [(_TWSE_REVENUE_URL, "TWSE"), (_TPEX_REVENUE_URL, "TPEX")]:
        try:
            resp = requests.get(
                url,
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
                verify=False,
            )
            if resp.status_code != 200:
                logger.debug("%s revenue OpenData HTTP %d", label, resp.status_code)
                continue

            data = resp.json()
            if not isinstance(data, list) or not data:
                continue

            # Find field keys by substring matching (handles encoding issues)
            sample = data[0]
            code_key = ym_key = rev_key = None
            for k in sample.keys():
                if "公司代號" in k or "SecuritiesCompanyCode" in k.replace(" ", ""):
                    code_key = k
                elif "資料年月" in k or "Year" == k:
                    ym_key = k
                elif "當月營收" in k and "累計" not in k:
                    rev_key = k

            if not code_key or not rev_key:
                logger.warning("%s revenue: cannot identify field keys", label)
                continue

            count = 0
            for row in data:
                stock_id = str(row.get(code_key, "")).strip()
                if not stock_id:
                    continue

                # Parse revenue (unit: 千元 → TWD)
                try:
                    rev_raw = float(str(row.get(rev_key, "0")).replace(",", ""))
                    revenue = rev_raw * 1000  # 千元 → TWD
                except (ValueError, TypeError):
                    continue

                if revenue <= 0:
                    continue

                # Parse date: "11502" → "2026-02-01"
                ym_str = str(row.get(ym_key, "")).strip()
                if len(ym_str) >= 5:
                    roc_year = int(ym_str[:3])
                    month = int(ym_str[3:5])
                    date_str = f"{roc_year + 1911:04d}-{month:02d}-01"
                else:
                    date_str = None

                if stock_id not in result:  # TWSE wins on duplicates
                    result[stock_id] = {"date": date_str, "revenue": revenue}
                    count += 1

            logger.info("%s monthly revenue: %d companies", label, count)

        except Exception as exc:
            logger.debug("%s revenue OpenData failed: %s", label, exc)

    if result:
        logger.info("Total monthly revenue fetched: %d companies (TWSE+TPEX)", len(result))
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
