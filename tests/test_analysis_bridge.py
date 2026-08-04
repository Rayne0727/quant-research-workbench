"""B.4B bridge gates, protocol reuse, and direct-upload equivalence tests."""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
from types import MappingProxyType

import pandas as pd
import pandas.testing as pdt
import pytest

from src.adapters import adapt_weekly_nav_data
from src.analysis_bridge import (
    ANALYSIS_BRIDGE_VERSION,
    NAV_ADAPTER_VERSION,
    STRICT_NAV_PROTOCOL_VERSION,
    STRICT_RETURN_PROTOCOL_VERSION,
    AnalysisBridgeValidationError,
    StrictProtocolResult,
    build_analysis_request_key,
    build_generic_analysis_input,
    build_generic_analysis_request,
    is_strict_protocol_result_current,
    validate_standardized_result,
)
from src.data_loader import validate_returns_data
from src.field_detection import ROLE_ORDER
from src.field_mapping import (
    PRIMARY_BASIS_NAV,
    PRIMARY_BASIS_RETURN,
    ConfirmedMapping,
)
from src.performance import (
    add_nav_performance_series,
    add_performance_series,
    calculate_nav_performance_metrics,
    calculate_performance_metrics,
)
from src.reporting import (
    ReportContext,
    build_standardized_data,
    generate_analysis_summary,
    generate_markdown_report,
)
from src.standardization import (
    StandardizationResult,
    standardize_confirmed_mapping,
)


def _mapping(
    primary_basis: str = PRIMARY_BASIS_RETURN,
    *,
    source_key: str = "source-key",
    **roles: str | None,
) -> ConfirmedMapping:
    values = {role: None for role in ROLE_ORDER}
    values["date"] = "trade_date"
    values[primary_basis] = "return_value" if primary_basis == PRIMARY_BASIS_RETURN else "nav_value"
    values.update(roles)
    return ConfirmedMapping(
        source_key=source_key,
        primary_basis=primary_basis,
        role_to_column=MappingProxyType(values),
        warnings=(),
    )


def _return_source(*, benchmark: bool = True) -> pd.DataFrame:
    data: dict[str, object] = {
        "trade_date": ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
        "return_value": [0.01, -0.005, 0.012, 0.003],
    }
    if benchmark:
        data["benchmark_value"] = [0.004, -0.002, 0.006, 0.001]
    return pd.DataFrame(data, index=[10, 20, 30, 40])


def _nav_source(*, daily_ret: bool = True) -> pd.DataFrame:
    data: dict[str, object] = {
        "trade_date": ["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23"],
        "nav_value": [100.0, 102.0, 101.0, 104.0],
    }
    if daily_ret:
        data["daily_value"] = [0.0, 0.02, -0.00980392156862745, 0.0297029702970297]
    return pd.DataFrame(data, index=[3, 6, 9, 12])


def _return_preview(*, benchmark: bool = True) -> StandardizationResult:
    mapping = _mapping(
        benchmark_return="benchmark_value" if benchmark else None,
    )
    return standardize_confirmed_mapping(_return_source(benchmark=benchmark), mapping)


def _nav_preview(*, daily_ret: bool = True) -> StandardizationResult:
    mapping = _mapping(
        PRIMARY_BASIS_NAV,
        daily_ret="daily_value" if daily_ret else None,
    )
    return standardize_confirmed_mapping(_nav_source(daily_ret=daily_ret), mapping)


def _report_context(
    data: pd.DataFrame,
    metrics: dict[str, object],
    *,
    nav: bool,
    diagnostics: object = None,
) -> ReportContext:
    return ReportContext(
        experiment_name="等价性实验",
        strategy_name="测试策略",
        research_notes="固定输入",
        data_format="每周调仓净值 CSV" if nav else "标准日频收益 CSV",
        primary_field="nav_strat" if nav else "strategy_return",
        start_date=pd.Timestamp(metrics["start_date"]),
        end_date=pd.Timestamp(metrics["end_date"]),
        observation_count=len(data),
        valid_return_count=int(metrics["n_days"]),
        metrics=metrics,
        has_benchmark="benchmark_cumulative_return" in metrics,
        diagnostics=diagnostics,
    )


def test_missing_standardization_result_cannot_build_request() -> None:
    with pytest.raises(AnalysisBridgeValidationError, match="标准化预览不存在"):
        build_generic_analysis_request(None)  # type: ignore[arg-type]


def test_failed_preview_cannot_enter_strict_validation() -> None:
    preview = replace(_return_preview(), is_preview_valid=False)
    with pytest.raises(AnalysisBridgeValidationError, match="标准化预检未通过"):
        validate_standardized_result(preview)


@pytest.mark.parametrize(
    ("preview", "protocol_name"),
    ((_return_preview(), "标准日收益协议"), (_nav_preview(), "净值适配协议")),
)
def test_valid_preview_enters_existing_protocol(
    preview: StandardizationResult,
    protocol_name: str,
) -> None:
    strict = validate_standardized_result(preview)
    assert strict.is_valid
    assert strict.protocol_name == protocol_name
    assert strict.errors == ()


def test_strict_validation_module_does_not_import_analysis_modules() -> None:
    source = Path("src/analysis_bridge.py").read_text(encoding="utf-8")
    for module_name in ("src.performance", "src.reporting", "src.comparison"):
        assert module_name not in source


def test_strict_validation_does_not_call_performance(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.performance as performance

    monkeypatch.setattr(
        performance,
        "calculate_performance_metrics",
        lambda *_args, **_kwargs: pytest.fail("strict gate called performance"),
    )
    assert validate_standardized_result(_return_preview()).is_valid


def test_analysis_input_requires_successful_strict_result() -> None:
    preview = _return_preview()
    invalid_frame = preview.analysis_frame.assign(extra=1)
    invalid = validate_standardized_result(replace(preview, analysis_frame=invalid_frame))
    assert not invalid.is_valid
    with pytest.raises(AnalysisBridgeValidationError, match="严格协议验证未通过"):
        build_generic_analysis_input(invalid)


def test_valid_strict_result_builds_independent_analysis_input() -> None:
    strict = validate_standardized_result(_return_preview())
    first = build_generic_analysis_input(strict)
    second = build_generic_analysis_input(strict)
    assert first is not strict.validated_frame
    assert second is not first
    pdt.assert_frame_equal(first, second)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("standardization_key", "changed-standardization"),
        ("primary_basis", PRIMARY_BASIS_NAV),
    ),
)
def test_standardization_identity_changes_invalidate_strict_result(
    field_name: str,
    value: str,
) -> None:
    preview = _return_preview()
    strict = validate_standardized_result(preview)
    assert not is_strict_protocol_result_current(strict, replace(preview, **{field_name: value}))


def test_source_and_mapping_changes_invalidate_strict_result() -> None:
    preview = _return_preview()
    strict = validate_standardized_result(preview)
    changed_mapping = replace(
        preview.confirmed_mapping,
        source_key="new-source",
    )
    assert not is_strict_protocol_result_current(
        strict,
        replace(preview, source_key="new-source", confirmed_mapping=changed_mapping),
    )
    assert not is_strict_protocol_result_current(
        replace(strict, mapping_key="new-mapping"),
        preview,
    )


def test_protocol_adapter_and_bridge_versions_change_request_key() -> None:
    preview = _return_preview()
    base = build_generic_analysis_request(preview)
    variants = (
        build_generic_analysis_request(preview, protocol_version="protocol-v2"),
        build_generic_analysis_request(preview, adapter_version="adapter-v2"),
        build_generic_analysis_request(preview, bridge_version="bridge-v2"),
    )
    assert all(item.analysis_request_key != base.analysis_request_key for item in variants)


def test_analysis_request_key_is_deterministic_and_includes_column_order() -> None:
    preview = _return_preview()
    request = build_generic_analysis_request(preview)
    repeated = build_generic_analysis_request(preview)
    reordered = build_analysis_request_key(
        preview.standardization_key,
        preview.primary_basis,
        STRICT_RETURN_PROTOCOL_VERSION,
        input_columns=tuple(reversed(request.analysis_input_columns)),
    )
    assert request.analysis_request_key == repeated.analysis_request_key
    assert reordered != request.analysis_request_key
    assert len(request.analysis_request_key) == 64


def test_request_carries_all_source_mapping_and_policy_bindings() -> None:
    preview = _nav_preview()
    request = build_generic_analysis_request(preview)
    assert request.source_key == preview.source_key
    assert request.mapping_key == preview.mapping_key
    assert request.standardization_key == preview.standardization_key
    assert request.primary_basis == PRIMARY_BASIS_NAV
    assert request.protocol_version == STRICT_NAV_PROTOCOL_VERSION
    assert request.adapter_version == NAV_ADAPTER_VERSION
    assert request.bridge_version == ANALYSIS_BRIDGE_VERSION


def test_return_protocol_passes_only_candidate_fields() -> None:
    preview = _return_preview()
    preview.diagnostic_frame["strategy_nav"] = [1.0, 1.1, 1.2, 1.3]
    preview.diagnostic_frame["drawdown"] = [0.0, -0.1, -0.05, -0.02]
    preview.diagnostic_frame["daily_ret"] = [0.0, 0.1, 0.1, 0.1]
    strict = validate_standardized_result(preview)
    assert strict.is_valid
    assert list(strict.validated_frame.columns) == [
        "date",
        "strategy_return",
        "benchmark_return",
    ]


def test_return_protocol_without_benchmark_uses_no_benchmark_path() -> None:
    strict = validate_standardized_result(_return_preview(benchmark=False))
    assert strict.is_valid
    assert not strict.has_benchmark
    assert "benchmark_return" not in strict.validated_frame.columns


def test_return_protocol_does_not_convert_percentage_units() -> None:
    preview = _return_preview(benchmark=False)
    frame = preview.analysis_frame.copy(deep=True)
    frame.loc[frame.index[0], "strategy_return"] = 1.0
    strict = validate_standardized_result(replace(preview, analysis_frame=frame))
    assert strict.is_valid
    assert strict.validated_frame.loc[0, "strategy_return"] == 1.0


def test_strict_return_error_is_controlled_and_blocks_analysis() -> None:
    preview = _return_preview(benchmark=False)
    frame = preview.analysis_frame.copy(deep=True)
    frame["strategy_return"] = [0.01, -1.0, 0.02, 0.03]
    strict = validate_standardized_result(replace(preview, analysis_frame=frame))
    assert not strict.is_valid
    assert "不能小于或等于 -1" in strict.errors[0]
    assert strict.validated_frame is None


def test_nav_protocol_passes_nav_and_optional_daily_ret_to_existing_adapter() -> None:
    strict = validate_standardized_result(_nav_preview())
    assert strict.is_valid
    assert list(strict.analysis_input_columns) == ["date", "nav_strat", "daily_ret"]
    assert {"strategy_nav", "strategy_return"}.issubset(strict.validated_frame.columns)
    assert strict.adapter_diagnostics is not None


def test_nav_protocol_without_daily_ret_still_validates() -> None:
    strict = validate_standardized_result(_nav_preview(daily_ret=False))
    assert strict.is_valid
    assert strict.adapter_diagnostics is None
    assert list(strict.analysis_input_columns) == ["date", "nav_strat"]


def test_nav_diagnostics_never_bypass_adapter() -> None:
    preview = _nav_preview()
    preview.diagnostic_frame["strategy_return"] = [0.9, 0.9, 0.9, 0.9]
    preview.diagnostic_frame["benchmark_return"] = [0.1, 0.1, 0.1, 0.1]
    preview.diagnostic_frame["benchmark_nav"] = [1.0, 2.0, 3.0, 4.0]
    strict = validate_standardized_result(preview)
    assert strict.is_valid
    assert "benchmark_return" not in strict.validated_frame.columns
    assert "benchmark_nav" not in strict.validated_frame.columns
    assert strict.validated_frame.loc[1, "strategy_return"] == pytest.approx(0.02)


def test_nav_is_normalized_only_by_existing_adapter_without_mutating_preview() -> None:
    preview = _nav_preview()
    before = preview.analysis_frame.copy(deep=True)
    strict = validate_standardized_result(preview)
    assert strict.validated_frame.loc[0, "strategy_nav"] == 1.0
    assert strict.validated_frame.loc[0, "nav_strat"] == 100.0
    pdt.assert_frame_equal(preview.analysis_frame, before)


def test_nav_adapter_error_is_controlled_and_blocks_analysis() -> None:
    preview = _nav_preview(daily_ret=False)
    frame = preview.analysis_frame.copy(deep=True)
    frame.loc[frame.index[1], "nav_strat"] = 0.0
    strict = validate_standardized_result(replace(preview, analysis_frame=frame))
    assert not strict.is_valid
    assert "必须全部大于 0" in strict.errors[0]


def test_nav_adapter_output_continues_into_existing_nav_performance_path() -> None:
    strict = validate_standardized_result(_nav_preview())
    analysis_input = build_generic_analysis_input(strict)
    metrics = calculate_nav_performance_metrics(analysis_input)
    performance_data = add_nav_performance_series(analysis_input)
    assert metrics["n_days"] == 3
    assert "drawdown" in performance_data.columns


def test_bridge_preserves_source_and_standardization_frames_deeply() -> None:
    source = _return_source()
    source_before = source.copy(deep=True)
    preview = standardize_confirmed_mapping(
        source,
        _mapping(benchmark_return="benchmark_value"),
    )
    preview_before = preview.analysis_frame.copy(deep=True)
    strict = validate_standardized_result(preview)
    analysis_input = build_generic_analysis_input(strict)
    analysis_input.iloc[0, 1] = 999.0
    pdt.assert_frame_equal(source, source_before)
    pdt.assert_frame_equal(preview.analysis_frame, preview_before)


def test_bridge_does_not_change_standardization_identifiers() -> None:
    preview = _return_preview()
    identity = (preview.source_key, preview.mapping_key, preview.standardization_key)
    validate_standardized_result(preview)
    assert identity == (preview.source_key, preview.mapping_key, preview.standardization_key)


def test_bridge_has_no_file_path_or_raw_byte_fields() -> None:
    field_names = {item.name for item in fields(StrictProtocolResult)}
    assert not {"path", "file_path", "content", "raw_bytes"}.intersection(field_names)


def test_bridge_does_not_write_or_create_temporary_csv(tmp_path: Path) -> None:
    before = set(tmp_path.iterdir())
    strict = validate_standardized_result(_return_preview())
    build_generic_analysis_input(strict)
    assert set(tmp_path.iterdir()) == before


def test_return_generic_path_matches_direct_protocol_data_and_metrics() -> None:
    source = _return_source().rename(
        columns={
            "trade_date": "date",
            "return_value": "strategy_return",
            "benchmark_value": "benchmark_return",
        }
    )
    direct = validate_returns_data(source)
    strict = validate_standardized_result(_return_preview())
    generic = build_generic_analysis_input(strict)
    pdt.assert_frame_equal(generic, direct, check_dtype=False)
    direct_performance = add_performance_series(direct)
    generic_performance = add_performance_series(generic)
    pdt.assert_frame_equal(generic_performance, direct_performance, check_dtype=False)
    assert calculate_performance_metrics(generic) == calculate_performance_metrics(direct)


def test_return_generic_path_matches_direct_report_and_export_data() -> None:
    source = _return_source().rename(
        columns={
            "trade_date": "date",
            "return_value": "strategy_return",
            "benchmark_value": "benchmark_return",
        }
    )
    direct = validate_returns_data(source)
    generic = build_generic_analysis_input(validate_standardized_result(_return_preview()))
    direct_metrics = calculate_performance_metrics(direct)
    generic_metrics = calculate_performance_metrics(generic)
    direct_performance = add_performance_series(direct)
    generic_performance = add_performance_series(generic)
    direct_context = _report_context(direct, direct_metrics, nav=False)
    generic_context = _report_context(generic, generic_metrics, nav=False)
    assert generate_analysis_summary(generic_context) == generate_analysis_summary(direct_context)
    assert generate_markdown_report(generic_context) == generate_markdown_report(direct_context)
    pdt.assert_frame_equal(
        build_standardized_data(generic_performance),
        build_standardized_data(direct_performance),
    )


def test_nav_generic_path_matches_direct_adapter_data_diagnostics_and_metrics() -> None:
    source = _nav_source().rename(
        columns={
            "trade_date": "date",
            "nav_value": "nav_strat",
            "daily_value": "daily_ret",
        }
    )
    direct_result = adapt_weekly_nav_data(source)
    strict = validate_standardized_result(_nav_preview())
    generic = build_generic_analysis_input(strict)
    pdt.assert_frame_equal(generic, direct_result.data, check_dtype=False)
    assert strict.adapter_diagnostics.comparison_count == direct_result.diagnostics.comparison_count
    assert strict.adapter_diagnostics.mismatch_count == direct_result.diagnostics.mismatch_count
    assert strict.adapter_diagnostics.max_absolute_difference == pytest.approx(
        direct_result.diagnostics.max_absolute_difference
    )
    assert strict.adapter_diagnostics.mean_absolute_difference == pytest.approx(
        direct_result.diagnostics.mean_absolute_difference
    )
    pdt.assert_frame_equal(
        strict.adapter_diagnostics.mismatches,
        direct_result.diagnostics.mismatches,
        check_dtype=False,
    )
    assert calculate_nav_performance_metrics(generic) == calculate_nav_performance_metrics(direct_result.data)


def test_nav_generic_path_matches_direct_report_chart_and_export_data() -> None:
    source = _nav_source().rename(
        columns={
            "trade_date": "date",
            "nav_value": "nav_strat",
            "daily_value": "daily_ret",
        }
    )
    direct_result = adapt_weekly_nav_data(source)
    strict = validate_standardized_result(_nav_preview())
    generic = build_generic_analysis_input(strict)
    direct_metrics = calculate_nav_performance_metrics(direct_result.data)
    generic_metrics = calculate_nav_performance_metrics(generic)
    direct_performance = add_nav_performance_series(direct_result.data)
    generic_performance = add_nav_performance_series(generic)
    pdt.assert_frame_equal(generic_performance, direct_performance, check_dtype=False)
    direct_context = _report_context(
        direct_result.data,
        direct_metrics,
        nav=True,
        diagnostics=direct_result.diagnostics,
    )
    generic_context = _report_context(
        generic,
        generic_metrics,
        nav=True,
        diagnostics=strict.adapter_diagnostics,
    )
    assert generate_analysis_summary(generic_context) == generate_analysis_summary(direct_context)
    assert generate_markdown_report(generic_context) == generate_markdown_report(direct_context)
    pdt.assert_frame_equal(
        build_standardized_data(generic_performance),
        build_standardized_data(direct_performance),
    )


def test_strict_result_counts_dates_and_benchmark_are_auditable() -> None:
    strict = validate_standardized_result(_return_preview())
    assert strict.row_count == 4
    assert strict.valid_observation_count == 4
    assert strict.date_start == pd.Timestamp("2026-01-02")
    assert strict.date_end == pd.Timestamp("2026-01-07")
    assert strict.has_benchmark


def test_nav_strict_result_reports_effective_return_count_and_diagnostics() -> None:
    strict = validate_standardized_result(_nav_preview())
    assert strict.row_count == 4
    assert strict.valid_observation_count == 3
    assert strict.adapter_diagnostics.comparison_count == 3
    assert strict.adapter_diagnostics.mismatch_count == 0


def test_same_input_produces_repeatable_strict_result() -> None:
    first = validate_standardized_result(_return_preview())
    second = validate_standardized_result(_return_preview())
    assert first.analysis_request_key == second.analysis_request_key
    assert first.errors == second.errors
    assert first.warnings == second.warnings
    pdt.assert_frame_equal(first.validated_frame, second.validated_frame)
