"""生成确定性的中文分析摘要、Markdown 报告和标准化数据导出。"""

from dataclasses import dataclass
from math import isclose, isfinite
import re
from typing import Mapping

import pandas as pd

from src.adapters import DailyReturnDiagnostics
from src.performance import calculate_drawdown


FIXED_DISCLAIMER = (
    "以上结果仅基于上传数据及当前计算口径生成，用于研究记录和结果核验，"
    "不构成投资建议。"
)
COMPARISON_DISCLAIMER = (
    "比较结果仅基于所上传数据的共同日期及当前计算口径，用于研究记录和结果核验，"
    "不构成投资建议。"
)
INVALID_FILENAME_CHARACTERS = re.compile(r'[\\/:*?"<>|]')


@dataclass(frozen=True)
class ReportContext:
    """汇总生成摘要和报告所需的已计算信息。"""

    experiment_name: str
    strategy_name: str
    research_notes: str
    data_format: str
    primary_field: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    observation_count: int
    valid_return_count: int
    metrics: Mapping[str, object]
    has_benchmark: bool = False
    diagnostics: DailyReturnDiagnostics | None = None


@dataclass(frozen=True)
class ComparisonReportContext:
    """汇总生成多实验比较摘要和报告所需的信息。"""

    experiment_names: tuple[str, ...]
    coverage_table: pd.DataFrame
    metrics_table: pd.DataFrame
    common_start_date: pd.Timestamp
    common_end_date: pd.Timestamp
    common_nav_observations: int
    common_return_observations: int


def generate_analysis_summary(context: ReportContext) -> str:
    """生成不含主观投资判断的确定性中文分析摘要。"""
    overview_lines = [f"- 实验名称：{context.experiment_name}"]
    if context.strategy_name:
        overview_lines.append(f"- 策略名称：{context.strategy_name}")
    overview_lines.extend(
        [
            f"- 数据格式：{context.data_format}",
            (
                f"- 日期范围：{_format_date(context.start_date)} 至 "
                f"{_format_date(context.end_date)}"
            ),
            f"- 数据观察日数：{context.observation_count}",
            f"- 有效收益日数：{context.valid_return_count}",
            f"- 主要计算字段：{context.primary_field}",
        ]
    )
    if context.primary_field == "nav_strat":
        overview_lines.append("- 绩效以nav_strat标准化净值及其推导收益为准。")

    performance_lines = [
        f"- 累计收益：{_format_percentage(context.metrics.get('cumulative_return'))}",
        f"- 年化收益：{_format_percentage(context.metrics.get('annualized_return'))}",
        (
            "- 年化波动率："
            f"{_format_percentage(context.metrics.get('annualized_volatility'))}"
        ),
        f"- 夏普比率：{_format_number(context.metrics.get('sharpe_ratio'))}",
        f"- 最大回撤：{_format_percentage(context.metrics.get('max_drawdown'))}",
        (
            "- 盈利日占比："
            f"{_format_percentage(context.metrics.get('positive_day_ratio'))}"
        ),
    ]

    sections: list[tuple[str, list[str]]] = [
        ("数据概况", overview_lines),
        ("绩效结果", performance_lines),
    ]

    if context.has_benchmark:
        strategy_return = _finite_number(
            context.metrics.get("cumulative_return")
        )
        benchmark_return = _finite_number(
            context.metrics.get("benchmark_cumulative_return")
        )
        period_difference = (
            strategy_return - benchmark_return
            if strategy_return is not None and benchmark_return is not None
            else None
        )
        sections.append(
            (
                "基准信息",
                [
                    f"- 基准累计收益：{_format_percentage(benchmark_return)}",
                    f"- 策略累计收益：{_format_percentage(strategy_return)}",
                    f"- 期间累计收益差：{_format_percentage(period_difference)}",
                ],
            )
        )

    limitation_lines: list[str] = []
    if context.valid_return_count < 60:
        limitation_lines.append(
            "- 当前样本交易日较少，年化收益、年化波动率和夏普比率对短期表现较敏感。"
        )

    diagnostics = context.diagnostics
    if diagnostics is not None and diagnostics.mismatch_count > 0:
        mismatch_ratio = (
            diagnostics.mismatch_count / diagnostics.comparison_count
            if diagnostics.comparison_count > 0
            else 0.0
        )
        limitation_lines.extend(
            [
                f"- daily_ret 有效比较数量：{diagnostics.comparison_count}",
                f"- daily_ret 不一致日期数量：{diagnostics.mismatch_count}",
                f"- daily_ret 不一致比例：{mismatch_ratio:.2%}",
                (
                    "- 最大绝对差异："
                    f"{_format_basis_points(diagnostics.max_absolute_difference)}"
                ),
                (
                    "- 平均绝对差异："
                    f"{_format_basis_points(diagnostics.mean_absolute_difference)}"
                ),
                "- 当前分析仍以nav_strat为准。",
            ]
        )

    if limitation_lines:
        sections.append(("数据限制", limitation_lines))
    sections.append(("固定声明", [FIXED_DISCLAIMER]))

    lines: list[str] = []
    for section_number, (section_title, section_lines) in enumerate(
        sections, start=1
    ):
        if lines:
            lines.append("")
        lines.append(f"### {section_number}. {section_title}")
        lines.extend(section_lines)
    return "\n".join(lines)


def generate_markdown_report(context: ReportContext) -> str:
    """生成包含实验信息和分析摘要的 UTF-8 Markdown 报告文本。"""
    information_lines = [
        f"# {context.experiment_name} 分析报告",
        "",
        "## 实验基本信息",
        f"- 实验名称：{context.experiment_name}",
        f"- 策略名称：{context.strategy_name or '未填写'}",
        f"- 研究备注：{context.research_notes or '未填写'}",
        "",
        "## 核心指标表",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        (
            "| 累计收益 | "
            f"{_format_percentage(context.metrics.get('cumulative_return'))} |"
        ),
        (
            "| 年化收益 | "
            f"{_format_percentage(context.metrics.get('annualized_return'))} |"
        ),
        (
            "| 年化波动率 | "
            f"{_format_percentage(context.metrics.get('annualized_volatility'))} |"
        ),
        f"| 夏普比率 | {_format_number(context.metrics.get('sharpe_ratio'))} |",
        (
            "| 最大回撤 | "
            f"{_format_percentage(context.metrics.get('max_drawdown'))} |"
        ),
        (
            "| 盈利日占比 | "
            f"{_format_percentage(context.metrics.get('positive_day_ratio'))} |"
        ),
        "",
        "## 确定性分析摘要",
        "",
        generate_analysis_summary(context),
    ]
    return "\n".join(information_lines) + "\n"


def generate_comparison_summary(context: ComparisonReportContext) -> str:
    """生成中性、确定性的共同日期区间比较摘要。"""
    overview_lines = [
        f"- 比较实验数量：{len(context.experiment_names)}",
        (
            f"- 共同日期范围：{_format_date(context.common_start_date)} 至 "
            f"{_format_date(context.common_end_date)}"
        ),
        f"- 共同净值观察日数：{context.common_nav_observations}",
        f"- 共同有效收益日数：{context.common_return_observations}",
    ]

    result_lines: list[str] = []
    cumulative_names, cumulative_value = _find_extreme_experiments(
        context.metrics_table, "cumulative_return", mode="max"
    )
    if cumulative_names:
        result_lines.append(
            "- 共同区间累计收益最高："
            f"{'、'.join(cumulative_names)}（{_format_percentage(cumulative_value)}）"
        )
    volatility_names, volatility_value = _find_extreme_experiments(
        context.metrics_table, "annualized_volatility", mode="min"
    )
    if volatility_names:
        result_lines.append(
            "- 年化波动率最低："
            f"{'、'.join(volatility_names)}（{_format_percentage(volatility_value)}）"
        )
    drawdown_names, drawdown_value = _find_extreme_experiments(
        context.metrics_table,
        "max_drawdown",
        mode="min",
        use_absolute=True,
    )
    if drawdown_names:
        result_lines.append(
            "- 最大回撤绝对值最小："
            f"{'、'.join(drawdown_names)}（{_format_percentage(drawdown_value)}）"
        )
    sharpe_names, sharpe_value = _find_extreme_experiments(
        context.metrics_table, "sharpe_ratio", mode="max"
    )
    if sharpe_names:
        result_lines.append(
            "- 夏普比率最高："
            f"{'、'.join(sharpe_names)}（{_format_number(sharpe_value)}）"
        )

    sections: list[tuple[str, list[str]]] = [
        ("比较概况", overview_lines),
        ("共同区间结果", result_lines),
    ]
    if context.common_return_observations < 60:
        sections.append(
            (
                "数据限制",
                [
                    "- 当前共同样本交易日较少，年化收益、年化波动率和夏普比率"
                    "对短期表现较敏感。"
                ],
            )
        )
    sections.append(("固定声明", [COMPARISON_DISCLAIMER]))
    return _render_numbered_sections(sections)


def generate_comparison_markdown_report(
    context: ComparisonReportContext,
) -> str:
    """生成包含覆盖表、指标表和确定性摘要的比较 Markdown 报告。"""
    lines = [
        "# 多实验比较报告",
        "",
        "## 实验清单",
        *[f"- {name}" for name in context.experiment_names],
        "",
        "## 原始数据覆盖",
        "",
        "| 实验名称 | 原始开始日期 | 原始结束日期 | 原始净值观察日数 |",
        "| --- | --- | --- | ---: |",
    ]
    for row in context.coverage_table.itertuples(index=False):
        lines.append(
            f"| {row.experiment_name} | {_format_date(row.original_start_date)} | "
            f"{_format_date(row.original_end_date)} | "
            f"{row.original_nav_observation_count} |"
        )
    lines.extend(
        [
            "",
            "## 共同日期说明",
            (
                f"共同日期范围为 {_format_date(context.common_start_date)} 至 "
                f"{_format_date(context.common_end_date)}，包含 "
                f"{context.common_nav_observations} 个净值观察日和 "
                f"{context.common_return_observations} 个有效收益日。"
            ),
            "以下结果仅使用所有实验共同存在的交易日期，并从共同首日重新归一。",
            "",
            "## 比较指标表",
            "",
            (
                "| 实验名称 | 累计收益 | 年化收益 | 年化波动率 | 夏普比率 | "
                "最大回撤 | 盈利日占比 | 有效收益日数 |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in context.metrics_table.itertuples(index=False):
        lines.append(
            f"| {row.experiment_name} | {_format_percentage(row.cumulative_return)} | "
            f"{_format_percentage(row.annualized_return)} | "
            f"{_format_percentage(row.annualized_volatility)} | "
            f"{_format_number(row.sharpe_ratio)} | "
            f"{_format_percentage(row.max_drawdown)} | "
            f"{_format_percentage(row.positive_day_ratio)} | "
            f"{row.effective_return_count} |"
        )
    lines.extend(
        [
            "",
            "## 确定性比较摘要",
            "",
            generate_comparison_summary(context),
        ]
    )
    return "\n".join(lines) + "\n"


def build_standardized_data(data: pd.DataFrame) -> pd.DataFrame:
    """选择并复制标准化分析字段，不修改输入 DataFrame。"""
    required_columns = ["date", "strategy_return", "strategy_nav", "drawdown"]
    missing_columns = [
        column for column in required_columns if column not in data.columns
    ]
    if missing_columns:
        raise ValueError(f"标准化数据缺少字段：{', '.join(missing_columns)}")

    export_columns = required_columns.copy()
    if "benchmark_return" in data.columns and "benchmark_nav" in data.columns:
        export_columns.extend(["benchmark_return", "benchmark_nav"])

    standardized_data = data.loc[:, export_columns].copy(deep=True)
    normalized_nav = (
        pd.to_numeric(standardized_data["strategy_nav"], errors="raise")
        / float(standardized_data["strategy_nav"].iloc[0])
    )
    standardized_data["strategy_nav"] = normalized_nav
    standardized_data["strategy_return"] = normalized_nav.pct_change(
        fill_method=None
    )
    standardized_data["drawdown"] = calculate_drawdown(normalized_nav)
    if "benchmark_nav" in standardized_data.columns:
        normalized_benchmark = (
            pd.to_numeric(standardized_data["benchmark_nav"], errors="raise")
            / float(standardized_data["benchmark_nav"].iloc[0])
        )
        standardized_data["benchmark_nav"] = normalized_benchmark
        standardized_data["benchmark_return"] = normalized_benchmark.pct_change(
            fill_method=None
        )
    standardized_data["date"] = pd.to_datetime(
        standardized_data["date"]
    ).dt.strftime("%Y-%m-%d")
    return standardized_data


def generate_standardized_csv(data: pd.DataFrame) -> bytes:
    """在内存中生成带 UTF-8 BOM 的标准化 CSV 字节。"""
    standardized_data = build_standardized_data(data)
    return standardized_data.to_csv(index=False).encode("utf-8-sig")


def sanitize_filename_component(value: str) -> str:
    """清理 Windows 文件名非法字符和不安全的首尾字符。"""
    cleaned = INVALID_FILENAME_CHARACTERS.sub("_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip(" ._")
    return cleaned


def make_report_filename(experiment_name: str) -> str:
    """生成安全的 Markdown 报告文件名。"""
    safe_name = sanitize_filename_component(experiment_name)
    return (
        f"{safe_name}_analysis_report.md"
        if safe_name
        else "quant_analysis_report.md"
    )


def make_standardized_data_filename(experiment_name: str) -> str:
    """生成安全的标准化 CSV 文件名。"""
    safe_name = sanitize_filename_component(experiment_name)
    return (
        f"{safe_name}_standardized_data.csv"
        if safe_name
        else "quant_standardized_data.csv"
    )


def _finite_number(value: object) -> float | None:
    """将有效有限数值转换为 float，否则返回 None。"""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    return numeric_value if isfinite(numeric_value) else None


def _format_percentage(value: object) -> str:
    numeric_value = _finite_number(value)
    return "不可用" if numeric_value is None else f"{numeric_value:.2%}"


def _format_number(value: object) -> str:
    numeric_value = _finite_number(value)
    return "不可用" if numeric_value is None else f"{numeric_value:.2f}"


def _format_basis_points(value: object) -> str:
    numeric_value = _finite_number(value)
    return "不可用" if numeric_value is None else f"{numeric_value * 10000:.2f} BP"


def _format_date(value: object) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _find_extreme_experiments(
    metrics_table: pd.DataFrame,
    column: str,
    mode: str,
    use_absolute: bool = False,
) -> tuple[list[str], float | None]:
    """查找极值及全部并列实验，忽略不可用数值。"""
    valid_rows: list[tuple[str, float, float]] = []
    for row in metrics_table[["experiment_name", column]].itertuples(index=False):
        numeric_value = _finite_number(row[1])
        if numeric_value is not None:
            comparison_value = abs(numeric_value) if use_absolute else numeric_value
            valid_rows.append((str(row[0]), numeric_value, comparison_value))
    if not valid_rows:
        return [], None

    target = (
        max(row[2] for row in valid_rows)
        if mode == "max"
        else min(row[2] for row in valid_rows)
    )
    tied_rows = [
        row
        for row in valid_rows
        if isclose(row[2], target, rel_tol=1e-12, abs_tol=1e-12)
    ]
    return [row[0] for row in tied_rows], tied_rows[0][1]


def _render_numbered_sections(
    sections: list[tuple[str, list[str]]],
) -> str:
    """将非空章节按实际顺序连续编号。"""
    lines: list[str] = []
    non_empty_sections = [
        (section_title, section_lines)
        for section_title, section_lines in sections
        if section_lines
    ]
    for section_number, (section_title, section_lines) in enumerate(
        non_empty_sections, start=1
    ):
        if lines:
            lines.append("")
        lines.append(f"### {section_number}. {section_title}")
        lines.extend(section_lines)
    return "\n".join(lines)
