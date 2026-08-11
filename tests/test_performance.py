"""基础绩效指标计算测试。"""

import math

import pandas as pd
import pytest

from src.performance import (
    TRADING_DAYS_PER_YEAR,
    add_performance_series,
    calculate_drawdown,
    calculate_nav,
    calculate_performance_metrics,
)


@pytest.fixture
def returns_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
            "strategy_return": [0.10, -0.05, 0.02],
        }
    )


def test_cumulative_nav_is_correct(returns_data: pd.DataFrame) -> None:
    nav = calculate_nav(returns_data["strategy_return"])

    expected = pd.Series([1.10, 1.045, 1.0659], name="strategy_nav")
    pd.testing.assert_series_equal(nav.reset_index(drop=True), expected)


def test_cumulative_return_is_correct(returns_data: pd.DataFrame) -> None:
    metrics = calculate_performance_metrics(returns_data)

    assert metrics["cumulative_return"] == pytest.approx(0.0659)


def test_drawdown_is_correct(returns_data: pd.DataFrame) -> None:
    nav = calculate_nav(returns_data["strategy_return"])
    drawdown = calculate_drawdown(nav)

    expected = pd.Series([0.0, -0.05, -0.031], name="drawdown")
    pd.testing.assert_series_equal(drawdown.reset_index(drop=True), expected)


def test_max_drawdown_is_not_positive(returns_data: pd.DataFrame) -> None:
    metrics = calculate_performance_metrics(returns_data)

    assert float(metrics["max_drawdown"]) <= 0


def test_annualized_volatility_is_correct(returns_data: pd.DataFrame) -> None:
    metrics = calculate_performance_metrics(returns_data)
    expected = pd.Series([0.10, -0.05, 0.02]).std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)

    assert metrics["annualized_volatility"] == pytest.approx(expected)


def test_zero_volatility_sharpe_ratio_is_none() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_return": [0.01, 0.01],
        }
    )

    metrics = calculate_performance_metrics(data)

    assert metrics["sharpe_ratio"] is None
    assert metrics["annualized_volatility"] == pytest.approx(0.0)


def test_metric_results_do_not_contain_infinity(
    returns_data: pd.DataFrame,
) -> None:
    metrics = calculate_performance_metrics(returns_data)

    numeric_values = [
        value for value in metrics.values() if isinstance(value, (int, float)) and value is not None
    ]
    assert all(math.isfinite(value) for value in numeric_values)


def test_performance_series_include_nav_and_drawdown(
    returns_data: pd.DataFrame,
) -> None:
    result = add_performance_series(returns_data)

    assert {"strategy_nav", "drawdown"}.issubset(result.columns)
