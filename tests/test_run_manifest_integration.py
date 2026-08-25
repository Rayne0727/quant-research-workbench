"""Integration contracts for downloadable single-analysis Run Manifests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError
from io import BytesIO
from types import MappingProxyType

import pandas as pd
import pytest

from src.adapters import DEFAULT_RETURN_TOLERANCE, adapt_weekly_nav_data
from src.analysis_bridge import (
    NAV_ADAPTER_VERSION,
    StrictProtocolResult,
    build_generic_analysis_input,
    validate_standardized_result,
)
from src.field_detection import ROLE_ORDER
from src.field_mapping import (
    PRIMARY_BASIS_NAV,
    PRIMARY_BASIS_RETURN,
    ConfirmedMapping,
    build_mapping_source_key,
)
from src.file_import import ImportedTable, import_table
from src.performance import (
    add_nav_performance_series,
    add_performance_series,
    calculate_nav_performance_metrics,
    calculate_performance_metrics,
)
from src.reporting import (
    ReportContext,
    generate_markdown_report,
    generate_standardized_csv,
)
from src.run_manifest import (
    MANIFEST_SCHEMA_VERSION,
    ApplicationMetadata,
    EnvironmentMetadata,
    make_manifest_filename,
)
from src.run_manifest_integration import (
    MANIFEST_MIME_TYPE,
    ManifestExport,
    ManifestIntegrationError,
    build_application_metadata,
    build_direct_nav_manifest_export,
    build_direct_return_manifest_export,
    build_environment_metadata,
    build_generic_nav_manifest_export,
    build_generic_return_manifest_export,
    manifest_export_matches,
)
from src.standardization import StandardizationResult, standardize_confirmed_mapping

GENERATED_AT = datetime(2026, 8, 25, 9, 30, tzinfo=UTC)
APPLICATION = ApplicationMetadata(version="0.3.0", build_revision=None)
ENVIRONMENT = EnvironmentMetadata(
    python="3.14.2",
    pandas="3.0.5",
    numpy="2.5.1",
    streamlit="1.60.0",
    openpyxl="3.1.5",
)
FULL_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class _GenericContext:
    raw_bytes: bytes
    imported_table: ImportedTable
    confirmed_mapping: ConfirmedMapping
    standardization_result: StandardizationResult
    analysis_data: pd.DataFrame
    strict_result: StrictProtocolResult


def _return_analysis_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]),
            "strategy_return": [0.01, -0.005, 0.012, 0.003],
        }
    )


def _nav_source_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23"]),
            "nav_strat": [100.0, 102.0, 101.0, 104.0],
            "daily_ret": [0.0, 0.02, -0.00980392156862745, 0.0297029702970297],
        }
    )


def _mapping(
    imported: ImportedTable,
    raw_bytes: bytes,
    *,
    primary_basis: str,
    value_column: str,
) -> ConfirmedMapping:
    source_key = build_mapping_source_key(
        content=raw_bytes,
        file_type=imported.file_type,
        sheet_name=imported.sheet_name,
        encoding=imported.encoding,
        delimiter=imported.delimiter,
        header_rule="first_row",
        columns=imported.column_names,
    )
    role_to_column = {role: None for role in ROLE_ORDER}
    role_to_column["date"] = "trade_date"
    role_to_column[primary_basis] = value_column
    if primary_basis == PRIMARY_BASIS_NAV and "daily_value" in imported.column_names:
        role_to_column["daily_ret"] = "daily_value"
    return ConfirmedMapping(
        source_key=source_key,
        primary_basis=primary_basis,
        role_to_column=MappingProxyType(role_to_column),
        warnings=(),
    )


def _generic_context(
    *,
    nav: bool = False,
    value_column: str | None = None,
    imported_table: ImportedTable | None = None,
    raw_bytes: bytes | None = None,
) -> _GenericContext:
    if nav:
        source = pd.DataFrame(
            {
                "trade_date": ["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23"],
                "nav_value": [100.0, 102.0, 101.0, 104.0],
                "daily_value": [0.0, 0.02, -0.00980392156862745, 0.0297029702970297],
            }
        )
        basis = PRIMARY_BASIS_NAV
        resolved_column = value_column or "nav_value"
    else:
        source = pd.DataFrame(
            {
                "trade_date": ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
                "return_value": [0.01, -0.005, 0.012, 0.003],
                "alt_return": [0.01, -0.005, 0.012, 0.003],
            }
        )
        basis = PRIMARY_BASIS_RETURN
        resolved_column = value_column or "return_value"
    resolved_bytes = raw_bytes or source.to_csv(index=False).encode("utf-8")
    resolved_import = imported_table or import_table("generic.csv", resolved_bytes)
    confirmed = _mapping(
        resolved_import,
        resolved_bytes,
        primary_basis=basis,
        value_column=resolved_column,
    )
    standardization = standardize_confirmed_mapping(resolved_import.dataframe, confirmed)
    strict = validate_standardized_result(standardization)
    return _GenericContext(
        raw_bytes=resolved_bytes,
        imported_table=resolved_import,
        confirmed_mapping=confirmed,
        standardization_result=standardization,
        analysis_data=build_generic_analysis_input(strict),
        strict_result=strict,
    )


def _generic_return_export(
    context: _GenericContext,
    *,
    cached_export: ManifestExport | None = None,
) -> ManifestExport:
    return build_generic_return_manifest_export(
        analysis_data=context.analysis_data,
        raw_source_bytes=context.raw_bytes,
        imported_table=context.imported_table,
        confirmed_mapping=context.confirmed_mapping,
        standardization_result=context.standardization_result,
        strict_result=context.strict_result,
        cached_export=cached_export,
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )


def _generic_nav_export(context: _GenericContext) -> ManifestExport:
    return build_generic_nav_manifest_export(
        analysis_data=context.analysis_data,
        raw_source_bytes=context.raw_bytes,
        imported_table=context.imported_table,
        confirmed_mapping=context.confirmed_mapping,
        standardization_result=context.standardization_result,
        strict_result=context.strict_result,
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )


def test_runtime_metadata_builders_use_current_application_and_packages() -> None:
    application = build_application_metadata()
    environment = build_environment_metadata()

    assert application.name == "Quant Research Workbench"
    assert application.version == "0.3.0"
    assert application.build_revision is None
    assert environment.python
    assert environment.pandas
    assert environment.numpy
    assert environment.streamlit
    assert environment.openpyxl


def test_direct_return_export_has_core_filename_mime_and_full_identities() -> None:
    raw = b"date,strategy_return\n2026-01-02,0.01\n"
    export = build_direct_return_manifest_export(
        analysis_data=_return_analysis_data(),
        raw_source_bytes=raw,
        display_filename=r"C:\private\returns.csv",
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    payload = json.loads(export.json_bytes)

    assert payload["schema_version"] == MANIFEST_SCHEMA_VERSION == "qrw-run-manifest-v2"
    assert FULL_SHA256.fullmatch(payload["identity"]["analysis_id"])
    assert FULL_SHA256.fullmatch(payload["identity"]["run_id"])
    assert FULL_SHA256.fullmatch(payload["source"]["sha256"])
    assert FULL_SHA256.fullmatch(payload["analysis"]["standardized_data_sha256"])
    assert export.filename == make_manifest_filename(export.manifest.run_identity.run_id)
    assert export.mime_type == MANIFEST_MIME_TYPE == "application/json"
    assert payload["source"]["display_filename"] == "returns.csv"


def test_direct_nav_export_records_real_adapter_contract() -> None:
    analysis_data = adapt_weekly_nav_data(_nav_source_data()).data
    export = build_direct_nav_manifest_export(
        analysis_data=analysis_data,
        raw_source_bytes=b"direct nav bytes",
        display_filename="nav.csv",
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    transformation = json.loads(export.json_bytes)["transformation"]

    assert transformation["adapter_version"] == NAV_ADAPTER_VERSION
    assert transformation["return_tolerance"] == DEFAULT_RETURN_TOLERANCE.hex()
    assert export.manifest.analysis_identity.analysis_mode == "nav"


def test_generic_return_export_has_real_provenance_without_nav_padding() -> None:
    context = _generic_context()
    export = _generic_return_export(context)
    transformation = json.loads(export.json_bytes)["transformation"]

    assert transformation["interpretation"]["encoding"] == context.imported_table.encoding
    assert transformation["mapping"]
    assert transformation["validation_protocol_version"] == context.strict_result.protocol_version
    assert transformation["workflow_keys"]["analysis_request_key"] == (
        context.strict_result.analysis_request_key
    )
    assert "adapter_version" not in transformation
    assert "return_tolerance" not in transformation


def test_generic_nav_export_records_real_adapter_and_tolerance() -> None:
    context = _generic_context(nav=True)
    export = _generic_nav_export(context)
    transformation = json.loads(export.json_bytes)["transformation"]

    assert transformation["adapter_version"] == context.strict_result.adapter_version
    assert transformation["adapter_version"] == NAV_ADAPTER_VERSION
    assert transformation["return_tolerance"] == DEFAULT_RETURN_TOLERANCE.hex()


def test_direct_and_generic_return_share_analysis_id_but_not_run_id() -> None:
    context = _generic_context()
    direct = build_direct_return_manifest_export(
        analysis_data=context.analysis_data,
        raw_source_bytes=context.raw_bytes,
        display_filename="generic.csv",
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    generic = _generic_return_export(context)

    assert (
        direct.manifest.analysis_identity.analysis_id
        == generic.manifest.analysis_identity.analysis_id
    )
    assert direct.manifest.run_identity.run_id != generic.manifest.run_identity.run_id


def test_direct_and_generic_nav_share_analysis_id_but_not_run_id() -> None:
    context = _generic_context(nav=True)
    direct = build_direct_nav_manifest_export(
        analysis_data=context.analysis_data,
        raw_source_bytes=context.raw_bytes,
        display_filename="generic.csv",
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    generic = _generic_nav_export(context)

    assert (
        direct.manifest.analysis_identity.analysis_id
        == generic.manifest.analysis_identity.analysis_id
    )
    assert direct.manifest.run_identity.run_id != generic.manifest.run_identity.run_id


def test_unchanged_rerun_reuses_export_and_generated_at() -> None:
    context = _generic_context()
    first = _generic_return_export(context)
    second = build_generic_return_manifest_export(
        analysis_data=context.analysis_data,
        raw_source_bytes=context.raw_bytes,
        imported_table=context.imported_table,
        confirmed_mapping=context.confirmed_mapping,
        standardization_result=context.standardization_result,
        strict_result=context.strict_result,
        cached_export=first,
        generated_at=GENERATED_AT + timedelta(days=1),
        application=APPLICATION,
        environment=ENVIRONMENT,
    )

    assert second is first
    assert manifest_export_matches(first, second.cache_signature)
    assert second.manifest.generated_at_utc == "2026-08-25T09:30:00Z"


def test_filename_only_change_updates_metadata_without_changing_ids() -> None:
    data = _return_analysis_data()
    first = build_direct_return_manifest_export(
        analysis_data=data,
        raw_source_bytes=b"same bytes",
        display_filename="first.csv",
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    second = build_direct_return_manifest_export(
        analysis_data=data,
        raw_source_bytes=b"same bytes",
        display_filename="renamed.csv",
        cached_export=first,
        generated_at=GENERATED_AT + timedelta(days=1),
        application=APPLICATION,
        environment=ENVIRONMENT,
    )

    assert second is not first
    assert (
        second.manifest.analysis_identity.analysis_id
        == first.manifest.analysis_identity.analysis_id
    )
    assert second.manifest.run_identity.run_id == first.manifest.run_identity.run_id
    assert second.manifest.source.display_filename == "renamed.csv"


def test_source_change_invalidates_cached_export() -> None:
    data = _return_analysis_data()
    first = build_direct_return_manifest_export(
        analysis_data=data,
        raw_source_bytes=b"source one",
        display_filename="returns.csv",
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    second = build_direct_return_manifest_export(
        analysis_data=data,
        raw_source_bytes=b"source two",
        display_filename="returns.csv",
        cached_export=first,
        generated_at=GENERATED_AT + timedelta(days=1),
        application=APPLICATION,
        environment=ENVIRONMENT,
    )

    assert second is not first
    assert second.manifest.run_identity.run_id != first.manifest.run_identity.run_id


def test_mapping_change_invalidates_cached_export() -> None:
    first_context = _generic_context(value_column="return_value")
    second_context = _generic_context(value_column="alt_return")
    first = _generic_return_export(first_context)
    second = _generic_return_export(second_context, cached_export=first)

    assert second is not first
    assert (
        second.manifest.analysis_identity.analysis_id
        == first.manifest.analysis_identity.analysis_id
    )
    assert second.manifest.run_identity.run_id != first.manifest.run_identity.run_id


def test_xlsx_sheet_change_invalidates_cached_export() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
            "return_value": [0.01, -0.005, 0.012, 0.003],
            "alt_return": [0.01, -0.005, 0.012, 0.003],
        }
    )
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="First", index=False)
        frame.to_excel(writer, sheet_name="Second", index=False)
    raw = workbook.getvalue()
    first_context = _generic_context(
        imported_table=import_table("book.xlsx", raw, sheet_name="First"),
        raw_bytes=raw,
    )
    second_context = _generic_context(
        imported_table=import_table("book.xlsx", raw, sheet_name="Second"),
        raw_bytes=raw,
    )
    first = _generic_return_export(first_context)
    second = _generic_return_export(second_context, cached_export=first)

    assert second is not first
    assert (
        second.manifest.analysis_identity.analysis_id
        == first.manifest.analysis_identity.analysis_id
    )
    assert second.manifest.run_identity.run_id != first.manifest.run_identity.run_id


def test_request_workflow_change_invalidates_without_polluting_return_identity() -> None:
    context = _generic_context()
    changed_strict = validate_standardized_result(
        context.standardization_result,
        adapter_version="unused-return-adapter-v2",
    )
    changed_context = replace(context, strict_result=changed_strict)
    first = _generic_return_export(context)
    second = _generic_return_export(changed_context, cached_export=first)

    assert second is not first
    assert (
        second.manifest.analysis_identity.analysis_id
        == first.manifest.analysis_identity.analysis_id
    )
    assert second.manifest.run_identity.run_id == first.manifest.run_identity.run_id
    assert second.cache_signature.workflow_keys != first.cache_signature.workflow_keys


def test_application_or_environment_change_invalidates_cache_but_not_ids() -> None:
    data = _return_analysis_data()
    first = build_direct_return_manifest_export(
        analysis_data=data,
        raw_source_bytes=b"same bytes",
        display_filename="returns.csv",
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    changed_environment = replace(ENVIRONMENT, pandas="3.1.0")
    second = build_direct_return_manifest_export(
        analysis_data=data,
        raw_source_bytes=b"same bytes",
        display_filename="returns.csv",
        cached_export=first,
        generated_at=GENERATED_AT + timedelta(days=1),
        application=APPLICATION,
        environment=changed_environment,
    )

    assert second is not first
    assert (
        second.manifest.analysis_identity.analysis_id
        == first.manifest.analysis_identity.analysis_id
    )
    assert second.manifest.run_identity.run_id == first.manifest.run_identity.run_id


def test_manifest_json_contains_no_raw_rows_paths_or_ui_metadata() -> None:
    context = _generic_context()
    serialized = _generic_return_export(context).json_bytes.decode("utf-8")

    assert "trade_date" in serialized
    assert '"rows":' not in serialized
    assert "0.012" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized
    for forbidden in ("session_state", "browser", "widget", "raw_rows", "raw_bytes"):
        assert forbidden not in serialized


def test_mismatched_authoritative_frame_is_rejected() -> None:
    context = _generic_context()
    changed = context.analysis_data.copy()
    changed.loc[0, "strategy_return"] = 0.5

    with pytest.raises(ManifestIntegrationError, match=r"authoritative|严格协议|analysis data"):
        build_generic_return_manifest_export(
            analysis_data=changed,
            raw_source_bytes=context.raw_bytes,
            imported_table=context.imported_table,
            confirmed_mapping=context.confirmed_mapping,
            standardization_result=context.standardization_result,
            strict_result=context.strict_result,
            generated_at=GENERATED_AT,
            application=APPLICATION,
            environment=ENVIRONMENT,
        )


def test_generic_context_guards_reject_stale_or_mismatched_artifacts() -> None:
    context = _generic_context()
    invalid_cases = (
        _generic_context(nav=True),
        replace(
            context,
            standardization_result=replace(
                context.standardization_result,
                is_preview_valid=False,
            ),
        ),
        replace(
            context,
            strict_result=replace(
                context.strict_result,
                is_valid=False,
                validated_frame=None,
            ),
        ),
        replace(
            context,
            strict_result=replace(
                context.strict_result,
                analysis_request_key="stale-request-key",
            ),
        ),
        replace(context, raw_bytes=b"different source bytes"),
    )

    for invalid_context in invalid_cases:
        with pytest.raises(ManifestIntegrationError):
            _generic_return_export(invalid_context)


@pytest.mark.parametrize(
    ("file_type", "encoding", "delimiter", "expected_message"),
    (
        ("CSV", None, None, "CSV解析信息不完整"),
        ("JSON", None, None, "解析信息不受"),
    ),
)
def test_generic_interpretation_rejects_incomplete_or_unsupported_metadata(
    file_type: str,
    encoding: str | None,
    delimiter: str | None,
    expected_message: str,
) -> None:
    initial = _generic_context()
    imported = replace(
        initial.imported_table,
        file_type=file_type,
        encoding=encoding,
        delimiter=delimiter,
    )
    context = _generic_context(imported_table=imported, raw_bytes=initial.raw_bytes)

    with pytest.raises(ManifestIntegrationError, match=expected_message):
        _generic_return_export(context)


def test_environment_metadata_allows_optional_openpyxl_to_be_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_openpyxl(package_name: str) -> str:
        if package_name == "openpyxl":
            raise PackageNotFoundError(package_name)
        return "test-version"

    monkeypatch.setattr("src.run_manifest_integration.version", missing_openpyxl)

    environment = build_environment_metadata()

    assert environment.openpyxl is None
    assert environment.pandas == "test-version"


@pytest.mark.parametrize("nav", [False, True])
def test_existing_report_and_standardized_csv_byte_regression(nav: bool) -> None:
    if nav:
        cleaned = adapt_weekly_nav_data(_nav_source_data()).data
        performance_data = add_nav_performance_series(cleaned)
        metrics = calculate_nav_performance_metrics(cleaned)
        diagnostics = adapt_weekly_nav_data(_nav_source_data()).diagnostics
    else:
        cleaned = _return_analysis_data()
        performance_data = add_performance_series(cleaned)
        metrics = calculate_performance_metrics(cleaned)
        diagnostics = None
    context = ReportContext(
        experiment_name="B.1b回归实验",
        strategy_name="固定策略",
        research_notes="固定输入",
        data_format="每周调仓净值 CSV" if nav else "标准日频收益 CSV",
        primary_field="nav_strat" if nav else "strategy_return",
        start_date=pd.Timestamp(metrics["start_date"]),
        end_date=pd.Timestamp(metrics["end_date"]),
        observation_count=len(cleaned),
        valid_return_count=int(metrics["n_days"]),
        metrics=metrics,
        has_benchmark=False,
        diagnostics=diagnostics,
    )
    report_hash = hashlib.sha256(generate_markdown_report(context).encode("utf-8")).hexdigest()
    csv_bytes = generate_standardized_csv(performance_data)
    assert isinstance(csv_bytes, bytes)
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    normalized_csv_bytes = csv_bytes.replace(b"\r\n", b"\n")
    csv_hash = hashlib.sha256(normalized_csv_bytes).hexdigest()

    expected = {
        False: (
            "32dae4b21f14516be6f54074186ac6fed75222b0b7540a051cdafabb10037fdd",
            "82d82a7c7b01275799d5fe23e00d131a8bd129878902753e2dd008697cf7ee57",
        ),
        True: (
            "9c3df073402017245082a74bcf9ba5a8e89096132d976583b975272e8848def5",
            "7973fdd41ac4fff52052038c13feb075e34e5675cf3369c57ca813ac0b4948a5",
        ),
    }
    assert (report_hash, csv_hash) == expected[nav]
