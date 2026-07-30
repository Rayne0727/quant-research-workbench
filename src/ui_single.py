"""单实验分析模式的 Streamlit 页面组织。"""

import logging
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.adapters import WeeklyNavValidationError, load_weekly_nav_csv
from src.config import MAX_ROWS_PER_FILE, SINGLE_FILE_MAX_MB
from src.data_loader import DataValidationError, load_returns_csv
from src.limits import UploadLimitError
from src.performance import (
    PerformanceCalculationError,
    add_nav_performance_series,
    add_performance_series,
    calculate_nav_performance_metrics,
    calculate_performance_metrics,
)
from src.reporting import (
    ReportContext,
    generate_analysis_summary,
    generate_markdown_report,
    generate_standardized_csv,
    make_report_filename,
    make_standardized_data_filename,
)
from src.templates import generate_daily_returns_template_csv


LOGGER = logging.getLogger(__name__)
STANDARD_RETURN_FORMAT = "标准日频收益 CSV"
WEEKLY_NAV_FORMAT = "每周调仓净值 CSV"
UNEXPECTED_ERROR_MESSAGE = (
    "应用处理过程中出现未预期错误。请检查文件格式；"
    "若问题持续存在，请重新启动应用并保留错误发生步骤。"
)


def render_single_page() -> None:
    """渲染单实验页面，并统一处理预期及未预期异常。"""
    try:
        _render_single_page()
    except (DataValidationError, WeeklyNavValidationError, UploadLimitError) as exc:
        st.error(str(exc))
    except PerformanceCalculationError as exc:
        st.error(f"绩效计算失败：{exc}")
    except Exception as exc:
        LOGGER.exception("单实验页面发生未预期错误：%s", type(exc).__name__)
        st.error(UNEXPECTED_ERROR_MESSAGE)


def _render_single_page() -> None:
    """组织单实验输入、指标、图表、摘要和导出。"""
    st.info("当前为单实验分析；系统不会自动猜测或切换文件格式。")

    st.markdown("### 1. 数据输入")
    st.caption(
        f"上传限制：单文件最大 {SINGLE_FILE_MAX_MB} MB，"
        f"每份 CSV 最多 {MAX_ROWS_PER_FILE} 行。"
    )
    data_mode = st.radio(
        "选择数据来源",
        options=("使用示例数据", "上传 CSV 文件"),
        horizontal=True,
        key="single_data_mode",
    )

    selected_format = STANDARD_RETURN_FORMAT
    uploaded_file = None
    if data_mode == "上传 CSV 文件":
        selected_format = st.radio(
            "选择数据格式",
            options=(STANDARD_RETURN_FORMAT, WEEKLY_NAV_FORMAT),
            horizontal=True,
            key="single_data_format",
        )
        uploaded_file = st.file_uploader(
            "选择 CSV 文件", type=("csv",), key="single_uploaded_file"
        )
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
            "收益率必须使用小数格式，例如 `0.01` 代表 `1%`，"
            "不能用 `1` 代表 `1%`。"
        )
    else:
        st.markdown(
            "必需字段：`date`、`nav_strat`；可选字段：`daily_ret`。  "
            "绩效以 `nav_strat` 标准化净值及其 `pct_change()` 推导收益为准；"
            "`daily_ret` 仅用于一致性诊断。"
        )
    st.caption(
        "标准日频模板中的 benchmark_return 可删除；0.01 代表 1%。"
        "模板数据仅用于格式演示，不代表真实策略结果。"
    )
    st.download_button(
        "下载标准日频收益CSV模板",
        data=generate_daily_returns_template_csv(),
        file_name="daily_returns_template.csv",
        mime="text/csv; charset=utf-8",
        key="daily_returns_template_download",
    )

    if data_mode == "上传 CSV 文件" and uploaded_file is None:
        st.info("请上传一份符合字段协议的 CSV 文件后开始分析。")
        return

    data_source = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "example_daily_returns.csv"
        if data_mode == "使用示例数据"
        else uploaded_file
    )

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

    default_experiment_name = (
        "示例日频收益实验"
        if data_mode == "使用示例数据"
        else Path(uploaded_file.name).stem
    )
    input_identity = (
        "sample"
        if data_mode == "使用示例数据"
        else f"{selected_format}:{uploaded_file.name}"
    )
    with st.expander("实验信息（可选）"):
        experiment_name = st.text_input(
            "实验名称",
            value=default_experiment_name,
            max_chars=100,
            key=f"experiment_name:{input_identity}",
        )
        strategy_name = st.text_input(
            "策略名称",
            value="",
            max_chars=100,
            key=f"strategy_name:{input_identity}",
        )
        research_notes = st.text_area(
            "研究备注",
            value="",
            max_chars=1000,
            key=f"research_notes:{input_identity}",
        )

    st.markdown("### 3. 核心指标")
    metric_row_one = st.columns(4)
    metric_row_one[0].metric(
        "累计收益", _format_percentage(metrics["cumulative_return"])
    )
    metric_row_one[1].metric(
        "年化收益", _format_percentage(metrics["annualized_return"])
    )
    metric_row_one[2].metric(
        "年化波动率", _format_percentage(metrics["annualized_volatility"])
    )
    metric_row_one[3].metric("夏普比率", _format_number(metrics["sharpe_ratio"]))

    is_nav_format = selected_format == WEEKLY_NAV_FORMAT
    has_benchmark = "benchmark_cumulative_return" in metrics
    metric_row_two = st.columns(4 if has_benchmark or is_nav_format else 3)
    metric_row_two[0].metric(
        "最大回撤", _format_percentage(metrics["max_drawdown"])
    )
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
            "当前样本交易日较少，年化收益、年化波动率和夏普比率"
            "对短期表现较敏感，仅供参考。"
        )

    if diagnostics is not None:
        _render_diagnostics(diagnostics)

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

    report_context = ReportContext(
        experiment_name=experiment_name.strip() or "未命名实验",
        strategy_name=strategy_name.strip(),
        research_notes=research_notes.strip(),
        data_format=selected_format,
        primary_field=primary_field,
        start_date=pd.Timestamp(metrics["start_date"]),
        end_date=pd.Timestamp(metrics["end_date"]),
        observation_count=(
            int(metrics["nav_observations"]) if is_nav_format else len(cleaned_data)
        ),
        valid_return_count=int(metrics["n_days"]),
        metrics=metrics,
        has_benchmark=has_benchmark,
        diagnostics=diagnostics,
    )
    analysis_summary = generate_analysis_summary(report_context)
    markdown_report = generate_markdown_report(report_context)
    standardized_csv = generate_standardized_csv(performance_data)

    st.markdown("### 6. 分析摘要")
    st.markdown(analysis_summary)

    st.markdown("### 7. 结果导出")
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "下载分析报告",
        data=markdown_report.encode("utf-8"),
        file_name=make_report_filename(experiment_name),
        mime="text/markdown; charset=utf-8",
    )
    download_columns[1].download_button(
        "下载标准化分析数据",
        data=standardized_csv,
        file_name=make_standardized_data_filename(experiment_name),
        mime="text/csv; charset=utf-8",
    )

    st.markdown("### 8. 数据预览")
    with st.expander("查看清洗后的数据（前 20 行）"):
        st.caption(f"字段：{', '.join(cleaned_data.columns)}")
        st.caption(f"记录数量：{len(cleaned_data)}")
        st.dataframe(cleaned_data.head(20), width="stretch")


def _render_diagnostics(diagnostics: object) -> None:
    """展示 daily_ret 一致性诊断，不默认展开具体记录。"""
    mismatch_ratio = (
        diagnostics.mismatch_count / diagnostics.comparison_count
        if diagnostics.comparison_count > 0
        else 0.0
    )
    st.markdown("#### daily_ret 一致性诊断")
    diagnostic_columns = st.columns(3)
    diagnostic_columns[0].metric("有效比较数量", str(diagnostics.comparison_count))
    diagnostic_columns[1].metric("不一致日期数量", str(diagnostics.mismatch_count))
    diagnostic_columns[2].metric("不一致比例", f"{mismatch_ratio:.2%}")
    difference_columns = st.columns(2)
    difference_columns[0].write(
        "**最大绝对差异（BP）**  \n"
        f"{_format_basis_points(diagnostics.max_absolute_difference)}"
    )
    difference_columns[1].write(
        "**平均绝对差异（BP）**  \n"
        f"{_format_basis_points(diagnostics.mean_absolute_difference)}"
    )
    if diagnostics.mismatch_count > 0:
        st.warning(
            "文件中的 daily_ret 与 nav_strat 推导收益存在不一致。"
            "当前绩效指标以 nav_strat 为准，daily_ret 仅用于一致性检查。"
        )
        with st.expander("查看前 10 条不一致记录"):
            mismatch_preview = diagnostics.mismatches.head(10).copy()
            mismatch_preview["difference_bps"] = (
                mismatch_preview["difference"] * 10000
            )
            st.dataframe(mismatch_preview, width="stretch")
    else:
        st.success("daily_ret 与 nav_strat 推导收益在容差 1e-8 内一致。")


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


def _format_basis_points(value: float | None) -> str:
    """将原始小数差异转换为保留两位小数的基点。"""
    return "不可用" if value is None else f"{value * 10000:.2f} BP"
