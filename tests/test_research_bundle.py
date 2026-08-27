"""Contracts for deterministic in-memory Research Bundle exports."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZIP_STORED, ZipFile

import pandas as pd
import pytest

from src.config import APP_VERSION
from src.research_bundle import (
    BUNDLE_INDEX_PATH,
    BUNDLE_INDEX_SCHEMA_VERSION,
    BUNDLE_MEMBER_PATHS,
    BUNDLE_MIME_TYPE,
    CONTENT_MEMBER_PATHS,
    REPORT_MIME_TYPE,
    REPORT_PATH,
    RUN_MANIFEST_PATH,
    STANDARDIZED_DATA_PATH,
    ZIP_MEMBER_CREATE_SYSTEM,
    ZIP_MEMBER_EXTERNAL_ATTR,
    ZIP_MEMBER_TIMESTAMP,
    BundleArtifact,
    BundleFileEntry,
    ResearchBundle,
    ResearchBundleError,
    build_research_bundle,
    make_bundle_filename,
)
from src.run_manifest import (
    ApplicationMetadata,
    CsvInterpretation,
    DirectStandardProvenance,
    EnvironmentMetadata,
    GenericNavProvenance,
    GenericReturnProvenance,
    MappingEntry,
    NavAdapterProvenance,
    RunProvenance,
    build_run_manifest,
)
from src.run_manifest_integration import (
    ManifestCacheSignature,
    ManifestExport,
    build_direct_return_manifest_export,
)

GENERATED_AT = datetime(2026, 8, 26, 8, 30, tzinfo=UTC)
APPLICATION = ApplicationMetadata(version=APP_VERSION)
ENVIRONMENT = EnvironmentMetadata(
    python="3.14.2",
    pandas="3.0.5",
    numpy="2.5.1",
    streamlit="1.60.0",
    openpyxl="3.1.5",
)
RAW_SOURCE_SENTINEL = b"raw-source-must-never-be-a-bundle-member"
REPORT_BYTES = "# 固定研究报告\n".encode()
CSV_BYTES = b"\xef\xbb\xbfdate,strategy_return\r\n2026-01-02,0.01\r\n"
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _return_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-05"]),
            "strategy_return": [0.01, -0.005],
        }
    )


def _nav_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-09"]),
            "strategy_nav": [1.0, 1.02],
            "strategy_return": [float("nan"), 0.02],
        }
    )


def _provenance(path_name: str) -> tuple[pd.DataFrame, str, RunProvenance]:
    if path_name == "direct_return":
        return _return_frame(), "daily_return", DirectStandardProvenance("return-v1")
    if path_name == "direct_nav":
        return (
            _nav_frame(),
            "nav",
            NavAdapterProvenance("nav-v1", "adapter-v1", 1e-8),
        )
    if path_name == "generic_return":
        return (
            _return_frame(),
            "daily_return",
            GenericReturnProvenance(
                interpretation=CsvInterpretation("utf-8", ","),
                mapping=(
                    MappingEntry("date", "trade_date"),
                    MappingEntry("strategy_return", "return_value"),
                ),
                mapping_policy_version="mapping-v1",
                standardization_policy_version="standardization-v1",
                validation_protocol_version="return-v1",
                bridge_version="bridge-v1",
            ),
        )
    if path_name == "generic_nav":
        return (
            _nav_frame(),
            "nav",
            GenericNavProvenance(
                interpretation=CsvInterpretation("utf-8", ","),
                mapping=(
                    MappingEntry("date", "trade_date"),
                    MappingEntry("strategy_nav", "nav_value"),
                ),
                mapping_policy_version="mapping-v1",
                standardization_policy_version="standardization-v1",
                validation_protocol_version="nav-v1",
                bridge_version="bridge-v1",
                adapter_version="adapter-v1",
                return_tolerance=1e-8,
            ),
        )
    raise AssertionError(f"unknown path fixture: {path_name}")


def _manifest_export(path_name: str = "direct_return") -> ManifestExport:
    frame, analysis_mode, provenance = _provenance(path_name)
    manifest = build_run_manifest(
        analysis_data=frame,
        analysis_mode=analysis_mode,
        raw_source_bytes=RAW_SOURCE_SENTINEL,
        provenance=provenance,
        application=APPLICATION,
        environment=ENVIRONMENT,
        generated_at=GENERATED_AT,
        display_filename="source.csv",
    )
    signature = ManifestCacheSignature(
        analysis_id=manifest.analysis_identity.analysis_id,
        run_id=manifest.run_identity.run_id,
        display_filename=manifest.source.display_filename,
        workflow_keys=manifest.provenance.workflow_keys,
        application=manifest.application,
        environment=manifest.environment,
    )
    return ManifestExport(manifest=manifest, cache_signature=signature)


def _bundle(path_name: str = "direct_return") -> ResearchBundle:
    return build_research_bundle(
        report_bytes=REPORT_BYTES,
        standardized_csv_bytes=CSV_BYTES,
        manifest_export=_manifest_export(path_name),
    )


def _opened_bundle(bundle: ResearchBundle) -> ZipFile:
    return ZipFile(BytesIO(bundle.zip_bytes))


def test_bundle_contains_exact_fixed_members_in_order() -> None:
    bundle = _bundle()

    with _opened_bundle(bundle) as archive:
        assert archive.namelist() == list(BUNDLE_MEMBER_PATHS)
        assert len(archive.infolist()) == 4
        assert archive.read(REPORT_PATH) == REPORT_BYTES
        assert archive.read(STANDARDIZED_DATA_PATH) == CSV_BYTES
        assert archive.read(RUN_MANIFEST_PATH) == _manifest_export().json_bytes


def test_index_records_exact_member_bytes_without_recording_itself() -> None:
    bundle = _bundle()

    with _opened_bundle(bundle) as archive:
        payload = json.loads(archive.read(BUNDLE_INDEX_PATH))
        assert payload["schema_version"] == BUNDLE_INDEX_SCHEMA_VERSION
        assert payload["application"] == {
            "name": APPLICATION.name,
            "version": APPLICATION.version,
        }
        assert payload["analysis_id"] == bundle.index.analysis_id
        assert payload["run_id"] == bundle.index.run_id
        assert [entry["path"] for entry in payload["files"]] == list(CONTENT_MEMBER_PATHS)
        assert BUNDLE_INDEX_PATH not in [entry["path"] for entry in payload["files"]]
        for entry in payload["files"]:
            actual_bytes = archive.read(entry["path"])
            expected_sha = f"sha256:{hashlib.sha256(actual_bytes).hexdigest()}"
            assert entry["size_bytes"] == len(actual_bytes)
            assert entry["sha256"] == expected_sha
            assert SHA256_PATTERN.fullmatch(entry["sha256"])


def test_index_serialization_is_compact_utf8_and_has_no_trailing_newline() -> None:
    index_bytes = _bundle().index.json_bytes

    assert index_bytes.decode("utf-8").startswith('{"analysis_id":')
    assert b"\n" not in index_bytes
    assert b": " not in index_bytes
    assert json.loads(index_bytes)["schema_version"] == BUNDLE_INDEX_SCHEMA_VERSION


def test_bundle_filename_mime_and_same_input_bytes_are_deterministic() -> None:
    first = _bundle()
    second = _bundle()
    run_hex = first.index.run_id.removeprefix("sha256:")

    assert first.filename == f"qrw_bundle_{run_hex[:16]}.zip"
    assert first.filename == make_bundle_filename(first.index.run_id)
    assert first.mime_type == BUNDLE_MIME_TYPE == "application/zip"
    assert first.zip_bytes == second.zip_bytes


def test_zip_metadata_is_fixed_and_platform_independent() -> None:
    with _opened_bundle(_bundle()) as archive:
        assert archive.comment == b""
        for info in archive.infolist():
            assert info.date_time == ZIP_MEMBER_TIMESTAMP
            assert info.compress_type == ZIP_STORED
            assert info.create_system == ZIP_MEMBER_CREATE_SYSTEM
            assert info.external_attr == ZIP_MEMBER_EXTERNAL_ATTR
            assert info.extra == b""
            assert info.comment == b""
            assert not info.is_dir()
            assert (info.external_attr >> 16) & 0o170000 == 0o100000


def test_member_paths_are_fixed_safe_ascii_names() -> None:
    with _opened_bundle(_bundle()) as archive:
        for name in archive.namelist():
            assert name.isascii()
            assert "/" not in name
            assert "\\" not in name
            assert ":" not in name
            assert name not in {".", ".."}


@pytest.mark.parametrize(
    "unsafe_path",
    ("", ".", "..", "/absolute", "folder/file", r"folder\file", "C:drive", "unknown.txt"),
)
def test_artifact_rejects_unsafe_or_unapproved_member_paths(unsafe_path: str) -> None:
    with pytest.raises(ResearchBundleError):
        BundleArtifact(unsafe_path, REPORT_MIME_TYPE, b"content")


def test_artifact_rejects_wrong_media_type_and_non_bytes_content() -> None:
    with pytest.raises(ResearchBundleError, match="media_type"):
        BundleArtifact(REPORT_PATH, "text/plain", b"content")
    with pytest.raises(TypeError, match="bytes"):
        BundleArtifact(REPORT_PATH, REPORT_MIME_TYPE, object())


def test_index_entry_rejects_non_content_path_media_size_and_hash() -> None:
    valid_sha = f"sha256:{'0' * 64}"

    with pytest.raises(ResearchBundleError, match="三个内容"):
        BundleFileEntry(BUNDLE_INDEX_PATH, "application/json", 1, valid_sha)
    with pytest.raises(ResearchBundleError, match="media_type"):
        BundleFileEntry(REPORT_PATH, "text/plain", 1, valid_sha)
    with pytest.raises(ResearchBundleError, match="size_bytes"):
        BundleFileEntry(REPORT_PATH, REPORT_MIME_TYPE, -1, valid_sha)
    with pytest.raises(ResearchBundleError, match="artifact sha256"):
        BundleFileEntry(REPORT_PATH, REPORT_MIME_TYPE, 1, "invalid")


def test_bundle_rejects_reordered_or_mismatched_artifacts_and_index() -> None:
    bundle = _bundle()

    with pytest.raises(ResearchBundleError, match="固定顺序"):
        ResearchBundle(artifacts=tuple(reversed(bundle.artifacts)), index=bundle.index)
    changed_report = replace(bundle.artifacts[0], content=b"changed")
    with pytest.raises(ResearchBundleError, match="exact artifact bytes"):
        ResearchBundle(artifacts=(changed_report, *bundle.artifacts[1:]), index=bundle.index)


@pytest.mark.parametrize(
    "path_name",
    ("direct_return", "direct_nav", "generic_return", "generic_nav"),
)
def test_bundle_accepts_all_four_single_analysis_manifest_exports(path_name: str) -> None:
    bundle = _bundle(path_name)

    with _opened_bundle(bundle) as archive:
        manifest_payload = json.loads(archive.read(RUN_MANIFEST_PATH))
        index_payload = json.loads(archive.read(BUNDLE_INDEX_PATH))
        assert index_payload["analysis_id"] == manifest_payload["identity"]["analysis_id"]
        assert index_payload["run_id"] == manifest_payload["identity"]["run_id"]


def test_raw_source_and_ui_metadata_are_not_added_to_bundle() -> None:
    bundle = _bundle()

    with _opened_bundle(bundle) as archive:
        assert RAW_SOURCE_SENTINEL not in bundle.zip_bytes
        assert archive.namelist() == list(BUNDLE_MEMBER_PATHS)
        index_text = archive.read(BUNDLE_INDEX_PATH).decode("utf-8")
        for forbidden in (
            "session_state",
            "browser",
            "widget",
            "raw_bytes",
            "raw_source",
            "C:\\Users\\",
            "/tmp/",
        ):
            assert forbidden not in index_text


def test_filename_only_source_rename_updates_manifest_member_not_bundle_identity() -> None:
    frame = _return_frame()
    first_export = build_direct_return_manifest_export(
        analysis_data=frame,
        raw_source_bytes=RAW_SOURCE_SENTINEL,
        display_filename="first.csv",
        generated_at=GENERATED_AT,
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    second_export = build_direct_return_manifest_export(
        analysis_data=frame,
        raw_source_bytes=RAW_SOURCE_SENTINEL,
        display_filename="renamed.csv",
        cached_export=first_export,
        generated_at=GENERATED_AT + timedelta(days=1),
        application=APPLICATION,
        environment=ENVIRONMENT,
    )
    first = build_research_bundle(
        report_bytes=REPORT_BYTES,
        standardized_csv_bytes=CSV_BYTES,
        manifest_export=first_export,
    )
    second = build_research_bundle(
        report_bytes=REPORT_BYTES,
        standardized_csv_bytes=CSV_BYTES,
        manifest_export=second_export,
    )

    assert first.index.analysis_id == second.index.analysis_id
    assert first.index.run_id == second.index.run_id
    assert first.filename == second.filename
    assert first.artifacts[2].content != second.artifacts[2].content
    assert first.index.files[2].sha256 != second.index.files[2].sha256
    assert first.zip_bytes != second.zip_bytes


def test_invalid_hashes_schema_and_index_order_are_rejected() -> None:
    bundle = _bundle()

    with pytest.raises(ResearchBundleError, match="run_id"):
        make_bundle_filename("not-a-run-id")
    with pytest.raises(ResearchBundleError, match="schema_version"):
        replace(bundle.index, schema_version="future-schema")
    with pytest.raises(ResearchBundleError, match="固定顺序"):
        replace(bundle.index, files=tuple(reversed(bundle.index.files)))
