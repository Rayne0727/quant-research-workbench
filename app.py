"""Quant Research Workbench 的 Streamlit 页面。"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.adapters import WeeklyNavValidationError, load_weekly_nav_csv
from src.data_loader import DataValidationError, load_returns_csv
from src.performance import (
    PerformanceCalculationError,
    add_nav_performance_series,
    add_performance_series,
    calculate_nav_performance_metrics,
    calculate_performance_metrics,
)


STANDARD_RETURN_FORMAT = "标准日频收益 CSV"
WEEKLY_NAV_FORMAT = "每周调仓净值 CSV"


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


def _format_difference(value: float | None) -> str:
    """以足够精度显示一致性诊断差异。"""
    return "不可用" if value is None else f"{value:.10g}"


st.set_page_config(page_title="Quant Research Workbench", page_icon="📈")

st.title("Quant Research Workbench")
st.subheader("量化研究实验台")
st.write(
    "上传标准日频收益或每周调仓净值 CSV，完成字段验证、基础绩效计算和图表展示。"
)
st.info("当前支持两种明确的数据格式；系统不会自动猜测或切换文件格式。")

st.markdown("### 1. 数据输入")
data_mode = st.radio(
    "选择数据来源",
    options=("使用示例数据", "上传 CSV 文件"),
    horizontal=True,
)

selected_format = STANDARD_RETURN_FORMAT
uploaded_file = None
if data_mode == "上传 CSV 文件":
    selected_format = st.radio(
        "选择数据格式",
        options=(STANDARD_RETURN_FORMAT, WEEKLY_NAV_FORMAT),
        horizontal=True,
    )
    uploaded_file = st.file_uploader("选择 CSV 文件", type=("csv",))
    current_mode = "用户上传数据模式"
else:
    current_mode = "示例数据模式"

primary_field = (
    "nav_strat" if selected_format == WEEKLY_NAV_FORMAT else "strategy_return"
)
st.caption(f"当前数据模式：{current_mode}")
st.caption(f"当前选择的数据格式：{selected_format}")
st.caption(f"当前实际用于计算绩效的主字段：{primary_field}")
if selected_format == WEEKLY_NAV_FORMAT:
    st.info("当前绩效以 nav_strat 推导结果为准。")

st.markdown("### 2. 数据说明")
if selected_format == STANDARD_RETURN_FORMAT:
    st.markdown(
        "必需字段：`date`、`strategy_return`；可选字段：`benchmark_return`。  "
        "收益率必须使用小数格式，例如 `0.01` 代表 `1%`，不能用 `1` 代表 `1%`。"
    )
else:
    st.markdown(
        "必需字段：`date`、`nav_strat`；可选字段：`daily_ret`。  "
        "绩效以 `nav_strat` 标准化净值及其 `pct_change()` 推导收益为准；"
        "`daily_ret` 仅用于一致性诊断。"
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
    diagnostics = None
    if selected_format == WEEKLY_NAV_FORMAT:
        adapter_result = load_weekly_nav_csv(data_source)
        cleaned_data = adapter_result.data
        diagnostics = adapter_result.diagnostics
        performance_data = add_nav_performance_series(cleaned_data)
        metrics = calculate_nav_performance_metrics(cleaned_data)
    else:
        cleaned_data = load_returns_csv(data_source)
        performance_data = add_performance_series(cleaned_data)
        metrics = calculate_performance_metrics(cleaned_data)
except (DataValidationError, WeeklyNavValidationError) as exc:
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

is_nav_format = selected_format == WEEKLY_NAV_FORMAT
has_benchmark = "benchmark_cumulative_return" in metrics
metric_row_two = st.columns(4 if has_benchmark or is_nav_format else 3)
metric_row_two[0].metric("最大回撤", _format_percentage(metrics["max_drawdown"]))
metric_row_two[1].metric(
    "盈利日占比", _format_percentage(metrics["positive_day_ratio"])
)
if is_nav_format:
    metric_row_two[2].metric("净值观察日数", str(metrics["nav_observations"]))
    metric_row_two[3].metric("有效收益日数", str(metrics["n_days"]))
else:
    metric_row_two[2].metric("有效交易日数", str(metrics["n_days"]))
if has_benchmark and not is_nav_format:
    metric_row_two[3].metric(
        "基准累计收益",
        _format_percentage(metrics["benchmark_cumulative_return"]),
    )

st.markdown("**数据起止日期**")
date_columns = st.columns(2)
date_columns[0].write(f"开始日期：{_format_date(metrics['start_date'])}")
date_columns[1].write(f"结束日期：{_format_date(metrics['end_date'])}")

if int(metrics["n_days"]) < 60:
    st.warning(
        "当前样本交易日较少，年化收益、年化波动率和夏普比率对短期表现较敏感，"
        "仅供参考。"
    )

if diagnostics is not None:
    st.markdown("#### daily_ret 一致性诊断")
    diagnostic_columns = st.columns(4)
    diagnostic_columns[0].metric("有效比较数量", str(diagnostics.comparison_count))
    diagnostic_columns[1].metric("不一致日期数量", str(diagnostics.mismatch_count))
    diagnostic_columns[2].metric(
        "最大绝对差异", _format_difference(diagnostics.max_absolute_difference)
    )
    diagnostic_columns[3].metric(
        "平均绝对差异", _format_difference(diagnostics.mean_absolute_difference)
    )
    if diagnostics.mismatch_count > 0:
        st.warning(
            "文件中的 daily_ret 与 nav_strat 推导收益存在不一致。"
            "当前绩效指标以 nav_strat 为准，daily_ret 仅用于一致性检查。"
        )
        with st.expander("查看前 10 条不一致记录"):
            st.dataframe(diagnostics.mismatches.head(10), width="stretch")
    else:
        st.success("daily_ret 与 nav_strat 推导收益在容差 1e-8 内一致。")

st.markdown("### 4. 图表")
nav_figure = go.Figure()
nav_figure.add_trace(
    go.Scatter(
        x=performance_data["date"],
        y=performance_data["strategy_nav"],
        mode="lines",
        name="策略标准化净值" if is_nav_format else "策略净值",
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
