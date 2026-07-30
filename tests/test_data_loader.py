"""标准日频收益 CSV 读取与验证测试。"""

from io import StringIO

import pandas as pd
import pytest

from src.data_loader import DataValidationError, load_returns_csv


def test_valid_csv_can_be_loaded() -> None:
    data = load_returns_csv(
        StringIO("date,strategy_return,benchmark_return\n2026-01-01,0.01,0.005\n2026-01-02,-0.02,-0.01\n")
    )

    assert len(data) == 2
    assert pd.api.types.is_datetime64_any_dtype(data["date"])


def test_missing_date_fails() -> None:
    with pytest.raises(DataValidationError, match="缺少必需字段：date"):
        load_returns_csv(StringIO("strategy_return\n0.01\n0.02\n"))


def test_missing_strategy_return_fails() -> None:
    with pytest.raises(DataValidationError, match="缺少必需字段：strategy_return"):
        load_returns_csv(StringIO("date\n2026-01-01\n2026-01-02\n"))


def test_invalid_date_fails() -> None:
    with pytest.raises(DataValidationError, match="无法识别的日期"):
        load_returns_csv(
            StringIO("date,strategy_return\nnot-a-date,0.01\n2026-01-02,0.02\n")
        )


def test_non_numeric_strategy_return_fails() -> None:
    with pytest.raises(DataValidationError, match="strategy_return.*无法转换"):
        load_returns_csv(
            StringIO("date,strategy_return\n2026-01-01,abc\n2026-01-02,0.02\n")
        )


def test_non_numeric_benchmark_return_fails() -> None:
    with pytest.raises(DataValidationError, match="benchmark_return.*无法转换"):
        load_returns_csv(
            StringIO(
                "date,strategy_return,benchmark_return\n"
                "2026-01-01,0.01,abc\n2026-01-02,0.02,0.01\n"
            )
        )


def test_duplicate_date_fails() -> None:
    with pytest.raises(DataValidationError, match="重复日期"):
        load_returns_csv(
            StringIO("date,strategy_return\n2026-01-01,0.01\n2026-01-01,0.02\n")
        )


@pytest.mark.parametrize("invalid_return", [-1, -1.2])
def test_return_less_than_or_equal_to_negative_one_fails(
    invalid_return: float,
) -> None:
    with pytest.raises(DataValidationError, match="不能小于或等于 -1"):
        load_returns_csv(
            StringIO(
                f"date,strategy_return\n2026-01-01,{invalid_return}\n"
                "2026-01-02,0.02\n"
            )
        )


def test_csv_without_benchmark_can_be_loaded() -> None:
    data = load_returns_csv(
        StringIO("date,strategy_return\n2026-01-01,0.01\n2026-01-02,0.02\n")
    )

    assert list(data.columns) == ["date", "strategy_return"]


def test_dates_are_sorted_ascending() -> None:
    data = load_returns_csv(
        StringIO("date,strategy_return\n2026-01-03,0.01\n2026-01-01,0.02\n")
    )

    assert data["date"].is_monotonic_increasing


def test_missing_required_value_fails() -> None:
    with pytest.raises(DataValidationError, match="strategy_return 存在缺失值"):
        load_returns_csv(
            StringIO("date,strategy_return\n2026-01-01,\n2026-01-02,0.02\n")
        )


def test_empty_csv_fails() -> None:
    with pytest.raises(DataValidationError, match="CSV 文件为空"):
        load_returns_csv(StringIO(""))


def test_one_record_fails() -> None:
    with pytest.raises(DataValidationError, match="至少需要保留 2 条"):
        load_returns_csv(StringIO("date,strategy_return\n2026-01-01,0.01\n"))
