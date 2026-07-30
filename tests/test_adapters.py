"""每周调仓净值 CSV 适配器测试。"""

from io import StringIO

import pandas as pd
import pytest

from src.adapters import (
    WeeklyNavValidationError,
    adapt_weekly_nav_data,
    load_weekly_nav_csv,
)
from src.performance import calculate_nav_performance_metrics


def test_valid_date_and_nav_can_be_processed() -> None:
    result = load_weekly_nav_csv(
        StringIO("date,nav_strat\n2026-01-01,1.0\n2026-01-02,1.1\n")
    )

    assert len(result.data) == 2
    assert result.diagnostics is None


def test_data_with_daily_return_can_be_processed() -> None:
    result = load_weekly_nav_csv(
        StringIO(
            "date,nav_strat,daily_ret\n"
            "2026-01-01,1.0,0.0\n2026-01-02,1.1,0.1\n"
        )
    )

    assert "daily_ret" in result.data.columns
    assert result.diagnostics is not None


def test_missing_date_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="缺少必需字段：date"):
        load_weekly_nav_csv(StringIO("nav_strat\n1.0\n1.1\n"))


def test_missing_nav_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="缺少必需字段：nav_strat"):
        load_weekly_nav_csv(StringIO("date\n2026-01-01\n2026-01-02\n"))


def test_invalid_date_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="无法识别的日期"):
        load_weekly_nav_csv(
            StringIO("date,nav_strat\nnot-a-date,1.0\n2026-01-02,1.1\n")
        )


def test_non_numeric_nav_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="nav_strat.*无法转换"):
        load_weekly_nav_csv(
            StringIO("date,nav_strat\n2026-01-01,abc\n2026-01-02,1.1\n")
        )


def test_zero_nav_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="必须全部大于 0"):
        load_weekly_nav_csv(
            StringIO("date,nav_strat\n2026-01-01,1.0\n2026-01-02,0\n")
        )


def test_negative_nav_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="必须全部大于 0"):
        load_weekly_nav_csv(
            StringIO("date,nav_strat\n2026-01-01,1.0\n2026-01-02,-0.5\n")
        )


def test_missing_nav_value_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="nav_strat 存在缺失值"):
        load_weekly_nav_csv(
            StringIO("date,nav_strat\n2026-01-01,1.0\n2026-01-02,\n")
        )


def test_duplicate_date_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="重复日期"):
        load_weekly_nav_csv(
            StringIO("date,nav_strat\n2026-01-01,1.0\n2026-01-01,1.1\n")
        )


def test_dates_are_sorted_ascending() -> None:
    result = load_weekly_nav_csv(
        StringIO("date,nav_strat\n2026-01-03,1.1\n2026-01-01,1.0\n")
    )

    assert result.data["date"].is_monotonic_increasing


def test_initial_nav_not_one_is_normalized_correctly() -> None:
    result = load_weekly_nav_csv(
        StringIO("date,nav_strat\n2026-01-01,2.0\n2026-01-02,2.2\n")
    )

    assert result.data["strategy_nav"].tolist() == pytest.approx([1.0, 1.1])


def test_first_strategy_nav_equals_one() -> None:
    result = load_weekly_nav_csv(
        StringIO("date,nav_strat\n2026-01-01,3.0\n2026-01-02,3.3\n")
    )

    assert result.data["strategy_nav"].iloc[0] == pytest.approx(1.0)


def test_strategy_return_equals_nav_percentage_change() -> None:
    result = load_weekly_nav_csv(
        StringIO(
            "date,nav_strat\n"
            "2026-01-01,2.0\n2026-01-02,2.2\n2026-01-03,2.09\n"
        )
    )

    expected = result.data["nav_strat"].pct_change(fill_method=None)
    expected.name = "strategy_return"
    pd.testing.assert_series_equal(result.data["strategy_return"], expected)


def test_first_row_is_not_counted_as_valid_return_day() -> None:
    result = load_weekly_nav_csv(
        StringIO(
            "date,nav_strat\n"
            "2026-01-01,1.0\n2026-01-02,1.1\n2026-01-03,1.2\n"
        )
    )
    metrics = calculate_nav_performance_metrics(result.data)

    assert pd.isna(result.data["strategy_return"].iloc[0])
    assert metrics["nav_observations"] == 3
    assert metrics["n_days"] == 2


def test_consistent_daily_return_has_no_mismatch() -> None:
    result = load_weekly_nav_csv(
        StringIO(
            "date,nav_strat,daily_ret\n"
            "2026-01-01,2.0,0.3\n"
            "2026-01-02,2.2,0.1\n"
            "2026-01-03,2.09,-0.05\n"
        )
    )

    assert result.diagnostics is not None
    assert result.diagnostics.comparison_count == 2
    assert result.diagnostics.mismatch_count == 0


def test_inconsistent_daily_return_is_counted() -> None:
    result = load_weekly_nav_csv(
        StringIO(
            "date,nav_strat,daily_ret\n"
            "2026-01-01,2.0,0.0\n"
            "2026-01-02,2.2,0.09\n"
            "2026-01-03,2.09,-0.04\n"
        )
    )

    assert result.diagnostics is not None
    assert result.diagnostics.comparison_count == 2
    assert result.diagnostics.mismatch_count == 2
    assert result.diagnostics.max_absolute_difference == pytest.approx(0.01)
    assert result.diagnostics.mean_absolute_difference == pytest.approx(0.01)


def test_mismatch_does_not_fail_entire_load() -> None:
    result = load_weekly_nav_csv(
        StringIO(
            "date,nav_strat,daily_ret\n"
            "2026-01-01,1.0,0.0\n2026-01-02,1.1,0.2\n"
        )
    )

    assert len(result.data) == 2
    assert result.diagnostics is not None
    assert result.diagnostics.mismatch_count == 1


def test_original_nav_data_is_not_modified() -> None:
    raw_data = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02"],
            "nav_strat": [2.0, 2.2],
        }
    )
    original = raw_data.copy(deep=True)

    adapt_weekly_nav_data(raw_data)

    pd.testing.assert_frame_equal(raw_data, original)


def test_performance_cumulative_return_matches_final_normalized_nav() -> None:
    result = load_weekly_nav_csv(
        StringIO(
            "date,nav_strat\n"
            "2026-01-01,2.0\n2026-01-02,2.2\n2026-01-03,2.4\n"
        )
    )
    metrics = calculate_nav_performance_metrics(result.data)

    assert metrics["cumulative_return"] == pytest.approx(
        result.data["strategy_nav"].iloc[-1] - 1
    )


def test_non_numeric_daily_return_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="daily_ret.*无法转换"):
        load_weekly_nav_csv(
            StringIO(
                "date,nav_strat,daily_ret\n"
                "2026-01-01,1.0,abc\n2026-01-02,1.1,0.1\n"
            )
        )


def test_one_nav_record_fails() -> None:
    with pytest.raises(WeeklyNavValidationError, match="至少需要 2 条"):
        load_weekly_nav_csv(StringIO("date,nav_strat\n2026-01-01,1.0\n"))
