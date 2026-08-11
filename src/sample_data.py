"""为原型页面提供固定的模拟收益数据。"""

from random import Random

import pandas as pd


def generate_sample_data() -> pd.DataFrame:
    """生成固定日期、日收益和累计收益组成的模拟数据。"""
    dates = pd.date_range(start="2026-01-05", periods=12, freq="B")
    daily_returns = [
        0.004,
        -0.002,
        0.006,
        0.001,
        -0.003,
        0.005,
        0.002,
        -0.001,
        0.007,
        -0.002,
        0.003,
        0.004,
    ]

    sample_data = pd.DataFrame({"date": dates, "daily_return": daily_returns})
    sample_data["cumulative_return"] = (1 + sample_data["daily_return"]).cumprod() - 1
    return sample_data


def generate_comparison_sample_data() -> list[tuple[str, pd.DataFrame]]:
    """生成三份日期部分错开、固定种子的标准化比较示例数据。"""
    specifications = [
        (
            "示例策略A_standardized_data.csv",
            "2025-01-02",
            150,
            202501,
            0.00045,
            0.0016,
            0.9,
        ),
        (
            "示例策略B_standardized_data.csv",
            "2025-01-09",
            145,
            202502,
            0.00030,
            0.0021,
            1.2,
        ),
        (
            "示例策略C_standardized_data.csv",
            "2025-01-16",
            140,
            202503,
            0.00020,
            0.0012,
            0.7,
        ),
    ]
    return [
        (
            filename,
            _build_standardized_sample(
                start_date,
                periods,
                seed,
                base_return,
                volatility,
                drawdown_scale,
            ),
        )
        for (
            filename,
            start_date,
            periods,
            seed,
            base_return,
            volatility,
            drawdown_scale,
        ) in specifications
    ]


def _build_standardized_sample(
    start_date: str,
    periods: int,
    seed: int,
    base_return: float,
    volatility: float,
    drawdown_scale: float,
) -> pd.DataFrame:
    """按固定种子和阶段状态生成首行净值为 1 的标准化数据。"""
    random_source = Random(seed)
    return_values = [float("nan")]
    shock_points = {42, 43, 88, 119}
    for index in range(1, periods):
        progress = index / (periods - 1)
        if progress < 0.18:
            phase_return = 0.00035
        elif progress < 0.30:
            phase_return = -0.00130 * drawdown_scale
        elif progress < 0.55:
            phase_return = 0.00055
        elif progress < 0.66:
            phase_return = -0.00200 * drawdown_scale
        elif progress < 0.82:
            phase_return = 0.00025
        else:
            phase_return = 0.00045
        shock_return = -0.0045 * drawdown_scale if index in shock_points else 0.0
        return_values.append(
            base_return + phase_return + shock_return + random_source.gauss(0.0, volatility)
        )

    strategy_return = pd.Series(return_values, dtype=float)
    strategy_nav = (1 + strategy_return.fillna(0)).cumprod()
    drawdown = strategy_nav / strategy_nav.cummax() - 1
    return pd.DataFrame(
        {
            "date": pd.bdate_range(start=start_date, periods=periods),
            "strategy_return": strategy_return,
            "strategy_nav": strategy_nav,
            "drawdown": drawdown,
        }
    )
