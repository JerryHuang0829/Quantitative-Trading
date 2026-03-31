"""Paper trading recorder.

Runs the portfolio rebalance logic once and saves the recommendation
to reports/paper_trading/YYYY-MM.json.  No real orders are placed.

Usage:
    # Inside Docker:
    docker compose run --rm --entrypoint python portfolio-bot scripts/paper_trade.py

    # Or directly (with venv):
    python scripts/paper_trade.py

    # With custom config:
    python scripts/paper_trade.py --config config/settings.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.data.finmind import FinMindSource
from src.portfolio.tw_stock import (
    build_tw_stock_universe,
    get_portfolio_config,
    run_tw_stock_portfolio_rebalance,
)
from src.storage.database import Database
from src.utils.config import load_config
from src.utils.constants import TW_TZ

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Windows 上直接跑會因為 pickle cache encoding 導致中文亂碼，
# 必須在 Docker 裡執行（Linux UTF-8 環境）。
if sys.platform == "win32":
    logger.warning(
        "⚠️  Running on Windows — FinMind cache pickles may have encoding issues.\n"
        "    建議改用 Docker 執行：\n"
        "    docker compose run --rm --entrypoint python portfolio-bot scripts/paper_trade.py"
    )

OUTPUT_DIR = Path("reports/paper_trading")


def main():
    parser = argparse.ArgumentParser(description="Paper trading recorder")
    parser.add_argument("--config", default="config/settings.yaml", help="Config file path")
    args = parser.parse_args()

    load_dotenv()

    config = load_config(args.config)
    portfolio_config = get_portfolio_config(config)

    token = os.getenv("FINMIND_TOKEN")
    source = FinMindSource(token=token)
    db = Database(config.get("database", {}).get("path", "data/signals.db"))

    logger.info("Running paper trade rebalance...")
    snapshot = run_tw_stock_portfolio_rebalance(config, source, db, portfolio_config)

    if snapshot is None:
        logger.error("Rebalance returned None — check logs for errors")
        sys.exit(1)

    # Build paper trading record
    now = datetime.now(TW_TZ)
    month_key = now.strftime("%Y-%m")

    record = {
        "date": now.strftime("%Y-%m-%d"),
        "month_key": month_key,
        "market_signal": snapshot["market_signal"],
        "market_regime": snapshot["market_regime"],
        "gross_exposure": snapshot["gross_exposure"],
        "total_candidates": snapshot["total_candidates"],
        "eligible_candidates": snapshot["eligible_candidates"],
        "selected_count": snapshot["selected_count"],
        "positions": [
            {
                "symbol": p["symbol"],
                "name": p.get("name", ""),
                "weight": p.get("target_weight", p.get("weight", 0)),
                "score": p.get("portfolio_score", p.get("score", 0)),
                "industry": p.get("industry", ""),
            }
            for p in snapshot["positions"]
        ],
        "top10_ranking": [
            {
                "rank": r["rank"],
                "symbol": r["symbol"],
                "name": r["name"],
                "score": r.get("score", r.get("portfolio_score", 0)),
            }
            for r in snapshot.get("ranking", [])
        ],
        "config_hash": snapshot.get("config_hash", ""),
    }

    # Save monthly record
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{month_key}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    # Append to performance tracker
    perf_path = OUTPUT_DIR / "history.json"
    history = []
    if perf_path.exists():
        with open(perf_path, "r", encoding="utf-8") as f:
            history = json.load(f)

    # Remove old entry for same month (re-run safe)
    history = [h for h in history if h["month_key"] != month_key]
    history.append({
        "month_key": month_key,
        "date": record["date"],
        "market_signal": record["market_signal"],
        "gross_exposure": record["gross_exposure"],
        "selected_count": record["selected_count"],
        "positions": record["positions"],
        "actual_return": None,  # Fill in next month
    })
    history.sort(key=lambda x: x["month_key"])

    with open(perf_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    # Print summary
    print("\n" + "=" * 50)
    print("  Paper Trading Record")
    print("=" * 50)
    print(f"\n  日期:       {record['date']}")
    print(f"  市場訊號:   {record['market_signal']}")
    print(f"  總曝險:     {record['gross_exposure']:.0%}")
    print(f"  持股數:     {record['selected_count']}")
    print(f"\n  --- 建議持股 ---")
    for p in record["positions"]:
        print(f"    {p['symbol']} {p['name']:　<6} 權重 {p['weight']:.1%}  分數 {p['score']:.1f}")
    print(f"\n  --- Top 10 排名 ---")
    for r in record["top10_ranking"]:
        print(f"    #{r['rank']} {r['symbol']} {r['name']:　<6} {r['score']:.1f}")
    print(f"\n  已儲存: {out_path}")
    print(f"  歷史紀錄: {perf_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
