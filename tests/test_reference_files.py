"""仓库静态参考文件的清单、路径和完整性测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import socket
import urllib.request

from openpyxl import Workbook
import pandas as pd
import pytest

import src.reference_files as reference_files
from src.reference_files import (
    ALLOWED_FILE_TYPES,
    DOCUMENTED_SUPPORT_FILES,
    REQUIRED_CATALOG_FIELDS,
    ReferenceFileError,
    _ensure_within_reference_root,
    load_reference_catalog,
    load_reference_file_bytes,
    load_reference_manifest,
    resolve_reference_file,
    validate_reference_catalog,
    validate_reference_manifest,
)
from src import ui_reference_files


REFERENCE_ROOT = Path("assets/reference_files")


def _catalog_payload(root: Path = REFERENCE_ROOT) -> dict[str, object]:
    return json.loads((root / "catalog.json").read_text(encoding="utf-8"))


def _manifest_payload(root: Path = REFERENCE_ROOT) -> list[dict[str, object]]:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def copied_reference_root(tmp_path: Path) -> Path:
    target = tmp_path / "reference_files"
    shutil.copytree(REFERENCE_ROOT, target)
    return target


def test_catalog_can_be_loaded_and_has_expected_schema() -> None:
    catalog = load_reference_catalog()

    assert catalog.schema_version == 1
    assert catalog.pack_version == "qrw-reference-files-v1"
    assert catalog.synthetic_data_only is True
    assert len(catalog.files) == 11


def test_catalog_entries_have_complete_public_metadata() -> None:
    payload = _catalog_payload()

    assert all(REQUIRED_CATALOG_FIELDS <= set(item) for item in payload["files"])


def test_catalog_ids_filenames_and_paths_are_unique() -> None:
    catalog = load_reference_catalog()

    assert len({entry.id for entry in catalog.files}) == len(catalog.files)
    assert len({entry.filename for entry in catalog.files}) == len(catalog.files)
    assert len({entry.relative_path for entry in catalog.files}) == len(catalog.files)


@pytest.mark.parametrize(
    "unsafe_path",
    (
        "/etc/passwd",
        "C:/Users/example/secret.csv",
        "C:\\Users\\example\\secret.csv",
        "../outside.csv",
        "valid/../../outside.csv",
    ),
)
def test_catalog_rejects_absolute_and_parent_paths(unsafe_path: str) -> None:
    payload = _catalog_payload()
    payload["files"][0]["relative_path"] = unsafe_path

    with pytest.raises(ReferenceFileError, match="路径"):
        validate_reference_catalog(payload)


def test_resolved_path_cannot_escape_reference_root() -> None:
    root = REFERENCE_ROOT.resolve()

    with pytest.raises(ReferenceFileError, match="超出允许目录"):
        _ensure_within_reference_root(root.parent / "outside.csv", root)


def test_catalog_referenced_files_exist_inside_expected_group_directories() -> None:
    catalog = load_reference_catalog()

    for entry in catalog.files:
        resolved = resolve_reference_file(entry.relative_path)
        assert resolved.exists()
        assert resolved.is_file()
        assert resolved.parent.name == entry.group


def test_manifest_referenced_files_exist() -> None:
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)

    assert all(resolve_reference_file(relative_path).is_file() for relative_path in manifest)


def test_catalog_and_manifest_are_mutually_complete() -> None:
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)
    expected_paths = {
        *(entry.relative_path for entry in catalog.files),
        *DOCUMENTED_SUPPORT_FILES,
    }

    assert set(manifest) == expected_paths


def test_manifest_sizes_and_sha256_match_static_files() -> None:
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)

    for relative_path, entry in manifest.items():
        file_bytes = resolve_reference_file(relative_path).read_bytes()
        assert len(file_bytes) == entry.size_bytes
        assert hashlib.sha256(file_bytes).hexdigest() == entry.sha256


def test_modified_file_with_same_size_fails_sha256_validation(
    copied_reference_root: Path,
) -> None:
    target = copied_reference_root / "valid" / "01_standard_returns_with_benchmark.csv"
    changed = bytearray(target.read_bytes())
    changed[-2] ^= 1
    target.write_bytes(changed)
    catalog = load_reference_catalog(root=copied_reference_root)

    with pytest.raises(ReferenceFileError, match="SHA-256"):
        load_reference_manifest(catalog, root=copied_reference_root)


def test_missing_catalog_file_fails_with_controlled_error(
    copied_reference_root: Path,
) -> None:
    target = copied_reference_root / "valid" / "02_standard_returns_no_benchmark.csv"
    target.unlink()

    with pytest.raises(ReferenceFileError, match="不存在"):
        load_reference_catalog(root=copied_reference_root)


def test_unknown_catalog_file_type_is_rejected() -> None:
    payload = _catalog_payload()
    payload["files"][0]["file_type"] = "PDF"

    with pytest.raises(ReferenceFileError, match="不支持"):
        validate_reference_catalog(payload)


def test_manifest_rejects_unknown_and_missing_entries(
    copied_reference_root: Path,
) -> None:
    catalog = load_reference_catalog(root=copied_reference_root)
    missing_payload = _manifest_payload(copied_reference_root)[:-1]
    with pytest.raises(ReferenceFileError, match="缺少"):
        validate_reference_manifest(
            missing_payload,
            catalog,
            root=copied_reference_root,
        )

    extra_path = copied_reference_root / "extra.csv"
    extra_path.write_bytes(b"a,b\n1,2\n")
    extra_bytes = extra_path.read_bytes()
    unknown_payload = _manifest_payload(copied_reference_root)
    unknown_payload.append(
        {
            "relative_path": "extra.csv",
            "sha256": hashlib.sha256(extra_bytes).hexdigest(),
            "size_bytes": len(extra_bytes),
        }
    )
    with pytest.raises(ReferenceFileError, match="未知"):
        validate_reference_manifest(
            unknown_payload,
            catalog,
            root=copied_reference_root,
        )


def test_csv_and_xlsx_mime_types_are_explicit() -> None:
    catalog = load_reference_catalog()
    mime_by_type = {entry.file_type: entry.mime_type for entry in catalog.files}

    assert mime_by_type["CSV"] == "text/csv"
    assert mime_by_type["XLSX"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert set(mime_by_type) == set(ALLOWED_FILE_TYPES)


def test_download_bytes_match_static_files_exactly() -> None:
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)

    for entry in catalog.files:
        assert load_reference_file_bytes(entry, manifest) == resolve_reference_file(
            entry.relative_path
        ).read_bytes()


def test_csv_download_does_not_use_dataframe_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pd.DataFrame,
        "to_csv",
        lambda *_args, **_kwargs: pytest.fail("download re-exported CSV"),
    )
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)
    entry = next(item for item in catalog.files if item.file_type == "CSV")

    assert load_reference_file_bytes(entry, manifest)


def test_xlsx_download_does_not_rewrite_workbook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        Workbook,
        "save",
        lambda *_args, **_kwargs: pytest.fail("download rewrote XLSX"),
    )
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)
    entry = next(item for item in catalog.files if item.file_type == "XLSX")

    assert load_reference_file_bytes(entry, manifest)


def test_public_catalog_objects_do_not_expose_server_absolute_paths() -> None:
    catalog = load_reference_catalog()
    root_text = str(REFERENCE_ROOT.resolve())

    assert all(root_text not in repr(entry) for entry in catalog.files)
    assert all(not Path(entry.relative_path).is_absolute() for entry in catalog.files)


def test_reference_loader_refuses_to_read_outside_file() -> None:
    with pytest.raises(ReferenceFileError, match="路径"):
        resolve_reference_file("../README.md")


def test_catalog_group_counts_and_expected_results_are_exact() -> None:
    catalog = load_reference_catalog()
    valid = catalog.by_group("valid")
    errors = catalog.by_group("error_examples")

    assert len(valid) == 6
    assert len(errors) == 5
    assert all(entry.expected_result == "pass" for entry in valid)
    assert all(entry.expected_result == "block" for entry in errors)


def test_every_reference_file_is_marked_as_synthetic() -> None:
    catalog = load_reference_catalog()

    assert catalog.synthetic_data_only
    assert "确定性合成数据" in catalog.disclaimer
    assert all("确定性合成数据" in entry.safety_note for entry in catalog.files)


def test_multisheet_xlsx_and_expected_outcomes_exist() -> None:
    catalog = load_reference_catalog()
    xlsx = next(entry for entry in catalog.files if entry.file_type == "XLSX")

    assert xlsx.filename == "11_multi_sheet_online_regression.xlsx"
    assert resolve_reference_file(xlsx.relative_path).suffix == ".xlsx"
    assert resolve_reference_file("expected_outcomes.csv").is_file()


def test_manifest_loading_is_deterministic_and_repeatable() -> None:
    catalog = load_reference_catalog()
    first = dict(load_reference_manifest(catalog))
    second = dict(load_reference_manifest(catalog))

    assert first == second


def test_loading_reference_library_does_not_modify_files() -> None:
    before = {
        path: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in REFERENCE_ROOT.rglob("*")
        if path.is_file()
    }
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)
    for entry in catalog.files:
        load_reference_file_bytes(entry, manifest)
    after = {
        path: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in REFERENCE_ROOT.rglob("*")
        if path.is_file()
    }

    assert after == before


def test_page_loader_returns_controlled_failure_when_files_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_files, "REFERENCE_ROOT", tmp_path)

    assert ui_reference_files._load_library() is None
    assert "下载已禁用" in ui_reference_files.LIBRARY_ERROR_MESSAGE


def test_integrity_failure_disables_page_library(
    copied_reference_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = copied_reference_root / "valid" / "03_generic_cn_returns.csv"
    target.write_bytes(target.read_bytes() + b"changed")
    monkeypatch.setattr(reference_files, "REFERENCE_ROOT", copied_reference_root)

    assert ui_reference_files._load_library() is None


def test_reference_page_does_not_import_analysis_or_upload_modules() -> None:
    source = Path("src/ui_reference_files.py").read_text(encoding="utf-8")
    reference_source = Path("src/reference_files.py").read_text(encoding="utf-8")
    forbidden_modules = (
        "src.performance",
        "src.reporting",
        "src.analysis_bridge",
        "src.data_loader",
        "src.file_import",
        "src.field_mapping",
        "src.standardization",
    )

    assert all(module not in source for module in forbidden_modules)
    assert all(module not in reference_source for module in forbidden_modules)


def test_reference_loading_does_not_write_to_data_directory() -> None:
    data_root = Path("data")
    before = {
        path.relative_to(data_root): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in data_root.rglob("*")
        if path.is_file()
    }
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)
    load_reference_file_bytes(catalog.files[0], manifest)
    after = {
        path.relative_to(data_root): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in data_root.rglob("*")
        if path.is_file()
    }

    assert after == before


def test_reference_loading_creates_no_temporary_files(tmp_path: Path) -> None:
    before = set(tmp_path.iterdir())
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)
    load_reference_file_bytes(catalog.files[-1], manifest)

    assert set(tmp_path.iterdir()) == before


def test_reference_loading_does_not_use_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: pytest.fail("reference loader used network"),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("reference loader used network"),
    )
    catalog = load_reference_catalog()
    manifest = load_reference_manifest(catalog)

    assert load_reference_file_bytes(catalog.files[0], manifest)
