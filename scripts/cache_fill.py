"""Cache Fill — 補齊 + 更新 OHLCV + Revenue 資料。

可中斷恢復：進度記錄在 data/cache_fill_progress.json。

Usage:
    # 只補缺失的（預設）
    docker compose run --rm --entrypoint python portfolio-bot scripts/cache_fill.py

    # 全面更新（補缺失 + 更新過時的到最新）
    docker compose run --rm --entrypoint python portfolio-bot scripts/cache_fill.py --refresh-all

    # 只補 top-80
    docker compose run --rm --entrypoint python portfolio-bot scripts/cache_fill.py --top-80-only

    # 查看進度
    docker compose run --rm --entrypoint python portfolio-bot scripts/cache_fill.py --status
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
import time
from datetime import datetime

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE_DIR = pathlib.Path(os.environ.get("DATA_CACHE_DIR", PROJECT_ROOT / "data" / "cache"))
PROGRESS_FILE = PROJECT_ROOT / "data" / "cache_fill_progress.json"


def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"ohlcv_done": [], "revenue_done": []}


def _save_progress(progress: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def _get_tradeable_stocks() -> set[str]:
    """Return deduplicated set of tradeable stock_ids (excl ETF, emerging, delisted)."""
    csv_path = CACHE_DIR / "stock_info" / "stock_info_snapshot.csv"
    si = pd.read_csv(csv_path)
    si["stock_id"] = si["stock_id"].astype(str).str.strip()

    if "date" in si.columns:
        si["date"] = pd.to_datetime(si["date"], errors="coerce")
        si = si.sort_values(["stock_id", "date"]).drop_duplicates("stock_id", keep="last")

    mask = (
        si["stock_id"].str.fullmatch(r"\d{4}")
        & ~si["stock_id"].str.startswith("00")
        & ~si["type"].str.contains("emerging", case=False, na=False)
    )
    tradeable = set(si[mask]["stock_id"])

    delist_path = CACHE_DIR / "delisting" / "_global.pkl"
    if delist_path.exists():
        try:
            dl = pd.read_pickle(delist_path)
            if "stock_id" in dl.columns:
                delisted = set(dl["stock_id"].astype(str))
                removed = tradeable & delisted
                tradeable -= delisted
                if removed:
                    logger.info("Excluded %d delisted stocks", len(removed))
        except Exception:
            pass

    return tradeable


def _get_top80() -> list[str]:
    """Return top-80 stocks by close×volume from OHLCV cache."""
    ohlcv_dir = CACHE_DIR / "ohlcv"
    size_proxy = {}
    for p in ohlcv_dir.glob("*.pkl"):
        try:
            df = pd.read_pickle(p)
            if len(df) >= 5:
                tv = (df["close"] * df["volume"]).tail(20).mean()
                size_proxy[p.stem] = float(tv) if pd.notna(tv) else 0.0
        except Exception:
            continue
    ranked = sorted(size_proxy.items(), key=lambda x: -x[1])
    return [r[0] for r in ranked[:80]]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Cache Fill — 補齊 + 更新 OHLCV + Revenue")
    parser.add_argument("--status", action="store_true", help="只顯示進度")
    parser.add_argument("--top-80-only", action="store_true", help="只補 top-80 缺失")
    parser.add_argument("--refresh-all", action="store_true",
                        help="全面更新：補缺失 + 更新所有過時資料到最新")
    args = parser.parse_args()

    progress = _load_progress()

    if args.status:
        print(f"OHLCV done: {len(progress['ohlcv_done'])}")
        print(f"Revenue done: {len(progress['revenue_done'])}")
        return

    tradeable = _get_tradeable_stocks()
    logger.info("Tradeable stocks (excl ETF/emerging/delisted): %d", len(tradeable))

    from src.data.finmind import FinMindSource

    token = os.environ.get("FINMIND_TOKEN")
    source = FinMindSource(token=token, backtest_mode=False)

    top80 = _get_top80()

    # ====== Phase 1: OHLCV ======
    ohlcv_dir = CACHE_DIR / "ohlcv"
    ohlcv_cached = {p.stem for p in ohlcv_dir.glob("*.pkl")} if ohlcv_dir.exists() else set()
    ohlcv_done_set = set(progress["ohlcv_done"])

    if args.refresh_all:
        # Update ALL tradeable stocks (both missing and stale)
        ohlcv_todo = sorted(tradeable - ohlcv_done_set)
    else:
        # Only missing stocks
        ohlcv_missing = tradeable - ohlcv_cached
        ohlcv_todo = sorted(ohlcv_missing - ohlcv_done_set)

    if args.top_80_only:
        ohlcv_todo = [s for s in ohlcv_todo if s in set(top80)]

    logger.info("=== Phase 1: OHLCV ===")
    logger.info("Mode: %s", "refresh-all" if args.refresh_all else "missing-only")
    logger.info("Todo: %d stocks", len(ohlcv_todo))

    ohlcv_updated = 0
    ohlcv_skipped = 0
    failed_count = 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    stale_cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=3)

    for i, sym in enumerate(ohlcv_todo, 1):
        if i % 100 == 0 or i <= 5:
            logger.info("[OHLCV %d/%d] %s ...", i, len(ohlcv_todo), sym)
        try:
            df = source.fetch_ohlcv(sym, "D", 2000)
            if df is not None and not df.empty:
                # In refresh-all mode, verify data actually updated
                if args.refresh_all:
                    max_date = df.index.max()
                    if pd.Timestamp(max_date).tz_localize(None) < stale_cutoff:
                        # Data returned but still stale — API likely failed silently
                        ohlcv_skipped += 1
                        failed_count += 1
                        continue  # Don't mark as done, retry next run
                ohlcv_updated += 1
                failed_count = 0
            else:
                ohlcv_skipped += 1
                failed_count += 1
        except Exception as exc:
            if i <= 10:
                logger.warning("  Error: %s", exc)
            ohlcv_skipped += 1
            failed_count += 1

        if failed_count == 0:
            progress["ohlcv_done"].append(sym)
        if i % 50 == 0:
            _save_progress(progress)

        if failed_count >= 20:
            logger.warning("20 consecutive failures — API quota likely exhausted. Progress saved.")
            _save_progress(progress)
            break

    _save_progress(progress)
    logger.info("OHLCV done: %d updated, %d skipped/failed", ohlcv_updated, ohlcv_skipped)

    # ====== Phase 2: Revenue ======
    rev_done_set = set(progress["revenue_done"])

    if args.refresh_all:
        # Update ALL tradeable stocks
        rev_todo_set = tradeable - rev_done_set
    else:
        # Only missing (no cache file or sentinel)
        rev_dir = CACHE_DIR / "revenue"
        rev_has_data = set()
        if rev_dir.exists():
            for p in rev_dir.glob("*.pkl"):
                try:
                    df = pd.read_pickle(p)
                    if not df.empty:
                        rev_has_data.add(p.stem)
                except Exception:
                    pass
        rev_todo_set = tradeable - rev_has_data - rev_done_set

    # Prioritize top-80
    top80_set = set(top80)
    top80_rev = sorted(rev_todo_set & top80_set)
    others_rev = sorted(rev_todo_set - top80_set)

    if args.top_80_only:
        rev_ordered = top80_rev
    else:
        rev_ordered = top80_rev + others_rev

    logger.info("=== Phase 2: Revenue ===")
    logger.info("Mode: %s", "refresh-all" if args.refresh_all else "missing-only")
    logger.info("Todo: %d stocks (top-80 first: %d)", len(rev_ordered), len(top80_rev))

    rev_updated = 0
    rev_skipped = 0
    failed_count = 0
    min_months = 12  # Need at least 12 months for YoY calculation

    for i, sym in enumerate(rev_ordered, 1):
        if i % 100 == 0 or i <= 5:
            logger.info("[Revenue %d/%d] %s ...", i, len(rev_ordered), sym)
        is_good = False
        try:
            df = source.fetch_month_revenue(sym, months=60)
            if df is not None and not df.empty and len(df) >= min_months:
                rev_updated += 1
                failed_count = 0
                is_good = True
            else:
                # None, empty, or < 12 months (TWSE fallback 1-month)
                # Don't mark as done — retry when FinMind has quota
                rev_skipped += 1
                failed_count += 1
        except Exception as exc:
            if i <= 10:
                logger.warning("  Error: %s", exc)
            rev_skipped += 1
            failed_count += 1

        if is_good:
            progress["revenue_done"].append(sym)
        if i % 50 == 0:
            _save_progress(progress)

        if failed_count >= 20:
            logger.warning("20 consecutive failures — API quota likely exhausted. Progress saved.")
            _save_progress(progress)
            break

    _save_progress(progress)
    logger.info("Revenue done: %d updated, %d skipped/failed", rev_updated, rev_skipped)

    # ====== Summary ======
    logger.info("=" * 50)
    logger.info("  OHLCV:   %d updated, %d skipped", ohlcv_updated, ohlcv_skipped)
    logger.info("  Revenue: %d updated, %d skipped", rev_updated, rev_skipped)
    logger.info("=" * 50)
    logger.info("Run cache_health.py to verify coverage.")
    if failed_count >= 20:
        logger.info("API quota exhausted. Delete data/cache_fill_progress.json and re-run to continue.")


if __name__ == "__main__":
    main()
