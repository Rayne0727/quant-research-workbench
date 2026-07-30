"""将每周调仓净值 CSV 适配为统一的策略分析数据。"""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import IO

import pandas as pd


REQUIRED_NAV_COLUMNS = ("date", "nav_strat")
OPTIONAL_NAV_COLUMNS = ("daily_ret",)
ALLOWED_NAV_COLUMNS = set(REQUIRED_NAV_COLUMNS + OPTIONAL_NAV_COLUMNS)
DEFAULT_RETURN_TOLERANCE = 1e-8
CsvSource = str | Path | IO[str] | IO[bytes]


class WeeklyNavValidationError(ValueError):
    """表示每周调仓净值 CSV 中可由用户修复的数据问题。"""


@dataclass(frozen=True)
class DailyReturnDiagnostics:
    """记录 daily_ret 与净值推导收益的一致性检查结果。"""

    comparison_count: int
    mismatch_count: int
    max_absolute_difference: float | None
    mean_absolute_difference: float | None
    mismatches: pd.DataFrame


@dataclass(frozen=True)
class WeeklyNavAdapterResult:
    """包含标准化净值数据和可选的一致性诊断。"""

    data: pd.DataFrame
    diagnostics: DailyReturnDiagnostics | None


def load_weekly_nav_csv(
    source: CsvSource,
    tolerance: float = DEFAULT_RETURN_TOLERANCE,
) -> WeeklyNavAdapterResult:
    """读取并严格验证每周调仓净值 CSV。"""
    try:
        if hasattr(source, "seek"):
            source.seek(0)
        raw_data = pd.read_csv(source)
    except pd.errors.EmptyDataError as exc:
        raise WeeklyNavValidationError(
            "CSV 文件为空，请提供包含表头和数据的文件。"
        ) from exc
    except UnicodeDecodeError as exc:
        raise WeeklyNavValidationError(
            "CSV 文件编码无法读取，请将文件保存为 UTF-8 编码。"
        ) from exc
    except pd.errors.ParserError as exc:
        raise WeeklyNavValidationError(
            "CSV 文件格式无法解析，请检查分隔符和每行字段数量。"
        ) from exc
    except (OSError, ValueError) as exc:
        raise WeeklyNavValidationError(
            "CSV 文件读取失败，请确认文件有效且未损坏。"
        ) from exc

    return adapt_weekly_nav_data(raw_data, tolerance=tolerance)


def adapt_weekly_nav_data(
    raw_data: pd.DataFrame,
    tolerance: float = DEFAULT_RETURN_TOLERANCE,
) -> WeeklyNavAdapterResult:
    """验证净值数据，并生成标准化净值、推导收益和诊断结果。"""
    if tolerance < 0:
        raise ValueError("一致性检查容差不能为负数。")
    if raw_data.empty:
        raise WeeklyNavValidationError(
            "CSV 文件没有数据记录，请至少提供 2 条净值记录。"
        )

    missing_columns = [
        column for column in REQUIRED_NAV_COLUMNS if column not in raw_data.columns
    ]
    if missing_columns:
        missing_text = "、".join(missing_columns)
        raise WeeklyNavValidationError(f"CSV 缺少必需字段：{missing_text}。")

    unsupported_columns = [
        str(column) for column in raw_data.columns if column not in ALLOWED_NAV_COLUMNS
    ]
    if unsupported_columns:
        unsupported_text = "、".join(unsupported_columns)
        raise WeeklyNavValidationError(
            f"CSV 包含当前格式不支持的字段：{unsupported_text}。"
            "每周调仓净值 CSV 仅支持 date、nav_strat 和可选的 daily_ret。"
        )

    cleaned_data = raw_data.copy(deep=True)
    for column in REQUIRED_NAV_COLUMNS:
        missing_mask = cleaned_data[column].isna() | (
            cleaned_data[column].astype("string").str.strip() == ""
        )
        if missing_mask.any():
            raise WeeklyNavValidationError(
                f"必需字段 {column} 存在缺失值，请补充后重试。"
            )

    parsed_dates = pd.to_datetime(
        cleaned_data["date"], errors="coerce", format="mixed"
    )
    if parsed_dates.isna().any():
        raise WeeklyNavValidationError(
            "date 字段包含无法识别的日期，请使用有效日期格式。"
        )
    cleaned_data["date"] = parsed_dates

    nav_values = pd.to_numeric(cleaned_data["nav_strat"], errors="coerce")
    if nav_values.isna().any():
        raise WeeklyNavValidationError("nav_strat 字段包含无法转换为数值的内容。")
    if not all(isfinite(value) for value in nav_values.to_numpy(dtype=float)):
        raise WeeklyNavValidationError(
            "nav_strat 字段只能包含有限数值，不能包含 NaN 或无穷大。"
        )
    if (nav_values <= 0).any():
        raise WeeklyNavValidationError("nav_strat 必须全部大于 0。")
    cleaned_data["nav_strat"] = nav_values.astype(float)

    if "daily_ret" in cleaned_data.columns:
        daily_values = cleaned_data["daily_ret"]
        daily_missing = daily_values.isna() | (
            daily_values.astype("string").str.strip() == ""
        )
        daily_returns = pd.to_numeric(daily_values, errors="coerce")
        invalid_daily = ~daily_missing & daily_returns.isna()
        if invalid_daily.any():
            raise WeeklyNavValidationError(
                "daily_ret 字段包含无法转换为数值的内容。"
            )
        finite_daily = daily_returns.dropna().to_numpy(dtype=float)
        if not all(isfinite(value) for value in finite_daily):
            raise WeeklyNavValidationError(
                "daily_ret 字段只能包含有限数值，不能包含无穷大。"
            )
        cleaned_data["daily_ret"] = daily_returns.astype(float)

    if cleaned_data["date"].duplicated().any():
        raise WeeklyNavValidationError(
            "date 字段存在重复日期，请确保每个交易日期只出现一次。"
        )
    if len(cleaned_data) < 2:
        raise WeeklyNavValidationError("至少需要 2 条净值记录。")

    cleaned_data = cleaned_data.sort_values("date").reset_index(drop=True)
    cleaned_data["strategy_nav"] = (
        cleaned_data["nav_strat"] / cleaned_data["nav_strat"].iloc[0]
    )
    cleaned_data["strategy_return"] = cleaned_data["nav_strat"].pct_change(
        fill_method=None
    )

    diagnostics = (
        _diagnose_daily_returns(cleaned_data, tolerance)
        if "daily_ret" in cleaned_data.columns
        else None
    )
    return WeeklyNavAdapterResult(data=cleaned_data, diagnostics=diagnostics)


def _diagnose_daily_returns(
    data: pd.DataFrame,
    tolerance: float,
) -> DailyReturnDiagnostics:
    """比较 daily_ret 和净值推导收益，第一行不参与比较。"""
    comparison_mask = data.index.to_series().gt(0) & data["daily_ret"].notna()
    comparison_data = data.loc[
        comparison_mask, ["date", "daily_ret", "strategy_return"]
    ].copy()
    comparison_data = comparison_data.rename(
        columns={"strategy_return": "nav_derived_return"}
    )
    comparison_data["difference"] = (
        comparison_data["daily_ret"] - comparison_data["nav_derived_return"]
    )
    absolute_differences = comparison_data["difference"].abs()
    mismatch_mask = absolute_differences > tolerance
    mismatches = comparison_data.loc[mismatch_mask].reset_index(drop=True)

    return DailyReturnDiagnostics(
        comparison_count=len(comparison_data),
        mismatch_count=len(mismatches),
        max_absolute_difference=(
            float(absolute_differences.max()) if not comparison_data.empty else None
        ),
        mean_absolute_difference=(
            float(absolute_differences.mean()) if not comparison_data.empty else None
        ),
        mismatches=mismatches,
    )
