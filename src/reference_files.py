"""安全加载仓库内置的确定性合成参考文件。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Final, Mapping


REFERENCE_ROOT: Final = Path(__file__).resolve().parents[1] / "assets" / "reference_files"
CATALOG_FILENAME: Final = "catalog.json"
MANIFEST_FILENAME: Final = "manifest.json"
DOCUMENTED_SUPPORT_FILES: Final = frozenset(
    {CATALOG_FILENAME, ".gitattributes", "README.md", "expected_outcomes.csv"}
)
ALLOWED_GROUPS: Final = frozenset({"valid", "error_examples"})
ALLOWED_FILE_TYPES: Final = MappingProxyType(
    {
        "CSV": (".csv", "text/csv"),
        "XLSX": (
            ".xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    }
)
EXPECTED_GROUP_COUNTS: Final = MappingProxyType({"valid": 6, "error_examples": 5})
REQUIRED_CATALOG_FIELDS: Final = frozenset(
    {
        "id",
        "filename",
        "relative_path",
        "title",
        "group",
        "file_type",
        "description",
        "recommended_entry",
        "recommended_primary_basis",
        "recommended_mapping",
        "contains_benchmark",
        "expected_result",
        "expected_stage",
        "expected_message",
        "safety_note",
    }
)


class ReferenceFileError(ValueError):
    """表示参考文件清单、路径或完整性不符合公开下载要求。"""


@dataclass(frozen=True)
class ReferenceFileEntry:
    """一份可下载参考文件的只读展示元数据。"""

    id: str
    filename: str
    relative_path: str
    title: str
    group: str
    file_type: str
    description: str
    recommended_entry: str
    recommended_primary_basis: str
    recommended_mapping: Mapping[str, str]
    contains_benchmark: bool
    expected_result: str
    expected_stage: str
    expected_message: str
    safety_note: str
    prohibited_automatic_action: str = ""

    @property
    def mime_type(self) -> str:
        """返回与清单文件类型对应的稳定下载 MIME 类型。"""

        return ALLOWED_FILE_TYPES[self.file_type][1]


@dataclass(frozen=True)
class ReferenceCatalog:
    """已验证的参考文件目录。"""

    schema_version: int
    pack_version: str
    synthetic_data_only: bool
    disclaimer: str
    files: tuple[ReferenceFileEntry, ...]

    def by_group(self, group: str) -> tuple[ReferenceFileEntry, ...]:
        """按目录中声明的固定顺序返回指定分组。"""

        return tuple(entry for entry in self.files if entry.group == group)


@dataclass(frozen=True)
class ManifestEntry:
    """静态资源在 manifest 中的大小和 SHA-256 记录。"""

    relative_path: str
    sha256: str
    size_bytes: int


def _reference_root(root: Path | None) -> Path:
    return Path(root if root is not None else REFERENCE_ROOT).resolve()


def _validate_relative_path(relative_path: object) -> PurePosixPath:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ReferenceFileError("参考文件相对路径不能为空。")
    if "\\" in relative_path:
        raise ReferenceFileError("参考文件路径必须使用仓库内的 POSIX 相对路径。")
    parsed = PurePosixPath(relative_path)
    if parsed.is_absolute() or re.match(r"^[A-Za-z]:", relative_path) or ".." in parsed.parts:
        raise ReferenceFileError("参考文件路径不能是绝对路径或包含 ..。")
    if any(part in {"", "."} for part in parsed.parts):
        raise ReferenceFileError("参考文件路径格式无效。")
    return parsed


def _ensure_within_reference_root(resolved: Path, root: Path) -> None:
    """拒绝解析后位于参考目录之外的路径，包括符号链接逃逸。"""

    if not resolved.is_relative_to(root):
        raise ReferenceFileError("参考文件路径解析后超出允许目录。")


def resolve_reference_file(relative_path: str, *, root: Path | None = None) -> Path:
    """将安全相对路径解析为参考目录内已存在的普通文件。"""

    parsed = _validate_relative_path(relative_path)
    root_path = _reference_root(root)
    candidate = root_path.joinpath(*parsed.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ReferenceFileError(f"参考文件不存在：{relative_path}") from exc
    _ensure_within_reference_root(resolved, root_path)
    if not resolved.is_file():
        raise ReferenceFileError(f"参考资源不是普通文件：{relative_path}")
    return resolved


def _required_text(item: Mapping[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ReferenceFileError(f"catalog 字段 {field} 必须是非空文本。")
    return value.strip()


def _validate_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, dict) or not value:
        raise ReferenceFileError("recommended_mapping 必须是非空对象。")
    normalized: dict[str, str] = {}
    for role, column_name in value.items():
        if not isinstance(role, str) or not role.strip():
            raise ReferenceFileError("推荐映射角色必须是非空文本。")
        if not isinstance(column_name, str) or not column_name.strip():
            raise ReferenceFileError("推荐映射字段必须是非空文本。")
        normalized[role.strip()] = column_name.strip()
    return MappingProxyType(normalized)


def _catalog_entry(item: object, *, root: Path) -> ReferenceFileEntry:
    if not isinstance(item, dict):
        raise ReferenceFileError("catalog 中的文件记录必须是对象。")
    missing = REQUIRED_CATALOG_FIELDS.difference(item)
    if missing:
        raise ReferenceFileError(
            "catalog 文件记录缺少字段：" + "、".join(sorted(missing))
        )

    relative_path = _required_text(item, "relative_path")
    parsed_path = _validate_relative_path(relative_path)
    filename = _required_text(item, "filename")
    group = _required_text(item, "group")
    file_type = _required_text(item, "file_type").upper()
    expected_result = _required_text(item, "expected_result")
    contains_benchmark = item.get("contains_benchmark")

    if filename != parsed_path.name:
        raise ReferenceFileError("catalog 文件名必须与相对路径末尾一致。")
    if group not in ALLOWED_GROUPS or parsed_path.parts[0] != group:
        raise ReferenceFileError("catalog 分组必须与相对路径目录一致。")
    if file_type not in ALLOWED_FILE_TYPES:
        raise ReferenceFileError(f"不支持的参考文件类型：{file_type}")
    expected_suffix = ALLOWED_FILE_TYPES[file_type][0]
    if parsed_path.suffix.lower() != expected_suffix:
        raise ReferenceFileError("catalog 文件类型与扩展名不一致。")
    if expected_result != ("pass" if group == "valid" else "block"):
        raise ReferenceFileError("catalog 分组与预期结果不一致。")
    if not isinstance(contains_benchmark, bool):
        raise ReferenceFileError("contains_benchmark 必须是布尔值。")

    safety_note = _required_text(item, "safety_note")
    if "确定性合成数据" not in safety_note:
        raise ReferenceFileError("每份参考文件必须明确标记为确定性合成数据。")

    resolve_reference_file(relative_path, root=root)
    return ReferenceFileEntry(
        id=_required_text(item, "id"),
        filename=filename,
        relative_path=relative_path,
        title=_required_text(item, "title"),
        group=group,
        file_type=file_type,
        description=_required_text(item, "description"),
        recommended_entry=_required_text(item, "recommended_entry"),
        recommended_primary_basis=_required_text(item, "recommended_primary_basis"),
        recommended_mapping=_validate_mapping(item.get("recommended_mapping")),
        contains_benchmark=contains_benchmark,
        expected_result=expected_result,
        expected_stage=_required_text(item, "expected_stage"),
        expected_message=_required_text(item, "expected_message"),
        safety_note=safety_note,
        prohibited_automatic_action=str(item.get("prohibited_automatic_action", "")).strip(),
    )


def validate_reference_catalog(
    payload: object,
    *,
    root: Path | None = None,
) -> ReferenceCatalog:
    """验证 catalog schema、分组、路径和静态文件存在性。"""

    if not isinstance(payload, dict):
        raise ReferenceFileError("catalog 根结构必须是对象。")
    if payload.get("schema_version") != 1:
        raise ReferenceFileError("catalog schema_version 必须为 1。")
    if payload.get("synthetic_data_only") is not True:
        raise ReferenceFileError("catalog 必须声明仅包含确定性合成数据。")
    pack_version = payload.get("pack_version")
    disclaimer = payload.get("disclaimer")
    raw_files = payload.get("files")
    if not isinstance(pack_version, str) or not pack_version.strip():
        raise ReferenceFileError("catalog pack_version 无效。")
    if not isinstance(disclaimer, str) or "确定性合成数据" not in disclaimer:
        raise ReferenceFileError("catalog 缺少合成数据声明。")
    if not isinstance(raw_files, list):
        raise ReferenceFileError("catalog files 必须是数组。")

    root_path = _reference_root(root)
    entries = tuple(_catalog_entry(item, root=root_path) for item in raw_files)
    identifiers = [entry.id for entry in entries]
    filenames = [entry.filename for entry in entries]
    paths = [entry.relative_path for entry in entries]
    if len(set(identifiers)) != len(identifiers):
        raise ReferenceFileError("catalog 文件 ID 必须唯一。")
    if len(set(filenames)) != len(filenames):
        raise ReferenceFileError("catalog 文件名必须唯一。")
    if len(set(paths)) != len(paths):
        raise ReferenceFileError("catalog 相对路径必须唯一。")
    for group, expected_count in EXPECTED_GROUP_COUNTS.items():
        actual_count = sum(entry.group == group for entry in entries)
        if actual_count != expected_count:
            raise ReferenceFileError(
                f"catalog 分组 {group} 应包含 {expected_count} 个文件。"
            )

    return ReferenceCatalog(
        schema_version=1,
        pack_version=pack_version.strip(),
        synthetic_data_only=True,
        disclaimer=disclaimer.strip(),
        files=entries,
    )


def load_reference_catalog(*, root: Path | None = None) -> ReferenceCatalog:
    """从固定参考目录加载并验证 UTF-8 catalog。"""

    root_path = _reference_root(root)
    catalog_path = root_path / CATALOG_FILENAME
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReferenceFileError("参考文件 catalog 无法安全读取。") from exc
    return validate_reference_catalog(payload, root=root_path)


def _manifest_entry(item: object, *, root: Path) -> ManifestEntry:
    if not isinstance(item, dict):
        raise ReferenceFileError("manifest 记录必须是对象。")
    relative_path = item.get("relative_path")
    sha256 = item.get("sha256")
    size_bytes = item.get("size_bytes")
    if not isinstance(relative_path, str):
        raise ReferenceFileError("manifest relative_path 无效。")
    _validate_relative_path(relative_path)
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ReferenceFileError("manifest SHA-256 必须是小写十六进制。")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
        raise ReferenceFileError("manifest size_bytes 必须是非负整数。")
    file_path = resolve_reference_file(relative_path, root=root)
    file_bytes = file_path.read_bytes()
    if len(file_bytes) != size_bytes:
        raise ReferenceFileError(f"参考文件大小校验失败：{relative_path}")
    if hashlib.sha256(file_bytes).hexdigest() != sha256:
        raise ReferenceFileError(f"参考文件 SHA-256 校验失败：{relative_path}")
    return ManifestEntry(relative_path, sha256, size_bytes)


def validate_reference_manifest(
    payload: object,
    catalog: ReferenceCatalog,
    *,
    root: Path | None = None,
) -> Mapping[str, ManifestEntry]:
    """验证 manifest 与 catalog 的相互完整性及全部静态文件哈希。"""

    if not isinstance(payload, list):
        raise ReferenceFileError("manifest 根结构必须是数组。")
    root_path = _reference_root(root)
    entries = tuple(_manifest_entry(item, root=root_path) for item in payload)
    paths = [entry.relative_path for entry in entries]
    if len(set(paths)) != len(paths):
        raise ReferenceFileError("manifest 相对路径必须唯一。")

    expected_paths = {
        *(entry.relative_path for entry in catalog.files),
        *DOCUMENTED_SUPPORT_FILES,
    }
    actual_paths = set(paths)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        unknown = sorted(actual_paths - expected_paths)
        details = []
        if missing:
            details.append("缺少：" + "、".join(missing))
        if unknown:
            details.append("未知：" + "、".join(unknown))
        raise ReferenceFileError("manifest 与 catalog 不完整一致；" + "；".join(details))
    return MappingProxyType({entry.relative_path: entry for entry in entries})


def load_reference_manifest(
    catalog: ReferenceCatalog,
    *,
    root: Path | None = None,
) -> Mapping[str, ManifestEntry]:
    """从固定参考目录读取并完整校验 manifest。"""

    root_path = _reference_root(root)
    manifest_path = root_path / MANIFEST_FILENAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReferenceFileError("参考文件 manifest 无法安全读取。") from exc
    return validate_reference_manifest(payload, catalog, root=root_path)


def load_reference_file_bytes(
    entry: ReferenceFileEntry,
    manifest: Mapping[str, ManifestEntry],
    *,
    root: Path | None = None,
) -> bytes:
    """读取静态原始字节，并在返回前再次核对大小与 SHA-256。"""

    manifest_entry = manifest.get(entry.relative_path)
    if manifest_entry is None:
        raise ReferenceFileError("参考文件缺少 manifest 记录，下载已禁用。")
    file_path = resolve_reference_file(entry.relative_path, root=root)
    file_bytes = file_path.read_bytes()
    if len(file_bytes) != manifest_entry.size_bytes:
        raise ReferenceFileError("参考文件大小已变化，下载已禁用。")
    if hashlib.sha256(file_bytes).hexdigest() != manifest_entry.sha256:
        raise ReferenceFileError("参考文件内容已变化，下载已禁用。")
    return file_bytes
