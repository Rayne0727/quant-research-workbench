"""Typed orchestration for single-analysis Run Manifest exports.

This module connects already validated analysis results to the immutable
Manifest core. It does not read uploads, calculate performance, use Streamlit,
or write files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from platform import python_version
from typing import Final

import pandas as pd

from src.adapters import DEFAULT_RETURN_TOLERANCE
from src.analysis_bridge import (
    NAV_ADAPTER_VERSION,
    STRICT_NAV_PROTOCOL_VERSION,
    STRICT_RETURN_PROTOCOL_VERSION,
    StrictProtocolResult,
    build_analysis_request_key,
)
from src.config import APP_NAME, APP_VERSION
from src.field_mapping import (
    PRIMARY_BASIS_NAV,
    PRIMARY_BASIS_RETURN,
    ConfirmedMapping,
    build_mapping_source_key,
)
from src.file_import import ImportedTable
from src.run_manifest import (
    AnalysisMode,
    ApplicationMetadata,
    CsvInterpretation,
    DirectStandardProvenance,
    EnvironmentMetadata,
    GenericNavProvenance,
    GenericReturnProvenance,
    NavAdapterProvenance,
    RunManifest,
    RunProvenance,
    WorkflowKeys,
    XlsxInterpretation,
    build_analysis_identity,
    build_canonical_analysis_data,
    build_run_identity,
    build_run_manifest,
    build_source_metadata,
    make_manifest_filename,
    manifest_json_bytes,
    mapping_entries,
)
from src.standardization import (
    MAPPING_KEY_POLICY_VERSION,
    StandardizationResult,
    is_standardization_result_current,
)

MANIFEST_MIME_TYPE: Final = "application/json"


class ManifestIntegrationError(ValueError):
    """Raised when UI artifacts do not describe one current analysis run."""


@dataclass(frozen=True)
class ManifestCacheSignature:
    """Timestamp-free signature used to reject stale cached exports."""

    analysis_id: str
    run_id: str
    display_filename: str | None
    workflow_keys: WorkflowKeys | None
    application: ApplicationMetadata
    environment: EnvironmentMetadata


@dataclass(frozen=True)
class ManifestExport:
    """Single source of truth for a downloadable Manifest artifact."""

    manifest: RunManifest
    cache_signature: ManifestCacheSignature

    @property
    def json_bytes(self) -> bytes:
        """Return core-serialized Manifest JSON bytes."""

        return manifest_json_bytes(self.manifest)

    @property
    def filename(self) -> str:
        """Return the deterministic core-generated download filename."""

        return make_manifest_filename(self.manifest.run_identity.run_id)

    @property
    def mime_type(self) -> str:
        """Return the public download MIME type."""

        return MANIFEST_MIME_TYPE


def build_application_metadata() -> ApplicationMetadata:
    """Build application provenance without querying Git or deployment APIs."""

    return ApplicationMetadata(name=APP_NAME, version=APP_VERSION, build_revision=None)


def build_environment_metadata() -> EnvironmentMetadata:
    """Build informational runtime provenance from installed package metadata."""

    return EnvironmentMetadata(
        python=python_version(),
        pandas=version("pandas"),
        numpy=version("numpy"),
        streamlit=version("streamlit"),
        openpyxl=_optional_package_version("openpyxl"),
    )


def manifest_export_matches(
    cached_export: ManifestExport | None,
    cache_signature: ManifestCacheSignature,
) -> bool:
    """Return whether a cached export exactly matches the current run context."""

    return bool(
        isinstance(cached_export, ManifestExport)
        and cached_export.cache_signature == cache_signature
    )


def build_direct_return_manifest_export(
    *,
    analysis_data: pd.DataFrame,
    raw_source_bytes: bytes,
    display_filename: str,
    cached_export: ManifestExport | None = None,
    generated_at: datetime | None = None,
    application: ApplicationMetadata | None = None,
    environment: EnvironmentMetadata | None = None,
) -> ManifestExport:
    """Build or reuse a Manifest for validated direct-return analysis data."""

    provenance = DirectStandardProvenance(protocol_version=STRICT_RETURN_PROTOCOL_VERSION)
    return _build_or_reuse_export(
        analysis_data=analysis_data,
        analysis_mode="daily_return",
        raw_source_bytes=raw_source_bytes,
        display_filename=display_filename,
        provenance=provenance,
        cached_export=cached_export,
        generated_at=generated_at,
        application=application,
        environment=environment,
    )


def build_direct_nav_manifest_export(
    *,
    analysis_data: pd.DataFrame,
    raw_source_bytes: bytes,
    display_filename: str,
    cached_export: ManifestExport | None = None,
    generated_at: datetime | None = None,
    application: ApplicationMetadata | None = None,
    environment: EnvironmentMetadata | None = None,
) -> ManifestExport:
    """Build or reuse a Manifest for the direct NAV adapter result."""

    provenance = NavAdapterProvenance(
        protocol_version=STRICT_NAV_PROTOCOL_VERSION,
        adapter_version=NAV_ADAPTER_VERSION,
        return_tolerance=DEFAULT_RETURN_TOLERANCE,
    )
    return _build_or_reuse_export(
        analysis_data=analysis_data,
        analysis_mode="nav",
        raw_source_bytes=raw_source_bytes,
        display_filename=display_filename,
        provenance=provenance,
        cached_export=cached_export,
        generated_at=generated_at,
        application=application,
        environment=environment,
    )


def build_generic_return_manifest_export(
    *,
    analysis_data: pd.DataFrame,
    raw_source_bytes: bytes,
    imported_table: ImportedTable,
    confirmed_mapping: ConfirmedMapping,
    standardization_result: StandardizationResult,
    strict_result: StrictProtocolResult,
    cached_export: ManifestExport | None = None,
    generated_at: datetime | None = None,
    application: ApplicationMetadata | None = None,
    environment: EnvironmentMetadata | None = None,
) -> ManifestExport:
    """Build or reuse a Manifest for a confirmed generic-return workflow."""

    _validate_generic_context(
        analysis_data=analysis_data,
        raw_source_bytes=raw_source_bytes,
        imported_table=imported_table,
        confirmed_mapping=confirmed_mapping,
        standardization_result=standardization_result,
        strict_result=strict_result,
        expected_basis=PRIMARY_BASIS_RETURN,
    )
    provenance = GenericReturnProvenance(
        interpretation=_generic_interpretation(imported_table),
        mapping=mapping_entries(confirmed_mapping.role_to_column),
        mapping_policy_version=MAPPING_KEY_POLICY_VERSION,
        standardization_policy_version=standardization_result.policy_version,
        validation_protocol_version=strict_result.protocol_version,
        bridge_version=strict_result.bridge_version,
        workflow_keys=_workflow_keys(strict_result),
    )
    return _build_or_reuse_export(
        analysis_data=analysis_data,
        analysis_mode="daily_return",
        raw_source_bytes=raw_source_bytes,
        display_filename=imported_table.file_name,
        provenance=provenance,
        cached_export=cached_export,
        generated_at=generated_at,
        application=application,
        environment=environment,
    )


def build_generic_nav_manifest_export(
    *,
    analysis_data: pd.DataFrame,
    raw_source_bytes: bytes,
    imported_table: ImportedTable,
    confirmed_mapping: ConfirmedMapping,
    standardization_result: StandardizationResult,
    strict_result: StrictProtocolResult,
    cached_export: ManifestExport | None = None,
    generated_at: datetime | None = None,
    application: ApplicationMetadata | None = None,
    environment: EnvironmentMetadata | None = None,
) -> ManifestExport:
    """Build or reuse a Manifest for a confirmed generic NAV workflow."""

    _validate_generic_context(
        analysis_data=analysis_data,
        raw_source_bytes=raw_source_bytes,
        imported_table=imported_table,
        confirmed_mapping=confirmed_mapping,
        standardization_result=standardization_result,
        strict_result=strict_result,
        expected_basis=PRIMARY_BASIS_NAV,
    )
    provenance = GenericNavProvenance(
        interpretation=_generic_interpretation(imported_table),
        mapping=mapping_entries(confirmed_mapping.role_to_column),
        mapping_policy_version=MAPPING_KEY_POLICY_VERSION,
        standardization_policy_version=standardization_result.policy_version,
        validation_protocol_version=strict_result.protocol_version,
        bridge_version=strict_result.bridge_version,
        adapter_version=strict_result.adapter_version,
        return_tolerance=DEFAULT_RETURN_TOLERANCE,
        workflow_keys=_workflow_keys(strict_result),
    )
    return _build_or_reuse_export(
        analysis_data=analysis_data,
        analysis_mode="nav",
        raw_source_bytes=raw_source_bytes,
        display_filename=imported_table.file_name,
        provenance=provenance,
        cached_export=cached_export,
        generated_at=generated_at,
        application=application,
        environment=environment,
    )


def _build_or_reuse_export(
    *,
    analysis_data: pd.DataFrame,
    analysis_mode: AnalysisMode,
    raw_source_bytes: bytes,
    display_filename: str,
    provenance: RunProvenance,
    cached_export: ManifestExport | None,
    generated_at: datetime | None,
    application: ApplicationMetadata | None,
    environment: EnvironmentMetadata | None,
) -> ManifestExport:
    resolved_application = application or build_application_metadata()
    resolved_environment = environment or build_environment_metadata()
    signature = _build_cache_signature(
        analysis_data=analysis_data,
        analysis_mode=analysis_mode,
        raw_source_bytes=raw_source_bytes,
        display_filename=display_filename,
        provenance=provenance,
        application=resolved_application,
        environment=resolved_environment,
    )
    if cached_export is not None and manifest_export_matches(cached_export, signature):
        return cached_export

    manifest = build_run_manifest(
        analysis_data=analysis_data,
        analysis_mode=analysis_mode,
        raw_source_bytes=raw_source_bytes,
        provenance=provenance,
        application=resolved_application,
        environment=resolved_environment,
        generated_at=generated_at or datetime.now(UTC),
        display_filename=display_filename,
    )
    return ManifestExport(manifest=manifest, cache_signature=signature)


def _build_cache_signature(
    *,
    analysis_data: pd.DataFrame,
    analysis_mode: AnalysisMode,
    raw_source_bytes: bytes,
    display_filename: str,
    provenance: RunProvenance,
    application: ApplicationMetadata,
    environment: EnvironmentMetadata,
) -> ManifestCacheSignature:
    canonical_data = build_canonical_analysis_data(analysis_data, analysis_mode)
    analysis_identity = build_analysis_identity(canonical_data)
    source = build_source_metadata(raw_source_bytes, display_filename=display_filename)
    run_identity = build_run_identity(analysis_identity, source, provenance)
    return ManifestCacheSignature(
        analysis_id=analysis_identity.analysis_id,
        run_id=run_identity.run_id,
        display_filename=source.display_filename,
        workflow_keys=provenance.workflow_keys,
        application=application,
        environment=environment,
    )


def _validate_generic_context(
    *,
    analysis_data: pd.DataFrame,
    raw_source_bytes: bytes,
    imported_table: ImportedTable,
    confirmed_mapping: ConfirmedMapping,
    standardization_result: StandardizationResult,
    strict_result: StrictProtocolResult,
    expected_basis: str,
) -> None:
    if confirmed_mapping.primary_basis != expected_basis:
        raise ManifestIntegrationError("字段映射主口径与 Manifest builder 不一致。")
    if not standardization_result.is_preview_valid or not is_standardization_result_current(
        standardization_result,
        confirmed_mapping,
    ):
        raise ManifestIntegrationError("标准化结果已失效，不能生成 Run Manifest。")
    if not strict_result.is_valid or strict_result.validated_frame is None:
        raise ManifestIntegrationError("严格协议结果未通过，不能生成 Run Manifest。")
    request_key = build_analysis_request_key(
        strict_result.standardization_key,
        strict_result.primary_basis,
        strict_result.protocol_version,
        adapter_version=strict_result.adapter_version,
        bridge_version=strict_result.bridge_version,
        input_columns=strict_result.analysis_input_columns,
    )
    if (
        strict_result.source_key != standardization_result.source_key
        or strict_result.mapping_key != standardization_result.mapping_key
        or strict_result.standardization_key != standardization_result.standardization_key
        or strict_result.primary_basis != standardization_result.primary_basis
        or strict_result.analysis_request_key != request_key
    ):
        raise ManifestIntegrationError("严格协议结果已失效，不能生成 Run Manifest。")
    if not analysis_data.equals(strict_result.validated_frame):
        raise ManifestIntegrationError("Manifest analysis data 必须来自当前严格协议结果。")

    expected_source_key = build_mapping_source_key(
        content=raw_source_bytes,
        file_type=imported_table.file_type,
        sheet_name=imported_table.sheet_name,
        encoding=imported_table.encoding,
        delimiter=imported_table.delimiter,
        header_rule="first_row",
        columns=imported_table.column_names,
    )
    if expected_source_key != strict_result.source_key:
        raise ManifestIntegrationError("原始来源或解析设置与当前分析结果不一致。")


def _generic_interpretation(
    imported_table: ImportedTable,
) -> CsvInterpretation | XlsxInterpretation:
    if imported_table.file_type == "CSV":
        if imported_table.encoding is None or imported_table.delimiter is None:
            raise ManifestIntegrationError("CSV解析信息不完整，不能生成 Run Manifest。")
        return CsvInterpretation(
            encoding=imported_table.encoding,
            delimiter=imported_table.delimiter,
            header_rule="first_row",
        )
    if imported_table.file_type == "XLSX" and imported_table.sheet_name is not None:
        return XlsxInterpretation(sheet_name=imported_table.sheet_name)
    raise ManifestIntegrationError("通用文件解析信息不受 Run Manifest 支持。")


def _workflow_keys(strict_result: StrictProtocolResult) -> WorkflowKeys:
    return WorkflowKeys(
        source_key=strict_result.source_key,
        mapping_key=strict_result.mapping_key,
        standardization_key=strict_result.standardization_key,
        analysis_request_key=strict_result.analysis_request_key,
    )


def _optional_package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None
