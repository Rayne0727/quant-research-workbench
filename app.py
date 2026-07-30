"""Quant Research Workbench 的 Streamlit 页面。"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data_loader import DataValidationError, load_returns_csv
from src.performance import (
    PerformanceCalculationError,
    add_performance_series,
    calculate_performance_metrics,
)


def _format_percentage(value: object) -> str:
    """将有效数值显示为保留两位小数的百分比。"""
    if value is None or not pd.notna(value):
        return "不可用"
    return f"{float(value):.2%}"


def _format_number(value: object) -> str:
    """将有效数值显示为保留两位小数的普通数字。"""
    if value is None or not pd.notna(value):
        return "不可用"
    return f"{float(value):.2f}"


def _format_date(value: object) -> str:
    """将日期指标显示为 YYYY-MM-DD。"""
    return pd.Timestamp(value).strftime("%Y-%m-%d")


st.set_page_config(page_title="Quant Research Workbench", page_icon="📈")

st.title("Quant Research Workbench")
st.subheader("量化研究实验台")
st.write(
    "上传标准日频策略收益 CSV，完成字段验证、基础绩效计算和图表展示。"
)
st.info("当前为第二阶段版本：仅支持标准日频收益 CSV，不支持自动猜测其他格式。")

st.markdown("### 1. 数据输入")
data_mode = st.radio(
    "选择数据来源",
    options=("使用示例数据", "上传 CSV 文件"),
    horizontal=True,
)

uploaded_file = None
if data_mode == "上传 CSV 文件":
    uploaded_file = st.file_uploader("选择 CSV 文件", type=("csv",))
    st.caption("当前模式：用户上传数据模式")
else:
    st.caption("当前模式：示例数据模式")

st.markdown("### 2. 数据说明")
st.markdown(
    "必需字段：`date`、`strategy_return`；可选字段：`benchmark_return`。  "
    "收益率必须使用小数格式，例如 `0.01` 代表 `1%`，不能用 `1` 代表 `1%`。"
)

if data_mode == "上传 CSV 文件" and uploaded_file is None:
    st.info("请上传一份符合字段协议的 CSV 文件后开始分析。")
    st.stop()

data_source = (
    Path(__file__).resolve().parent / "data" / "example_daily_returns.csv"
    if data_mode == "使用示例数据"
    else uploaded_file
)

try:
    cleaned_data = load_returns_csv(data_source)
    performance_data = add_performance_series(cleaned_data)
    metrics = calculate_performance_metrics(cleaned_data)
except DataValidationError as exc:
    st.error(str(exc))
    st.stop()
except PerformanceCalculationError as exc:
    st.error(f"绩效计算失败：{exc}")
    st.stop()
except Exception:
    st.error("处理数据时发生未预期错误，请检查 CSV 格式后重试。")
    st.stop()

st.markdown("### 3. 核心指标")
metric_row_one = st.columns(4)
metric_row_one[0].metric("累计收益", _format_percentage(metrics["cumulative_return"]))
metric_row_one[1].metric("年化收益", _format_percentage(metrics["annualized_return"]))
metric_row_one[2].metric(
    "年化波动率", _format_percentage(metrics["annualized_volatility"])
)
metric_row_one[3].metric("夏普比率", _format_number(metrics["sharpe_ratio"]))

metric_row_two = st.columns(4)
metric_row_two[0].metric("最大回撤", _format_percentage(metrics["max_drawdown"]))
metric_row_two[1].metric(
    "盈利日占比", _format_percentage(metrics["positive_day_ratio"])
)
metric_row_two[2].metric("有效交易日数", str(metrics["n_days"]))
metric_row_two[3].metric(
    "数据起止日期",
    f"{_format_date(metrics['start_date'])} 至 {_format_date(metrics['end_date'])}",
)

if "benchmark_cumulative_return" in metrics:
    st.metric(
        "基准累计收益",
        _format_percentage(metrics["benchmark_cumulative_return"]),
    )

st.markdown("### 4. 图表")
nav_figure = go.Figure()
nav_figure.add_trace(
    go.Scatter(
        x=performance_data["date"],
        y=performance_data["strategy_nav"],
        mode="lines",
        name="策略净值",
    )
)
if "benchmark_nav" in performance_data.columns:
    nav_figure.add_trace(
        go.Scatter(
            x=performance_data["date"],
            y=performance_data["benchmark_nav"],
            mode="lines",
            name="基准净值",
        )
    )
nav_figure.update_layout(
    title="累计净值曲线",
    xaxis_title="日期",
    yaxis_title="累计净值",
    hovermode="x unified",
)
st.plotly_chart(nav_figure, width="stretch")

drawdown_figure = go.Figure()
drawdown_figure.add_trace(
    go.Scatter(
        x=performance_data["date"],
        y=performance_data["drawdown"],
        mode="lines",
        name="策略回撤",
        fill="tozeroy",
    )
)
drawdown_figure.update_layout(
    title="回撤曲线",
    xaxis_title="日期",
    yaxis_title="回撤",
    hovermode="x unified",
)
drawdown_figure.update_yaxes(tickformat=".1%")
st.plotly_chart(drawdown_figure, width="stretch")

st.markdown("### 5. 数据预览")
with st.expander("查看清洗后的数据（前 20 行）"):
    st.caption(f"字段：{', '.join(cleaned_data.columns)}")
    st.caption(f"记录数量：{len(cleaned_data)}")
    st.dataframe(cleaned_data.head(20), width="stretch")
