"""确定性摘要、Markdown 报告和标准化数据导出测试。"""

from dataclasses import replace
import re

import pandas as pd
import pytest

from src.adapters import DailyReturnDiagnostics
from src.reporting import (
    FIXED_DISCLAIMER,
    ReportContext,
    build_standardized_data,
    generate_analysis_summary,
    generate_markdown_report,
    generate_standardized_csv,
    make_report_filename,
    sanitize_filename_component,
)


@pytest.fixture
def base_metrics() -> dict[str, object]:
    return {
        "cumulative_return": 0.12,
        "annualized_return": 0.18,
        "annualized_volatility": 0.15,
        "sharpe_ratio": 1.2,
        "max_drawdown": -0.08,
        "positive_day_ratio": 0.55,
    }


@pytest.fixture
def standard_context(base_metrics: dict[str, object]) -> ReportContext:
    return ReportContext(
        experiment_name="标准实验",
        strategy_name="示例策略",
        research_notes="用于测试",
        data_format="标准日频收益 CSV",
        primary_field="strategy_return",
        start_date=pd.Timestamp("2026-01-01"),
        end_date=pd.Timestamp("2026-04-30"),
        observation_count=80,
        valid_return_count=80,
        metrics=base_metrics,
    )


@pytest.fixture
def nav_context(base_metrics: dict[str, object]) -> ReportContext:
    return ReportContext(
        experiment_name="净值实验",
        strategy_name="",
        research_notes="",
        data_format="每周调仓净值 CSV",
        primary_field="nav_strat",
        start_date=pd.Timestamp("2025-01-02"),
        end_date=pd.Timestamp("2026-05-08"),
        observation_count=319,
        valid_return_count=318,
        metrics=base_metrics,
    )


def test_standard_format_can_generate_summary(
    standard_context: ReportContext,
) -> None:
    assert generate_analysis_summary(standard_context)


def test_weekly_nav_format_can_generate_summary(nav_context: ReportContext) -> None:
    summary = generate_analysis_summary(nav_context)

    assert "nav_strat标准化净值及其推导收益" in summary


def test_summary_contains_experiment_name(standard_context: ReportContext) -> None:
    assert "标准实验" in generate_analysis_summary(standard_context)


def test_summary_contains_date_range(standard_context: ReportContext) -> None:
    summary = generate_analysis_summary(standard_context)

    assert "2026-01-01" in summary
    assert "2026-04-30" in summary


def test_summary_contains_core_metrics(standard_context: ReportContext) -> None:
    summary = generate_analysis_summary(standard_context)

    for metric_name in ("累计收益", "年化收益", "年化波动率", "夏普比率", "最大回撤", "盈利日占比"):
        assert metric_name in summary


def test_no_benchmark_section_when_benchmark_absent(
    standard_context: ReportContext,
) -> None:
    assert "### 3. 基准信息" not in generate_analysis_summary(standard_context)


def test_benchmark_section_contains_period_difference(
    standard_context: ReportContext,
) -> None:
    metrics = dict(standard_context.metrics)
    metrics["benchmark_cumulative_return"] = 0.07
    context = replace(standard_context, metrics=metrics, has_benchmark=True)

    summary = generate_analysis_summary(context)

    assert "期间累计收益差：5.00%" in summary


def test_period_difference_is_not_called_alpha(
    standard_context: ReportContext,
) -> None:
    metrics = dict(standard_context.metrics)
    metrics["benchmark_cumulative_return"] = 0.07
    context = replace(standard_context, metrics=metrics, has_benchmark=True)

    assert "alpha" not in generate_analysis_summary(context).lower()


def test_short_sample_contains_limitation(standard_context: ReportContext) -> None:
    context = replace(standard_context, valid_return_count=20)

    assert "当前样本交易日较少" in generate_analysis_summary(context)


def test_long_sample_does_not_contain_short_limitation(
    standard_context: ReportContext,
) -> None:
    assert "当前样本交易日较少" not in generate_analysis_summary(standard_context)


def test_consistent_daily_return_has_no_mismatch_warning(
    nav_context: ReportContext,
) -> None:
    diagnostics = DailyReturnDiagnostics(
        comparison_count=2,
        mismatch_count=0,
        max_absolute_difference=0.0,
        mean_absolute_difference=0.0,
        mismatches=pd.DataFrame(),
    )
    context = replace(nav_context, diagnostics=diagnostics)

    assert "daily_ret 不一致日期数量" not in generate_analysis_summary(context)


def test_inconsistent_daily_return_contains_count(
    nav_context: ReportContext,
) -> None:
    diagnostics = DailyReturnDiagnostics(
        comparison_count=10,
        mismatch_count=2,
        max_absolute_difference=0.001,
        mean_absolute_difference=0.0002,
        mismatches=pd.DataFrame(),
    )
    context = replace(nav_context, diagnostics=diagnostics)

    summary = generate_analysis_summary(context)

    assert "不一致日期数量：2" in summary
    assert "不一致比例：20.00%" in summary


def test_summary_does_not_contain_nan(standard_context: ReportContext) -> None:
    metrics = dict(standard_context.metrics)
    metrics["annualized_return"] = float("nan")
    context = replace(standard_context, metrics=metrics)

    assert "nan" not in generate_analysis_summary(context).lower()


def test_summary_does_not_contain_infinity(standard_context: ReportContext) -> None:
    metrics = dict(standard_context.metrics)
    metrics["annualized_volatility"] = float("inf")
    context = replace(standard_context, metrics=metrics)

    assert "inf" not in generate_analysis_summary(context).lower()


def test_unavailable_sharpe_is_shown_in_chinese(
    standard_context: ReportContext,
) -> None:
    metrics = dict(standard_context.metrics)
    metrics["sharpe_ratio"] = None
    context = replace(standard_context, metrics=metrics)

    assert "夏普比率：不可用" in generate_analysis_summary(context)


def test_markdown_report_contains_fixed_disclaimer(
    standard_context: ReportContext,
) -> None:
    report = generate_markdown_report(standard_context)

    assert FIXED_DISCLAIMER in report
    assert "## 核心指标表" in report
    assert "| 指标 | 结果 |" in report


def test_illegal_filename_characters_are_sanitized() -> None:
    filename = make_report_filename('实验\\/:*?"<>|名称')

    assert filename.endswith("_analysis_report.md")
    assert not any(character in filename for character in '\\/:*?"<>|')


def test_empty_filename_falls_back_to_default() -> None:
    assert make_report_filename('\\/:*?"<>|') == "quant_analysis_report.md"


def test_standardized_data_contains_expected_columns() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_return": [0.01, -0.02],
            "strategy_nav": [1.01, 0.9898],
            "drawdown": [0.0, -0.02],
            "benchmark_return": [0.005, -0.01],
            "benchmark_nav": [1.005, 0.99495],
        }
    )

    result = build_standardized_data(data)

    assert list(result.columns) == [
        "date",
        "strategy_return",
        "strategy_nav",
        "drawdown",
        "benchmark_return",
        "benchmark_nav",
    ]


def test_weekly_nav_export_first_nav_equals_one() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_return": [None, 0.1],
            "strategy_nav": [1.0, 1.1],
            "drawdown": [0.0, 0.0],
        }
    )

    assert build_standardized_data(data)["strategy_nav"].iloc[0] == 1.0


def test_standardized_export_rebases_nav_and_leaves_first_return_empty() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_return": [0.01, 0.1],
            "strategy_nav": [1.01, 1.111],
            "drawdown": [0.0, 0.0],
        }
    )

    result = build_standardized_data(data)

    assert result["strategy_nav"].tolist() == pytest.approx([1.0, 1.1])
    assert pd.isna(result["strategy_return"].iloc[0])
    assert result["strategy_return"].iloc[1] == pytest.approx(0.1)


def test_weekly_nav_export_does_not_use_daily_return() -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "daily_ret": [0.0, 0.5],
            "strategy_return": [None, 0.1],
            "strategy_nav": [1.0, 1.1],
            "drawdown": [0.0, 0.0],
        }
    )

    result = build_standardized_data(data)

    assert result["strategy_nav"].tolist() == [1.0, 1.1]
    assert "daily_ret" not in result.columns


def test_report_generation_does_not_modify_input_dataframe(
    standard_context: ReportContext,
) -> None:
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "strategy_return": [0.01, -0.02],
            "strategy_nav": [1.01, 0.9898],
            "drawdown": [0.0, -0.02],
        }
    )
    original = data.copy(deep=True)

    generate_analysis_summary(standard_context)
    generate_markdown_report(standard_context)
    generate_standardized_csv(data)

    pd.testing.assert_frame_equal(data, original)


def test_filename_component_replaces_whitespace() -> None:
    assert sanitize_filename_component("  my experiment  ") == "my_experiment"


def _section_headings(text: str) -> list[str]:
    """提取确定性摘要中的编号章节标题。"""
    return re.findall(r"^### \d+\. .+$", text, flags=re.MULTILINE)


def test_continuous_numbering_without_benchmark_with_limitation(
    standard_context: ReportContext,
) -> None:
    context = replace(standard_context, valid_return_count=20)

    assert _section_headings(generate_analysis_summary(context)) == [
        "### 1. 数据概况",
        "### 2. 绩效结果",
        "### 3. 数据限制",
        "### 4. 固定声明",
    ]


def test_continuous_numbering_with_benchmark_and_limitation(
    standard_context: ReportContext,
) -> None:
    metrics = dict(standard_context.metrics)
    metrics["benchmark_cumulative_return"] = 0.07
    context = replace(
        standard_context,
        metrics=metrics,
        has_benchmark=True,
        valid_return_count=20,
    )

    assert _section_headings(generate_analysis_summary(context)) == [
        "### 1. 数据概况",
        "### 2. 绩效结果",
        "### 3. 基准信息",
        "### 4. 数据限制",
        "### 5. 固定声明",
    ]


def test_continuous_numbering_without_benchmark_or_limitation(
    standard_context: ReportContext,
) -> None:
    assert _section_headings(generate_analysis_summary(standard_context)) == [
        "### 1. 数据概况",
        "### 2. 绩效结果",
        "### 3. 固定声明",
    ]


def test_section_numbering_does_not_jump_from_two_to_four(
    standard_context: ReportContext,
) -> None:
    summary = generate_analysis_summary(
        replace(standard_context, valid_return_count=20)
    )

    assert "### 4. 数据限制" not in summary


def test_page_summary_and_markdown_report_have_same_section_order(
    standard_context: ReportContext,
) -> None:
    context = replace(standard_context, valid_return_count=20)
    summary = generate_analysis_summary(context)
    markdown_report = generate_markdown_report(context)

    assert _section_headings(markdown_report) == _section_headings(summary)
