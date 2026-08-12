"""确定性字段候选识别测试。"""

from __future__ import annotations

import math

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import src.field_detection as field_detection_module
from src.field_detection import (
    MAX_CROSS_FIELD_CHECKS,
    MAX_PROFILE_SAMPLE_SIZE,
    MIN_RECOMMENDATION_SCORE,
    ROLE_ORDER,
    detect_field_candidates,
    normalize_field_name,
)


def _dates(count: int = 8) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", periods=count, freq="D")


def _returns(count: int = 8) -> pd.Series:
    values = [0.01, -0.02, 0.015, 0.0, -0.005, 0.012, -0.008, 0.006]
    return pd.Series((values * math.ceil(count / len(values)))[:count], dtype=float)


def _nav(returns: pd.Series) -> pd.Series:
    return (1 + returns).cumprod()


def _recommended(dataframe: pd.DataFrame, role: str):
    return detect_field_candidates(dataframe).suggestions[role].recommended


def test_english_date_exact_alias_scores_high() -> None:
    candidate = _recommended(pd.DataFrame({"trade_date": _dates()}), "date")

    assert candidate is not None
    assert candidate.column_name == "trade_date"
    assert candidate.score >= 85
    assert candidate.confidence == "高置信度"


def test_chinese_date_exact_alias_scores_high() -> None:
    candidate = _recommended(pd.DataFrame({"交易日期": _dates()}), "date")

    assert candidate is not None
    assert candidate.column_name == "交易日期"
    assert candidate.score >= 85


def test_parseable_values_raise_date_score() -> None:
    valid = _recommended(pd.DataFrame({"date": _dates().astype(str)}), "date")
    invalid = _recommended(pd.DataFrame({"date": ["甲", "乙", "丙"]}), "date")

    assert valid is not None
    assert invalid is not None
    assert valid.score > invalid.score


def test_integer_security_codes_are_not_high_confidence_dates() -> None:
    candidate = _recommended(
        pd.DataFrame({"security_code": [600000, 600001, 600002, 600003]}),
        "date",
    )

    assert candidate is None or candidate.score < 85


@pytest.mark.parametrize(
    ("column_name", "role"),
    (
        ("portfolio_return", "strategy_return"),
        ("组合收益率", "strategy_return"),
        ("net_value", "strategy_nav"),
        ("组合净值", "strategy_nav"),
        ("benchmark_ret", "benchmark_return"),
        ("基准净值", "benchmark_nav"),
        ("drawdown", "drawdown"),
        ("daily_ret", "daily_ret"),
    ),
)
def test_explicit_business_aliases_are_recommended(
    column_name: str,
    role: str,
) -> None:
    if role in {"strategy_nav", "benchmark_nav"}:
        values = [1.2, 1.22, 1.19, 1.25, 1.24]
    elif role == "drawdown":
        values = [0.0, -0.02, -0.01, 0.0, -0.03]
    else:
        values = [0.01, -0.02, 0.0, 0.015, -0.005]
    candidate = _recommended(pd.DataFrame({column_name: values}), role)

    assert candidate is not None
    assert candidate.column_name == column_name
    assert candidate.score >= MIN_RECOMMENDATION_SCORE


def test_generic_return_has_ambiguity_warning() -> None:
    candidate = _recommended(pd.DataFrame({"return": _returns()}), "strategy_return")

    assert candidate is not None
    assert candidate.score < 85
    assert any("通用" in warning or "可能" in warning for warning in candidate.warnings)


def test_value_is_not_high_confidence_nav() -> None:
    candidate = _recommended(
        pd.DataFrame({"value": [1.0, 1.01, 1.02, 1.03]}),
        "strategy_nav",
    )

    assert candidate is None or candidate.score < 85


def test_index_is_not_automatically_a_benchmark() -> None:
    dataframe = pd.DataFrame({"index": [0.01, -0.01, 0.02, -0.005]})

    return_candidate = _recommended(dataframe, "benchmark_return")
    nav_candidate = _recommended(dataframe, "benchmark_nav")
    assert return_candidate is None or return_candidate.score < 85
    assert nav_candidate is None or nav_candidate.score < 85


def test_cumulative_return_is_not_mistaken_for_nav() -> None:
    candidate = _recommended(
        pd.DataFrame({"累计收益": [0.01, 0.02, 0.015, 0.03]}),
        "strategy_nav",
    )

    assert candidate is None


def test_max_drawdown_aggregate_is_not_a_drawdown_series() -> None:
    candidate = _recommended(pd.DataFrame({"最大回撤": [-0.23]}), "drawdown")

    assert candidate is None


def test_large_return_values_warn_about_percentage_units() -> None:
    candidate = _recommended(
        pd.DataFrame({"portfolio_return": [2.0, -3.0, 1.5, -0.8]}),
        "strategy_return",
    )

    assert candidate is not None
    assert any("百分数单位" in warning for warning in candidate.warnings)


def test_nav_can_be_recommended_when_initial_value_is_not_one() -> None:
    candidate = _recommended(
        pd.DataFrame({"strategy_nav": [100.0, 101.0, 99.0, 103.0]}),
        "strategy_nav",
    )

    assert candidate is not None
    assert candidate.column_name == "strategy_nav"


def test_positive_values_alone_do_not_create_high_nav_confidence() -> None:
    candidate = _recommended(
        pd.DataFrame({"result": [10.0, 11.0, 12.0, 13.0]}),
        "strategy_nav",
    )

    assert candidate is None or candidate.score < 85


def test_consistent_nav_and_return_add_consistency_reason() -> None:
    returns = _returns()
    dataframe = pd.DataFrame({"portfolio_return": returns, "strategy_nav": _nav(returns)})
    result = detect_field_candidates(dataframe)
    candidate = result.suggestions["strategy_return"].recommended

    assert candidate is not None
    assert any("高度一致" in reason for reason in candidate.reasons)


def test_inconsistent_nav_and_return_add_risk_warning() -> None:
    dataframe = pd.DataFrame(
        {
            "portfolio_return": _returns(),
            "strategy_nav": [1.0, 1.2, 1.4, 1.1, 1.5, 1.3, 1.6, 1.2],
        }
    )
    result = detect_field_candidates(dataframe)
    candidate = result.suggestions["strategy_return"].recommended

    assert candidate is not None
    assert any("明显差异" in warning for warning in candidate.warnings)


def test_consistent_drawdown_and_nav_add_consistency_reason() -> None:
    returns = _returns()
    nav = _nav(returns)
    dataframe = pd.DataFrame({"strategy_nav": nav, "drawdown": nav / nav.cummax() - 1})
    result = detect_field_candidates(dataframe)
    candidate = result.suggestions["drawdown"].recommended

    assert candidate is not None
    assert any("高度一致" in reason for reason in candidate.reasons)


def test_one_column_competing_for_roles_adds_conflict_warning() -> None:
    result = detect_field_candidates(pd.DataFrame({"daily_return": _returns()}))

    assert result.suggestions["strategy_return"].recommended is not None
    assert result.suggestions["daily_ret"].recommended is not None
    assert any("多个角色" in warning for warning in result.global_warnings)


def test_all_exposed_candidate_scores_stay_in_range() -> None:
    dataframe = pd.DataFrame(
        {
            "date": _dates(),
            "portfolio_return": _returns(),
            "strategy_nav": _nav(_returns()),
            "drawdown": [0.0, -0.1, -0.05, 0.0, -0.2, -0.1, 0.0, -0.02],
        }
    )
    result = detect_field_candidates(dataframe)

    for suggestion in result.suggestions.values():
        candidates = ([suggestion.recommended] if suggestion.recommended else []) + list(
            suggestion.alternatives
        )
        assert all(0 <= candidate.score <= 100 for candidate in candidates)


def test_below_threshold_is_reported_as_unrecognized() -> None:
    result = detect_field_candidates(pd.DataFrame({"result": ["甲", "乙", "丙"]}))

    assert result.suggestions["date"].recommended is None
    assert result.suggestions["date"].status == "未识别"


def test_same_input_returns_identical_result() -> None:
    dataframe = pd.DataFrame({"trade_date": _dates(), "portfolio_return": _returns()})

    assert detect_field_candidates(dataframe) == detect_field_candidates(dataframe)


def test_input_dataframe_is_not_modified() -> None:
    dataframe = pd.DataFrame({"Trade Date": _dates().astype(str), "Return": _returns()})
    original = dataframe.copy(deep=True)

    detect_field_candidates(dataframe)

    assert_frame_equal(dataframe, original)
    assert dataframe.columns.tolist() == ["Trade Date", "Return"]


def test_large_column_profile_uses_bounded_sample() -> None:
    dataframe = pd.DataFrame({"portfolio_return": range(20_050)})

    profile = detect_field_candidates(dataframe).column_profiles["portfolio_return"]
    assert profile.non_null_count == 20_050
    assert profile.analyzed_count == MAX_PROFILE_SAMPLE_SIZE


def test_bounded_sample_preserves_non_default_index_and_position_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(field_detection_module, "MAX_PROFILE_SAMPLE_SIZE", 4)
    series = pd.Series(
        [10, 20, 30, 40, 50, 60],
        index=[100, 90, 80, 70, 60, 50],
    )

    sample = field_detection_module._bounded_non_null_sample(series)

    assert sample.index.tolist() == [100, 90, 70, 50]
    assert sample.tolist() == [10, 20, 40, 60]


def test_wide_frame_does_not_run_all_pairwise_checks() -> None:
    dataframe = pd.DataFrame(
        {f"column_{index}": [index, index + 1, index + 2] for index in range(500)}
    )

    result = detect_field_candidates(dataframe)
    assert len(result.column_profiles) == 500
    assert result.cross_field_checks <= MAX_CROSS_FIELD_CHECKS


def test_column_profile_reports_expected_statistics() -> None:
    dataframe = pd.DataFrame({"amount": [1.0, 2.0, None, -1.0]})

    profile = detect_field_candidates(dataframe).column_profiles["amount"]
    assert profile.dtype == "float64"
    assert profile.non_null_count == 3
    assert profile.non_null_ratio == pytest.approx(0.75)
    assert profile.unique_count == 3
    assert profile.numeric_ratio == 1.0
    assert profile.numeric_min == -1.0
    assert profile.numeric_max == 2.0
    assert profile.positive_ratio == pytest.approx(2 / 3)
    assert profile.non_positive_ratio == pytest.approx(1 / 3)


def test_name_normalization_is_unicode_aware_and_deterministic() -> None:
    assert (
        normalize_field_name("\ufeff \uff34\uff52\uff41\uff44\uff45  Date--Value.. ")
        == "trade_date_value"
    )


def test_mixed_type_profile_adds_warning_to_named_candidate() -> None:
    dataframe = pd.DataFrame({"portfolio_return": [0.01, "未知", -0.02]})
    candidate = _recommended(dataframe, "strategy_return")

    assert candidate is not None
    assert any("混合类型" in warning for warning in candidate.warnings)


def test_close_candidates_require_manual_confirmation() -> None:
    dataframe = pd.DataFrame({"date": _dates(), "trade_date": _dates()})
    result = detect_field_candidates(dataframe)

    assert any("前两名候选" in warning for warning in result.global_warnings)


def test_integer_yyyymmdd_date_is_not_high_confidence_without_confirmation() -> None:
    candidate = _recommended(
        pd.DataFrame({"trade_date": [20260101, 20260102, 20260103]}),
        "date",
    )

    assert candidate is not None
    assert candidate.score < 85
    assert any("纯整数" in warning for warning in candidate.warnings)


@pytest.mark.parametrize("column_name", ["time", "value", "return", "index", "result"])
def test_ambiguous_names_are_not_all_high_confidence(column_name: str) -> None:
    dataframe = pd.DataFrame({column_name: [1.0, 1.1, 0.9, 1.2]})
    result = detect_field_candidates(dataframe)

    assert all(
        suggestion.recommended is None or suggestion.recommended.score < 85
        for suggestion in result.suggestions.values()
    )


def test_positive_drawdown_values_add_definition_warning() -> None:
    candidate = _recommended(
        pd.DataFrame({"drawdown": [0.0, 0.01, 0.02, 0.03]}),
        "drawdown",
    )

    assert candidate is not None
    assert any("正值" in warning for warning in candidate.warnings)


def test_non_finite_values_are_visible_in_profile() -> None:
    profile = detect_field_candidates(
        pd.DataFrame({"portfolio_return": [0.01, float("inf"), -0.02]})
    ).column_profiles["portfolio_return"]

    assert profile.all_finite_numeric is False


def test_each_role_exposes_at_most_three_candidates() -> None:
    dataframe = pd.DataFrame(
        {
            "date": _dates(),
            "trade_date": _dates(),
            "timestamp": _dates(),
            "time": _dates(),
        }
    )
    result = detect_field_candidates(dataframe)

    for role in ROLE_ORDER:
        suggestion = result.suggestions[role]
        total = (1 if suggestion.recommended is not None else 0) + len(suggestion.alternatives)
        assert total <= 3


def test_empty_dataframe_returns_all_roles_as_unrecognized() -> None:
    result = detect_field_candidates(pd.DataFrame())

    assert tuple(result.suggestions) == ROLE_ORDER
    assert all(item.recommended is None for item in result.suggestions.values())


def test_rejects_non_dataframe_input() -> None:
    with pytest.raises(TypeError, match=r"pandas\.DataFrame"):
        detect_field_candidates([])  # type: ignore[arg-type]
