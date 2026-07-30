"""计算日频策略收益的基础绩效指标。"""

from math import isclose, isfinite, sqrt
from typing import TypeAlias

import pandas as pd


TRADING_DAYS_PER_YEAR = 252
MetricValue: TypeAlias = float | int | pd.Timestamp | None


class PerformanceCalculationError(ValueError):
    """表示输入数据无法产生有效绩效结果。"""


def calculate_nav(returns: pd.Series) -> pd.Series:
    """按 (1 + daily_return).cumprod() 计算累计净值。"""
    numeric_returns = pd.to_numeric(returns, errors="coerce").astype(float)
    if numeric_returns.empty:
        raise PerformanceCalculationError("没有可用于计算累计净值的收益数据。")
    if numeric_returns.isna().any() or not all(
        isfinite(value) for value in numeric_returns
    ):
        raise PerformanceCalculationError("收益数据包含 NaN 或无穷大，无法计算累计净值。")
    if (numeric_returns <= -1).any():
        raise PerformanceCalculationError("收益率不能小于或等于 -1。")

    nav = (1 + numeric_returns).cumprod()
    if not all(isfinite(value) for value in nav) or (nav <= 0).any():
        raise PerformanceCalculationError("累计净值无法有效计算，请检查收益数据。")
    nav.name = "strategy_nav"
    return nav


def calculate_drawdown(nav: pd.Series) -> pd.Series:
    """按 nav / nav.cummax() - 1 计算回撤序列。"""
    numeric_nav = pd.to_numeric(nav, errors="coerce").astype(float)
    if numeric_nav.empty or numeric_nav.isna().any():
        raise PerformanceCalculationError("累计净值无效，无法计算回撤。")
    if not all(isfinite(value) for value in numeric_nav) or (numeric_nav <= 0).any():
        raise PerformanceCalculationError("累计净值必须为有限正数。")

    drawdown = numeric_nav / numeric_nav.cummax() - 1
    if not all(isfinite(value) for value in drawdown):
        raise PerformanceCalculationError("回撤序列无法有效计算。")
    drawdown.name = "drawdown"
    return drawdown


def add_performance_series(data: pd.DataFrame) -> pd.DataFrame:
    """为清洗后的数据增加策略净值、回撤及可选基准净值。"""
    if "strategy_return" not in data.columns:
        raise PerformanceCalculationError("缺少 strategy_return，无法计算绩效。")

    result = data.copy()
    result["strategy_nav"] = calculate_nav(result["strategy_return"])
    result["drawdown"] = calculate_drawdown(result["strategy_nav"])

    if "benchmark_return" in result.columns:
        benchmark_returns = pd.to_numeric(
            result["benchmark_return"], errors="coerce"
        ).astype(float)
        result["benchmark_nav"] = (1 + benchmark_returns).cumprod(skipna=False)
        finite_values = result["benchmark_nav"].dropna().to_numpy(dtype=float)
        if not all(isfinite(value) for value in finite_values):
            raise PerformanceCalculationError("基准累计净值无法有效计算。")

    return result


def calculate_performance_metrics(data: pd.DataFrame) -> dict[str, MetricValue]:
    """按指定日频口径计算策略绩效指标。"""
    if len(data) < 2:
        raise PerformanceCalculationError("至少需要 2 条有效记录才能计算绩效指标。")
    if "date" not in data.columns or "strategy_return" not in data.columns:
        raise PerformanceCalculationError("绩效计算需要 date 和 strategy_return 字段。")

    performance_data = add_performance_series(data)
    strategy_returns = performance_data["strategy_return"].astype(float)
    nav = performance_data["strategy_nav"]
    drawdown = performance_data["drawdown"]
    n_days = len(performance_data)

    final_nav = float(nav.iloc[-1])
    cumulative_return = final_nav - 1
    try:
        annualized_value = final_nav ** (TRADING_DAYS_PER_YEAR / n_days) - 1
    except OverflowError:
        annualized_value = float("inf")
    annualized_return = _finite_or_none(annualized_value)

    daily_volatility = float(strategy_returns.std(ddof=1))
    annualized_volatility = _finite_or_none(
        daily_volatility * sqrt(TRADING_DAYS_PER_YEAR)
    )
    if isclose(daily_volatility, 0.0, abs_tol=1e-15, rel_tol=0.0):
        sharpe_ratio = None
    else:
        sharpe_ratio = _finite_or_none(
            float(
                strategy_returns.mean()
                / daily_volatility
                * sqrt(TRADING_DAYS_PER_YEAR)
            )
        )

    metrics: dict[str, MetricValue] = {
        "cumulative_return": cumulative_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": float(drawdown.min()),
        "positive_day_ratio": float((strategy_returns > 0).mean()),
        "n_days": n_days,
        "start_date": pd.Timestamp(performance_data["date"].iloc[0]),
        "end_date": pd.Timestamp(performance_data["date"].iloc[-1]),
    }

    if "benchmark_nav" in performance_data.columns:
        final_benchmark_nav = performance_data["benchmark_nav"].iloc[-1]
        metrics["benchmark_cumulative_return"] = (
            _finite_or_none(float(final_benchmark_nav - 1))
            if pd.notna(final_benchmark_nav)
            else None
        )

    return metrics


def _finite_or_none(value: float) -> float | None:
    """将非有限指标转换为 None，避免把 NaN 或无穷大交给页面。"""
    return float(value) if isfinite(value) else None
