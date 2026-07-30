"""为原型页面提供固定的模拟收益数据。"""

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

    sample_data = pd.DataFrame(
        {"date": dates, "daily_return": daily_returns}
    )
    sample_data["cumulative_return"] = (
        1 + sample_data["daily_return"]
    ).cumprod() - 1
    return sample_data


def generate_comparison_sample_data() -> list[tuple[str, pd.DataFrame]]:
    """生成三份日期部分错开、固定可重复的标准化比较示例数据。"""
    specifications = [
        (
            "示例策略A_standardized_data.csv",
            "2025-01-02",
            150,
            [0.0015, -0.0008, 0.0020, 0.0004, -0.0010],
        ),
        (
            "示例策略B_standardized_data.csv",
            "2025-01-09",
            145,
            [0.0010, 0.0006, -0.0012, 0.0018, -0.0004],
        ),
        (
            "示例策略C_standardized_data.csv",
            "2025-01-16",
            140,
            [0.0007, -0.0003, 0.0011, 0.0005, -0.0006],
        ),
    ]
    return [
        (
            filename,
            _build_standardized_sample(start_date, periods, return_pattern),
        )
        for filename, start_date, periods, return_pattern in specifications
    ]


def _build_standardized_sample(
    start_date: str,
    periods: int,
    return_pattern: list[float],
) -> pd.DataFrame:
    """按固定收益循环生成首行净值为 1 的标准化数据。"""
    strategy_return = pd.Series(
        [float("nan")]
        + [return_pattern[index % len(return_pattern)] for index in range(periods - 1)],
        dtype=float,
    )
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
