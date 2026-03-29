"""CLI entrypoint for running backtests locally or inside Docker."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.backtest.engine import BacktestEngine
from src.data.finmind import FinMindSource
from src.utils.config import load_config


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Taiwan stock portfolio backtest")
    parser.add_argument("--config", default="config/settings.yaml", help="Path to YAML config")
    parser.add_argument("--start", required=True, help="Backtest start date in YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Backtest end date in YYYY-MM-DD")
    parser.add_argument("--benchmark", default="0050", help="Benchmark symbol")
    parser.add_argument(
        "--output-dir",
        default="reports/backtests",
        help="Directory for metrics/report artifacts",
    )
    parser.add_argument(
        "--slippage-bps",
        type=int,
        default=5,
        help="Per-trade slippage assumption in basis points",
    )
    return parser.parse_args()


def _preflight_check(source, benchmark_symbol: str = "0050") -> bool:
    """回測前檢查關鍵 API 是否可用，避免在長時間運算後才 fail-fast。

    Returns True if all critical checks pass, False otherwise.
    """
    print("=" * 50)
    print("  Preflight Check — FinMind API Availability")
    print("=" * 50)
    ok = True

    # 1. TaiwanStockInfo — 必要（universe 建構）
    try:
        df = source.fetch_stock_info()
        if df is not None and not df.empty:
            print(f"  [OK] TaiwanStockInfo: {len(df)} rows")
        else:
            print("  [FAIL] TaiwanStockInfo: empty response")
            ok = False
    except Exception as exc:
        print(f"  [FAIL] TaiwanStockInfo: {exc}")
        ok = False

    # 2. Benchmark OHLCV — 必要（benchmark 比較）
    try:
        df = source.fetch_ohlcv(benchmark_symbol, "D", 10)
        if df is not None and not df.empty:
            print(f"  [OK] Benchmark OHLCV ({benchmark_symbol}): {len(df)} rows")
        else:
            print(f"  [FAIL] Benchmark OHLCV ({benchmark_symbol}): empty response")
            ok = False
    except Exception as exc:
        print(f"  [FAIL] Benchmark OHLCV ({benchmark_symbol}): {exc}")
        ok = False

    # 3. Institutional — 警告（factor 會降級為 0，但不阻斷回測）
    try:
        df = source.fetch_institutional("2330", days=10)
        if df is not None and not df.empty:
            print(f"  [OK] Institutional (2330): {len(df)} rows")
        else:
            print("  [WARN] Institutional (2330): empty — factor scores will be zero")
    except Exception as exc:
        print(f"  [WARN] Institutional (2330): {exc} — factor scores will be zero")

    print("=" * 50)
    if not ok:
        print("  PREFLIGHT FAILED — FinMind API unavailable.")
        print("  Likely cause: 600 req/hr quota exceeded.")
        print("  Suggestion: wait until the next hour boundary and retry.")
        print("  This run will NOT produce KPI artifacts.")
        print("=" * 50)
    else:
        print("  PREFLIGHT PASSED — proceeding with backtest.")
        print("=" * 50)
    print()
    return ok


def main() -> None:
    args = _parse_args()
    load_dotenv()

    config = load_config(args.config)
    token = os.getenv("FINMIND_TOKEN")
    source = FinMindSource(token=token)

    if not _preflight_check(source, benchmark_symbol=args.benchmark):
        print("Aborting backtest due to preflight failure.")
        raise SystemExit(1)

    engine = BacktestEngine(source, config, slippage_bps=args.slippage_bps)

    start_date = datetime.strptime(args.start, "%Y-%m-%d")
    end_date = datetime.strptime(args.end, "%Y-%m-%d")
    result = engine.run(start_date, end_date, benchmark_symbol=args.benchmark)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"backtest_{start_date:%Y%m%d}_{end_date:%Y%m%d}"

    metrics_path = output_dir / f"{stem}_metrics.json"
    report_path = output_dir / f"{stem}_report.txt"
    snapshots_path = output_dir / f"{stem}_snapshots.json"

    metrics_path.write_text(
        json.dumps(result.get("metrics", {}), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    report_path.write_text(result.get("report", ""), encoding="utf-8")
    snapshots_path.write_text(
        json.dumps(result.get("monthly_snapshots", []), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(result.get("report", ""))
    print(f"\nSaved metrics to {metrics_path}")
    print(f"Saved report to {report_path}")
    print(f"Saved snapshots to {snapshots_path}")


if __name__ == "__main__":
    main()
