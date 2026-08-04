"""B.4A 标准化预览、预检和来源绑定测试。"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
import inspect
from types import MappingProxyType

import pandas as pd
import pandas.testing as pdt
import pytest

from src.field_detection import ROLE_ORDER
from src.field_mapping import (
    PRIMARY_BASIS_NAV,
    PRIMARY_BASIS_RETURN,
    ConfirmedMapping,
    build_mapping_source_key,
)
import src.standardization as standardization_module
from src.standardization import (
    BLOCKING,
    MAPPING_KEY_POLICY_VERSION,
    STANDARDIZATION_POLICY_VERSION,
    WARNING,
    StandardizationResult,
    analysis_output_columns,
    build_mapping_key,
    build_standardization_key,
    is_standardization_result_current,
    standardize_confirmed_mapping,
)


def _mapping(
    primary_basis: str = PRIMARY_BASIS_RETURN,
    *,
    source_key: str = "source-key",
    warnings: tuple[str, ...] = (),
    **overrides: str | None,
) -> ConfirmedMapping:
    role_to_column: dict[str, str | None] = {
        role: None for role in ROLE_ORDER
    }
    role_to_column["date"] = "when"
    if primary_basis == PRIMARY_BASIS_RETURN:
        role_to_column["strategy_return"] = "ret"
    elif primary_basis == PRIMARY_BASIS_NAV:
        role_to_column["strategy_nav"] = "nav"
    role_to_column.update(overrides)
    return ConfirmedMapping(
        source_key=source_key,
        primary_basis=primary_basis,
        role_to_column=MappingProxyType(role_to_column),
        warnings=warnings,
    )


def _return_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "when": [
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
                "2026-01-04",
            ],
            "ret": [0.01, -0.02, 0.03, 0.005],
            "bench": [0.005, -0.01, 0.02, 0.002],
            "nav": [1.0, 0.98, 1.0094, 1.014447],
            "bench_nav": [1.0, 0.99, 1.0098, 1.0118196],
            "dd": [0.0, -0.02, -0.001, 0.0],
            "daily": [pd.NA, -0.02, 0.03, 0.005],
        },
        index=pd.Index([10, 20, 30, 40], name="source_row"),
    )


def _codes(result: StandardizationResult, level: str | None = None) -> set[str]:
    return {
        issue.code
        for issue in result.issues
        if level is None or issue.level == level
    }


def _issues(result: StandardizationResult, code: str):
    return [issue for issue in result.issues if issue.code == code]


def test_return_primary_builds_fixed_candidate_structure() -> None:
    result = standardize_confirmed_mapping(_return_frame(), _mapping())

    assert result.structure_type == "收益率分析候选表"
    assert result.analysis_frame.columns.tolist() == ["date", "strategy_return"]
    assert result.diagnostic_frame.empty


def test_mapped_benchmark_return_is_added_in_fixed_order() -> None:
    result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(benchmark_return="bench"),
    )

    assert result.analysis_frame.columns.tolist() == [
        "date",
        "strategy_return",
        "benchmark_return",
    ]


def test_unmapped_fields_are_not_added_to_candidate_frame() -> None:
    result = standardize_confirmed_mapping(_return_frame(), _mapping())

    assert "benchmark_return" not in result.analysis_frame
    assert "strategy_nav" not in result.analysis_frame


def test_nav_primary_renames_strategy_nav_to_nav_strat() -> None:
    result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(PRIMARY_BASIS_NAV),
    )

    assert result.structure_type == "净值适配候选表"
    assert result.analysis_frame.columns.tolist() == ["date", "nav_strat"]
    assert result.analysis_frame["nav_strat"].tolist() == _return_frame()["nav"].tolist()


def test_nav_primary_keeps_mapped_daily_ret_in_candidate_frame() -> None:
    frame = _return_frame()
    frame["daily"] = [0.0, -0.02, 0.03, 0.005]
    result = standardize_confirmed_mapping(
        frame,
        _mapping(PRIMARY_BASIS_NAV, daily_ret="daily"),
    )

    assert result.analysis_frame.columns.tolist() == ["date", "nav_strat", "daily_ret"]


@pytest.mark.parametrize(
    ("primary_basis", "overrides", "expected_diagnostics"),
    (
        (
            PRIMARY_BASIS_RETURN,
            {"strategy_nav": "nav", "benchmark_nav": "bench_nav", "drawdown": "dd", "daily_ret": "daily"},
            ["strategy_nav", "benchmark_nav", "drawdown", "daily_ret"],
        ),
        (
            PRIMARY_BASIS_NAV,
            {"strategy_return": "ret", "benchmark_return": "bench", "benchmark_nav": "bench_nav", "drawdown": "dd"},
            ["strategy_return", "benchmark_return", "benchmark_nav", "drawdown"],
        ),
    ),
)
def test_non_primary_roles_only_enter_diagnostic_frame(
    primary_basis: str,
    overrides: dict[str, str],
    expected_diagnostics: list[str],
) -> None:
    result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(primary_basis, **overrides),
    )

    assert result.diagnostic_frame.columns.tolist() == expected_diagnostics
    assert not set(expected_diagnostics).intersection(result.analysis_frame.columns)


def test_benchmark_nav_never_derives_benchmark_return() -> None:
    result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(benchmark_nav="bench_nav"),
    )

    assert "benchmark_nav" in result.diagnostic_frame
    assert "benchmark_return" not in result.analysis_frame


def test_strategy_nav_never_derives_strategy_return() -> None:
    result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(PRIMARY_BASIS_NAV),
    )

    assert "strategy_return" not in result.analysis_frame
    assert result.analysis_frame.columns.tolist() == ["date", "nav_strat"]


def test_primary_basis_explicitly_controls_output_structure() -> None:
    return_mapping = _mapping(strategy_nav="nav")
    nav_mapping = _mapping(PRIMARY_BASIS_NAV, strategy_return="ret")

    assert analysis_output_columns(return_mapping) == ("date", "strategy_return")
    assert analysis_output_columns(nav_mapping) == ("date", "nav_strat")


def test_original_dataframe_is_deeply_unchanged() -> None:
    frame = _return_frame()
    original = frame.copy(deep=True)

    result = standardize_confirmed_mapping(
        frame,
        _mapping(strategy_nav="nav", benchmark_return="bench", drawdown="dd"),
    )

    pdt.assert_frame_equal(frame, original, check_exact=True)
    assert result.analysis_frame is not frame
    assert result.diagnostic_frame is not frame


def test_original_columns_index_order_and_row_count_are_preserved() -> None:
    frame = _return_frame()
    original_columns = frame.columns.copy()
    original_index = frame.index.copy()
    original_rows = frame.to_dict("records")

    result = standardize_confirmed_mapping(frame, _mapping())

    assert frame.columns.equals(original_columns)
    assert frame.index.equals(original_index)
    assert frame.to_dict("records") == original_rows
    assert len(result.analysis_frame) == len(frame)
    assert result.analysis_frame.index.equals(frame.index)


def test_standardization_does_not_sort_or_deduplicate_dates() -> None:
    frame = pd.DataFrame(
        {"when": ["2026-01-02", "2026-01-01", "2026-01-01"], "ret": [0.1, 0.2, 0.3]},
        index=[8, 4, 6],
    )

    result = standardize_confirmed_mapping(frame, _mapping())

    assert result.analysis_frame.index.tolist() == [8, 4, 6]
    assert result.analysis_frame["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-02",
        "2026-01-01",
        "2026-01-01",
    ]
    assert len(result.analysis_frame) == 3
    assert {"date_duplicate", "date_not_strictly_increasing"} <= _codes(result, BLOCKING)


def test_standardization_does_not_fill_or_drop_invalid_rows() -> None:
    frame = pd.DataFrame(
        {"when": ["2026-01-01", "bad", None], "ret": [0.01, "1.2%", None]},
        index=[1, 5, 9],
    )

    result = standardize_confirmed_mapping(frame, _mapping())

    assert len(result.analysis_frame) == 3
    assert result.analysis_frame.index.tolist() == [1, 5, 9]
    assert result.analysis_frame["date"].isna().sum() == 2
    assert result.analysis_frame["strategy_return"].isna().sum() == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (1, 1),
        (1.25, 1.25),
        (Decimal("1.234567890123456789"), Decimal("1.234567890123456789")),
        ("1.25", Decimal("1.25")),
        ("  -1.25  ", Decimal("-1.25")),
        ("1e-4", Decimal("1e-4")),
    ),
)
def test_allowed_numeric_values_convert_without_rounding(value: object, expected: object) -> None:
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "ret": [value, 0.01]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert result.analysis_frame.loc[0, "strategy_return"] == expected
    assert "numeric_unparseable" not in _codes(result)


@pytest.mark.parametrize(
    "value",
    (
        "1.2%",
        "1,234.56",
        "$1.20",
        "￥1.20",
        "(1.20)",
        "1万",
        "1亿",
        "1K",
        "1M",
        "一",
        "--",
    ),
)
def test_unsupported_numeric_formats_are_not_silently_converted(value: str) -> None:
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "ret": [value, 0.01]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert pd.isna(result.analysis_frame.loc[0, "strategy_return"])
    assert "numeric_unparseable" in _codes(result, BLOCKING)


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf"), Decimal("NaN")))
def test_nan_and_infinity_are_blocking_for_analysis_fields(value: object) -> None:
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "ret": [value, 0.01]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert "numeric_non_finite" in _codes(result, BLOCKING)
    assert result.is_preview_valid is False


def test_numeric_precision_is_not_actively_rounded() -> None:
    precise = Decimal("0.1234567890123456789012345678")
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "ret": [precise, Decimal("0.01")]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert result.analysis_frame.loc[0, "strategy_return"] == precise


@pytest.mark.parametrize(
    "value",
    (
        pd.Timestamp("2026-01-01"),
        datetime(2026, 1, 1),
        "2026-01-01",
        "2026/01/01",
        "20260101",
        "2026-01-01T09:30:00",
    ),
)
def test_supported_date_formats_convert_deterministically(value: object) -> None:
    frame = pd.DataFrame({"when": [value, "2026-01-02"], "ret": [0.01, 0.02]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert result.analysis_frame.loc[0, "date"].date().isoformat() == "2026-01-01"
    assert "date_unparseable" not in _codes(result)


@pytest.mark.parametrize("value", ("01/02/2026", "02/01/2026", "2026.01.01", "not-a-date"))
def test_ambiguous_or_invalid_dates_are_blocking(value: str) -> None:
    frame = pd.DataFrame({"when": [value, "2026-01-02"], "ret": [0.01, 0.02]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert "date_unparseable" in _codes(result, BLOCKING)
    assert result.is_preview_valid is False


def test_empty_date_is_blocking() -> None:
    frame = pd.DataFrame({"when": [None, "2026-01-02"], "ret": [0.01, 0.02]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert "date_missing" in _codes(result, BLOCKING)


def test_same_natural_day_with_times_is_blocking_and_not_aggregated() -> None:
    frame = pd.DataFrame(
        {"when": ["2026-01-01T09:00:00", "2026-01-01T15:00:00"], "ret": [0.01, 0.02]}
    )

    result = standardize_confirmed_mapping(frame, _mapping())

    assert "date_same_natural_day_duplicate" in _codes(result, BLOCKING)
    assert len(result.analysis_frame) == 2


def test_timezone_dates_use_utc_rule_and_warn() -> None:
    frame = pd.DataFrame(
        {
            "when": [
                datetime(2026, 1, 1, 8, tzinfo=timezone.utc),
                "2026-01-02T08:00:00+08:00",
            ],
            "ret": [0.01, 0.02],
        }
    )

    result = standardize_confirmed_mapping(frame, _mapping())

    assert str(result.analysis_frame["date"].dtype) == "datetime64[ns]"
    assert result.analysis_frame.loc[1, "date"] == pd.Timestamp("2026-01-02T00:00:00")
    assert "date_contains_timezone" in _codes(result, WARNING)


def test_optional_benchmark_return_missing_or_invalid_is_blocking() -> None:
    frame = _return_frame()
    frame["bench"] = [0.01, None, "1.2%", 0.02]

    result = standardize_confirmed_mapping(frame, _mapping(benchmark_return="bench"))

    assert {"numeric_missing", "numeric_unparseable"} <= _codes(result, BLOCKING)
    assert result.is_preview_valid is False


def test_unmapped_benchmark_return_does_not_block() -> None:
    frame = _return_frame().drop(columns=["bench"])

    result = standardize_confirmed_mapping(frame, _mapping())

    assert not any(issue.role == "benchmark_return" for issue in result.issues)


@pytest.mark.parametrize("value", (-1, -1.01))
def test_strategy_return_at_or_below_minus_one_is_blocking(value: float) -> None:
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "ret": [0.01, value]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert "return_at_or_below_minus_one" in _codes(result, BLOCKING)


@pytest.mark.parametrize(
    ("values", "expected_code"),
    (
        ([2.0, 3.0, 0.01, 0.02], "return_large_absolute_values"),
        ([0.5, -0.4, 0.01, 0.02], "return_many_extreme_values"),
        ([0.01, 0.02, 0.03, 0.04], "return_all_positive"),
        ([0.0, 0.0, 0.0, 0.0], "return_all_zero"),
        ([0.01, 0.01, 0.02, 0.02], "return_low_uniqueness"),
    ),
)
def test_return_risk_patterns_generate_warnings(values: list[float], expected_code: str) -> None:
    frame = pd.DataFrame(
        {"when": pd.date_range("2026-01-01", periods=4).strftime("%Y-%m-%d"), "ret": values}
    )

    result = standardize_confirmed_mapping(frame, _mapping())

    assert expected_code in _codes(result, WARNING)


def test_numeric_one_is_kept_as_one_not_one_percent() -> None:
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "ret": [1, 0.01]})

    result = standardize_confirmed_mapping(frame, _mapping())

    assert result.analysis_frame.loc[0, "strategy_return"] == 1
    assert result.analysis_frame.loc[0, "strategy_return"] != 0.01


@pytest.mark.parametrize(
    ("values", "expected_code"),
    (
        ([1.0, None], "numeric_missing"),
        ([1.0, "bad"], "numeric_unparseable"),
        ([1.0, 0.0], "nav_non_positive"),
    ),
)
def test_primary_nav_invalid_values_are_blocking(values: list[object], expected_code: str) -> None:
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "nav": values})

    result = standardize_confirmed_mapping(frame, _mapping(PRIMARY_BASIS_NAV))

    assert expected_code in _codes(result, BLOCKING)


def test_primary_nav_requires_two_valid_observations() -> None:
    frame = pd.DataFrame({"when": ["2026-01-01"], "nav": [1.0]})

    result = standardize_confirmed_mapping(frame, _mapping(PRIMARY_BASIS_NAV))

    assert "nav_insufficient_observations" in _codes(result, BLOCKING)


def test_nav_not_starting_at_one_is_warning_not_blocking() -> None:
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "nav": [100.0, 101.0]})

    result = standardize_confirmed_mapping(frame, _mapping(PRIMARY_BASIS_NAV))

    assert "nav_initial_value_far_from_one" in _codes(result, WARNING)
    assert result.is_preview_valid is True
    assert result.analysis_frame.loc[0, "nav_strat"] == 100.0


@pytest.mark.parametrize(
    ("values", "expected_code"),
    (
        ([1.0, 1.0, 1.0], "nav_constant"),
        ([1.0, 1.0, 1.01, 1.01], "nav_low_uniqueness"),
        ([1.0, 2.0, 2.1], "nav_extreme_jump"),
    ),
)
def test_nav_risk_patterns_generate_warnings(values: list[float], expected_code: str) -> None:
    frame = pd.DataFrame(
        {"when": pd.date_range("2026-01-01", periods=len(values)).strftime("%Y-%m-%d"), "nav": values}
    )

    result = standardize_confirmed_mapping(frame, _mapping(PRIMARY_BASIS_NAV))

    assert expected_code in _codes(result, WARNING)


def test_nav_is_not_normalized_and_return_is_not_derived() -> None:
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-01-02"], "nav": [100.0, 101.0]})

    result = standardize_confirmed_mapping(frame, _mapping(PRIMARY_BASIS_NAV))

    assert result.analysis_frame["nav_strat"].tolist() == [100.0, 101.0]
    assert "strategy_return" not in result.analysis_frame


def test_diagnostic_invalid_values_are_warnings_only() -> None:
    frame = _return_frame()
    frame["dd"] = [0.0, "bad", None, -0.1]

    result = standardize_confirmed_mapping(frame, _mapping(drawdown="dd"))

    diagnostic_issues = [issue for issue in result.issues if issue.role == "drawdown"]
    assert diagnostic_issues
    assert all(issue.level == WARNING for issue in diagnostic_issues)
    assert result.is_preview_valid is True


@pytest.mark.parametrize(
    ("values", "expected_code"),
    (
        ([0.0, 0.1, -0.1, -0.2], "drawdown_positive"),
        ([0.0, -1.1, -0.1, -0.2], "drawdown_below_minus_one"),
        ([0.0, None, -0.1, -0.2], "numeric_missing"),
    ),
)
def test_drawdown_diagnostic_checks(values: list[object], expected_code: str) -> None:
    frame = _return_frame()
    frame["dd"] = values

    result = standardize_confirmed_mapping(frame, _mapping(drawdown="dd"))

    assert expected_code in _codes(result, WARNING)
    assert "drawdown" not in result.analysis_frame


def test_drawdown_nav_inconsistency_is_warning() -> None:
    frame = _return_frame()
    frame["dd"] = [0.0, -0.5, -0.4, -0.3]

    result = standardize_confirmed_mapping(
        frame,
        _mapping(strategy_nav="nav", drawdown="dd"),
    )

    assert "drawdown_nav_mismatch" in _codes(result, WARNING)


@pytest.mark.parametrize(
    ("values", "expected_code"),
    (
        ([0.0, "bad", 0.01, 0.02], "numeric_unparseable"),
        ([0.0, -1.0, 0.01, 0.02], "return_at_or_below_minus_one"),
    ),
)
def test_daily_ret_diagnostic_checks(values: list[object], expected_code: str) -> None:
    frame = _return_frame()
    frame["daily"] = values

    result = standardize_confirmed_mapping(frame, _mapping(daily_ret="daily"))

    assert expected_code in _codes(result, WARNING)
    assert result.is_preview_valid is True


def test_daily_ret_nav_inconsistency_is_warning_without_overwrite() -> None:
    frame = _return_frame()
    frame["daily"] = [0.0, 0.5, 0.5, 0.5]
    original_daily = frame["daily"].copy(deep=True)

    result = standardize_confirmed_mapping(
        frame,
        _mapping(PRIMARY_BASIS_NAV, daily_ret="daily"),
    )

    assert "daily_ret_nav_mismatch" in _codes(result, WARNING)
    pdt.assert_series_equal(frame["daily"], original_daily)
    assert result.analysis_frame["daily_ret"].tolist() == original_daily.tolist()


def test_auxiliary_strategy_fields_never_override_selected_basis() -> None:
    return_result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(strategy_nav="nav"),
    )
    nav_result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(PRIMARY_BASIS_NAV, strategy_return="ret"),
    )

    assert return_result.analysis_frame["strategy_return"].tolist() == _return_frame()["ret"].tolist()
    assert "strategy_nav" in return_result.diagnostic_frame
    assert nav_result.analysis_frame["nav_strat"].tolist() == _return_frame()["nav"].tolist()
    assert "strategy_return" in nav_result.diagnostic_frame


def test_same_mapping_input_produces_same_keys_and_result() -> None:
    mapping = _mapping(benchmark_return="bench")
    first = standardize_confirmed_mapping(_return_frame(), mapping)
    second = standardize_confirmed_mapping(_return_frame(), mapping)

    assert build_mapping_key(mapping) == build_mapping_key(mapping)
    assert first.mapping_key == second.mapping_key
    assert first.standardization_key == second.standardization_key
    pdt.assert_frame_equal(first.analysis_frame, second.analysis_frame)
    assert first.issues == second.issues


def test_mapping_key_includes_source_basis_all_roles_and_mapping_policy() -> None:
    base = _mapping()
    changed_source = _mapping(source_key="other-source")
    changed_basis = _mapping(PRIMARY_BASIS_NAV)
    changed_role = _mapping(benchmark_return="bench")

    assert MAPPING_KEY_POLICY_VERSION == "b3-confirmed-mapping-v1"
    assert len({build_mapping_key(item) for item in (base, changed_source, changed_basis, changed_role)}) == 4


@pytest.mark.parametrize(
    "changed_metadata",
    (
        {"encoding": "gb18030"},
        {"delimiter": ";"},
        {"sheet_name": "Sheet2"},
        {"columns": ("ret", "when")},
    ),
)
def test_source_parse_metadata_changes_standardization_key(
    changed_metadata: dict[str, object],
) -> None:
    metadata: dict[str, object] = {
        "content_digest": "a" * 64,
        "file_type": "CSV",
        "sheet_name": None,
        "encoding": "utf-8",
        "delimiter": ",",
        "header_rule": "first_row",
        "columns": ("when", "ret"),
    }
    base_source = build_mapping_source_key(**metadata)
    changed_source = build_mapping_source_key(**(metadata | changed_metadata))
    base = standardize_confirmed_mapping(_return_frame(), _mapping(source_key=base_source))
    changed = standardize_confirmed_mapping(_return_frame(), _mapping(source_key=changed_source))

    assert base.standardization_key != changed.standardization_key


def test_policy_version_changes_standardization_key() -> None:
    mapping = _mapping()
    mapping_key = build_mapping_key(mapping)

    first = build_standardization_key("source", mapping_key, "v1")
    second = build_standardization_key("source", mapping_key, "v2")

    assert first != second


def test_mapping_and_source_changes_invalidate_old_preview() -> None:
    first_mapping = _mapping()
    first = standardize_confirmed_mapping(_return_frame(), first_mapping)

    assert is_standardization_result_current(first, first_mapping) is True
    assert is_standardization_result_current(first, _mapping(source_key="new-source")) is False
    assert is_standardization_result_current(first, _mapping(benchmark_return="bench")) is False


def test_standardization_result_binds_mapping_policy_and_counts() -> None:
    mapping = _mapping()
    result = standardize_confirmed_mapping(_return_frame(), mapping)

    assert result.confirmed_mapping is mapping
    assert result.source_key == mapping.source_key
    assert result.policy_version == STANDARDIZATION_POLICY_VERSION
    assert len(result.mapping_key) == 64
    assert len(result.standardization_key) == 64
    assert result.source_row_count == result.row_count == 4
    assert result.column_count == 2


def test_result_does_not_store_upload_bytes_or_local_path() -> None:
    result = standardize_confirmed_mapping(_return_frame(), _mapping())

    assert not any(isinstance(value, bytes) for value in vars(result).values())
    assert "C:\\Users\\" not in repr(result)
    assert not hasattr(result, "content")
    assert not hasattr(result, "file_path")


def test_blocking_issue_controls_preview_validity() -> None:
    valid = standardize_confirmed_mapping(_return_frame(), _mapping())
    invalid_frame = _return_frame()
    invalid_frame.loc[20, "ret"] = -1
    invalid = standardize_confirmed_mapping(invalid_frame, _mapping())

    assert valid.is_preview_valid is True
    assert invalid.is_preview_valid is False


def test_standardization_module_is_isolated_from_analysis_and_ui_modules() -> None:
    source = inspect.getsource(standardization_module)
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "src.performance" not in imported_modules
    assert "src.reporting" not in imported_modules
    assert "src.comparison" not in imported_modules
    assert "src.adapters" not in imported_modules
    assert "streamlit" not in source
    assert "plotly" not in source
    assert "to_csv" not in source


def test_missing_source_column_is_reported_without_mutation() -> None:
    frame = _return_frame().drop(columns=["ret"])

    result = standardize_confirmed_mapping(frame, _mapping())

    assert "source_column_missing" in _codes(result, BLOCKING)
    assert "ret" not in frame.columns


def test_mapping_warning_about_b2_difference_is_retained() -> None:
    warning = "strategy_return 选择的“ret”与 B.2 首选建议“return”不同。"

    result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(warnings=(warning,)),
    )

    assert _issues(result, "mapping_differs_from_b2")[0].message == warning


def test_both_strategy_fields_warn_but_keep_user_primary_basis() -> None:
    result = standardize_confirmed_mapping(
        _return_frame(),
        _mapping(strategy_nav="nav"),
    )

    assert "multiple_strategy_basis_mapped" in _codes(result, WARNING)
    assert result.primary_basis == PRIMARY_BASIS_RETURN
    assert "strategy_return" in result.analysis_frame
    assert "strategy_nav" in result.diagnostic_frame
