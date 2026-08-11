"""验证并比较多份标准化分析数据 CSV。"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce
from math import isclose, isfinite
from pathlib import Path
from typing import IO

import pandas as pd

from src.config import (
    COMPARISON_FILE_MAX_MB,
    MAX_COMPARISON_FILES,
    MAX_ROWS_PER_FILE,
)
from src.limits import validate_file_size, validate_row_count
from src.performance import (
    add_nav_performance_series,
    calculate_nav_performance_metrics,
)

MIN_EXPERIMENTS = 2
MAX_EXPERIMENTS = MAX_COMPARISON_FILES
COMPARISON_TOLERANCE = 1e-8
REQUIRED_COLUMNS = ("date", "strategy_return", "strategy_nav", "drawdown")
OPTIONAL_COLUMNS = ("benchmark_return", "benchmark_nav")
ALLOWED_COLUMNS = set(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
CsvSource = str | Path | IO[str] | IO[bytes]


class ComparisonValidationError(ValueError):
    """表示用户可通过修改标准化 CSV 解决的比较数据问题。"""


@dataclass(frozen=True)
class StandardizedExperiment:
    """一份通过验证的标准化实验数据。"""

    name: str
    filename: str
    data: pd.DataFrame
    original_start_date: pd.Timestamp
    original_end_date: pd.Timestamp
    original_nav_observations: int


@dataclass(frozen=True)
class ComparisonResult:
    """多实验共同日期对齐后的数据和指标。"""

    experiments: tuple[StandardizedExperiment, ...]
    common_dates: pd.DatetimeIndex
    common_start_date: pd.Timestamp
    common_end_date: pd.Timestamp
    common_nav_observations: int
    common_return_observations: int
    coverage_table: pd.DataFrame
    metrics_table: pd.DataFrame
    aligned_experiments: dict[str, pd.DataFrame]
    aligned_nav_table: pd.DataFrame


def extract_experiment_name(filename: str) -> str:
    """从标准化 CSV 文件名生成最多 100 字符的安全实验名称。"""
    stem = Path(filename).stem.strip()
    stem = re.sub(r"_standardized_data$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r'[\\/:*?"<>|]', "", stem).strip()
    return (stem or "未命名实验")[:100]


def load_and_compare_standardized_files(
    files: Sequence[tuple[str, CsvSource]],
) -> ComparisonResult:
    """读取多份命名 CSV，并在全部合法后执行比较。"""
    _validate_file_count(len(files))
    for filename, source in files:
        validate_file_size(source, filename, COMPARISON_FILE_MAX_MB)

    datasets: list[tuple[str, pd.DataFrame]] = []
    for filename, source in files:
        try:
            if hasattr(source, "seek"):
                source.seek(0)
            raw_data = pd.read_csv(source)
        except pd.errors.EmptyDataError as exc:
            raise ComparisonValidationError(f"{filename}：CSV 文件为空，请提供有效数据。") from exc
        except UnicodeDecodeError as exc:
            raise ComparisonValidationError(
                f"{filename}：文件编码无法读取，请使用 UTF-8 编码。"
            ) from exc
        except pd.errors.ParserError as exc:
            raise ComparisonValidationError(
                f"{filename}：CSV 格式无法解析，请检查分隔符和字段数量。"
            ) from exc
        except (OSError, ValueError) as exc:
            raise ComparisonValidationError(
                f"{filename}：文件读取失败，请确认文件有效且未损坏。"
            ) from exc
        validate_row_count(raw_data, filename, MAX_ROWS_PER_FILE)
        datasets.append((filename, raw_data))
    return compare_standardized_datasets(datasets)


def compare_standardized_datasets(
    datasets: Sequence[tuple[str, pd.DataFrame]],
) -> ComparisonResult:
    """验证多份 DataFrame，并按所有实验共有交易日期重新计算绩效。"""
    _validate_file_count(len(datasets))
    experiments = tuple(
        validate_standardized_data(raw_data, filename) for filename, raw_data in datasets
    )
    experiment_names = [experiment.name for experiment in experiments]
    if len(set(experiment_names)) != len(experiment_names):
        raise ComparisonValidationError("存在重复实验名称，请修改文件名后重新上传。")

    common_dates = reduce(
        lambda left, right: left.intersection(right),
        (pd.DatetimeIndex(experiment.data["date"]) for experiment in experiments),
    ).sort_values()
    if len(common_dates) < 2:
        raise ComparisonValidationError("所有实验的共同净值观察日少于 2 天，无法进行比较。")

    common_start = pd.Timestamp(common_dates[0])
    common_end = pd.Timestamp(common_dates[-1])
    aligned_experiments: dict[str, pd.DataFrame] = {}
    metric_rows: list[dict[str, object]] = []
    aligned_nav_table = pd.DataFrame({"date": common_dates})

    for experiment in experiments:
        indexed_data = experiment.data.set_index("date")
        common_data = indexed_data.loc[common_dates].reset_index()
        comparison_nav = common_data["strategy_nav"] / common_data["strategy_nav"].iloc[0]
        comparison_return = comparison_nav.pct_change(fill_method=None)
        performance_input = pd.DataFrame(
            {
                "date": common_data["date"],
                "strategy_nav": comparison_nav,
                "strategy_return": comparison_return,
            }
        )
        performance_data = add_nav_performance_series(performance_input)
        metrics = calculate_nav_performance_metrics(performance_input)
        aligned_data = pd.DataFrame(
            {
                "date": performance_data["date"],
                "comparison_nav": performance_data["strategy_nav"],
                "comparison_return": performance_data["strategy_return"],
                "comparison_drawdown": performance_data["drawdown"],
            }
        )
        aligned_experiments[experiment.name] = aligned_data
        aligned_nav_table[experiment.name] = aligned_data["comparison_nav"]
        metric_rows.append(
            {
                "experiment_name": experiment.name,
                "common_start_date": common_start,
                "common_end_date": common_end,
                "nav_observation_count": int(metrics["nav_observations"]),
                "effective_return_count": int(metrics["n_days"]),
                "cumulative_return": metrics["cumulative_return"],
                "annualized_return": metrics["annualized_return"],
                "annualized_volatility": metrics["annualized_volatility"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "max_drawdown": metrics["max_drawdown"],
                "positive_day_ratio": metrics["positive_day_ratio"],
            }
        )

    coverage_table = pd.DataFrame(
        [
            {
                "experiment_name": experiment.name,
                "original_start_date": experiment.original_start_date,
                "original_end_date": experiment.original_end_date,
                "original_nav_observation_count": (experiment.original_nav_observations),
            }
            for experiment in experiments
        ]
    )
    return ComparisonResult(
        experiments=experiments,
        common_dates=common_dates,
        common_start_date=common_start,
        common_end_date=common_end,
        common_nav_observations=len(common_dates),
        common_return_observations=len(common_dates) - 1,
        coverage_table=coverage_table,
        metrics_table=pd.DataFrame(metric_rows),
        aligned_experiments=aligned_experiments,
        aligned_nav_table=aligned_nav_table,
    )


def validate_standardized_data(
    raw_data: pd.DataFrame,
    filename: str,
    tolerance: float = COMPARISON_TOLERANCE,
) -> StandardizedExperiment:
    """严格验证单份标准化数据，不修改传入 DataFrame。"""
    error_prefix = f"{filename}："
    validate_row_count(raw_data, filename, MAX_ROWS_PER_FILE)
    if raw_data.empty:
        raise ComparisonValidationError(f"{error_prefix}CSV 文件没有数据记录。")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in raw_data.columns]
    if missing_columns:
        raise ComparisonValidationError(
            f"{error_prefix}缺少必需字段：{'、'.join(missing_columns)}。"
        )
    unsupported_columns = [
        str(column) for column in raw_data.columns if column not in ALLOWED_COLUMNS
    ]
    if unsupported_columns:
        raise ComparisonValidationError(
            f"{error_prefix}包含不支持的字段：{'、'.join(unsupported_columns)}。"
        )

    cleaned_data = raw_data.copy(deep=True)
    date_missing = cleaned_data["date"].isna() | (
        cleaned_data["date"].astype("string").str.strip() == ""
    )
    if date_missing.any():
        raise ComparisonValidationError(f"{error_prefix}date 存在缺失值。")
    parsed_dates = pd.to_datetime(cleaned_data["date"], errors="coerce", format="mixed")
    if parsed_dates.isna().any():
        raise ComparisonValidationError(f"{error_prefix}date 包含无法识别的日期。")
    cleaned_data["date"] = parsed_dates
    if cleaned_data["date"].duplicated().any():
        raise ComparisonValidationError(f"{error_prefix}date 存在重复日期。")
    cleaned_data = cleaned_data.sort_values("date").reset_index(drop=True)

    nav_missing = cleaned_data["strategy_nav"].isna() | (
        cleaned_data["strategy_nav"].astype("string").str.strip() == ""
    )
    if nav_missing.any():
        raise ComparisonValidationError(f"{error_prefix}strategy_nav 存在缺失值。")
    strategy_nav = pd.to_numeric(cleaned_data["strategy_nav"], errors="coerce")
    if strategy_nav.isna().any():
        raise ComparisonValidationError(f"{error_prefix}strategy_nav 包含无法转换为数值的内容。")
    if not all(isfinite(value) for value in strategy_nav):
        raise ComparisonValidationError(f"{error_prefix}strategy_nav 不能包含 NaN 或无穷大。")
    if (strategy_nav <= 0).any():
        raise ComparisonValidationError(f"{error_prefix}strategy_nav 必须全部大于 0。")
    if len(cleaned_data) < 2:
        raise ComparisonValidationError(f"{error_prefix}至少需要 2 个净值观察日。")
    if not isclose(float(strategy_nav.iloc[0]), 1.0, abs_tol=tolerance, rel_tol=0):
        raise ComparisonValidationError(f"{error_prefix}strategy_nav 第一行必须约等于 1。")
    cleaned_data["strategy_nav"] = strategy_nav.astype(float)

    raw_returns = cleaned_data["strategy_return"]
    return_missing = raw_returns.isna() | (raw_returns.astype("string").str.strip() == "")
    strategy_return = pd.to_numeric(raw_returns, errors="coerce")
    invalid_return = ~return_missing & strategy_return.isna()
    if invalid_return.any():
        raise ComparisonValidationError(f"{error_prefix}strategy_return 包含无法转换为数值的内容。")
    if return_missing.iloc[1:].any():
        raise ComparisonValidationError(f"{error_prefix}strategy_return 第一行之后不能缺失。")
    finite_returns = strategy_return.dropna()
    if not all(isfinite(value) for value in finite_returns):
        raise ComparisonValidationError(f"{error_prefix}strategy_return 不能包含无穷大。")
    if (finite_returns <= -1).any():
        raise ComparisonValidationError(f"{error_prefix}strategy_return 不能小于或等于 -1。")
    expected_returns = cleaned_data["strategy_nav"].pct_change(fill_method=None)
    return_differences = (strategy_return.iloc[1:] - expected_returns.iloc[1:]).abs()
    if (return_differences > tolerance).any():
        raise ComparisonValidationError(
            f"{error_prefix}strategy_return 与 strategy_nav 推导收益不一致。"
        )
    cleaned_data["strategy_return"] = strategy_return.astype(float)

    drawdown_missing = cleaned_data["drawdown"].isna() | (
        cleaned_data["drawdown"].astype("string").str.strip() == ""
    )
    if drawdown_missing.any():
        raise ComparisonValidationError(f"{error_prefix}drawdown 存在缺失值。")
    drawdown = pd.to_numeric(cleaned_data["drawdown"], errors="coerce")
    if drawdown.isna().any() or not all(isfinite(value) for value in drawdown):
        raise ComparisonValidationError(f"{error_prefix}drawdown 必须为有效有限数值。")
    expected_drawdown = cleaned_data["strategy_nav"] / cleaned_data["strategy_nav"].cummax() - 1
    if ((drawdown - expected_drawdown).abs() > tolerance).any():
        raise ComparisonValidationError(f"{error_prefix}drawdown 与 strategy_nav 推导回撤不一致。")
    cleaned_data["drawdown"] = drawdown.astype(float)

    return StandardizedExperiment(
        name=extract_experiment_name(filename),
        filename=filename,
        data=cleaned_data,
        original_start_date=pd.Timestamp(cleaned_data["date"].iloc[0]),
        original_end_date=pd.Timestamp(cleaned_data["date"].iloc[-1]),
        original_nav_observations=len(cleaned_data),
    )


def generate_comparison_metrics_csv(result: ComparisonResult) -> bytes:
    """在内存中导出保留原始数值的比较指标 CSV。"""
    export_data = result.metrics_table.copy(deep=True)
    for column in ("common_start_date", "common_end_date"):
        export_data[column] = pd.to_datetime(export_data[column]).dt.strftime("%Y-%m-%d")
    return export_data.to_csv(index=False).encode("utf-8-sig")


def generate_aligned_nav_csv(result: ComparisonResult) -> bytes:
    """在内存中导出共同日期对齐的净值宽表 CSV。"""
    export_data = result.aligned_nav_table.copy(deep=True)
    export_data["date"] = pd.to_datetime(export_data["date"]).dt.strftime("%Y-%m-%d")
    return export_data.to_csv(index=False).encode("utf-8-sig")


def _validate_file_count(file_count: int) -> None:
    if file_count < MIN_EXPERIMENTS:
        raise ComparisonValidationError("多实验比较至少需要上传 2 份标准化 CSV。")
    if file_count > MAX_EXPERIMENTS:
        raise ComparisonValidationError(f"当前版本最多支持 {MAX_EXPERIMENTS} 份标准化 CSV。")
