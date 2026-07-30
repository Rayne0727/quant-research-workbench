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
