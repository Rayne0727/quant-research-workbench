"""基础绩效指标计算测试。"""

import math

import pandas as pd
import pytest

from src.performance import (
    TRADING_DAYS_PER_YEAR,
    PerformanceCalculationError,
    add_nav_performance_series,
    add_performance_series,
    calculate_drawdown,
    calculate_nav,
    calculate_nav_performance_metrics,
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


@pytest.mark.parametrize(
    ("returns", "message"),
    (
        (pd.Series(dtype=float), "没有可用于计算累计净值"),
        (pd.Series([0.01, float("nan")]), "包含 NaN 或无穷大"),
        (pd.Series([0.01, float("inf")]), "包含 NaN 或无穷大"),
        (pd.Series([0.01, -1.0]), "不能小于或等于 -1"),
    ),
)
def test_nav_rejects_invalid_return_boundaries(returns: pd.Series, message: str) -> None:
    with pytest.raises(PerformanceCalculationError, match=message):
        calculate_nav(returns)


@pytest.mark.parametrize(
    "nav",
    (
        pd.Series(dtype=float),
        pd.Series([1.0, float("nan")]),
        pd.Series([1.0, 0.0]),
        pd.Series([1.0, float("inf")]),
    ),
)
def test_drawdown_rejects_missing_nonpositive_or_nonfinite_nav(nav: pd.Series) -> None:
    with pytest.raises(PerformanceCalculationError, match="累计净值"):
        calculate_drawdown(nav)


def test_performance_series_require_strategy_return() -> None:
    with pytest.raises(PerformanceCalculationError, match="缺少 strategy_return"):
        add_performance_series(pd.DataFrame({"date": pd.to_datetime(["2026-01-01"])}))


def test_benchmark_nav_and_metric_follow_benchmark_returns(returns_data: pd.DataFrame) -> None:
    data = returns_data.assign(benchmark_return=[0.02, -0.01, 0.03])
    original = data.copy(deep=True)

    result = add_performance_series(data)
    metrics = calculate_performance_metrics(data)

    expected_nav = pd.Series([1.02, 1.0098, 1.040094], name="benchmark_nav")
    pd.testing.assert_series_equal(result["benchmark_nav"].reset_index(drop=True), expected_nav)
    assert metrics["benchmark_cumulative_return"] == pytest.approx(0.040094)
    pd.testing.assert_frame_equal(data, original)


def test_missing_final_benchmark_return_produces_no_benchmark_metric() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_return": [0.01, 0.02],
            "benchmark_return": [0.01, float("nan")],
        }
    )

    metrics = calculate_performance_metrics(data)

    assert metrics["benchmark_cumulative_return"] is None


@pytest.mark.parametrize(
    "data",
    (
        pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "strategy_return": [0.01]}),
        pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-02"])}),
    ),
)
def test_performance_metrics_reject_insufficient_or_missing_inputs(data: pd.DataFrame) -> None:
    with pytest.raises(PerformanceCalculationError):
        calculate_performance_metrics(data)


def test_nav_performance_series_use_existing_nav_without_rebuilding_it() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "strategy_nav": [1.0, 0.9, 1.1],
            "strategy_return": [float("nan"), 9.0, 9.0],
        }
    )
    original = data.copy(deep=True)

    result = add_nav_performance_series(data)

    assert result["strategy_nav"].tolist() == [1.0, 0.9, 1.1]
    assert result["drawdown"].tolist() == pytest.approx([0.0, -0.1, 0.0])
    pd.testing.assert_frame_equal(data, original)


def test_nav_performance_requires_complete_contract_and_two_observations() -> None:
    missing_return = pd.DataFrame(
        {"date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "strategy_nav": [1.0, 1.1]}
    )
    one_observation = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"]),
            "strategy_nav": [1.0],
            "strategy_return": [float("nan")],
        }
    )

    with pytest.raises(PerformanceCalculationError, match="需要 date、strategy_nav"):
        calculate_nav_performance_metrics(missing_return)
    with pytest.raises(PerformanceCalculationError, match="至少需要 2 条净值记录"):
        calculate_nav_performance_metrics(one_observation)


def test_nav_performance_rejects_no_valid_or_nonfinite_derived_returns() -> None:
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])

    with pytest.raises(PerformanceCalculationError, match="没有有效的净值推导收益"):
        calculate_nav_performance_metrics(
            pd.DataFrame(
                {
                    "date": dates,
                    "strategy_nav": [1.0, 1.1],
                    "strategy_return": [float("nan"), float("nan")],
                }
            )
        )
    with pytest.raises(PerformanceCalculationError, match="包含 NaN 或无穷大"):
        calculate_nav_performance_metrics(
            pd.DataFrame(
                {
                    "date": dates,
                    "strategy_nav": [1.0, 1.1],
                    "strategy_return": [float("nan"), float("inf")],
                }
            )
        )


def test_single_nav_return_has_defined_count_but_no_volatility_or_sharpe() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_nav": [1.0, 1.1],
            "strategy_return": [float("nan"), 0.1],
        }
    )

    metrics = calculate_nav_performance_metrics(data)

    assert metrics["cumulative_return"] == pytest.approx(0.1)
    assert metrics["n_days"] == 1
    assert metrics["nav_observations"] == 2
    assert metrics["annualized_volatility"] is None
    assert metrics["sharpe_ratio"] is None
