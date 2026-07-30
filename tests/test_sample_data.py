"""模拟数据生成函数的测试。"""

from src.sample_data import generate_sample_data


def test_sample_data_is_not_empty() -> None:
    """模拟数据不应为空。"""
    sample_data = generate_sample_data()

    assert not sample_data.empty


def test_sample_data_has_expected_columns() -> None:
    """模拟数据应包含日期、日收益和累计收益字段。"""
    sample_data = generate_sample_data()

    assert list(sample_data.columns) == [
        "date",
        "daily_return",
        "cumulative_return",
    ]


def test_sample_dates_are_sorted_ascending() -> None:
    """模拟日期应按升序排列。"""
    sample_data = generate_sample_data()

    assert sample_data["date"].is_monotonic_increasing


def test_cumulative_return_length_matches_data_length() -> None:
    """累计收益序列长度应与模拟数据长度一致。"""
    sample_data = generate_sample_data()

    assert len(sample_data["cumulative_return"]) == len(sample_data)
