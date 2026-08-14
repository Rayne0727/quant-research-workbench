"""Deterministic single-run identities and immutable Run Manifest models.

This core module does not read files, call Streamlit, or run performance
calculations.  Callers provide exact source bytes and an already validated
analysis DataFrame; the module only creates stable representations and hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from math import isfinite, isnan
from numbers import Real
from pathlib import PurePosixPath, PureWindowsPath
from typing import Final, Literal

import pandas as pd

MANIFEST_SCHEMA_VERSION: Final = "qrw-run-manifest-v1"
CANONICALIZATION_VERSION: Final = "qrw-run-canonicalization-v1"
ANALYSIS_IDENTITY_VERSION: Final = "qrw-analysis-identity-v1"
RUN_IDENTITY_VERSION: Final = "qrw-run-identity-v1"
SINGLE_ANALYSIS_SEMANTICS_VERSION: Final = "qrw-single-analysis-v1"

DAILY_RETURN_MODE: Final = "daily_return"
NAV_MODE: Final = "nav"
AnalysisMode = Literal["daily_return", "nav"]

DIRECT_STANDARD_MODE: Final = "direct_standard"
GENERIC_IMPORT_MODE: Final = "generic_import"
NAV_ADAPTER_MODE: Final = "nav_adapter"
InputMode = Literal["direct_standard", "generic_import", "nav_adapter"]

TRADING_DAYS_PER_YEAR: Final = 252
RISK_FREE_RATE_ANNUAL: Final = 0.0
VOLATILITY_DDOF: Final = 1

DAILY_RETURN_COLUMNS: Final = ("date", "strategy_return")
NAV_COLUMNS: Final = ("date", "strategy_nav", "strategy_return")
MAPPING_ROLE_ORDER: Final = (
    "date",
    "strategy_return",
    "strategy_nav",
    "benchmark_return",
    "benchmark_nav",
    "drawdown",
    "daily_ret",
)

_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORKFLOW_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CanonicalCell = str | None


class RunManifestError(ValueError):
    """Raised when identity input violates the canonical contract."""


@dataclass(frozen=True)
class WorkflowKeys:
    """Optional legacy workflow keys retained only for traceability."""

    source_key: str | None = None
    mapping_key: str | None = None
    standardization_key: str | None = None
    analysis_request_key: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("source_key", self.source_key),
            ("mapping_key", self.mapping_key),
            ("standardization_key", self.standardization_key),
            ("analysis_request_key", self.analysis_request_key),
        ):
            if value is not None and not _WORKFLOW_KEY_PATTERN.fullmatch(value):
                raise RunManifestError(f"{name} 必须是 64 位小写十六进制。")


@dataclass(frozen=True)
class CsvInterpretation:
    """CSV interpretation settings that define generic-import provenance."""

    encoding: str
    delimiter: str
    header_rule: str = "first_row"

    def __post_init__(self) -> None:
        object.__setattr__(self, "encoding", _semantic_text(self.encoding, "encoding"))
        object.__setattr__(self, "delimiter", _semantic_text(self.delimiter, "delimiter"))
        object.__setattr__(self, "header_rule", _semantic_text(self.header_rule, "header_rule"))


@dataclass(frozen=True)
class XlsxInterpretation:
    """Selected XLSX sheet; the workbook digest is stored separately."""

    sheet_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sheet_name", _semantic_text(self.sheet_name, "sheet_name"))


@dataclass(frozen=True)
class MappingEntry:
    """One explicitly mapped generic-import business role."""

    role: str
    column: str

    def __post_init__(self) -> None:
        role = _semantic_text(self.role, "mapping role")
        column = _semantic_text(self.column, "mapping column")
        if role not in MAPPING_ROLE_ORDER:
            raise RunManifestError(f"不支持的映射角色：{role}")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "column", column)


@dataclass(frozen=True)
class DirectStandardProvenance:
    """A CSV already conforming to the standard daily-return protocol."""

    protocol_version: str
    workflow_keys: WorkflowKeys | None = None
    input_mode: Literal["direct_standard"] = field(default=DIRECT_STANDARD_MODE, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "protocol_version",
            _semantic_text(self.protocol_version, "protocol_version"),
        )


@dataclass(frozen=True)
class GenericImportProvenance:
    """Generic CSV/XLSX interpretation, mapping, and transformation provenance."""

    interpretation: CsvInterpretation | XlsxInterpretation
    mapping: tuple[MappingEntry, ...]
    mapping_policy_version: str
    standardization_policy_version: str
    validation_protocol_version: str
    bridge_version: str
    workflow_keys: WorkflowKeys | None = None
    input_mode: Literal["generic_import"] = field(default=GENERIC_IMPORT_MODE, init=False)

    def __post_init__(self) -> None:
        normalized_mapping = tuple(
            sorted(
                self.mapping,
                key=lambda entry: MAPPING_ROLE_ORDER.index(entry.role),
            )
        )
        roles = [entry.role for entry in normalized_mapping]
        if len(set(roles)) != len(roles):
            raise RunManifestError("同一个映射角色不能出现多次。")
        object.__setattr__(self, "mapping", normalized_mapping)
        for name in (
            "mapping_policy_version",
            "standardization_policy_version",
            "validation_protocol_version",
            "bridge_version",
        ):
            object.__setattr__(self, name, _semantic_text(getattr(self, name), name))


@dataclass(frozen=True)
class NavAdapterProvenance:
    """Direct NAV input interpreted by the existing NAV adapter."""

    protocol_version: str
    adapter_version: str
    return_tolerance: float
    workflow_keys: WorkflowKeys | None = None
    input_mode: Literal["nav_adapter"] = field(default=NAV_ADAPTER_MODE, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "protocol_version",
            _semantic_text(self.protocol_version, "protocol_version"),
        )
        object.__setattr__(
            self,
            "adapter_version",
            _semantic_text(self.adapter_version, "adapter_version"),
        )
        tolerance = float(self.return_tolerance)
        if not isfinite(tolerance) or tolerance < 0:
            raise RunManifestError("return_tolerance 必须是非负有限数值。")
        object.__setattr__(self, "return_tolerance", _normalize_zero(tolerance))


RunProvenance = DirectStandardProvenance | GenericImportProvenance | NavAdapterProvenance


@dataclass(frozen=True)
class SourceMetadata:
    """Raw-source digest and non-identity display metadata."""

    source_sha256: str
    size_bytes: int
    display_filename: str | None = None

    def __post_init__(self) -> None:
        _require_sha256(self.source_sha256, "source_sha256")
        if self.size_bytes < 0:
            raise RunManifestError("size_bytes 不能为负数。")
        object.__setattr__(self, "display_filename", _safe_display_filename(self.display_filename))


@dataclass(frozen=True)
class CanonicalAnalysisData:
    """Canonical rows used for data hashing; rows never enter Manifest JSON."""

    analysis_mode: AnalysisMode
    columns: tuple[str, ...]
    rows: tuple[tuple[CanonicalCell, ...], ...]
    standardized_data_sha256: str


@dataclass(frozen=True)
class AnalysisIdentity:
    """Identity of result-affecting analysis data and semantics."""

    analysis_id: str
    standardized_data_sha256: str
    analysis_mode: AnalysisMode
    consumed_columns: tuple[str, ...]
    semantics_version: str
    trading_days_per_year: int
    risk_free_rate_annual: float
    volatility_ddof: int


@dataclass(frozen=True)
class RunIdentity:
    """Provenance-sensitive identity containing an analysis identity."""

    run_id: str
    analysis_id: str
    source_sha256: str
    input_mode: InputMode


@dataclass(frozen=True)
class ApplicationMetadata:
    """Informational application metadata excluded from both identities."""

    version: str
    build_revision: str | None = None
    name: str = "Quant Research Workbench"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _semantic_text(self.name, "application name"))
        object.__setattr__(self, "version", _semantic_text(self.version, "application version"))
        if self.build_revision is not None:
            object.__setattr__(
                self,
                "build_revision",
                _semantic_text(self.build_revision, "build_revision"),
            )


@dataclass(frozen=True)
class EnvironmentMetadata:
    """Informational runtime versions excluded from both identities."""

    python: str
    pandas: str
    numpy: str
    streamlit: str
    openpyxl: str | None = None

    def __post_init__(self) -> None:
        for name in ("python", "pandas", "numpy", "streamlit"):
            object.__setattr__(self, name, _semantic_text(getattr(self, name), name))
        if self.openpyxl is not None:
            object.__setattr__(self, "openpyxl", _semantic_text(self.openpyxl, "openpyxl"))


@dataclass(frozen=True)
class DataSummary:
    """Human-readable verification metadata derived from canonical data."""

    row_count: int
    valid_return_count: int
    start_date: str
    end_date: str
    benchmark_present: bool
    strategy_nav_present: bool


@dataclass(frozen=True)
class RunManifest:
    """Immutable single-run Manifest envelope."""

    analysis_identity: AnalysisIdentity
    run_identity: RunIdentity
    application: ApplicationMetadata
    source: SourceMetadata
    provenance: RunProvenance
    data_summary: DataSummary
    environment: EnvironmentMetadata
    generated_at_utc: str
    schema_version: str = field(default=MANIFEST_SCHEMA_VERSION, init=False)


def canonical_json_bytes(payload: object) -> bytes:
    """Serialize all identity and Manifest payloads with one JSON contract."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_source_sha256(raw_bytes: bytes) -> str:
    """Return a full digest of exact raw bytes without metadata mixing."""

    return _sha256_identifier(raw_bytes)


def build_source_metadata(
    raw_bytes: bytes,
    *,
    display_filename: str | None = None,
) -> SourceMetadata:
    """Build privacy-safe source metadata from exact bytes."""

    return SourceMetadata(
        source_sha256=compute_source_sha256(raw_bytes),
        size_bytes=len(raw_bytes),
        display_filename=display_filename,
    )


def mapping_entries(mapping: Mapping[str, str | None]) -> tuple[MappingEntry, ...]:
    """Convert a mapping to stable fixed-role order and omit unmapped roles."""

    unknown_roles = sorted(set(mapping).difference(MAPPING_ROLE_ORDER))
    if unknown_roles:
        raise RunManifestError(f"不支持的映射角色：{'、'.join(unknown_roles)}")
    entries: list[MappingEntry] = []
    for role in MAPPING_ROLE_ORDER:
        column = mapping.get(role)
        if column is not None:
            entries.append(MappingEntry(role, column))
    return tuple(entries)


def build_canonical_analysis_data(
    data: pd.DataFrame,
    analysis_mode: AnalysisMode,
) -> CanonicalAnalysisData:
    """Represent validated performance input without sorting or mutation."""

    if not isinstance(data, pd.DataFrame):
        raise TypeError("data 必须是 pandas.DataFrame")
    mode = _analysis_mode(analysis_mode)
    columns = _consumed_columns(data, mode)
    if data.empty:
        raise RunManifestError("analysis data 不能为空。")

    rows: list[tuple[CanonicalCell, ...]] = []
    selected = data.loc[:, list(columns)]
    for row_number, values in enumerate(selected.itertuples(index=False, name=None)):
        canonical_row: list[CanonicalCell] = []
        for column, value in zip(columns, values, strict=True):
            if column == "date":
                canonical_row.append(_canonical_date(value))
            else:
                allow_missing = _missing_allowed(mode, column, row_number)
                canonical_row.append(_canonical_float(value, allow_missing=allow_missing))
        rows.append(tuple(canonical_row))

    payload = {
        "analysis_mode": mode,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "columns": list(columns),
        "rows": [list(row) for row in rows],
    }
    return CanonicalAnalysisData(
        analysis_mode=mode,
        columns=columns,
        rows=tuple(rows),
        standardized_data_sha256=_sha256_identifier(canonical_json_bytes(payload)),
    )


def build_analysis_identity(
    canonical_data: CanonicalAnalysisData,
    *,
    semantics_version: str = SINGLE_ANALYSIS_SEMANTICS_VERSION,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
    risk_free_rate_annual: float = RISK_FREE_RATE_ANNUAL,
    volatility_ddof: int = VOLATILITY_DDOF,
) -> AnalysisIdentity:
    """Build a semantic identity independent of ingestion provenance."""

    semantics = _semantic_text(semantics_version, "semantics_version")
    if trading_days_per_year <= 0:
        raise RunManifestError("trading_days_per_year 必须大于 0。")
    if volatility_ddof < 0:
        raise RunManifestError("volatility_ddof 不能为负数。")
    risk_free = float(risk_free_rate_annual)
    if not isfinite(risk_free):
        raise RunManifestError("risk_free_rate_annual 必须是有限数值。")
    risk_free = _normalize_zero(risk_free)
    payload = {
        "analysis_identity_version": ANALYSIS_IDENTITY_VERSION,
        "analysis_mode": canonical_data.analysis_mode,
        "consumed_columns": list(canonical_data.columns),
        "parameters": {
            "risk_free_rate_annual": risk_free.hex(),
            "trading_days_per_year": trading_days_per_year,
            "volatility_ddof": volatility_ddof,
        },
        "semantics_version": semantics,
        "standardized_data_sha256": canonical_data.standardized_data_sha256,
    }
    return AnalysisIdentity(
        analysis_id=_sha256_identifier(canonical_json_bytes(payload)),
        standardized_data_sha256=canonical_data.standardized_data_sha256,
        analysis_mode=canonical_data.analysis_mode,
        consumed_columns=canonical_data.columns,
        semantics_version=semantics,
        trading_days_per_year=trading_days_per_year,
        risk_free_rate_annual=risk_free,
        volatility_ddof=volatility_ddof,
    )


def build_run_identity(
    analysis_identity: AnalysisIdentity,
    source: SourceMetadata,
    provenance: RunProvenance,
) -> RunIdentity:
    """Build provenance identity without workflow keys or display metadata."""

    payload = {
        "analysis_id": analysis_identity.analysis_id,
        "provenance": _provenance_identity_payload(provenance),
        "run_identity_version": RUN_IDENTITY_VERSION,
        "source_sha256": source.source_sha256,
    }
    return RunIdentity(
        run_id=_sha256_identifier(canonical_json_bytes(payload)),
        analysis_id=analysis_identity.analysis_id,
        source_sha256=source.source_sha256,
        input_mode=provenance.input_mode,
    )


def build_run_manifest(
    *,
    analysis_data: pd.DataFrame,
    analysis_mode: AnalysisMode,
    raw_source_bytes: bytes,
    provenance: RunProvenance,
    application: ApplicationMetadata,
    environment: EnvironmentMetadata,
    generated_at: datetime,
    display_filename: str | None = None,
    semantics_version: str = SINGLE_ANALYSIS_SEMANTICS_VERSION,
) -> RunManifest:
    """Build canonical data, both identities, and the immutable Manifest."""

    _validate_mode_provenance(analysis_mode, provenance)
    canonical_data = build_canonical_analysis_data(analysis_data, analysis_mode)
    analysis_identity = build_analysis_identity(
        canonical_data,
        semantics_version=semantics_version,
    )
    source = build_source_metadata(raw_source_bytes, display_filename=display_filename)
    run_identity = build_run_identity(analysis_identity, source, provenance)
    return RunManifest(
        analysis_identity=analysis_identity,
        run_identity=run_identity,
        application=application,
        source=source,
        provenance=provenance,
        data_summary=_build_data_summary(canonical_data),
        environment=environment,
        generated_at_utc=_generated_at_utc(generated_at),
    )


def manifest_payload(manifest: RunManifest) -> dict[str, object]:
    """Return the stable public JSON shape without canonical analysis rows."""

    application: dict[str, object] = {
        "name": manifest.application.name,
        "version": manifest.application.version,
    }
    if manifest.application.build_revision is not None:
        application["build_revision"] = manifest.application.build_revision

    source: dict[str, object] = {
        "sha256": manifest.source.source_sha256,
        "size_bytes": manifest.source.size_bytes,
    }
    if manifest.source.display_filename is not None:
        source["display_filename"] = manifest.source.display_filename

    environment: dict[str, object] = {
        "numpy": manifest.environment.numpy,
        "pandas": manifest.environment.pandas,
        "python": manifest.environment.python,
        "streamlit": manifest.environment.streamlit,
    }
    if manifest.environment.openpyxl is not None:
        environment["openpyxl"] = manifest.environment.openpyxl

    identity = manifest.analysis_identity
    return {
        "analysis": {
            "analysis_mode": identity.analysis_mode,
            "consumed_columns": list(identity.consumed_columns),
            "parameters": {
                "risk_free_rate_annual": identity.risk_free_rate_annual.hex(),
                "trading_days_per_year": identity.trading_days_per_year,
                "volatility_ddof": identity.volatility_ddof,
            },
            "semantics_version": identity.semantics_version,
            "standardized_data_sha256": identity.standardized_data_sha256,
        },
        "application": application,
        "data_summary": {
            "benchmark_present": manifest.data_summary.benchmark_present,
            "end_date": manifest.data_summary.end_date,
            "row_count": manifest.data_summary.row_count,
            "start_date": manifest.data_summary.start_date,
            "strategy_nav_present": manifest.data_summary.strategy_nav_present,
            "valid_return_count": manifest.data_summary.valid_return_count,
        },
        "environment": environment,
        "generated_at_utc": manifest.generated_at_utc,
        "identity": {
            "analysis_id": manifest.run_identity.analysis_id,
            "analysis_identity_version": ANALYSIS_IDENTITY_VERSION,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "run_id": manifest.run_identity.run_id,
            "run_identity_version": RUN_IDENTITY_VERSION,
        },
        "schema_version": manifest.schema_version,
        "source": source,
        "transformation": _provenance_manifest_payload(manifest.provenance),
    }


def manifest_json_bytes(manifest: RunManifest) -> bytes:
    """Serialize one compact UTF-8 Manifest without a trailing newline."""

    return canonical_json_bytes(manifest_payload(manifest))


def make_manifest_filename(run_id: str) -> str:
    """Build a deterministic safe filename from the full run digest."""

    _require_sha256(run_id, "run_id")
    return f"qrw_run_{run_id.removeprefix('sha256:')[:16]}.json"


def _semantic_text(value: str, field_name: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value))
    if not normalized:
        raise RunManifestError(f"{field_name} 不能为空。")
    return normalized


def _safe_display_filename(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", str(value))
    basename = PureWindowsPath(normalized).name
    basename = PurePosixPath(basename).name
    return basename if basename not in {"", ".", ".."} else None


def _sha256_identifier(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _require_sha256(value: str, field_name: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise RunManifestError(f"{field_name} 必须是 sha256: 加 64 位小写十六进制。")


def _analysis_mode(value: str) -> AnalysisMode:
    normalized = _semantic_text(value, "analysis_mode")
    if normalized == DAILY_RETURN_MODE:
        return DAILY_RETURN_MODE
    if normalized == NAV_MODE:
        return NAV_MODE
    raise RunManifestError(f"不支持的 analysis_mode：{normalized}")


def _consumed_columns(data: pd.DataFrame, mode: AnalysisMode) -> tuple[str, ...]:
    columns = DAILY_RETURN_COLUMNS if mode == DAILY_RETURN_MODE else NAV_COLUMNS
    required = set(columns)
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise RunManifestError(f"analysis data 缺少字段：{'、'.join(missing)}")
    if mode == DAILY_RETURN_MODE and "benchmark_return" in data.columns:
        return (*columns, "benchmark_return")
    if not required.issubset(data.columns):
        raise RunManifestError("analysis data 字段不完整。")
    return columns


def _canonical_date(value: object) -> str:
    if value is None or value is pd.NaT:
        raise RunManifestError("date 不允许缺失。")
    if not isinstance(value, (str, date, datetime, pd.Timestamp)):
        raise RunManifestError("date 必须是明确日期、时间或 ISO-8601 文本。")
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RunManifestError("date 必须可以转换为 Timestamp。") from exc
    if pd.isna(timestamp):
        raise RunManifestError("date 不允许缺失。")
    if timestamp.tzinfo is not None and timestamp.utcoffset() is not None:
        timestamp = timestamp.tz_convert("UTC")
        return timestamp.isoformat().replace("+00:00", "Z")
    return timestamp.isoformat()


def _canonical_float(value: object, *, allow_missing: bool) -> CanonicalCell:
    if _is_missing_numeric(value):
        if allow_missing:
            return None
        raise RunManifestError("result-affecting numeric value 不允许缺失。")
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RunManifestError("result-affecting value 必须是数值。")
    numeric = float(value)
    if not isfinite(numeric):
        raise RunManifestError("result-affecting value 必须是有限数值。")
    return _normalize_zero(numeric).hex()


def _is_missing_numeric(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return bool(isinstance(value, Real) and isnan(float(value)))


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value


def _missing_allowed(mode: AnalysisMode, column: str, row_number: int) -> bool:
    if mode == DAILY_RETURN_MODE:
        return column == "benchmark_return"
    return column == "strategy_return" and row_number == 0


def _provenance_identity_payload(provenance: RunProvenance) -> dict[str, object]:
    if isinstance(provenance, DirectStandardProvenance):
        return {
            "file_format": "csv",
            "input_mode": provenance.input_mode,
            "protocol_version": provenance.protocol_version,
        }
    if isinstance(provenance, NavAdapterProvenance):
        return {
            "adapter_version": provenance.adapter_version,
            "file_format": "csv",
            "input_mode": provenance.input_mode,
            "protocol_version": provenance.protocol_version,
            "return_tolerance": provenance.return_tolerance.hex(),
        }
    interpretation: dict[str, object]
    if isinstance(provenance.interpretation, CsvInterpretation):
        interpretation = {
            "delimiter": provenance.interpretation.delimiter,
            "encoding": provenance.interpretation.encoding,
            "file_format": "csv",
            "header_rule": provenance.interpretation.header_rule,
        }
    else:
        interpretation = {
            "file_format": "xlsx",
            "sheet_name": provenance.interpretation.sheet_name,
        }
    return {
        "bridge_version": provenance.bridge_version,
        "input_mode": provenance.input_mode,
        "interpretation": interpretation,
        "mapping": [{"column": entry.column, "role": entry.role} for entry in provenance.mapping],
        "mapping_policy_version": provenance.mapping_policy_version,
        "standardization_policy_version": provenance.standardization_policy_version,
        "validation_protocol_version": provenance.validation_protocol_version,
    }


def _validate_mode_provenance(
    analysis_mode: AnalysisMode,
    provenance: RunProvenance,
) -> None:
    if isinstance(provenance, DirectStandardProvenance) and analysis_mode != DAILY_RETURN_MODE:
        raise RunManifestError("direct_standard 仅对应 daily_return analysis mode。")
    if isinstance(provenance, NavAdapterProvenance) and analysis_mode != NAV_MODE:
        raise RunManifestError("nav_adapter 仅对应 nav analysis mode。")


def _workflow_keys_payload(keys: WorkflowKeys | None) -> dict[str, object] | None:
    if keys is None:
        return None
    payload: dict[str, object] = {
        name: value
        for name, value in (
            ("source_key", keys.source_key),
            ("mapping_key", keys.mapping_key),
            ("standardization_key", keys.standardization_key),
            ("analysis_request_key", keys.analysis_request_key),
        )
        if value is not None
    }
    return payload or None


def _provenance_manifest_payload(provenance: RunProvenance) -> dict[str, object]:
    payload = _provenance_identity_payload(provenance)
    workflow_keys = _workflow_keys_payload(provenance.workflow_keys)
    if workflow_keys is not None:
        payload["workflow_keys"] = workflow_keys
    return payload


def _build_data_summary(canonical_data: CanonicalAnalysisData) -> DataSummary:
    date_index = canonical_data.columns.index("date")
    return_index = canonical_data.columns.index("strategy_return")
    return DataSummary(
        row_count=len(canonical_data.rows),
        valid_return_count=sum(row[return_index] is not None for row in canonical_data.rows),
        start_date=str(canonical_data.rows[0][date_index]),
        end_date=str(canonical_data.rows[-1][date_index]),
        benchmark_present="benchmark_return" in canonical_data.columns,
        strategy_nav_present="strategy_nav" in canonical_data.columns,
    )


def _generated_at_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RunManifestError("generated_at 必须包含明确 timezone。")
    normalized = value.astimezone(UTC).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")
