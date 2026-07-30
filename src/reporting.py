"""生成确定性的中文分析摘要、Markdown 报告和标准化数据导出。"""

from dataclasses import dataclass
from math import isfinite
import re
from typing import Mapping

import pandas as pd

from src.adapters import DailyReturnDiagnostics


FIXED_DISCLAIMER = (
    "以上结果仅基于上传数据及当前计算口径生成，用于研究记录和结果核验，"
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


def generate_analysis_summary(context: ReportContext) -> str:
    """生成不含主观投资判断的确定性中文分析摘要。"""
    lines = [
        "### 1. 数据概况",
        f"- 实验名称：{context.experiment_name}",
    ]
    if context.strategy_name:
        lines.append(f"- 策略名称：{context.strategy_name}")
    lines.extend(
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
        lines.append("- 绩效以nav_strat标准化净值及其推导收益为准。")

    lines.extend(
        [
            "",
            "### 2. 绩效结果",
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
    )

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
        lines.extend(
            [
                "",
                "### 3. 基准信息",
                f"- 基准累计收益：{_format_percentage(benchmark_return)}",
                f"- 策略累计收益：{_format_percentage(strategy_return)}",
                f"- 期间累计收益差：{_format_percentage(period_difference)}",
            ]
        )

    lines.extend(["", "### 4. 数据限制"])
    has_limitation = False
    if context.valid_return_count < 60:
        lines.append(
            "- 当前样本交易日较少，年化收益、年化波动率和夏普比率对短期表现较敏感。"
        )
        has_limitation = True

    diagnostics = context.diagnostics
    if diagnostics is not None and diagnostics.mismatch_count > 0:
        mismatch_ratio = (
            diagnostics.mismatch_count / diagnostics.comparison_count
            if diagnostics.comparison_count > 0
            else 0.0
        )
        lines.extend(
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
        has_limitation = True

    if not has_limitation:
        lines.append("- 当前未触发额外的数据限制提示。")

    lines.extend(["", "### 5. 固定声明", FIXED_DISCLAIMER])
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
