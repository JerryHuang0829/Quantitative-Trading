"""Performance metrics and KPI calculation for backtest results."""

from __future__ import annotations

import logging
from math import sqrt

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.015  # 台灣無風險利率假設 1.5%

# Stock split detection: single-day price change exceeding this threshold
# triggers automatic forward-adjustment.  Common ratios: 1:2 (−50%),
# 1:4 (−75%), 1:5 (−80%), 1:10 (−90%).  A −40% threshold catches all of
# these while being well above normal daily moves (Taiwan daily limit ±10%).
_SPLIT_DETECTION_THRESHOLD = -0.40
# Reverse split (consolidation) detection: single-day price jump exceeding
# this threshold triggers automatic adjustment.  Taiwan daily limit is +10%,
# so any single-day gain >100% must be a reverse split (e.g. 10:1 = +900%).
_REVERSE_SPLIT_THRESHOLD = 1.00


def adjust_splits(prices: pd.Series) -> pd.Series:
    """Detect and forward-adjust stock splits/reverse splits in a closing-price series.

    When a single-day price drop exceeds ``_SPLIT_DETECTION_THRESHOLD`` (e.g.
    −40%), we assume a forward stock split occurred and multiply all *prior*
    prices by the split ratio (< 1) so the series becomes continuous.

    When a single-day price jump meets or exceeds ``_REVERSE_SPLIT_THRESHOLD``
    (e.g. +100%), we assume a reverse split (consolidation) occurred and
    multiply all *prior* prices by the consolidation ratio (> 1) so the series
    becomes continuous.  Both cases use the same ``prior *= ratio`` logic.

    Parameters
    ----------
    prices : pd.Series
        Closing price series indexed by date (must be sorted ascending).

    Returns
    -------
    pd.Series
        Forward-adjusted closing prices (same index, same dtype).
    """
    if prices.empty or len(prices) < 2:
        return prices.copy()

    adjusted = prices.copy().astype(float)
    daily_ret = adjusted.pct_change()

    # Detect both forward splits (big drops) and reverse splits (big jumps)
    split_mask = (daily_ret < _SPLIT_DETECTION_THRESHOLD) | (daily_ret >= _REVERSE_SPLIT_THRESHOLD)

    if not split_mask.any():
        return adjusted

    # Process splits from newest to oldest so earlier adjustments compound
    split_dates = split_mask[split_mask].index.sort_values(ascending=False)
    for split_date in split_dates:
        loc = adjusted.index.get_loc(split_date)
        if loc == 0:
            continue
        price_before = adjusted.iloc[loc - 1]
        price_after = adjusted.iloc[loc]
        if price_before == 0:
            continue
        ratio = price_after / price_before  # e.g. 0.25 for 1:4 split, 10.0 for 10:1 reverse
        adjusted.iloc[:loc] *= ratio
        split_type = "Reverse split" if ratio > 1 else "Split"
        logger.info(
            "%s detected on %s: %.2f → %.2f (ratio %.4f), adjusted %d prior prices",
            split_type,
            split_date.date() if hasattr(split_date, "date") else split_date,
            price_before, price_after, ratio, loc,
        )

    return adjusted


def adjust_dividends(
    prices: pd.Series,
    dividends: list[dict],
    symbol: str,
) -> pd.Series:
    """Forward-adjust closing prices for cash dividends (total return series).

    On each ex-dividend date, all prior prices are multiplied by an adjustment
    factor so that ``pct_change()`` on the result yields total returns
    (price change + reinvested dividends).

    Parameters
    ----------
    prices : pd.Series
        Closing price series indexed by date (sorted ascending).
        Should already be split-adjusted via ``adjust_splits()``.
    dividends : list[dict]
        Each dict must have keys: stock_id, ex_date (str 'YYYY-MM-DD'),
        cash_dividend (float).  Optionally ``close_before`` (closing price
        the day before ex-date in original units) for split-safe adjustment.
    symbol : str
        Stock ID to filter dividends for.

    Returns
    -------
    pd.Series
        Dividend-adjusted closing prices (same index).
    """
    if not dividends or prices.empty or len(prices) < 2:
        return prices.copy()

    # Filter dividends for this symbol
    sym_divs = [
        d for d in dividends
        if d["stock_id"] == symbol and d["cash_dividend"] > 0
    ]
    if not sym_divs:
        return prices.copy()

    adjusted = prices.copy().astype(float)

    # Process from oldest to newest: unlike splits (which use a price ratio
    # invariant to scale), dividend adjustment adds a fixed dollar amount.
    # Processing newest-to-oldest would use already-reduced prices in the
    # factor denominator, causing over-adjustment.  Oldest-first ensures each
    # ex-date's price_on_ex is the original (un-adjusted by later dividends).
    sym_divs.sort(key=lambda d: d["ex_date"], reverse=False)

    for div in sym_divs:
        ex_date_str = div["ex_date"]
        cash_div = div["cash_dividend"]

        # Find the ex-date in the price index
        ex_ts = pd.Timestamp(ex_date_str, tz=prices.index.tz)
        if ex_ts not in adjusted.index:
            # Try matching without exact timestamp (date-level match)
            matches = adjusted.index[adjusted.index.normalize() == ex_ts.normalize()]
            if matches.empty:
                continue
            ex_ts = matches[0]

        loc = adjusted.index.get_loc(ex_ts)
        if loc == 0:
            continue

        # Adjustment factor: use scale-invariant formula when close_before
        # is available (from TWSE data).  This avoids the mismatch between
        # split-adjusted prices and original-unit dividend amounts.
        #   factor = 1 - cash_div / close_before  (≡ ref_price / close_before)
        # Fallback: factor = price_on_ex / (price_on_ex + cash_div) — only
        # correct when the price series has NOT been split-adjusted.
        close_before = div.get("close_before")
        if close_before and close_before > 0:
            factor = 1.0 - cash_div / close_before
        else:
            price_on_ex = adjusted.iloc[loc]
            if price_on_ex <= 0:
                continue
            factor = price_on_ex / (price_on_ex + cash_div)
        if factor <= 0 or factor >= 1:
            continue
        adjusted.iloc[:loc] *= factor

        logger.debug(
            "Dividend adjust %s on %s: $%.2f div, factor %.6f, adjusted %d prior prices",
            symbol, ex_date_str, cash_div, factor, loc,
        )

    return adjusted


def compute_metrics(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    risk_free_rate: float = RISK_FREE_RATE,
) -> dict:
    """計算完整 KPI 報表。

    Parameters
    ----------
    portfolio_returns : pd.Series
        日報酬序列（decimal, e.g. 0.01 = 1%）
    benchmark_returns : pd.Series | None
        基準日報酬序列
    risk_free_rate : float
        年化無風險利率

    Returns
    -------
    dict
        包含所有 KPI 的字典
    """
    result: dict = {}

    if portfolio_returns.empty:
        logger.warning("Empty portfolio returns; cannot compute metrics")
        return result

    # --- 絕對績效 ---
    total_return = (1 + portfolio_returns).prod() - 1
    n_days = len(portfolio_returns)
    n_years = n_days / TRADING_DAYS_PER_YEAR
    ann_return = (1 + total_return) ** (1 / max(n_years, 0.01)) - 1 if n_years > 0 else 0.0

    result["total_return"] = round(total_return, 6)
    result["annualized_return"] = round(ann_return, 6)
    result["trading_days"] = n_days
    result["years"] = round(n_years, 2)

    # --- 風險指標 ---
    daily_std = portfolio_returns.std()
    ann_volatility = daily_std * sqrt(TRADING_DAYS_PER_YEAR)
    result["annualized_volatility"] = round(ann_volatility, 6)

    # Max Drawdown
    cumulative = (1 + portfolio_returns).cumprod()
    running_max = cumulative.cummax()
    drawdowns = (cumulative - running_max) / running_max
    max_dd = drawdowns.min()
    result["max_drawdown"] = round(max_dd, 6)

    # Max Drawdown 持續期間
    dd_end_idx = drawdowns.idxmin()
    dd_start_idx = cumulative[:dd_end_idx].idxmax() if dd_end_idx is not None else None
    result["max_drawdown_start"] = str(dd_start_idx) if dd_start_idx is not None else None
    result["max_drawdown_end"] = str(dd_end_idx) if dd_end_idx is not None else None

    # --- 尾部風險指標 ---
    # CVaR (Expected Shortfall) 95%: 最差 5% 日子的平均虧損
    percentile_5 = np.percentile(portfolio_returns, 5)
    cvar_95 = float(portfolio_returns[portfolio_returns <= percentile_5].mean()) if (portfolio_returns <= percentile_5).any() else 0.0
    result["cvar_95"] = round(cvar_95, 6)

    # Tail Ratio: |P95| / |P5|，<1.0 代表下行尾巴比上行大
    percentile_95 = np.percentile(portfolio_returns, 95)
    tail_ratio = abs(percentile_95) / abs(percentile_5) if percentile_5 != 0 else 0.0
    result["tail_ratio"] = round(tail_ratio, 4)

    # Drawdown Duration: 最大水下天數 + 平均水下天數
    underwater = drawdowns < 0
    if underwater.any():
        # 找出每段水下期間的長度
        dd_groups = (~underwater).cumsum()
        dd_durations = underwater.groupby(dd_groups).sum()
        dd_durations = dd_durations[dd_durations > 0]
        result["max_drawdown_duration_days"] = int(dd_durations.max()) if len(dd_durations) > 0 else 0
        result["avg_drawdown_duration_days"] = round(float(dd_durations.mean()), 1) if len(dd_durations) > 0 else 0.0
        # 水下時間比例
        result["underwater_pct"] = round(float(underwater.sum()) / len(underwater), 4)
    else:
        result["max_drawdown_duration_days"] = 0
        result["avg_drawdown_duration_days"] = 0.0
        result["underwater_pct"] = 0.0

    # --- 分布特徵 ---
    from scipy import stats as sp_stats
    result["skewness"] = round(float(sp_stats.skew(portfolio_returns)), 4)
    result["kurtosis"] = round(float(sp_stats.kurtosis(portfolio_returns)), 4)
    # Jarque-Bera 常態性檢定：p < 0.05 表示非常態，Sharpe 不完全可信
    jb_stat, jb_pvalue = sp_stats.jarque_bera(portfolio_returns)
    result["jarque_bera_stat"] = round(float(jb_stat), 4)
    result["jarque_bera_pvalue"] = round(float(jb_pvalue), 6)

    # --- 風險調整報酬 ---
    daily_rf = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess_daily = portfolio_returns - daily_rf

    sharpe = (excess_daily.mean() / excess_daily.std() * sqrt(TRADING_DAYS_PER_YEAR)) if excess_daily.std() > 0 else 0.0
    result["sharpe_ratio"] = round(sharpe, 4)

    # Sortino: 只用下行波動
    downside = excess_daily[excess_daily < 0]
    downside_std = downside.std() if len(downside) > 0 else 0.0
    sortino = (excess_daily.mean() / downside_std * sqrt(TRADING_DAYS_PER_YEAR)) if downside_std > 0 else 0.0
    result["sortino_ratio"] = round(sortino, 4)

    # Calmar
    calmar = ann_return / abs(max_dd) if max_dd != 0 else 0.0
    result["calmar_ratio"] = round(calmar, 4)

    # --- 相對基準績效 ---
    if benchmark_returns is not None and not benchmark_returns.empty:
        # 對齊日期
        aligned = pd.DataFrame(
            {"portfolio": portfolio_returns, "benchmark": benchmark_returns}
        ).dropna()

        if not aligned.empty:
            excess_vs_bench = aligned["portfolio"] - aligned["benchmark"]

            bench_total = (1 + aligned["benchmark"]).prod() - 1
            bench_ann = (1 + bench_total) ** (1 / max(n_years, 0.01)) - 1 if n_years > 0 else 0.0
            result["benchmark_annualized_return"] = round(bench_ann, 6)

            # Alpha (annualized excess)
            alpha_ann = ann_return - bench_ann
            result["annualized_alpha"] = round(alpha_ann, 6)

            # Tracking Error
            te = excess_vs_bench.std() * sqrt(TRADING_DAYS_PER_YEAR)
            result["tracking_error"] = round(te, 6)

            # Information Ratio
            ir = alpha_ann / te if te > 0 else 0.0
            result["information_ratio"] = round(ir, 4)

            # Beta
            cov_matrix = aligned[["portfolio", "benchmark"]].cov()
            bench_var = aligned["benchmark"].var()
            beta = cov_matrix.loc["portfolio", "benchmark"] / bench_var if bench_var > 0 else 1.0
            result["beta"] = round(beta, 4)

            # Default to price_only; engine.py overrides to "total_return"
            # when dividend data is available (P4.5).
            result["benchmark_type"] = "price_only"

    return result


def format_report(metrics: dict, benchmark_name: str = "0050") -> str:
    """將 KPI 字典格式化為可讀報表。"""
    lines = ["=" * 50, "  Backtest Performance Report", "=" * 50, ""]

    lines.append("--- 絕對績效 ---")
    lines.append(f"  年化報酬:       {metrics.get('annualized_return', 0):.2%}")
    lines.append(f"  總報酬:         {metrics.get('total_return', 0):.2%}")
    lines.append(f"  回測期間:       {metrics.get('years', 0):.1f} 年 ({metrics.get('trading_days', 0)} 交易日)")
    lines.append("")

    lines.append("--- 風險指標 ---")
    lines.append(f"  年化波動率:     {metrics.get('annualized_volatility', 0):.2%}")
    lines.append(f"  最大回撤:       {metrics.get('max_drawdown', 0):.2%}")
    if "max_drawdown_duration_days" in metrics:
        lines.append(f"  最大水下天數:   {metrics.get('max_drawdown_duration_days', 0)} 天")
        lines.append(f"  平均水下天數:   {metrics.get('avg_drawdown_duration_days', 0):.1f} 天")
        lines.append(f"  水下時間比例:   {metrics.get('underwater_pct', 0):.1%}")
    if "cvar_95" in metrics:
        lines.append(f"  CVaR 95%:       {metrics.get('cvar_95', 0):.2%}")
        lines.append(f"  Tail Ratio:     {metrics.get('tail_ratio', 0):.2f}")
    if "skewness" in metrics:
        lines.append(f"  偏態:           {metrics.get('skewness', 0):.2f}")
        lines.append(f"  峰度:           {metrics.get('kurtosis', 0):.2f}")
        jb_p = metrics.get("jarque_bera_pvalue", 1.0)
        normality = "非常態 ⚠️" if jb_p < 0.05 else "近似常態"
        lines.append(f"  Jarque-Bera p:  {jb_p:.4f} ({normality})")
    lines.append("")

    lines.append("--- 風險調整報酬 ---")
    lines.append(f"  Sharpe Ratio:   {metrics.get('sharpe_ratio', 0):.2f}")
    lines.append(f"  Sortino Ratio:  {metrics.get('sortino_ratio', 0):.2f}")
    lines.append(f"  Calmar Ratio:   {metrics.get('calmar_ratio', 0):.2f}")
    lines.append("")

    if "annualized_alpha" in metrics:
        lines.append(f"--- 相對 {benchmark_name} ---")
        lines.append(f"  Benchmark 年化: {metrics.get('benchmark_annualized_return', 0):.2%}")
        lines.append(f"  年化 Alpha:     {metrics.get('annualized_alpha', 0):.2%}")
        lines.append(f"  Beta:           {metrics.get('beta', 0):.2f}")
        lines.append(f"  Tracking Error: {metrics.get('tracking_error', 0):.2%}")
        lines.append(f"  Info Ratio:     {metrics.get('information_ratio', 0):.2f}")

    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)
