"""标准化多实验比较的验证、对齐、指标和报告测试。"""

import re
from io import BytesIO, StringIO

import pandas as pd
import pytest

from src.comparison import (
    ComparisonValidationError,
    compare_standardized_datasets,
    extract_experiment_name,
    generate_aligned_nav_csv,
    generate_comparison_metrics_csv,
    load_and_compare_standardized_files,
    validate_standardized_data,
)
from src.reporting import (
    COMPARISON_DISCLAIMER,
    ComparisonReportContext,
    generate_comparison_markdown_report,
    generate_comparison_summary,
)
from src.sample_data import generate_comparison_sample_data


def _standardized_data(
    dates: list[str] | None = None,
    returns: list[float] | None = None,
) -> pd.DataFrame:
    dates = dates or ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"]
    returns = returns or [0.01, -0.005, 0.002]
    strategy_return = pd.Series([float("nan"), *returns], dtype=float)
    strategy_nav = (1 + strategy_return.fillna(0)).cumprod()
    drawdown = strategy_nav / strategy_nav.cummax() - 1
    return pd.DataFrame(
        {
            "date": dates,
            "strategy_return": strategy_return,
            "strategy_nav": strategy_nav,
            "drawdown": drawdown,
        }
    )


def _datasets(count: int = 2) -> list[tuple[str, pd.DataFrame]]:
    return [
        (f"experiment_{index}_standardized_data.csv", _standardized_data())
        for index in range(count)
    ]


def _report_context(result) -> ComparisonReportContext:
    return ComparisonReportContext(
        experiment_names=tuple(experiment.name for experiment in result.experiments),
        coverage_table=result.coverage_table,
        metrics_table=result.metrics_table,
        common_start_date=result.common_start_date,
        common_end_date=result.common_end_date,
        common_nav_observations=result.common_nav_observations,
        common_return_observations=result.common_return_observations,
    )


def test_two_valid_standardized_csv_files_can_be_compared() -> None:
    csv_one = _standardized_data().to_csv(index=False)
    csv_two = _standardized_data(returns=[0.005, 0.001, -0.002]).to_csv(index=False)

    result = load_and_compare_standardized_files(
        [
            ("one_standardized_data.csv", StringIO(csv_one)),
            ("two_standardized_data.csv", StringIO(csv_two)),
        ]
    )

    assert len(result.experiments) == 2


def test_six_valid_files_can_be_compared() -> None:
    assert len(compare_standardized_datasets(_datasets(6)).experiments) == 6


def test_fewer_than_two_files_fails() -> None:
    with pytest.raises(ComparisonValidationError, match="至少需要上传 2 份"):
        compare_standardized_datasets(_datasets(1))


def test_more_than_six_files_fails() -> None:
    with pytest.raises(ComparisonValidationError, match="最多支持 6 份"):
        compare_standardized_datasets(_datasets(7))


def test_missing_required_column_fails() -> None:
    data = _standardized_data().drop(columns="drawdown")

    with pytest.raises(ComparisonValidationError, match="缺少必需字段：drawdown"):
        validate_standardized_data(data, "missing.csv")


def test_empty_csv_fails_with_filename() -> None:
    with pytest.raises(ComparisonValidationError, match=r"empty\.csv.*文件为空"):
        load_and_compare_standardized_files(
            [
                ("empty.csv", StringIO("")),
                ("valid.csv", StringIO(_standardized_data().to_csv(index=False))),
            ]
        )


def test_missing_date_value_fails() -> None:
    data = _standardized_data()
    data.loc[1, "date"] = None

    with pytest.raises(ComparisonValidationError, match="date 存在缺失值"):
        validate_standardized_data(data, "missing_date.csv")


def test_invalid_date_fails() -> None:
    data = _standardized_data()
    data.loc[1, "date"] = "not-a-date"

    with pytest.raises(ComparisonValidationError, match="无法识别的日期"):
        validate_standardized_data(data, "invalid_date.csv")


def test_duplicate_date_fails() -> None:
    data = _standardized_data()
    data.loc[1, "date"] = data.loc[0, "date"]

    with pytest.raises(ComparisonValidationError, match="重复日期"):
        validate_standardized_data(data, "duplicate.csv")


def test_non_numeric_strategy_nav_fails() -> None:
    data = _standardized_data()
    data["strategy_nav"] = data["strategy_nav"].astype(object)
    data.loc[1, "strategy_nav"] = "abc"

    with pytest.raises(ComparisonValidationError, match="无法转换为数值"):
        validate_standardized_data(data, "bad_nav.csv")


@pytest.mark.parametrize("invalid_nav", [None, float("inf")])
def test_missing_or_infinite_strategy_nav_fails(invalid_nav: float | None) -> None:
    data = _standardized_data()
    data.loc[1, "strategy_nav"] = invalid_nav

    with pytest.raises(ComparisonValidationError, match="strategy_nav"):
        validate_standardized_data(data, "bad_nav.csv")


@pytest.mark.parametrize("invalid_nav", [0.0, -0.1])
def test_non_positive_strategy_nav_fails(invalid_nav: float) -> None:
    data = _standardized_data()
    data.loc[1, "strategy_nav"] = invalid_nav

    with pytest.raises(ComparisonValidationError, match="必须全部大于 0"):
        validate_standardized_data(data, "bad_nav.csv")


def test_first_strategy_nav_not_one_fails() -> None:
    data = _standardized_data()
    data["strategy_nav"] *= 2

    with pytest.raises(ComparisonValidationError, match="第一行必须约等于 1"):
        validate_standardized_data(data, "not_normalized.csv")


def test_first_strategy_return_can_be_empty() -> None:
    experiment = validate_standardized_data(_standardized_data(), "valid.csv")

    assert pd.isna(experiment.data["strategy_return"].iloc[0])


def test_later_strategy_return_missing_fails() -> None:
    data = _standardized_data()
    data.loc[2, "strategy_return"] = None

    with pytest.raises(ComparisonValidationError, match="第一行之后不能缺失"):
        validate_standardized_data(data, "missing_return.csv")


def test_strategy_return_at_or_below_minus_one_fails() -> None:
    data = _standardized_data()
    data.loc[1, "strategy_return"] = -1.0

    with pytest.raises(ComparisonValidationError, match="不能小于或等于 -1"):
        validate_standardized_data(data, "bad_return.csv")


def test_strategy_return_inconsistent_with_nav_fails() -> None:
    data = _standardized_data()
    data.loc[2, "strategy_return"] += 0.01

    with pytest.raises(ComparisonValidationError, match="推导收益不一致"):
        validate_standardized_data(data, "bad_return.csv")


def test_drawdown_inconsistent_with_nav_fails() -> None:
    data = _standardized_data()
    data.loc[2, "drawdown"] -= 0.01

    with pytest.raises(ComparisonValidationError, match="推导回撤不一致"):
        validate_standardized_data(data, "bad_drawdown.csv")


def test_unsupported_column_fails_without_guessing() -> None:
    data = _standardized_data()
    data["nav"] = data["strategy_nav"]

    with pytest.raises(ComparisonValidationError, match="包含不支持的字段：nav"):
        validate_standardized_data(data, "extra_column.csv")


def test_dates_are_sorted_ascending() -> None:
    data = _standardized_data().iloc[::-1].reset_index(drop=True)

    experiment = validate_standardized_data(data, "reversed.csv")

    assert experiment.data["date"].is_monotonic_increasing


def test_common_dates_are_calculated_correctly() -> None:
    first = _standardized_data(
        dates=["2026-01-01", "2026-01-02", "2026-01-05"],
        returns=[0.01, 0.02],
    )
    second = _standardized_data(
        dates=["2026-01-02", "2026-01-05", "2026-01-06"],
        returns=[-0.01, 0.01],
    )

    result = compare_standardized_datasets([("first.csv", first), ("second.csv", second)])

    assert result.common_dates.tolist() == pd.to_datetime(["2026-01-02", "2026-01-05"]).tolist()


def test_common_dates_use_set_intersection_not_calendar_range() -> None:
    first = _standardized_data(
        dates=["2026-01-01", "2026-01-02", "2026-01-05"],
        returns=[0.01, 0.02],
    )
    second = _standardized_data(
        dates=["2026-01-01", "2026-01-03", "2026-01-05"],
        returns=[-0.01, 0.01],
    )

    result = compare_standardized_datasets([("first.csv", first), ("second.csv", second)])

    assert result.common_dates.tolist() == pd.to_datetime(["2026-01-01", "2026-01-05"]).tolist()


def test_missing_dates_are_not_filled() -> None:
    result = compare_standardized_datasets(
        [
            (
                "first.csv",
                _standardized_data(
                    dates=["2026-01-01", "2026-01-02", "2026-01-05"],
                    returns=[0.01, 0.02],
                ),
            ),
            (
                "second.csv",
                _standardized_data(
                    dates=["2026-01-01", "2026-01-03", "2026-01-05"],
                    returns=[-0.01, 0.01],
                ),
            ),
        ]
    )

    assert len(result.common_dates) == 2


def test_fewer_than_two_common_observation_days_fails() -> None:
    first = _standardized_data(dates=["2026-01-01", "2026-01-02"], returns=[0.01])
    second = _standardized_data(dates=["2026-01-02", "2026-01-03"], returns=[0.01])

    with pytest.raises(ComparisonValidationError, match="共同净值观察日少于 2"):
        compare_standardized_datasets([("first.csv", first), ("second.csv", second)])


def test_all_aligned_nav_series_start_at_one() -> None:
    result = compare_standardized_datasets(_datasets())

    assert all(
        aligned["comparison_nav"].iloc[0] == pytest.approx(1.0)
        for aligned in result.aligned_experiments.values()
    )


def test_first_common_return_is_empty() -> None:
    result = compare_standardized_datasets(_datasets())

    assert all(
        pd.isna(aligned["comparison_return"].iloc[0])
        for aligned in result.aligned_experiments.values()
    )


def test_common_return_comes_from_common_nav_percentage_change() -> None:
    result = compare_standardized_datasets(_datasets())

    for aligned in result.aligned_experiments.values():
        expected = aligned["comparison_nav"].pct_change(fill_method=None)
        expected.name = "comparison_return"
        pd.testing.assert_series_equal(aligned["comparison_return"], expected)


def test_metrics_are_recalculated_for_common_period() -> None:
    result = compare_standardized_datasets(_datasets())

    for row in result.metrics_table.itertuples(index=False):
        final_nav = result.aligned_experiments[row.experiment_name]["comparison_nav"].iloc[-1]
        assert row.cumulative_return == pytest.approx(final_nav - 1)


def test_original_dataframes_are_not_modified() -> None:
    datasets = _datasets()
    originals = [data.copy(deep=True) for _, data in datasets]

    compare_standardized_datasets(datasets)

    for (_, data), original in zip(datasets, originals, strict=True):
        pd.testing.assert_frame_equal(data, original)


def test_duplicate_experiment_names_fail() -> None:
    with pytest.raises(ComparisonValidationError, match="存在重复实验名称"):
        compare_standardized_datasets(
            [
                ("same_standardized_data.csv", _standardized_data()),
                ("same.csv", _standardized_data()),
            ]
        )


def test_filename_removes_standardized_data_suffix() -> None:
    assert (
        extract_experiment_name("phase3_B5_ridge_F3_standardized_data.csv") == "phase3_B5_ridge_F3"
    )


def test_experiment_name_is_sanitized_and_limited() -> None:
    name = extract_experiment_name(f" {'a' * 120}:bad_standardized_data.csv")

    assert len(name) == 100
    assert ":" not in name


def test_metrics_table_contains_expected_columns() -> None:
    result = compare_standardized_datasets(_datasets())

    assert list(result.metrics_table.columns) == [
        "experiment_name",
        "common_start_date",
        "common_end_date",
        "nav_observation_count",
        "effective_return_count",
        "cumulative_return",
        "annualized_return",
        "annualized_volatility",
        "sharpe_ratio",
        "max_drawdown",
        "positive_day_ratio",
    ]


def test_aligned_nav_wide_table_contains_all_experiments() -> None:
    result = compare_standardized_datasets(_datasets())

    assert list(result.aligned_nav_table.columns) == [
        "date",
        "experiment_0",
        "experiment_1",
    ]


def test_summary_without_valid_sharpe_has_no_nan_or_inf() -> None:
    flat = _standardized_data(returns=[0.0, 0.0, 0.0])
    result = compare_standardized_datasets(
        [("flat_a.csv", flat), ("flat_b.csv", flat.copy(deep=True))]
    )

    summary = generate_comparison_summary(_report_context(result)).lower()

    assert "nan" not in summary
    assert "inf" not in summary


def test_tied_results_list_all_tied_experiments() -> None:
    data = _standardized_data()
    result = compare_standardized_datasets(
        [("tie_a.csv", data), ("tie_b.csv", data.copy(deep=True))]
    )

    summary = generate_comparison_summary(_report_context(result))

    assert "tie_a、tie_b" in summary


def test_comparison_summary_does_not_call_any_strategy_best() -> None:
    result = compare_standardized_datasets(_datasets())

    assert "最佳策略" not in generate_comparison_summary(_report_context(result))


def test_comparison_report_contains_fixed_disclaimer() -> None:
    result = compare_standardized_datasets(_datasets())

    report = generate_comparison_markdown_report(_report_context(result))

    assert COMPARISON_DISCLAIMER in report


def test_comparison_report_section_numbering_is_continuous() -> None:
    result = compare_standardized_datasets(_datasets())
    report = generate_comparison_markdown_report(_report_context(result))
    numbers = [int(number) for number in re.findall(r"^### (\d+)\.", report, flags=re.MULTILINE)]

    assert numbers == list(range(1, len(numbers) + 1))


def test_metrics_csv_uses_raw_numbers_not_percent_strings() -> None:
    result = compare_standardized_datasets(_datasets())

    exported = pd.read_csv(BytesIO(generate_comparison_metrics_csv(result)))

    assert pd.api.types.is_numeric_dtype(exported["cumulative_return"])
    assert not exported["cumulative_return"].astype(str).str.contains("%").any()


def test_aligned_nav_csv_contains_date_and_all_experiments() -> None:
    result = compare_standardized_datasets(_datasets())

    exported = pd.read_csv(BytesIO(generate_aligned_nav_csv(result)))

    assert list(exported.columns) == ["date", "experiment_0", "experiment_1"]


def test_validation_error_contains_filename() -> None:
    data = _standardized_data().drop(columns="drawdown")

    with pytest.raises(ComparisonValidationError, match=r"named_file\.csv"):
        validate_standardized_data(data, "named_file.csv")


def test_comparison_sample_data_is_fixed_and_has_long_common_period() -> None:
    first_result = compare_standardized_datasets(generate_comparison_sample_data())
    second_result = compare_standardized_datasets(generate_comparison_sample_data())

    assert first_result.common_nav_observations >= 120
    assert first_result.metrics_table["cumulative_return"].nunique() == 3
    assert (first_result.metrics_table["max_drawdown"] < 0).all()
    pd.testing.assert_frame_equal(
        first_result.aligned_nav_table,
        second_result.aligned_nav_table,
    )
