"""多实验比较模式的 Streamlit 页面组织。"""

import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.comparison import (
    ComparisonResult,
    ComparisonValidationError,
    compare_standardized_datasets,
    extract_experiment_name,
    generate_aligned_nav_csv,
    generate_comparison_metrics_csv,
    load_and_compare_standardized_files,
)
from src.config import (
    COMPARISON_FILE_MAX_MB,
    MAX_COMPARISON_FILES,
    MAX_ROWS_PER_FILE,
)
from src.limits import UploadLimitError
from src.reporting import (
    ComparisonReportContext,
    generate_comparison_markdown_report,
    generate_comparison_summary,
)
from src.sample_data import generate_comparison_sample_data
from src.templates import generate_comparison_template_csv


LOGGER = logging.getLogger(__name__)
UNEXPECTED_ERROR_MESSAGE = (
    "应用处理过程中出现未预期错误。请检查文件格式；"
    "若问题持续存在，请重新启动应用并保留错误发生步骤。"
)


def render_comparison_page() -> None:
    """渲染比较页面，并统一处理预期及未预期异常。"""
    try:
        _render_comparison_page()
    except (ComparisonValidationError, UploadLimitError) as exc:
        st.error(str(exc))
    except Exception as exc:
        LOGGER.exception("多实验比较页面发生未预期错误：%s", type(exc).__name__)
        st.error(UNEXPECTED_ERROR_MESSAGE)


def _render_comparison_page() -> None:
    """组织只接受标准化 CSV 的多实验比较内容。"""
    st.info(
        "多实验比较仅使用标准化文件中的策略字段；"
        "基准字段暂不参与跨实验比较。"
    )
    st.markdown("### 1. 数据输入")
    source_mode = st.radio(
        "选择比较数据来源",
        options=("使用比较示例数据", "上传标准化 CSV"),
        horizontal=True,
        key="comparison_source_mode",
    )
    st.caption("当前模式：多实验比较")
    st.caption(
        f"上传限制：2 至 {MAX_COMPARISON_FILES} 份文件，每份最大 "
        f"{COMPARISON_FILE_MAX_MB} MB、最多 {MAX_ROWS_PER_FILE} 行。"
    )
    st.markdown(
        "必需字段：`date`、`strategy_return`、`strategy_nav`、`drawdown`；  "
        "可选字段：`benchmark_return`、`benchmark_nav`。系统不会自动映射其他字段。"
    )
    st.caption(
        "模板第一行收益为空且净值为1，仅用于标准化字段格式演示，"
        "不代表真实策略结果。"
    )
    st.download_button(
        "下载标准化比较CSV模板",
        data=generate_comparison_template_csv(),
        file_name="standardized_comparison_template.csv",
        mime="text/csv; charset=utf-8",
        key="comparison_template_download",
    )

    if source_mode == "使用比较示例数据":
        sample_datasets = generate_comparison_sample_data()
        st.caption(f"上传文件数量：{len(sample_datasets)}（固定比较示例）")
        result = compare_standardized_datasets(sample_datasets)
    else:
        uploaded_files = st.file_uploader(
            f"选择 2 至 {MAX_COMPARISON_FILES} 份标准化分析 CSV",
            type=("csv",),
            accept_multiple_files=True,
            key="comparison_uploaded_files",
        )
        st.caption(f"上传文件数量：{len(uploaded_files)}")
        if uploaded_files:
            parsed_names = [
                extract_experiment_name(uploaded_file.name)
                for uploaded_file in uploaded_files
            ]
            st.caption(f"实验名称：{'、'.join(parsed_names)}")
        if len(uploaded_files) < 2:
            st.info("多实验比较至少需要上传 2 份标准化 CSV。")
            return
        if len(uploaded_files) > MAX_COMPARISON_FILES:
            st.error(
                f"当前版本最多支持 {MAX_COMPARISON_FILES} 份标准化 CSV。"
            )
            return
        result = load_and_compare_standardized_files(
            [
                (uploaded_file.name, uploaded_file)
                for uploaded_file in uploaded_files
            ]
        )

    experiment_names = [
        experiment.name for experiment in result.experiments
    ]
    st.caption(f"实验名称：{'、'.join(experiment_names)}")
    _render_coverage(result)
    _render_metrics(result)
    _render_charts(result)
    _render_summary_and_downloads(result)


def _render_coverage(result: ComparisonResult) -> None:
    """展示原始数据覆盖范围和共同交易日期概况。"""
    st.markdown("### 2. 数据覆盖概况")
    coverage_display = result.coverage_table.rename(
        columns={
            "experiment_name": "实验名称",
            "original_start_date": "原始开始日期",
            "original_end_date": "原始结束日期",
            "original_nav_observation_count": "原始净值观察日数",
        }
    ).copy()
    for column in ("原始开始日期", "原始结束日期"):
        coverage_display[column] = pd.to_datetime(
            coverage_display[column]
        ).dt.strftime("%Y-%m-%d")
    st.dataframe(coverage_display, hide_index=True, width="stretch")

    common_columns = st.columns(4)
    common_columns[0].metric(
        "共同开始日期", result.common_start_date.strftime("%Y-%m-%d")
    )
    common_columns[1].metric(
        "共同结束日期", result.common_end_date.strftime("%Y-%m-%d")
    )
    common_columns[2].metric(
        "共同净值观察日数", str(result.common_nav_observations)
    )
    common_columns[3].metric(
        "共同有效收益日数", str(result.common_return_observations)
    )
    st.info("以下指标均基于所有实验共同存在的交易日期重新计算。")
    if result.common_return_observations < 60:
        st.warning(
            "当前共同样本交易日较少，年化收益、年化波动率和夏普比率"
            "对短期表现较敏感，仅供参考。"
        )


def _render_metrics(result: ComparisonResult) -> None:
    """展示经过格式化的共同区间核心指标表。"""
    st.markdown("### 3. 核心比较指标表")
    metrics_display = result.metrics_table[
        [
            "experiment_name",
            "cumulative_return",
            "annualized_return",
            "annualized_volatility",
            "sharpe_ratio",
            "max_drawdown",
            "positive_day_ratio",
            "effective_return_count",
        ]
    ].copy()
    for column in (
        "cumulative_return",
        "annualized_return",
        "annualized_volatility",
        "max_drawdown",
        "positive_day_ratio",
    ):
        metrics_display[column] = metrics_display[column].map(_format_percentage)
    metrics_display["sharpe_ratio"] = metrics_display["sharpe_ratio"].map(
        _format_number
    )
    metrics_display = metrics_display.rename(
        columns={
            "experiment_name": "实验名称",
            "cumulative_return": "累计收益",
            "annualized_return": "年化收益",
            "annualized_volatility": "年化波动率",
            "sharpe_ratio": "夏普比率",
            "max_drawdown": "最大回撤",
            "positive_day_ratio": "盈利日占比",
            "effective_return_count": "有效收益日数",
        }
    )
    st.dataframe(metrics_display, hide_index=True, width="stretch")


def _render_charts(result: ComparisonResult) -> None:
    """绘制共同区间净值和回撤两张独立图表。"""
    st.markdown("### 4. 净值比较图")
    nav_figure = go.Figure()
    for experiment_name, aligned_data in result.aligned_experiments.items():
        nav_figure.add_trace(
            go.Scatter(
                x=aligned_data["date"],
                y=aligned_data["comparison_nav"],
                mode="lines",
                name=experiment_name,
            )
        )
    nav_figure.update_layout(
        xaxis_title="日期",
        yaxis_title="标准化净值",
        hovermode="x unified",
    )
    st.plotly_chart(nav_figure, width="stretch")

    st.markdown("### 5. 回撤比较图")
    drawdown_figure = go.Figure()
    for experiment_name, aligned_data in result.aligned_experiments.items():
        drawdown_figure.add_trace(
            go.Scatter(
                x=aligned_data["date"],
                y=aligned_data["comparison_drawdown"],
                mode="lines",
                name=experiment_name,
            )
        )
    drawdown_figure.update_layout(
        xaxis_title="日期",
        yaxis_title="回撤",
        hovermode="x unified",
    )
    drawdown_figure.update_yaxes(tickformat=".1%")
    st.plotly_chart(drawdown_figure, width="stretch")


def _render_summary_and_downloads(result: ComparisonResult) -> None:
    """展示确定性摘要并提供三种仅在内存中生成的下载。"""
    context = ComparisonReportContext(
        experiment_names=tuple(
            experiment.name for experiment in result.experiments
        ),
        coverage_table=result.coverage_table,
        metrics_table=result.metrics_table,
        common_start_date=result.common_start_date,
        common_end_date=result.common_end_date,
        common_nav_observations=result.common_nav_observations,
        common_return_observations=result.common_return_observations,
    )
    st.markdown("### 6. 确定性比较摘要")
    st.markdown(generate_comparison_summary(context))

    st.markdown("### 7. 比较结果导出")
    download_columns = st.columns(3)
    download_columns[0].download_button(
        "下载比较指标",
        data=generate_comparison_metrics_csv(result),
        file_name="multi_experiment_metrics.csv",
        mime="text/csv; charset=utf-8",
    )
    download_columns[1].download_button(
        "下载对齐净值数据",
        data=generate_aligned_nav_csv(result),
        file_name="multi_experiment_aligned_nav.csv",
        mime="text/csv; charset=utf-8",
    )
    download_columns[2].download_button(
        "下载比较报告",
        data=generate_comparison_markdown_report(context).encode("utf-8"),
        file_name="multi_experiment_comparison_report.md",
        mime="text/markdown; charset=utf-8",
    )


def _format_percentage(value: object) -> str:
    """将有限数值格式化为两位小数百分比。"""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return "不可用"
    return f"{numeric_value:.2%}" if pd.notna(numeric_value) else "不可用"


def _format_number(value: object) -> str:
    """将有限数值格式化为两位小数普通数字。"""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return "不可用"
    return f"{numeric_value:.2f}" if pd.notna(numeric_value) else "不可用"
