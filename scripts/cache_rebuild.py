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
import sys
import time as _time
from datetime import datetime, timedelta

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
NEW_CACHE = pathlib.Path(os.environ.get("DATA_CACHE_DIR_NEW",
                                         PROJECT_ROOT / "data" / "cache_new"))
PROGRESS_DIR = PROJECT_ROOT / "data"

TWSE_INTERVAL = 1.5  # seconds between TWSE API calls
START_YEAR = 2019
START_MONTH = 1


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
        _parse_company_profile,
    )
    import requests
    import urllib3
    urllib3.disable_warnings()

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

    # --- Dividends (TWSE) ---
    div_dir = NEW_CACHE / "dividends"
    div_dir.mkdir(parents=True, exist_ok=True)
    try:
        now = datetime.now()
        divs = fetch_twse_dividends(START_YEAR, now.year)
        if divs:
            with open(div_dir / "_global.pkl", "wb") as f:
                pickle.dump(divs, f)
            (div_dir / "_global.meta").write_text(now.strftime("%Y-%m-%d"))
            logger.info("Dividends saved: %d records", len(divs))
    except Exception as exc:
        logger.error("Dividends failed: %s", exc)

    _mark_phase_done(1)
    logger.info("Phase 1 complete")


# =========================================================================
# Phase 2: 上市股 OHLCV from TWSE STOCK_DAY
# =========================================================================

def phase2_twse_ohlcv():
    """Fetch OHLCV for all TWSE-listed stocks using STOCK_DAY."""
    logger.info("=== Phase 2: 上市股 OHLCV (TWSE) ===")

    from src.data.twse_scraper import fetch_twse_stock_day

    si = pd.read_csv(NEW_CACHE / "stock_info" / "stock_info_snapshot.csv")
    si["stock_id"] = si["stock_id"].astype(str).str.strip()
    twse_stocks = sorted(set(
        si[si["type"] == "twse"]["stock_id"]
        [si["stock_id"].str.fullmatch(r"\d{4}")]
    ))

    done_set = set(_load_phase_progress(2))
    todo = [s for s in twse_stocks if s not in done_set]
    logger.info("TWSE stocks: %d total, %d done, %d todo", len(twse_stocks), len(done_set), len(todo))

    ohlcv_dir = NEW_CACHE / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    end_year = now.year
    end_month = now.month

    for i, sym in enumerate(todo, 1):
        if i % 50 == 0 or i <= 3:
            logger.info("[Phase2 %d/%d] %s ...", i, len(todo), sym)

        all_records = []
        year, month = START_YEAR, START_MONTH
        consecutive_empty = 0

        while (year, month) <= (end_year, end_month):
            records = fetch_twse_stock_day(sym, year, month)
            if records:
                all_records.extend(records)
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                # If 12 consecutive empty months, stock likely not listed yet or delisted
                if consecutive_empty >= 12:
                    break

            # Next month
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1

            _time.sleep(TWSE_INTERVAL)

        if all_records:
            df = pd.DataFrame(all_records)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            df.index = df.index.tz_localize("UTC")
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            df.to_pickle(ohlcv_dir / f"{sym}.pkl")

        done_set.add(sym)
        if i % 10 == 0:
            _save_phase_progress(2, sorted(done_set))

    _save_phase_progress(2, sorted(done_set))
    logger.info("Phase 2 complete: %d TWSE stocks processed", len(todo))


# =========================================================================
# Phase 3: 上櫃股 OHLCV from FinMind
# =========================================================================

def phase3_tpex_ohlcv():
    """Fetch OHLCV for TPEX stocks using FinMind, save with clean 5-column format."""
    logger.info("=== Phase 3: 上櫃股 OHLCV (FinMind) ===")

    from FinMind.data import DataLoader

    si = pd.read_csv(NEW_CACHE / "stock_info" / "stock_info_snapshot.csv")
    si["stock_id"] = si["stock_id"].astype(str).str.strip()
    tpex_stocks = sorted(set(
        si[si["type"] == "tpex"]["stock_id"]
        [si["stock_id"].str.fullmatch(r"\d{4}")]
    ))

    done_set = set(_load_phase_progress(3))
    todo = [s for s in tpex_stocks if s not in done_set]
    logger.info("TPEX stocks: %d total, %d done, %d todo", len(tpex_stocks), len(done_set), len(todo))

    token = os.environ.get("FINMIND_TOKEN")
    loader = DataLoader()
    if token:
        loader.login_by_token(api_token=token)

    ohlcv_dir = NEW_CACHE / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    start_date = f"{START_YEAR}-{START_MONTH:02d}-01"
    end_date = datetime.now().strftime("%Y-%m-%d")

    failed_count = 0
    data_not_found = []

    for i, sym in enumerate(todo, 1):
        if i % 50 == 0 or i <= 3:
            logger.info("[Phase3 %d/%d] %s ...", i, len(todo), sym)

        try:
            _time.sleep(0.5)  # Rate limit
            raw = loader.taiwan_stock_daily(
                stock_id=sym, start_date=start_date, end_date=end_date,
            )
            if raw is not None and not raw.empty:
                # Normalize to clean 5-column format (same as Phase 2)
                df = raw.rename(columns={
                    "date": "timestamp", "max": "high", "min": "low",
                    "Trading_Volume": "volume",
                })
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                df = df.set_index("timestamp").sort_index()
                for col in ("open", "high", "low", "close", "volume"):
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df[["open", "high", "low", "close", "volume"]].dropna()
                if not df.empty:
                    df.to_pickle(ohlcv_dir / f"{sym}.pkl")
                    failed_count = 0
                else:
                    data_not_found.append(sym)
                    failed_count += 1
            else:
                data_not_found.append(sym)
                failed_count += 1
        except KeyError as exc:
            if str(exc) == "'data'":
                data_not_found.append(sym)
            else:
                failed_count += 1
        except Exception as exc:
            if i <= 5:
                logger.warning("  Error: %s", exc)
            failed_count += 1

        done_set.add(sym)
        if i % 50 == 0:
            _save_phase_progress(3, sorted(done_set))

        if failed_count >= 20:
            logger.warning("20 consecutive non-data failures — quota likely exhausted")
            _save_phase_progress(3, sorted(done_set))
            break

    _save_phase_progress(3, sorted(done_set))
    if data_not_found:
        failed_path = PROJECT_ROOT / "data" / "cache_rebuild_failed_tpex.json"
        with open(failed_path, "w") as f:
            json.dump(data_not_found, f)
        logger.info("TPEX data-not-found: %d stocks (saved to %s)", len(data_not_found), failed_path)
    logger.info("Phase 3 complete")


# =========================================================================
# Phase 4: Revenue from FinMind
# =========================================================================

def phase4_revenue():
    """Fetch Revenue for all stocks using FinMind."""
    logger.info("=== Phase 4: Revenue (FinMind) ===")

    from src.data.finmind import FinMindSource

    si = pd.read_csv(NEW_CACHE / "stock_info" / "stock_info_snapshot.csv")
    si["stock_id"] = si["stock_id"].astype(str).str.strip()
    all_stocks = sorted(set(
        si[si["stock_id"].str.fullmatch(r"\d{4}")]["stock_id"]
    ))

    done_set = set(_load_phase_progress(4))
    todo = [s for s in all_stocks if s not in done_set]
    logger.info("Revenue: %d total, %d done, %d todo", len(all_stocks), len(done_set), len(todo))

    token = os.environ.get("FINMIND_TOKEN")
    source = FinMindSource(token=token, backtest_mode=False,
                           cache_dir=str(NEW_CACHE))

    failed_count = 0

    for i, sym in enumerate(todo, 1):
        if i % 100 == 0 or i <= 3:
            logger.info("[Phase4 %d/%d] %s ...", i, len(todo), sym)

        is_good = False
        try:
            df = source.fetch_month_revenue(sym, months=60)
            if df is not None and not df.empty and len(df) >= 12:
                is_good = True
                failed_count = 0
            elif df is not None and not df.empty:
                # < 12 months — don't count as done
                failed_count += 1
            else:
                failed_count += 1
        except KeyError:
            pass  # data not found, don't count toward quota stop
        except Exception:
            failed_count += 1

        if is_good:
            done_set.add(sym)
        if i % 50 == 0:
            _save_phase_progress(4, sorted(done_set))

        if failed_count >= 20:
            logger.warning("20 consecutive failures — quota likely exhausted")
            _save_phase_progress(4, sorted(done_set))
            break

    _save_phase_progress(4, sorted(done_set))
    logger.info("Phase 4 complete")


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
