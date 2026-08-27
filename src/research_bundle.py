"""Deterministic in-memory packaging for single-analysis research artifacts.

The bundle layer accepts final downloadable artifacts and a current Manifest
export. It does not read sources, transform data, rebuild identities, or write
files.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Final
from zipfile import ZIP_STORED, ZipFile, ZipInfo

if TYPE_CHECKING:
    from src.run_manifest import ApplicationMetadata
    from src.run_manifest_integration import ManifestExport

BUNDLE_INDEX_SCHEMA_VERSION: Final = "qrw-research-bundle-index-v1"
BUNDLE_MIME_TYPE: Final = "application/zip"
BUNDLE_INDEX_MIME_TYPE: Final = "application/json"

REPORT_PATH: Final = "analysis_report.md"
STANDARDIZED_DATA_PATH: Final = "standardized_data.csv"
RUN_MANIFEST_PATH: Final = "run_manifest.json"
BUNDLE_INDEX_PATH: Final = "bundle_index.json"

REPORT_MIME_TYPE: Final = "text/markdown; charset=utf-8"
STANDARDIZED_DATA_MIME_TYPE: Final = "text/csv; charset=utf-8"
RUN_MANIFEST_MIME_TYPE: Final = "application/json"

CONTENT_MEMBER_PATHS: Final = (
    REPORT_PATH,
    STANDARDIZED_DATA_PATH,
    RUN_MANIFEST_PATH,
)
BUNDLE_MEMBER_PATHS: Final = (*CONTENT_MEMBER_PATHS, BUNDLE_INDEX_PATH)
ZIP_MEMBER_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)
ZIP_MEMBER_CREATE_SYSTEM: Final = 3
ZIP_MEMBER_EXTERNAL_ATTR: Final = 0o100644 << 16

_MEMBER_MEDIA_TYPES: Final = {
    REPORT_PATH: REPORT_MIME_TYPE,
    STANDARDIZED_DATA_PATH: STANDARDIZED_DATA_MIME_TYPE,
    RUN_MANIFEST_PATH: RUN_MANIFEST_MIME_TYPE,
    BUNDLE_INDEX_PATH: BUNDLE_INDEX_MIME_TYPE,
}
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ResearchBundleError(ValueError):
    """Raised when bundle inputs violate the fixed packaging contract."""


@dataclass(frozen=True)
class BundleArtifact:
    """One exact byte payload written under an application-defined member path."""

    path: str
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        _validate_member_path(self.path)
        expected_media_type = _MEMBER_MEDIA_TYPES.get(self.path)
        if expected_media_type is None:
            raise ResearchBundleError(f"不支持的研究包成员：{self.path}")
        if self.media_type != expected_media_type:
            raise ResearchBundleError(f"{self.path} 的 media_type 不符合固定合同。")
        if not isinstance(self.content, bytes):
            raise TypeError("bundle artifact content 必须是 bytes。")


@dataclass(frozen=True)
class BundleFileEntry:
    """Integrity metadata for one non-index bundle artifact."""

    path: str
    media_type: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_member_path(self.path)
        if self.path not in CONTENT_MEMBER_PATHS:
            raise ResearchBundleError("bundle index 只能记录三个内容 artifact。")
        if self.media_type != _MEMBER_MEDIA_TYPES[self.path]:
            raise ResearchBundleError(f"{self.path} 的 index media_type 不符合固定合同。")
        if self.size_bytes < 0:
            raise ResearchBundleError("bundle artifact size_bytes 不能为负数。")
        _require_sha256_identifier(self.sha256, "artifact sha256")


@dataclass(frozen=True)
class BundleIndex:
    """Artifact inventory and exact-byte integrity index; not a new identity."""

    application: ApplicationMetadata
    analysis_id: str
    run_id: str
    files: tuple[BundleFileEntry, ...]
    schema_version: str = BUNDLE_INDEX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BUNDLE_INDEX_SCHEMA_VERSION:
            raise ResearchBundleError("bundle index schema_version 不受支持。")
        _require_sha256_identifier(self.analysis_id, "analysis_id")
        _require_sha256_identifier(self.run_id, "run_id")
        if tuple(entry.path for entry in self.files) != CONTENT_MEMBER_PATHS:
            raise ResearchBundleError("bundle index files 必须按固定顺序记录三个内容 artifact。")

    @property
    def json_bytes(self) -> bytes:
        """Serialize the fixed public index shape as compact UTF-8 JSON."""

        return bundle_index_json_bytes(self)


@dataclass(frozen=True)
class ResearchBundle:
    """Frozen bundle inputs with filename, index bytes, and ZIP bytes derived on demand."""

    artifacts: tuple[BundleArtifact, ...]
    index: BundleIndex

    def __post_init__(self) -> None:
        if tuple(artifact.path for artifact in self.artifacts) != CONTENT_MEMBER_PATHS:
            raise ResearchBundleError("ResearchBundle 必须按固定顺序保存三个内容 artifact。")
        expected_entries = tuple(_build_file_entry(artifact) for artifact in self.artifacts)
        if self.index.files != expected_entries:
            raise ResearchBundleError("bundle index 必须与 exact artifact bytes 一致。")

    @property
    def members(self) -> tuple[BundleArtifact, ...]:
        """Return all four ZIP members in their fixed archive order."""

        index_artifact = BundleArtifact(
            path=BUNDLE_INDEX_PATH,
            media_type=BUNDLE_INDEX_MIME_TYPE,
            content=self.index.json_bytes,
        )
        return (*self.artifacts, index_artifact)

    @property
    def zip_bytes(self) -> bytes:
        """Build deterministic ZIP_STORED bytes entirely in memory."""

        output = BytesIO()
        with ZipFile(output, mode="w", compression=ZIP_STORED) as archive:
            archive.comment = b""
            for artifact in self.members:
                archive.writestr(_zip_info(artifact.path), artifact.content)
        return output.getvalue()

    @property
    def filename(self) -> str:
        """Return a safe run-derived bundle download filename."""

        return make_bundle_filename(self.index.run_id)

    @property
    def mime_type(self) -> str:
        """Return the public ZIP download MIME type."""

        return BUNDLE_MIME_TYPE


def build_research_bundle(
    *,
    report_bytes: bytes,
    standardized_csv_bytes: bytes,
    manifest_export: ManifestExport,
) -> ResearchBundle:
    """Package final standalone bytes without rebuilding any analysis artifact."""

    artifacts = (
        BundleArtifact(REPORT_PATH, REPORT_MIME_TYPE, report_bytes),
        BundleArtifact(
            STANDARDIZED_DATA_PATH,
            STANDARDIZED_DATA_MIME_TYPE,
            standardized_csv_bytes,
        ),
        BundleArtifact(
            RUN_MANIFEST_PATH,
            RUN_MANIFEST_MIME_TYPE,
            manifest_export.json_bytes,
        ),
    )
    manifest = manifest_export.manifest
    index = BundleIndex(
        application=manifest.application,
        analysis_id=manifest.run_identity.analysis_id,
        run_id=manifest.run_identity.run_id,
        files=tuple(_build_file_entry(artifact) for artifact in artifacts),
    )
    return ResearchBundle(artifacts=artifacts, index=index)


def bundle_index_json_bytes(index: BundleIndex) -> bytes:
    """Serialize an integrity index without adding it to its own inventory."""

    payload: dict[str, object] = {
        "analysis_id": index.analysis_id,
        "application": {
            "name": index.application.name,
            "version": index.application.version,
        },
        "files": [
            {
                "media_type": entry.media_type,
                "path": entry.path,
                "sha256": entry.sha256,
                "size_bytes": entry.size_bytes,
            }
            for entry in index.files
        ],
        "run_id": index.run_id,
        "schema_version": index.schema_version,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def make_bundle_filename(run_id: str) -> str:
    """Build the deterministic public filename from the full run digest."""

    _require_sha256_identifier(run_id, "run_id")
    return f"qrw_bundle_{run_id.removeprefix('sha256:')[:16]}.zip"


def _build_file_entry(artifact: BundleArtifact) -> BundleFileEntry:
    return BundleFileEntry(
        path=artifact.path,
        media_type=artifact.media_type,
        size_bytes=len(artifact.content),
        sha256=_sha256_identifier(artifact.content),
    )


def _zip_info(path: str) -> ZipInfo:
    _validate_member_path(path)
    info = ZipInfo(filename=path, date_time=ZIP_MEMBER_TIMESTAMP)
    info.compress_type = ZIP_STORED
    info.create_system = ZIP_MEMBER_CREATE_SYSTEM
    info.external_attr = ZIP_MEMBER_EXTERNAL_ATTR
    info.extra = b""
    info.comment = b""
    return info


def _validate_member_path(path: str) -> None:
    if not path or path in {".", ".."}:
        raise ResearchBundleError("研究包成员路径不能为空或点路径。")
    if "/" in path or "\\" in path or ":" in path:
        raise ResearchBundleError("研究包成员路径不得包含目录、盘符或路径分隔符。")


def _sha256_identifier(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _require_sha256_identifier(value: str, field_name: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ResearchBundleError(f"{field_name} 必须是 sha256:<64 lowercase hex>。")
