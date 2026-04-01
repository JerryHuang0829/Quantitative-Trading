"""Dashboard 共用資料讀取函式。"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
BACKTESTS_DIR = REPORTS_DIR / "backtests"
PAPER_TRADING_DIR = REPORTS_DIR / "paper_trading"
WALK_FORWARD_DIR = REPORTS_DIR / "walk_forward"


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_latest_paper_trade() -> dict | None:
    """載入最新一期的 paper trading 紀錄。"""
    files = sorted(PAPER_TRADING_DIR.glob("2???-??.json"), reverse=True)
    if not files:
        return None
    return load_json(files[0])


def load_paper_trading_history() -> list[dict]:
    history_path = PAPER_TRADING_DIR / "history.json"
    data = load_json(history_path)
    return data if isinstance(data, list) else []


def load_walk_forward_summary() -> dict | None:
    return load_json(WALK_FORWARD_DIR / "summary.json")


def load_backtest_metrics(subdir: str, start: str, end: str) -> dict | None:
    """載入指定回測的 metrics。
    subdir: 子目錄名（如 'p2_if0', 'split_fix'），空字串表示根目錄。
    start/end: 'YYYYMMDD' 格式。
    """
    base = BACKTESTS_DIR / subdir if subdir else BACKTESTS_DIR
    path = base / f"backtest_{start}_{end}_metrics.json"
    return load_json(path)


def load_backtest_snapshots(subdir: str, start: str, end: str) -> list[dict]:
    base = BACKTESTS_DIR / subdir if subdir else BACKTESTS_DIR
    path = base / f"backtest_{start}_{end}_snapshots.json"
    data = load_json(path)
    return data if isinstance(data, list) else []


def load_daily_returns(subdir: str, start: str, end: str) -> dict | None:
    """載入日頻報酬序列。回傳 {"portfolio": {date: ret}, "benchmark": {date: ret}}。"""
    base = BACKTESTS_DIR / subdir if subdir else BACKTESTS_DIR
    path = base / f"backtest_{start}_{end}_daily_returns.json"
    return load_json(path)


def list_backtest_experiments() -> list[dict]:
    """掃描 reports/backtests/ 所有回測實驗，回傳 {label, subdir, start, end}。"""
    results = []
    for metrics_file in sorted(BACKTESTS_DIR.rglob("backtest_*_metrics.json")):
        parts = metrics_file.stem.replace("backtest_", "").replace("_metrics", "")
        dates = parts.split("_")
        if len(dates) != 2:
            continue
        start, end = dates
        subdir = str(metrics_file.parent.relative_to(BACKTESTS_DIR))
        if subdir == ".":
            subdir = ""
        label = f"{subdir or 'root'}: {start[:4]}-{start[4:6]} → {end[:4]}-{end[4:6]}"
        results.append({
            "label": label,
            "subdir": subdir,
            "start": start,
            "end": end,
            "path": str(metrics_file),
        })
    return results
