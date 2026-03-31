"""Tests for compute_metrics() in metrics.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.metrics import compute_metrics


class TestComputeMetrics:
    """compute_metrics: KPI calculation from daily return series."""

    def test_empty_series(self):
        result = compute_metrics(pd.Series(dtype="float64"))
        assert result == {}

    def test_positive_returns(self):
        # 100 days of +1% daily
        rets = pd.Series([0.01] * 100, index=pd.date_range("2024-01-01", periods=100))
        result = compute_metrics(rets)
        assert result["total_return"] > 0
        assert result["annualized_return"] > 0
        assert result["sharpe_ratio"] > 0
        assert result["max_drawdown"] == 0.0  # Never draws down

    def test_negative_returns(self):
        # 100 days of -0.5% daily
        rets = pd.Series([-0.005] * 100, index=pd.date_range("2024-01-01", periods=100))
        result = compute_metrics(rets)
        assert result["total_return"] < 0
        assert result["max_drawdown"] < 0  # Negative = drawdown

    def test_zero_returns(self):
        rets = pd.Series([0.0] * 50, index=pd.date_range("2024-01-01", periods=50))
        result = compute_metrics(rets)
        assert result["total_return"] == 0.0
        assert result["annualized_volatility"] == 0.0

    def test_with_benchmark(self):
        dates = pd.date_range("2024-01-01", periods=100)
        portfolio = pd.Series([0.01] * 100, index=dates)
        benchmark = pd.Series([0.005] * 100, index=dates)
        result = compute_metrics(portfolio, benchmark)
        assert "annualized_alpha" in result
        assert result["annualized_alpha"] > 0  # Portfolio beats benchmark
        assert "beta" in result
        assert "tracking_error" in result
        assert "benchmark_type" in result
        assert result["benchmark_type"] == "price_only"

    def test_no_benchmark_skips_relative(self):
        rets = pd.Series([0.01] * 50, index=pd.date_range("2024-01-01", periods=50))
        result = compute_metrics(rets)
        assert "annualized_alpha" not in result
        assert "beta" not in result

    def test_trading_days_count(self):
        rets = pd.Series([0.01] * 252, index=pd.date_range("2024-01-01", periods=252))
        result = compute_metrics(rets)
        assert result["trading_days"] == 252
        assert abs(result["years"] - 1.0) < 0.01

    def test_max_drawdown_calculation(self):
        # Up 10%, then down 20%, then recover
        rets = pd.Series(
            [0.05, 0.05, -0.10, -0.10, 0.05, 0.05],
            index=pd.date_range("2024-01-01", periods=6),
        )
        result = compute_metrics(rets)
        assert result["max_drawdown"] < 0
        assert result["max_drawdown"] > -1.0

    def test_sortino_uses_downside_only(self):
        # Mix of positive and negative returns
        rets = pd.Series(
            [0.02, -0.01, 0.03, -0.005, 0.01],
            index=pd.date_range("2024-01-01", periods=5),
        )
        result = compute_metrics(rets)
        # Sortino should be >= Sharpe (less penalty for upside volatility)
        if result.get("sharpe_ratio", 0) > 0:
            assert result["sortino_ratio"] >= result["sharpe_ratio"]
