"""Cache Rebuild — 全新重建 cache（TWSE 為主，FinMind 為輔）。

建立全新 data/cache_new/ 目錄，不動現有 cache。
Phase 0: 建立空目錄
Phase 1: stock_info + dividends（TWSE）
Phase 2: 上市股 OHLCV（TWSE STOCK_DAY）
Phase 3: 上櫃股 OHLCV（FinMind）
Phase 4: Revenue（FinMind）
Phase 5: market_value（TWSE 計算）

Usage:
    docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py
    docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --status
    docker compose run --rm --entrypoint python portfolio-bot scripts/cache_rebuild.py --phase 2
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import pickle
import random
import sys
import time as _time
from datetime import datetime, timedelta

import pandas as pd
import requests as _requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
NEW_CACHE = pathlib.Path(os.environ.get("DATA_CACHE_DIR_NEW",
                                         PROJECT_ROOT / "data" / "cache_new"))
PROGRESS_DIR = PROJECT_ROOT / "data"

TWSE_INTERVAL = 1.5  # seconds between TWSE API calls
START_YEAR = 2019
START_MONTH = 1

# ---------------------------------------------------------------------------
# SOCKS5 Proxy Pool — bypass HiNetCDN IP block on www.twse.com.tw/rwd/zh/
# ---------------------------------------------------------------------------
_PROXY_LIST_URL = "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt"
_PROXY_POOL: list[str] = []  # filled by _init_proxy_pool()
_PROXY_IDX = 0


def _init_proxy_pool(min_working: int = 3, max_scan: int = 150):
    """Scan for working SOCKS5 proxies that can reach TWSE rwd/zh/ endpoints."""
    global _PROXY_POOL
    import urllib3
    urllib3.disable_warnings()

    # First check if direct access works (no proxy needed)
    try:
        r = _requests.get(
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
            params={"date": "20250301", "stockNo": "2330", "response": "json"},
            timeout=8, verify=False,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200 and r.json().get("data"):
            logger.info("TWSE direct access OK — no proxy needed")
            _PROXY_POOL = ["DIRECT"]
            return
    except Exception:
        pass

    logger.info("TWSE blocked (IP ban by HiNetCDN), scanning SOCKS5 proxies...")
    try:
        resp = _requests.get(_PROXY_LIST_URL, timeout=15, verify=False)
        candidates = [p.strip() for p in resp.text.strip().split("\n") if p.strip() and ":" in p]
    except Exception as exc:
        logger.error("Cannot fetch proxy list: %s", exc)
        return

    random.shuffle(candidates)
    working = []
    for i, addr in enumerate(candidates[:max_scan], 1):
        px = {"https": f"socks5h://{addr}", "http": f"socks5h://{addr}"}
        try:
            r = _requests.get(
                "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
                params={"date": "20250301", "stockNo": "2330", "response": "json"},
                proxies=px, timeout=6, verify=False,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200 and r.json().get("data"):
                working.append(addr)
                logger.info("  [%d/%d] proxy OK: %s (found %d/%d)",
                            i, max_scan, addr, len(working), min_working)
                if len(working) >= min_working:
                    break
        except Exception:
            pass

    _PROXY_POOL = working
    if working:
        logger.info("Proxy pool ready: %d proxies", len(working))
    else:
        logger.warning("No working proxies found — TWSE rwd/zh/ requests will fail")


def _get_proxy_kwargs() -> dict:
    """Return requests kwargs to route through the proxy pool (round-robin)."""
    global _PROXY_IDX
    if not _PROXY_POOL or _PROXY_POOL == ["DIRECT"]:
        return {}
    addr = _PROXY_POOL[_PROXY_IDX % len(_PROXY_POOL)]
    _PROXY_IDX += 1
    return {"proxies": {"https": f"socks5h://{addr}", "http": f"socks5h://{addr}"}}


def _twse_rwd_get(url: str, params: dict, timeout: int = 15, max_retries: int = 3) -> _requests.Response | None:
    """GET a TWSE rwd/zh/ URL, retrying across proxy pool on failure."""
    import urllib3
    urllib3.disable_warnings()

    for attempt in range(max_retries):
        proxy_kw = _get_proxy_kwargs()
        try:
            resp = _requests.get(
                url, params=params, timeout=timeout, verify=False,
                headers={"User-Agent": "Mozilla/5.0"},
                **proxy_kw,
            )
            if resp.status_code == 200:
                return resp
            # 307 = still blocked on this proxy, try next
        except Exception:
            pass
    return None


def _progress_file(phase: int) -> pathlib.Path:
    """Each phase has its own progress file to avoid concurrent write conflicts."""
    return PROGRESS_DIR / f"cache_rebuild_p{phase}.json"


def _load_phase_progress(phase: int) -> list:
    p = _progress_file(phase)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return []


def _save_phase_progress(phase: int, done_list: list):
    with open(_progress_file(phase), "w") as f:
        json.dump(done_list, f)


def _is_phase_done(phase: int) -> bool:
    flag = PROGRESS_DIR / f"cache_rebuild_p{phase}_done.flag"
    return flag.exists()


def _mark_phase_done(phase: int):
    flag = PROGRESS_DIR / f"cache_rebuild_p{phase}_done.flag"
    flag.write_text(datetime.now().isoformat())


def _fetch_dividends_via_proxy(start_year: int, end_year: int) -> list[dict]:
    """Fetch TWT49U dividends year-by-year via proxy pool."""
    all_records: list[dict] = []

    for year in range(start_year, end_year + 1):
        resp = _twse_rwd_get(
            "https://www.twse.com.tw/rwd/zh/exRight/TWT49U",
            params={
                "startDate": f"{year}0101",
                "endDate": f"{year}1231",
                "response": "json",
            },
            timeout=15,
        )
        if resp is None:
            logger.warning("TWT49U failed for year %d", year)
            continue

        try:
            rows = resp.json().get("data", [])
        except Exception:
            continue

        year_count = 0
        for row in rows:
            if len(row) < 7:
                continue
            div_type = str(row[6]).strip()
            if div_type != "\u606f":  # "息"
                continue
            stock_id = str(row[1]).strip()
            ex_date = _parse_roc_date(str(row[0]))
            if not ex_date or not stock_id:
                continue
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

        logger.info("TWSE dividends %d: %d cash-dividend records", year, year_count)
        _time.sleep(1.0)

    logger.info("TWSE dividends total: %d records across %d-%d",
                len(all_records), start_year, end_year)
    return all_records


# =========================================================================
# Phase 1: stock_info from TWSE + TPEX OpenAPI
# =========================================================================

def phase1_stock_info():
    """Build stock_info from TWSE + TPEX company profile APIs."""
    if _is_phase_done(1):
        logger.info("Phase 1 already done, skipping")
        return

    logger.info("=== Phase 1: stock_info + dividends ===")

    from src.data.twse_scraper import (
        fetch_twse_issued_capital,
        fetch_twse_dividends,
    )
    import urllib3
    urllib3.disable_warnings()
    import requests

    records = []

    # --- TWSE (上市) ---
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
            timeout=15, headers={"User-Agent": "Mozilla/5.0"}, verify=False,
        )
        if resp.status_code == 200:
            data = resp.json()
            sample = data[0]
            keys = list(sample.keys())
            # Find keys by substring
            code_key = name_key = abbr_key = ind_key = date_key = None
            for k in keys:
                if "公司代號" in k: code_key = k
                elif "公司簡稱" in k: abbr_key = k
                elif "公司名稱" in k and not name_key: name_key = k
                elif "產業" in k or "營業" in k: ind_key = k
                elif "上市日期" in k or "上櫃日期" in k: date_key = k

            for row in data:
                sid = str(row.get(code_key, "")).strip()
                if not sid:
                    continue
                name = str(row.get(abbr_key, row.get(name_key, sid))).strip()
                # Industry code → need mapping (use code for now)
                industry = str(row.get(ind_key, "")).strip()
                date_str = str(row.get(date_key, "")).strip()
                # Parse date: YYYYMMDD → YYYY-MM-DD
                if len(date_str) == 8:
                    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                else:
                    date_fmt = ""
                records.append({
                    "stock_id": sid,
                    "stock_name": name,
                    "industry_category": industry,
                    "type": "twse",
                    "date": date_fmt,
                })
            logger.info("TWSE stock_info: %d companies", len([r for r in records if r["type"] == "twse"]))
    except Exception as exc:
        logger.error("TWSE stock_info failed: %s", exc)

    # --- TPEX (上櫃) ---
    try:
        resp = requests.get(
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
            timeout=15, headers={"User-Agent": "Mozilla/5.0"}, verify=False,
        )
        if resp.status_code == 200:
            data = resp.json()
            sample = data[0]
            code_key = name_key = ind_key = date_key = None
            for k in sample.keys():
                kl = k.lower()
                if "securitiescompanycod" in kl: code_key = k
                elif "companyname" in kl: name_key = k
                elif "securitiesindustryco" in kl: ind_key = k
                elif "dateoflisting" in kl: date_key = k

            for row in data:
                sid = str(row.get(code_key, "")).strip()
                if not sid:
                    continue
                name = str(row.get(name_key, sid)).strip()
                industry = str(row.get(ind_key, "")).strip()
                date_str = str(row.get(date_key, "")).strip()
                if len(date_str) == 8:
                    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                else:
                    date_fmt = ""
                records.append({
                    "stock_id": sid,
                    "stock_name": name,
                    "industry_category": industry,
                    "type": "tpex",
                    "date": date_fmt,
                })
            logger.info("TPEX stock_info: %d companies",
                        len([r for r in records if r["type"] == "tpex"]))
    except Exception as exc:
        logger.error("TPEX stock_info failed: %s", exc)

    if not records:
        logger.error("No stock_info records — cannot continue")
        return

    # Save stock_info
    si_dir = NEW_CACHE / "stock_info"
    si_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    df.to_pickle(si_dir / "_global.pkl")
    df.to_csv(si_dir / "stock_info_snapshot.csv", index=False)
    (si_dir / "_global.meta").write_text(datetime.now().strftime("%Y-%m-%d"))
    logger.info("stock_info saved: %d records", len(df))

    # --- Dividends (TWSE TWT49U via proxy) ---
    div_dir = NEW_CACHE / "dividends"
    div_dir.mkdir(parents=True, exist_ok=True)
    try:
        now = datetime.now()
        divs = _fetch_dividends_via_proxy(START_YEAR, now.year)
        if divs:
            with open(div_dir / "_global.pkl", "wb") as f:
                pickle.dump(divs, f)
            (div_dir / "_global.meta").write_text(now.strftime("%Y-%m-%d"))
            logger.info("Dividends saved: %d records", len(divs))
        else:
            logger.warning("Dividends: 0 records (TWSE TWT49U may be blocked)")
    except Exception as exc:
        logger.error("Dividends failed: %s", exc)

    _mark_phase_done(1)
    logger.info("Phase 1 complete")


# =========================================================================
# Phase 2: 上市股 OHLCV from TWSE STOCK_DAY
# =========================================================================

def _parse_roc_date(roc_str: str) -> str | None:
    """Convert ROC date like '112/07/18' or '112年07月18日' to '2023-07-18'."""
    import re
    m = re.match(r"(\d+)\D+(\d+)\D+(\d+)", roc_str)
    if not m:
        return None
    year = int(m.group(1)) + 1911
    month = int(m.group(2))
    day = int(m.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _generate_trading_dates_yyyymmdd(start_year: int, start_month: int) -> list[str]:
    """Generate weekday dates from start to today as YYYYMMDD strings (for TWSE)."""
    from datetime import date as _date
    d = _date(start_year, start_month, 1)
    today = _date.today()
    dates = []
    while d <= today:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return dates


def phase2_twse_ohlcv():
    """Fetch OHLCV for all TWSE stocks using STOCK_DAY_ALL (逐日全市場快照 via proxy)."""
    logger.info("=== Phase 2: 上市股 OHLCV (TWSE STOCK_DAY_ALL) ===")
    import urllib3
    urllib3.disable_warnings()

    si = pd.read_csv(NEW_CACHE / "stock_info" / "stock_info_snapshot.csv")
    si["stock_id"] = si["stock_id"].astype(str).str.strip()
    twse_stock_set = set(
        si[si["type"] == "twse"]["stock_id"]
        [si["stock_id"].str.fullmatch(r"\d{4}")]
    )
    logger.info("TWSE target stocks: %d", len(twse_stock_set))

    ohlcv_dir = NEW_CACHE / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    # Progress: list of date strings (YYYYMMDD) already done
    done_dates = set(_load_phase_progress(2))
    all_dates = _generate_trading_dates_yyyymmdd(START_YEAR, START_MONTH)
    todo_dates = [d for d in all_dates if d not in done_dates]
    logger.info("Trading dates: %d total, %d done, %d todo",
                len(all_dates), len(done_dates), len(todo_dates))

    # Accumulate per-stock records
    stock_records: dict[str, list[dict]] = {}
    consecutive_empty = 0

    for i, date_str in enumerate(todo_dates, 1):
        if i % 50 == 0 or i <= 3:
            logger.info("[Phase2 %d/%d] %s ...", i, len(todo_dates), date_str)

        resp = _twse_rwd_get(
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL",
            params={"date": date_str, "response": "json"},
            timeout=20,
        )
        if resp is None:
            consecutive_empty += 1
            if consecutive_empty >= 10:
                logger.warning("10 consecutive failures, pausing 60s to refresh proxies...")
                _time.sleep(60)
                consecutive_empty = 0
            done_dates.add(date_str)
            _time.sleep(TWSE_INTERVAL)
            continue

        try:
            data = resp.json()
            rows = data.get("data") or []
        except Exception:
            rows = []

        if not rows:
            consecutive_empty += 1
            done_dates.add(date_str)
            _time.sleep(TWSE_INTERVAL)
            continue

        consecutive_empty = 0
        # Parse date from response (ROC format like "114年03月03日") or from our date_str
        resp_date = data.get("date", "")
        iso_date = _parse_roc_date(resp_date) if resp_date else None
        if not iso_date:
            iso_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        # STOCK_DAY_ALL columns:
        # [0]=Code [1]=Name [2]=TradeVolume [3]=TradeValue [4]=Open [5]=High [6]=Low [7]=Close [8]=Change [9]=Transaction
        for row in rows:
            if len(row) < 8:
                continue
            sid = str(row[0]).strip()
            if sid not in twse_stock_set:
                continue
            try:
                open_str = str(row[4]).replace(",", "").strip()
                high_str = str(row[5]).replace(",", "").strip()
                low_str = str(row[6]).replace(",", "").strip()
                close_str = str(row[7]).replace(",", "").strip()
                vol_str = str(row[2]).replace(",", "").strip()
                if not close_str or close_str == "--" or not open_str or open_str == "--":
                    continue
                record = {
                    "date": iso_date,
                    "open": float(open_str),
                    "high": float(high_str),
                    "low": float(low_str),
                    "close": float(close_str),
                    "volume": int(float(vol_str)),
                }
                stock_records.setdefault(sid, []).append(record)
            except (ValueError, TypeError, IndexError):
                continue

        done_dates.add(date_str)
        if i % 20 == 0:
            _save_phase_progress(2, sorted(done_dates))

        _time.sleep(TWSE_INTERVAL)

    # Save all stock pkl files
    logger.info("Saving %d TWSE stocks to pkl...", len(stock_records))
    for sid, records in stock_records.items():
        if not records:
            continue
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df.index = df.index.tz_localize("UTC")
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        if not df.empty:
            pkl_path = ohlcv_dir / f"{sid}.pkl"
            if pkl_path.exists():
                try:
                    existing = pd.read_pickle(pkl_path)
                    df = pd.concat([existing, df])
                    df = df[~df.index.duplicated(keep="last")].sort_index()
                except Exception:
                    pass
            df.to_pickle(pkl_path)

    _save_phase_progress(2, sorted(done_dates))
    logger.info("Phase 2 complete: %d dates processed, %d stocks saved",
                len(todo_dates), len(stock_records))


# =========================================================================
# Phase 3: 上櫃股 OHLCV from TPEX dailyQuotes (官方)
# =========================================================================

TPEX_INTERVAL = 0.5  # seconds between TPEX API calls

def _generate_trading_dates(start_year: int, start_month: int) -> list[str]:
    """Generate weekday dates from start to today as ROC date strings (YYY/MM/DD)."""
    from datetime import date as _date
    d = _date(start_year, start_month, 1)
    today = _date.today()
    dates = []
    while d <= today:
        if d.weekday() < 5:  # Mon-Fri
            roc_year = d.year - 1911
            dates.append(f"{roc_year}/{d.month:02d}/{d.day:02d}")
        d += timedelta(days=1)
    return dates


def phase3_tpex_ohlcv():
    """Fetch OHLCV for all TPEX stocks using dailyQuotes (逐日全市場快照)."""
    logger.info("=== Phase 3: 上櫃股 OHLCV (TPEX 官方) ===")
    import urllib3
    urllib3.disable_warnings()
    import re

    si = pd.read_csv(NEW_CACHE / "stock_info" / "stock_info_snapshot.csv")
    si["stock_id"] = si["stock_id"].astype(str).str.strip()
    tpex_stock_set = set(
        si[si["type"] == "tpex"]["stock_id"]
        [si["stock_id"].str.fullmatch(r"\d{4}")]
    )
    logger.info("TPEX target stocks: %d", len(tpex_stock_set))

    ohlcv_dir = NEW_CACHE / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    # Progress: list of date strings already done
    done_dates = set(_load_phase_progress(3))
    all_dates = _generate_trading_dates(START_YEAR, START_MONTH)
    todo_dates = [d for d in all_dates if d not in done_dates]
    logger.info("Trading dates: %d total, %d done, %d todo",
                len(all_dates), len(done_dates), len(todo_dates))

    # Accumulate records per stock in memory, flush periodically
    # {stock_id: [{"date": ..., "open": ..., ...}, ...]}
    stock_records: dict[str, list[dict]] = {}
    consecutive_empty = 0

    for i, date_str in enumerate(todo_dates, 1):
        if i % 50 == 0 or i <= 3:
            logger.info("[Phase3 %d/%d] %s ...", i, len(todo_dates), date_str)

        try:
            resp = _requests.get(
                "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
                params={"date": date_str, "response": "json"},
                timeout=15, verify=False,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            if resp.status_code != 200:
                consecutive_empty += 1
                if consecutive_empty >= 10:
                    logger.warning("10 consecutive failures, pausing 30s...")
                    _time.sleep(30)
                    consecutive_empty = 0
                done_dates.add(date_str)
                _time.sleep(TPEX_INTERVAL)
                continue

            data = resp.json()
            tables = data.get("tables", [])
            if not tables or not tables[0].get("data"):
                # Holiday or no trading
                consecutive_empty += 1
                done_dates.add(date_str)
                _time.sleep(TPEX_INTERVAL)
                continue

            consecutive_empty = 0
            rows = tables[0]["data"]
            # Parse ROC date -> ISO date
            roc_date = data.get("date", date_str)  # e.g. "114/03/03"
            iso_date = _parse_roc_date(roc_date)
            if not iso_date:
                # Fallback: parse from date_str
                parts = date_str.split("/")
                y = int(parts[0]) + 1911
                iso_date = f"{y}-{parts[1]}-{parts[2]}"

            day_count = 0
            for row in rows:
                sid = str(row[0]).strip()
                if sid not in tpex_stock_set:
                    continue
                try:
                    # [2]=收盤 [4]=開盤 [5]=最高 [6]=最低 [8]=成交股數
                    close_str = str(row[2]).replace(",", "").strip()
                    open_str = str(row[4]).replace(",", "").strip()
                    high_str = str(row[5]).replace(",", "").strip()
                    low_str = str(row[6]).replace(",", "").strip()
                    vol_str = str(row[8]).replace(",", "").strip()
                    # Skip if any price is empty or "--"
                    if not close_str or close_str == "--" or not open_str or open_str == "--":
                        continue
                    record = {
                        "date": iso_date,
                        "open": float(open_str),
                        "high": float(high_str),
                        "low": float(low_str),
                        "close": float(close_str),
                        "volume": int(float(vol_str)),
                    }
                    stock_records.setdefault(sid, []).append(record)
                    day_count += 1
                except (ValueError, TypeError, IndexError):
                    continue

        except Exception as exc:
            logger.debug("Phase3 error on %s: %s", date_str, exc)
            consecutive_empty += 1

        done_dates.add(date_str)
        if i % 20 == 0:
            _save_phase_progress(3, sorted(done_dates))

        _time.sleep(TPEX_INTERVAL)

    # Save all stock pkl files
    logger.info("Saving %d TPEX stocks to pkl...", len(stock_records))
    for sid, records in stock_records.items():
        if not records:
            continue
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df.index = df.index.tz_localize("UTC")
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        if not df.empty:
            # Merge with existing pkl if any (from resumed runs)
            pkl_path = ohlcv_dir / f"{sid}.pkl"
            if pkl_path.exists():
                try:
                    existing = pd.read_pickle(pkl_path)
                    df = pd.concat([existing, df])
                    df = df[~df.index.duplicated(keep="last")].sort_index()
                except Exception:
                    pass
            df.to_pickle(pkl_path)

    _save_phase_progress(3, sorted(done_dates))
    logger.info("Phase 3 complete: %d dates processed, %d stocks saved",
                len(todo_dates), len(stock_records))


# =========================================================================
# Phase 4: Revenue from FinMind
# =========================================================================

def _scan_finmind_proxies(count: int = 3, max_scan: int = 120) -> list[str]:
    """Find SOCKS5 proxies that can reach api.finmindtrade.com."""
    import urllib3
    urllib3.disable_warnings()

    logger.info("Scanning SOCKS5 proxies for FinMind API (%d needed)...", count)
    try:
        resp = _requests.get(_PROXY_LIST_URL, timeout=15, verify=False)
        candidates = [p.strip() for p in resp.text.strip().split("\n")
                      if p.strip() and ":" in p]
    except Exception as exc:
        logger.error("Cannot fetch proxy list: %s", exc)
        return []

    random.shuffle(candidates)
    working = []
    for i, addr in enumerate(candidates[:max_scan], 1):
        px = {"https": f"socks5h://{addr}", "http": f"socks5h://{addr}"}
        try:
            r = _requests.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={"dataset": "TaiwanStockMonthRevenue",
                        "data_id": "2330", "start_date": "2025-01-01"},
                proxies=px, timeout=8, verify=False,
            )
            if r.status_code == 200 and "data" in r.json():
                working.append(addr)
                logger.info("  [%d/%d] FinMind proxy OK: %s (found %d/%d)",
                            i, max_scan, addr, len(working), count)
                if len(working) >= count:
                    break
        except Exception:
            pass

    logger.info("FinMind proxy scan done: %d working proxies", len(working))
    return working


def phase4_revenue():
    """Fetch Revenue using FinMind — sequential token+proxy rotation.

    Each token uses a different proxy (different IP) to avoid FinMind's
    IP-based rate limit. Runs one token at a time until quota exhausted,
    then switches to next token+proxy pair. No threading, no race conditions.
    """
    logger.info("=== Phase 4: Revenue (FinMind, sequential token+proxy) ===")

    from src.data.finmind import FinMindSource

    si = pd.read_csv(NEW_CACHE / "stock_info" / "stock_info_snapshot.csv")
    si["stock_id"] = si["stock_id"].astype(str).str.strip()
    all_stocks = sorted(set(
        si[si["stock_id"].str.fullmatch(r"\d{4}")]["stock_id"]
    ))

    done_set = set(_load_phase_progress(4))
    todo = [s for s in all_stocks if s not in done_set]
    logger.info("Revenue: %d total, %d done, %d todo",
                len(all_stocks), len(done_set), len(todo))

    if not todo:
        logger.info("Phase 4: nothing to do")
        return

    # Collect available tokens (order matters: try each until quota exhausted)
    tokens = []
    for key in ["FINMIND_TOKEN4", "FINMIND_TOKEN", "FINMIND_TOKEN2", "FINMIND_TOKEN3"]:
        t = os.environ.get(key)
        if t:
            tokens.append((key, t))

    if not tokens:
        logger.error("No FINMIND_TOKEN found")
        return

    logger.info("Found %d FinMind tokens", len(tokens))

    # Try direct connection first; scan proxies only when direct quota exhausted
    use_proxy = False
    fm_proxies: list[str] = []

    total_ok = 0

    for token_idx, (token_name, token_val) in enumerate(tokens):
        # Refresh todo (previous token may have completed some)
        todo = [s for s in all_stocks if s not in done_set]
        if not todo:
            break

        source = FinMindSource(token=token_val, backtest_mode=False,
                               cache_dir=str(NEW_CACHE))

        # First token: try direct. Subsequent tokens: use proxy.
        if token_idx == 0:
            logger.info("[Token %d/%d] %s via DIRECT — %d stocks remaining",
                        token_idx + 1, len(tokens), token_name, len(todo))
        else:
            # Scan proxies on demand (only when we actually need them)
            if not fm_proxies:
                fm_proxies = _scan_finmind_proxies(count=len(tokens) - 1)
            pidx = token_idx - 1
            if pidx < len(fm_proxies):
                proxy_addr = fm_proxies[pidx]
                px = {"https": f"socks5h://{proxy_addr}", "http": f"socks5h://{proxy_addr}"}
                source.loader._FinMindApi__session.proxies.update(px)
                logger.info("[Token %d/%d] %s via proxy %s — %d stocks remaining",
                            token_idx + 1, len(tokens), token_name, proxy_addr, len(todo))
            else:
                logger.warning("[Token %d] No proxy available — skipping", token_idx + 1)
                continue

        failed_count = 0
        token_ok = 0

        for i, sym in enumerate(todo, 1):
            if i % 100 == 0 or i <= 3:
                logger.info("[Token %d] [%d/%d] %s ...",
                            token_idx + 1, i, len(todo), sym)

            is_good = False
            try:
                df = source.fetch_month_revenue(sym, months=60)
                if df is not None and not df.empty and len(df) >= 12:
                    is_good = True
                    failed_count = 0
                elif df is not None and not df.empty:
                    failed_count += 1
                else:
                    failed_count += 1
            except KeyError:
                pass
            except Exception:
                failed_count += 1

            if is_good:
                done_set.add(sym)
                token_ok += 1
                total_ok += 1
            if i % 50 == 0:
                _save_phase_progress(4, sorted(done_set))

            # Only stop on actual quota exhaustion (HTTP 402), not on
            # stocks that FinMind genuinely has no data for.
            # Use a high threshold — many 8xxx/9xxx stocks have no revenue data.
            if failed_count >= 100:
                logger.warning("[Token %d] %s — 100 consecutive failures, likely quota exhausted after %d OK — switching",
                               token_idx + 1, token_name, token_ok)
                _save_phase_progress(4, sorted(done_set))
                break

        logger.info("[Token %d] %s finished: %d OK", token_idx + 1, token_name, token_ok)

    _save_phase_progress(4, sorted(done_set))
    remaining = len(all_stocks) - len(done_set)
    logger.info("Phase 4 done this run: %d OK (total %d/%d, remaining %d)",
                total_ok, len(done_set), len(all_stocks), remaining)
    if remaining > 0:
        logger.info("Re-run --phase 4 after quota resets to continue")


# =========================================================================
# Phase 5: market_value from TWSE
# =========================================================================

def phase5_market_value():
    """Compute market_value from TWSE shares × OHLCV cache."""
    if _is_phase_done(5):
        logger.info("Phase 5 already done, skipping")
        return

    logger.info("=== Phase 5: market_value ===")

    from src.data.twse_scraper import fetch_twse_issued_capital

    shares = fetch_twse_issued_capital()
    if not shares:
        logger.error("Cannot fetch issued capital")
        return

    ohlcv_dir = NEW_CACHE / "ohlcv"
    records = []
    for p in ohlcv_dir.glob("*.pkl"):
        sym = p.stem
        if sym not in shares:
            continue
        try:
            df = pd.read_pickle(p)
            if df.empty or "close" not in df.columns:
                continue
            close = df[["close"]].copy()
            close.index = pd.to_datetime(close.index, utc=True)
            monthly = close.resample("ME").last().dropna()
            for ts, row in monthly.iterrows():
                records.append({
                    "stock_id": sym,
                    "date": ts.tz_localize(None),
                    "market_value": float(row["close"]) * shares[sym],
                })
        except Exception:
            continue

    if records:
        mv_dir = NEW_CACHE / "market_value"
        mv_dir.mkdir(parents=True, exist_ok=True)
        result = pd.DataFrame(records)
        result["date"] = pd.to_datetime(result["date"])
        result["market_value"] = pd.to_numeric(result["market_value"], errors="coerce")
        result = result.sort_values(["stock_id", "date"]).reset_index(drop=True)
        result.to_pickle(mv_dir / "_global.pkl")
        (mv_dir / "_global.meta").write_text(datetime.now().strftime("%Y-%m-%d"))
        logger.info("market_value saved: %d stocks, %d records", len(shares), len(result))

    _mark_phase_done(5)
    logger.info("Phase 5 complete")


# =========================================================================
# Main
# =========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Cache Rebuild — 全新重建")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--phase", type=int, help="只跑指定 phase (1-5)")
    args = parser.parse_args()

    if args.status:
        print(f"Phase 1 (stock_info):   {'done' if _is_phase_done(1) else 'pending'}")
        print(f"Phase 2 (TWSE OHLCV):   {len(_load_phase_progress(2))} stocks done")
        print(f"Phase 3 (TPEX OHLCV):   {len(_load_phase_progress(3))} stocks done")
        print(f"Phase 4 (Revenue):      {len(_load_phase_progress(4))} stocks done")
        print(f"Phase 5 (market_value): {'done' if _is_phase_done(5) else 'pending'}")
        return

    NEW_CACHE.mkdir(parents=True, exist_ok=True)

    if args.phase:
        phases = [args.phase]
    else:
        phases = [1, 2, 3, 4, 5]

    # Init proxy pool for phases that need TWSE rwd/zh/ access (1, 2)
    if any(p in phases for p in (1, 2)):
        _init_proxy_pool()

    for p in phases:
        if p == 1:
            phase1_stock_info()
        elif p == 2:
            phase2_twse_ohlcv()
        elif p == 3:
            phase3_tpex_ohlcv()
        elif p == 4:
            phase4_revenue()
        elif p == 5:
            phase5_market_value()

    logger.info("=" * 50)
    logger.info("Cache rebuild finished. New cache at: %s", NEW_CACHE)
    logger.info("To switch: mv data/cache data/cache_old && mv data/cache_new data/cache")


if __name__ == "__main__":
    main()
