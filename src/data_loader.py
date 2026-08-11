"""读取并验证标准日频策略收益 CSV。"""

from math import isfinite
from pathlib import Path
from typing import IO

import pandas as pd

from src.config import MAX_ROWS_PER_FILE, SINGLE_FILE_MAX_MB
from src.limits import get_source_filename, validate_file_size, validate_row_count

REQUIRED_COLUMNS = ("date", "strategy_return")
OPTIONAL_COLUMNS = ("benchmark_return",)
ALLOWED_COLUMNS = set(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
CsvSource = str | Path | IO[str] | IO[bytes]


class DataValidationError(ValueError):
    """表示用户可以通过修改 CSV 内容解决的数据问题。"""


def load_returns_csv(source: CsvSource) -> pd.DataFrame:
    """读取 CSV，并返回通过标准协议验证且按日期升序排列的数据。"""
    filename = get_source_filename(source)
    validate_file_size(source, filename, SINGLE_FILE_MAX_MB)
    try:
        if hasattr(source, "seek"):
            source.seek(0)
        raw_data = pd.read_csv(source)
    except pd.errors.EmptyDataError as exc:
        raise DataValidationError("CSV 文件为空，请提供包含表头和数据的文件。") from exc
    except UnicodeDecodeError as exc:
        raise DataValidationError("CSV 文件编码无法读取，请将文件保存为 UTF-8 编码。") from exc
    except pd.errors.ParserError as exc:
        raise DataValidationError("CSV 文件格式无法解析，请检查分隔符和每行字段数量。") from exc
    except (OSError, ValueError) as exc:
        raise DataValidationError("CSV 文件读取失败，请确认文件有效且未损坏。") from exc

    validate_row_count(raw_data, filename, MAX_ROWS_PER_FILE)
    return validate_returns_data(raw_data)


def validate_returns_data(raw_data: pd.DataFrame) -> pd.DataFrame:
    """严格验证字段和数据，不猜测字段，也不静默删除记录。"""
    if raw_data.empty:
        raise DataValidationError("CSV 文件没有数据记录，请至少提供 2 条有效记录。")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in raw_data.columns]
    if missing_columns:
        missing_text = "、".join(missing_columns)
        raise DataValidationError(f"CSV 缺少必需字段：{missing_text}。")

    unsupported_columns = [
        str(column) for column in raw_data.columns if column not in ALLOWED_COLUMNS
    ]
    if unsupported_columns:
        unsupported_text = "、".join(unsupported_columns)
        raise DataValidationError(
            f"CSV 包含当前阶段不支持的字段：{unsupported_text}。"
            "仅支持 date、strategy_return 和可选的 benchmark_return。"
        )

    cleaned_data = raw_data.copy()
    for column in REQUIRED_COLUMNS:
        missing_mask = cleaned_data[column].isna() | (
            cleaned_data[column].astype("string").str.strip() == ""
        )
        if missing_mask.any():
            raise DataValidationError(f"必需字段 {column} 存在缺失值，请补充后重试。")

    parsed_dates = pd.to_datetime(cleaned_data["date"], errors="coerce", format="mixed")
    if parsed_dates.isna().any():
        raise DataValidationError("date 字段包含无法识别的日期，请使用有效日期格式。")
    cleaned_data["date"] = parsed_dates

    strategy_returns = pd.to_numeric(cleaned_data["strategy_return"], errors="coerce")
    if strategy_returns.isna().any():
        raise DataValidationError("strategy_return 字段包含无法转换为数值的内容。")
    if not all(isfinite(value) for value in strategy_returns.to_numpy(dtype=float)):
        raise DataValidationError("strategy_return 字段只能包含有限数值，不能包含无穷大。")
    if (strategy_returns <= -1).any():
        raise DataValidationError("strategy_return 不能小于或等于 -1。")
    cleaned_data["strategy_return"] = strategy_returns.astype(float)

    if "benchmark_return" in cleaned_data.columns:
        benchmark_values = cleaned_data["benchmark_return"]
        benchmark_missing = benchmark_values.isna() | (
            benchmark_values.astype("string").str.strip() == ""
        )
        benchmark_returns = pd.to_numeric(benchmark_values, errors="coerce")
        invalid_benchmark = ~benchmark_missing & benchmark_returns.isna()
        if invalid_benchmark.any():
            raise DataValidationError("benchmark_return 字段包含无法转换为数值的内容。")
        finite_benchmark = benchmark_returns.dropna().to_numpy(dtype=float)
        if not all(isfinite(value) for value in finite_benchmark):
            raise DataValidationError("benchmark_return 字段只能包含有限数值，不能包含无穷大。")
        cleaned_data["benchmark_return"] = benchmark_returns.astype(float)

    if cleaned_data["date"].duplicated().any():
        raise DataValidationError("date 字段存在重复日期，请确保每个交易日期只出现一次。")

    if len(cleaned_data) < 2:
        raise DataValidationError("清洗后至少需要保留 2 条有效记录。")

    return cleaned_data.sort_values("date").reset_index(drop=True)
