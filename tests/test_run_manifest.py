"""Contract tests for deterministic single-run identities and Manifest JSON."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.analysis_bridge import (
    ANALYSIS_BRIDGE_VERSION,
    NAV_ADAPTER_VERSION,
    STRICT_NAV_PROTOCOL_VERSION,
    STRICT_RETURN_PROTOCOL_VERSION,
)
from src.run_manifest import (
    ANALYSIS_IDENTITY_VERSION,
    CANONICALIZATION_VERSION,
    MANIFEST_SCHEMA_VERSION,
    RUN_IDENTITY_VERSION,
    SINGLE_ANALYSIS_SEMANTICS_VERSION,
    ApplicationMetadata,
    CsvInterpretation,
    DirectStandardProvenance,
    EnvironmentMetadata,
    GenericImportProvenance,
    MappingEntry,
    NavAdapterProvenance,
    RunManifestError,
    WorkflowKeys,
    XlsxInterpretation,
    build_analysis_identity,
    build_canonical_analysis_data,
    build_run_manifest,
    build_source_metadata,
    canonical_json_bytes,
    compute_source_sha256,
    make_manifest_filename,
    manifest_json_bytes,
    manifest_payload,
    mapping_entries,
)
from src.standardization import MAPPING_KEY_POLICY_VERSION, STANDARDIZATION_POLICY_VERSION

GENERATED_AT = datetime(2026, 8, 14, 12, 30, tzinfo=UTC)
RAW_SOURCE = b"date,strategy_return\n2026-01-01,0.01\n"


def _daily_frame(*, benchmark: bool = False) -> pd.DataFrame:
    data: dict[str, object] = {
        "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
        "strategy_return": [0.01, -0.02, 0.03],
    }
    if benchmark:
        data["benchmark_return"] = [0.005, -0.01, 0.02]
    return pd.DataFrame(data)


def _nav_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
            "strategy_nav": [1.0, 1.01, 0.99],
            "strategy_return": [None, 0.01, 0.99 / 1.01 - 1],
            "nav_strat": [100.0, 101.0, 99.0],
            "daily_ret": [None, 0.01, -0.02],
        }
    )


def _application(
    *,
    version: str = "0.2.0",
    build_revision: str | None = "a" * 40,
) -> ApplicationMetadata:
    return ApplicationMetadata(version=version, build_revision=build_revision)


def _environment(*, pandas_version: str = "3.0.5") -> EnvironmentMetadata:
    return EnvironmentMetadata(
        python="3.14.2",
        pandas=pandas_version,
        numpy="2.5.1",
        streamlit="1.60.0",
    )


def _direct(*, workflow_keys: WorkflowKeys | None = None) -> DirectStandardProvenance:
    return DirectStandardProvenance(
        protocol_version=STRICT_RETURN_PROTOCOL_VERSION,
        workflow_keys=workflow_keys,
    )


def _generic(
    *,
    mapping: tuple[MappingEntry, ...] | None = None,
    standardization_policy: str = STANDARDIZATION_POLICY_VERSION,
    interpretation: CsvInterpretation | XlsxInterpretation | None = None,
    workflow_keys: WorkflowKeys | None = None,
) -> GenericImportProvenance:
    return GenericImportProvenance(
        interpretation=interpretation or CsvInterpretation("utf-8", ","),
        mapping=mapping
        or mapping_entries(
            {
                "date": "交易日期",
                "strategy_return": "策略收益率",
            }
        ),
        mapping_policy_version=MAPPING_KEY_POLICY_VERSION,
        standardization_policy_version=standardization_policy,
        validation_protocol_version=STRICT_RETURN_PROTOCOL_VERSION,
        bridge_version=ANALYSIS_BRIDGE_VERSION,
        workflow_keys=workflow_keys,
    )


def _nav(*, tolerance: float = 1e-8) -> NavAdapterProvenance:
    return NavAdapterProvenance(
        protocol_version=STRICT_NAV_PROTOCOL_VERSION,
        adapter_version=NAV_ADAPTER_VERSION,
        return_tolerance=tolerance,
    )


def _manifest(
    *,
    data: pd.DataFrame | None = None,
    raw_source: bytes = RAW_SOURCE,
    provenance: DirectStandardProvenance | GenericImportProvenance | None = None,
    application: ApplicationMetadata | None = None,
    environment: EnvironmentMetadata | None = None,
    generated_at: datetime = GENERATED_AT,
    display_filename: str | None = "returns.csv",
    semantics_version: str = SINGLE_ANALYSIS_SEMANTICS_VERSION,
):
    return build_run_manifest(
        analysis_data=data if data is not None else _daily_frame(),
        analysis_mode="daily_return",
        raw_source_bytes=raw_source,
        provenance=provenance or _direct(),
        application=application or _application(),
        environment=environment or _environment(),
        generated_at=generated_at,
        display_filename=display_filename,
        semantics_version=semantics_version,
    )


def test_identity_versions_are_independent_from_app_version() -> None:
    assert MANIFEST_SCHEMA_VERSION == "qrw-run-manifest-v1"
    assert CANONICALIZATION_VERSION == "qrw-run-canonicalization-v1"
    assert ANALYSIS_IDENTITY_VERSION == "qrw-analysis-identity-v1"
    assert RUN_IDENTITY_VERSION == "qrw-run-identity-v1"
    assert SINGLE_ANALYSIS_SEMANTICS_VERSION == "qrw-single-analysis-v1"


def test_same_analysis_input_has_same_standardized_data_sha256() -> None:
    first = build_canonical_analysis_data(_daily_frame(), "daily_return")
    second = build_canonical_analysis_data(_daily_frame(), "daily_return")

    assert first.standardized_data_sha256 == second.standardized_data_sha256


def test_same_semantic_analysis_has_same_analysis_id() -> None:
    first = build_analysis_identity(build_canonical_analysis_data(_daily_frame(), "daily_return"))
    second = build_analysis_identity(build_canonical_analysis_data(_daily_frame(), "daily_return"))

    assert first.analysis_id == second.analysis_id


def test_same_provenance_has_same_run_id() -> None:
    assert _manifest().run_identity.run_id == _manifest().run_identity.run_id


def test_generated_at_changes_without_changing_ids() -> None:
    first = _manifest(generated_at=GENERATED_AT)
    second = _manifest(generated_at=GENERATED_AT + timedelta(days=1))

    assert first.analysis_identity.analysis_id == second.analysis_identity.analysis_id
    assert first.run_identity.run_id == second.run_identity.run_id
    assert manifest_json_bytes(first) != manifest_json_bytes(second)


def test_environment_changes_without_changing_ids() -> None:
    first = _manifest(environment=_environment(pandas_version="3.0.5"))
    second = _manifest(environment=_environment(pandas_version="3.1.0"))

    assert first.analysis_identity.analysis_id == second.analysis_identity.analysis_id
    assert first.run_identity.run_id == second.run_identity.run_id


@pytest.mark.parametrize(
    "application",
    [
        _application(version="0.3.0"),
        _application(build_revision="b" * 40),
        _application(build_revision=None),
    ],
)
def test_application_metadata_changes_without_changing_ids(
    application: ApplicationMetadata,
) -> None:
    first = _manifest()
    second = _manifest(application=application)

    assert first.analysis_identity.analysis_id == second.analysis_identity.analysis_id
    assert first.run_identity.run_id == second.run_identity.run_id


def test_filename_changes_without_changing_any_identity() -> None:
    first = _manifest(display_filename="first.csv")
    second = _manifest(display_filename="renamed.csv")

    assert first.source.source_sha256 == second.source.source_sha256
    assert first.analysis_identity.analysis_id == second.analysis_identity.analysis_id
    assert first.run_identity.run_id == second.run_identity.run_id


def test_raw_bytes_change_only_run_id_when_analysis_is_same() -> None:
    first = _manifest(raw_source=b"first source")
    second = _manifest(raw_source=b"second source")

    assert first.analysis_identity.analysis_id == second.analysis_identity.analysis_id
    assert first.run_identity.run_id != second.run_identity.run_id


def test_analysis_data_change_changes_both_ids() -> None:
    changed = _daily_frame()
    changed.loc[1, "strategy_return"] = -0.03

    first = _manifest()
    second = _manifest(data=changed)

    assert first.analysis_identity.analysis_id != second.analysis_identity.analysis_id
    assert first.run_identity.run_id != second.run_identity.run_id


def test_mapping_change_only_changes_run_id_when_data_is_same() -> None:
    first = _manifest(provenance=_generic())
    second = _manifest(
        provenance=_generic(
            mapping=mapping_entries(
                {
                    "date": "日期",
                    "strategy_return": "收益",
                }
            )
        )
    )

    assert first.analysis_identity.analysis_id == second.analysis_identity.analysis_id
    assert first.run_identity.run_id != second.run_identity.run_id


def test_standardization_policy_only_changes_run_id() -> None:
    first = _manifest(provenance=_generic(standardization_policy="standardization-v1"))
    second = _manifest(provenance=_generic(standardization_policy="standardization-v2"))

    assert first.analysis_identity.analysis_id == second.analysis_identity.analysis_id
    assert first.run_identity.run_id != second.run_identity.run_id


def test_analysis_semantics_change_changes_both_ids() -> None:
    first = _manifest(semantics_version="analysis-v1")
    second = _manifest(semantics_version="analysis-v2")

    assert first.analysis_identity.analysis_id != second.analysis_identity.analysis_id
    assert first.run_identity.run_id != second.run_identity.run_id


def test_benchmark_content_change_changes_both_ids() -> None:
    first_data = _daily_frame(benchmark=True)
    second_data = _daily_frame(benchmark=True)
    second_data.loc[1, "benchmark_return"] = -0.02

    first = _manifest(data=first_data)
    second = _manifest(data=second_data)

    assert first.analysis_identity.analysis_id != second.analysis_identity.analysis_id
    assert first.run_identity.run_id != second.run_identity.run_id


def test_mapping_dict_insertion_order_does_not_change_run_id() -> None:
    first_mapping = {"date": "交易日期", "strategy_return": "策略收益率"}
    second_mapping = {"strategy_return": "策略收益率", "date": "交易日期"}

    first = _manifest(provenance=_generic(mapping=mapping_entries(first_mapping)))
    second = _manifest(provenance=_generic(mapping=mapping_entries(second_mapping)))

    assert first.run_identity.run_id == second.run_identity.run_id


def test_mapping_tuple_order_does_not_change_run_id() -> None:
    entries = (
        MappingEntry("strategy_return", "策略收益率"),
        MappingEntry("date", "交易日期"),
    )
    first = _manifest(provenance=_generic(mapping=entries))
    second = _manifest(provenance=_generic(mapping=tuple(reversed(entries))))

    assert first.run_identity.run_id == second.run_identity.run_id


def test_unicode_composed_and_decomposed_strings_have_same_run_id() -> None:
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")
    first = _manifest(provenance=_generic(mapping=(MappingEntry("date", composed),)))
    second = _manifest(provenance=_generic(mapping=(MappingEntry("date", decomposed),)))

    assert first.run_identity.run_id == second.run_identity.run_id


def test_negative_zero_and_zero_have_same_data_identity() -> None:
    negative = _daily_frame()
    positive = _daily_frame()
    negative.loc[1, "strategy_return"] = -0.0
    positive.loc[1, "strategy_return"] = 0.0

    assert (
        build_canonical_analysis_data(negative, "daily_return").standardized_data_sha256
        == build_canonical_analysis_data(positive, "daily_return").standardized_data_sha256
    )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_invalid_strategy_number_is_rejected(invalid: float) -> None:
    data = _daily_frame()
    data.loc[1, "strategy_return"] = invalid

    with pytest.raises(RunManifestError, match=r"有限|缺失"):
        build_canonical_analysis_data(data, "daily_return")


def test_nav_first_return_missing_is_canonical_null() -> None:
    result = build_canonical_analysis_data(_nav_frame(), "nav")

    assert result.rows[0][2] is None
    assert result.rows[1][2] is not None


def test_nav_later_return_missing_is_rejected() -> None:
    data = _nav_frame()
    data.loc[1, "strategy_return"] = None

    with pytest.raises(RunManifestError, match="不允许缺失"):
        build_canonical_analysis_data(data, "nav")


def test_optional_benchmark_missing_is_canonical_null() -> None:
    data = _daily_frame(benchmark=True)
    data.loc[1, "benchmark_return"] = None

    result = build_canonical_analysis_data(data, "daily_return")

    assert result.rows[1][2] is None


def test_dataframe_index_does_not_change_data_hash() -> None:
    first = _daily_frame()
    second = _daily_frame()
    second.index = [10, 20, 30]

    assert (
        build_canonical_analysis_data(first, "daily_return").standardized_data_sha256
        == build_canonical_analysis_data(second, "daily_return").standardized_data_sha256
    )


def test_row_order_changes_data_hash_without_automatic_sorting() -> None:
    first = _daily_frame()
    second = _daily_frame().iloc[::-1].reset_index(drop=True)

    assert (
        build_canonical_analysis_data(first, "daily_return").standardized_data_sha256
        != build_canonical_analysis_data(second, "daily_return").standardized_data_sha256
    )


def test_dataframe_column_order_uses_fixed_consumed_column_contract() -> None:
    first = _daily_frame(benchmark=True)
    second = first.loc[:, ["benchmark_return", "strategy_return", "date"]]

    first_result = build_canonical_analysis_data(first, "daily_return")
    second_result = build_canonical_analysis_data(second, "daily_return")

    assert first_result.columns == ("date", "strategy_return", "benchmark_return")
    assert first_result.standardized_data_sha256 == second_result.standardized_data_sha256


def test_unconsumed_diagnostic_columns_do_not_change_analysis_id() -> None:
    first = _daily_frame()
    second = _daily_frame().assign(drawdown=[0.0, -0.02, 0.0], daily_ret=[1.0, 2.0, 3.0])

    assert (
        build_canonical_analysis_data(first, "daily_return").standardized_data_sha256
        == build_canonical_analysis_data(second, "daily_return").standardized_data_sha256
    )


def test_same_workbook_bytes_different_sheet_changes_only_run_id() -> None:
    first = _manifest(
        provenance=_generic(interpretation=XlsxInterpretation("Sheet1")),
        raw_source=b"same workbook bytes",
    )
    second = _manifest(
        provenance=_generic(interpretation=XlsxInterpretation("Sheet2")),
        raw_source=b"same workbook bytes",
    )

    assert first.source.source_sha256 == second.source.source_sha256
    assert first.analysis_identity.analysis_id == second.analysis_identity.analysis_id
    assert first.run_identity.run_id != second.run_identity.run_id


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"C:\Users\Example\secret.csv", "secret.csv"),
        ("/home/example/secret.csv", "secret.csv"),
    ],
)
def test_absolute_path_is_reduced_to_basename(path: str, expected: str) -> None:
    manifest = _manifest(display_filename=path)
    serialized = manifest_json_bytes(manifest).decode("utf-8")

    assert manifest.source.display_filename == expected
    assert expected in serialized
    assert "Users" not in serialized
    assert "/home/" not in serialized


def test_manifest_does_not_contain_raw_source_contents() -> None:
    sensitive = b"client_secret_strategy_return=0.123456"

    serialized = manifest_json_bytes(_manifest(raw_source=sensitive))

    assert sensitive not in serialized
    assert b"client_secret" not in serialized


@pytest.mark.parametrize(
    "forbidden",
    ["session_state", "browser", "widget", "absolute_path", "file_path", "raw_bytes"],
)
def test_manifest_contains_no_ui_session_or_path_metadata(forbidden: str) -> None:
    assert forbidden not in manifest_json_bytes(_manifest()).decode("utf-8").lower()


def test_all_public_hashes_use_full_prefixed_sha256() -> None:
    manifest = _manifest()
    pattern = re.compile(r"^sha256:[0-9a-f]{64}$")

    assert pattern.fullmatch(manifest.source.source_sha256)
    assert pattern.fullmatch(manifest.analysis_identity.standardized_data_sha256)
    assert pattern.fullmatch(manifest.analysis_identity.analysis_id)
    assert pattern.fullmatch(manifest.run_identity.run_id)


def test_manifest_filename_is_deterministic_and_safe() -> None:
    run_id = _manifest().run_identity.run_id

    filename = make_manifest_filename(run_id)

    assert filename == f"qrw_run_{run_id.removeprefix('sha256:')[:16]}.json"
    assert re.fullmatch(r"qrw_run_[0-9a-f]{16}\.json", filename)
    assert "returns" not in filename


def test_manifest_json_is_deterministic_for_same_complete_object() -> None:
    manifest = _manifest()

    assert manifest_json_bytes(manifest) == manifest_json_bytes(manifest)
    assert not manifest_json_bytes(manifest).endswith(b"\n")


def test_canonical_json_ignores_mapping_insertion_order() -> None:
    first = {"b": 2, "a": 1}
    second = {"a": 1, "b": 2}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_direct_and_generic_share_analysis_id_but_not_run_id() -> None:
    direct = _manifest(provenance=_direct())
    generic = _manifest(provenance=_generic())

    assert direct.analysis_identity.analysis_id == generic.analysis_identity.analysis_id
    assert direct.run_identity.run_id != generic.run_identity.run_id


def test_nav_and_daily_return_modes_do_not_force_false_equivalence() -> None:
    daily = build_analysis_identity(build_canonical_analysis_data(_daily_frame(), "daily_return"))
    nav = build_analysis_identity(build_canonical_analysis_data(_nav_frame(), "nav"))

    assert daily.analysis_id != nav.analysis_id


def test_nav_provenance_builds_nav_manifest() -> None:
    manifest = build_run_manifest(
        analysis_data=_nav_frame(),
        analysis_mode="nav",
        raw_source_bytes=b"nav source",
        provenance=_nav(),
        application=_application(),
        environment=_environment(),
        generated_at=GENERATED_AT,
        display_filename="nav.csv",
    )

    assert manifest.run_identity.input_mode == "nav_adapter"
    assert manifest.data_summary.valid_return_count == 2
    assert manifest.data_summary.strategy_nav_present is True


@pytest.mark.parametrize(
    ("analysis_mode", "provenance"),
    [("nav", _direct()), ("daily_return", _nav())],
)
def test_provenance_must_match_real_analysis_mode(
    analysis_mode: str,
    provenance: DirectStandardProvenance | NavAdapterProvenance,
) -> None:
    data = _nav_frame() if analysis_mode == "nav" else _daily_frame()

    with pytest.raises(RunManifestError, match="analysis mode"):
        build_run_manifest(
            analysis_data=data,
            analysis_mode=analysis_mode,
            raw_source_bytes=RAW_SOURCE,
            provenance=provenance,
            application=_application(),
            environment=_environment(),
            generated_at=GENERATED_AT,
        )


def test_timezone_aware_dates_are_normalized_to_utc() -> None:
    first = _daily_frame()
    second = _daily_frame()
    first["date"] = [
        datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8))),
        datetime(2026, 1, 2, 8, tzinfo=timezone(timedelta(hours=8))),
        datetime(2026, 1, 5, 8, tzinfo=timezone(timedelta(hours=8))),
    ]
    second["date"] = [
        datetime(2026, 1, 1, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 0, tzinfo=UTC),
    ]

    assert (
        build_canonical_analysis_data(first, "daily_return").standardized_data_sha256
        == build_canonical_analysis_data(second, "daily_return").standardized_data_sha256
    )


def test_timezone_naive_generated_at_is_rejected() -> None:
    with pytest.raises(RunManifestError, match="timezone"):
        _manifest(generated_at=datetime(2026, 8, 14, 12, 30))


def test_workflow_keys_are_serialized_but_do_not_define_run_id() -> None:
    first_keys = WorkflowKeys(source_key="a" * 64, analysis_request_key="b" * 64)
    second_keys = WorkflowKeys(source_key="c" * 64, analysis_request_key="d" * 64)
    first = _manifest(provenance=_direct(workflow_keys=first_keys))
    second = _manifest(provenance=_direct(workflow_keys=second_keys))

    assert first.run_identity.run_id == second.run_identity.run_id
    assert manifest_payload(first)["transformation"] != manifest_payload(second)["transformation"]


def test_source_sha_is_exact_raw_bytes_only() -> None:
    raw = b"same semantic data\r\n"

    assert (
        compute_source_sha256(raw)
        == build_source_metadata(
            raw,
            display_filename="one.csv",
        ).source_sha256
    )
    assert compute_source_sha256(raw) != compute_source_sha256(raw.replace(b"\r\n", b"\n"))


def test_invalid_full_sha_is_rejected_by_filename_builder() -> None:
    with pytest.raises(RunManifestError, match="64"):
        make_manifest_filename("abc")


def test_golden_reference_file_identity_contract() -> None:
    path = Path("assets/reference_files/valid/03_generic_cn_returns.csv")
    raw = path.read_bytes()
    imported = pd.read_csv(path).rename(
        columns={
            "交易日期": "date",
            "策略收益率": "strategy_return",
            "基准收益率": "benchmark_return",
        }
    )
    manifest = build_run_manifest(
        analysis_data=imported,
        analysis_mode="daily_return",
        raw_source_bytes=raw,
        provenance=_generic(
            mapping=mapping_entries(
                {
                    "date": "交易日期",
                    "strategy_return": "策略收益率",
                    "benchmark_return": "基准收益率",
                }
            )
        ),
        application=_application(),
        environment=_environment(),
        generated_at=GENERATED_AT,
        display_filename=path.name,
    )

    assert manifest.source.source_sha256 == (
        "sha256:11c892d66399ee948bc2a3dcdd4c2b11b6d4c5c948062cd962579daf793d61a5"
    )
    assert manifest.analysis_identity.standardized_data_sha256 == (
        "sha256:7c97657012dd132d6bc835ee0bf859ba7e5d4130450bafa4c4e36bbd577b8a7b"
    )
    assert manifest.analysis_identity.analysis_id == (
        "sha256:a102bb94927dd3612f77c34a6fa345d7128b2ad5ebd20a45c349c1f8b80f3898"
    )
    assert manifest.run_identity.run_id == (
        "sha256:4fe36a699745ef5273b54cd4c414dcc617bd8ec35f5619be7d4c2634910f5bc3"
    )


def test_manifest_schema_contains_required_sections_without_null_padding() -> None:
    payload = manifest_payload(
        _manifest(display_filename=None, application=_application(build_revision=None))
    )

    assert set(payload) == {
        "analysis",
        "application",
        "data_summary",
        "environment",
        "generated_at_utc",
        "identity",
        "schema_version",
        "source",
        "transformation",
    }
    assert "display_filename" not in payload["source"]
    assert "build_revision" not in payload["application"]
    assert json.loads(canonical_json_bytes(payload))
