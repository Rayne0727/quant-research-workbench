"""生成仅用于字段格式演示的 CSV 模板。"""

import pandas as pd


def generate_daily_returns_template_csv() -> bytes:
    """在内存中生成标准日频收益 CSV 模板。"""
    template = pd.DataFrame(
        {
            "date": ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
            "strategy_return": [0.01, -0.005, 0.002, 0.004],
            "benchmark_return": [0.006, -0.003, 0.001, 0.002],
        }
    )
    return template.to_csv(index=False).encode("utf-8-sig")


def build_comparison_template_data() -> pd.DataFrame:
    """生成可通过现有标准化比较协议验证的固定模板数据。"""
    strategy_return = pd.Series([float("nan"), 0.01, -0.005, 0.002])
    strategy_nav = (1 + strategy_return.fillna(0)).cumprod()
    drawdown = strategy_nav / strategy_nav.cummax() - 1
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-05", periods=4),
            "strategy_return": strategy_return,
            "strategy_nav": strategy_nav,
            "drawdown": drawdown,
        }
    )


def generate_comparison_template_csv() -> bytes:
    """在内存中生成标准化比较 CSV 模板。"""
    template = build_comparison_template_data().copy()
    template["date"] = template["date"].dt.strftime("%Y-%m-%d")
    return template.to_csv(index=False).encode("utf-8-sig")
