"""CSV/XLSX 通用文件读取与预览层测试。"""

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
import pandas as pd
import pytest

from src.config import SINGLE_FILE_MAX_MB
from src.file_import import (
    CSV_ENCODING_ERROR,
    FileImportError,
    get_xlsx_sheet_names,
    import_table,
    read_uploaded_bytes,
)
from src.limits import BYTES_PER_MB, UploadLimitError


def _xlsx_bytes(
    sheets: dict[str, list[list[object]]],
    *,
    hidden_sheets: tuple[str, ...] = (),
) -> bytes:
    """在内存中生成固定 XLSX 测试文件。"""
    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)
    for sheet_name, rows in sheets.items():
        worksheet = workbook.create_sheet(sheet_name)
        for row in rows:
            worksheet.append(row)
        if sheet_name in hidden_sheets:
            worksheet.sheet_state = "hidden"

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


class _NamedUpload(BytesIO):
    """为内存字节增加上传文件名。"""

    def __init__(self, content: bytes, name: str) -> None:
        super().__init__(content)
        self.name = name


class _OversizedUpload:
    """确保超限元数据在读取内容前被拒绝。"""

    name = "oversized.csv"
    size = (SINGLE_FILE_MAX_MB + 1) * BYTES_PER_MB

    def read(self) -> bytes:
        raise AssertionError("超限文件不应进入读取阶段")


def test_reads_utf8_csv() -> None:
    result = import_table("returns.csv", "日期,收益\n2026-01-01,0.01\n".encode())

    assert result.encoding == "utf-8"
    assert result.dataframe.iloc[0].tolist() == ["2026-01-01", 0.01]


def test_reads_utf8_bom_csv() -> None:
    result = import_table(
        "returns.csv", "日期,收益\n2026-01-01,0.01\n".encode("utf-8-sig")
    )

    assert result.encoding == "utf-8-sig"
    assert result.column_names == ("日期", "收益")


def test_reads_gb18030_csv() -> None:
    result = import_table(
        "returns.csv", "日期,策略\n2026-01-01,上涨\n".encode("gb18030")
    )

    assert result.encoding == "gb18030"
    assert result.dataframe.iloc[0, 1] == "上涨"


@pytest.mark.parametrize(
    ("delimiter", "content"),
    (
        (",", b"a,b\n1,2\n"),
        ("\t", b"a\tb\n1\t2\n"),
        (";", b"a;b\n1;2\n"),
        ("|", b"a|b\n1|2\n"),
    ),
)
def test_auto_detects_supported_csv_delimiters(
    delimiter: str,
    content: bytes,
) -> None:
    result = import_table("table.csv", content)

    assert result.delimiter == delimiter
    assert result.column_names == ("a", "b")


def test_manual_csv_delimiter_override_is_applied() -> None:
    result = import_table("table.csv", b"a;b\n1;2\n", delimiter=";")

    assert result.delimiter == ";"
    assert result.column_count == 2


def test_invalid_manual_delimiter_is_rejected() -> None:
    with pytest.raises(FileImportError, match="分隔符设置无效"):
        import_table("table.csv", b"a,b\n1,2\n", delimiter=":")


def test_unsupported_csv_encoding_fails_without_ignoring_bytes() -> None:
    with pytest.raises(FileImportError, match=CSV_ENCODING_ERROR):
        import_table("table.csv", b"a,b\n\xff\xff,1\n")


def test_empty_csv_fails() -> None:
    with pytest.raises(FileImportError, match="文件为空"):
        import_table("empty.csv", b"")


def test_header_only_csv_fails() -> None:
    with pytest.raises(FileImportError, match="CSV文件为空"):
        import_table("header.csv", b"a,b\n")


def test_malformed_csv_fails_with_controlled_parser_error() -> None:
    with pytest.raises(FileImportError, match="CSV文件无法解析"):
        import_table("broken.csv", b'a,b\n1,"unterminated\n')


@pytest.mark.parametrize("extension", (".xls", ".xlsm", ".ods", ".zip", ".json"))
def test_unsupported_extensions_fail(extension: str) -> None:
    with pytest.raises(FileImportError, match="不支持的文件类型"):
        import_table(f"table{extension}", b"not-used")


def test_reads_valid_xlsx() -> None:
    content = _xlsx_bytes({"数据": [["日期", "收益"], ["2026-01-01", 0.01]]})

    result = import_table("table.xlsx", content)

    assert result.file_type == "XLSX"
    assert result.sheet_name == "数据"
    assert result.sheet_count == 1
    assert result.dataframe.iloc[0, 1] == pytest.approx(0.01)


def test_gets_multiple_xlsx_sheet_names_in_workbook_order() -> None:
    content = _xlsx_bytes(
        {
            "说明": [["text"], ["demo"]],
            "数据": [["value"], [1]],
        }
    )

    assert get_xlsx_sheet_names("table.xlsx", content) == ("说明", "数据")


def test_multiple_xlsx_sheets_require_explicit_selection() -> None:
    content = _xlsx_bytes(
        {"first": [["value"], [1]], "second": [["value"], [2]]}
    )

    with pytest.raises(FileImportError, match="请先明确选择"):
        import_table("table.xlsx", content)


def test_reads_explicitly_selected_xlsx_sheet() -> None:
    content = _xlsx_bytes(
        {"first": [["value"], [1]], "second": [["value"], [2]]}
    )

    result = import_table("table.xlsx", content, sheet_name="second")

    assert result.sheet_name == "second"
    assert result.dataframe.iloc[0, 0] == 2


def test_hidden_xlsx_sheet_is_listed_and_readable() -> None:
    content = _xlsx_bytes(
        {"visible": [["value"], [1]], "hidden": [["value"], [2]]},
        hidden_sheets=("hidden",),
    )

    assert get_xlsx_sheet_names("table.xlsx", content) == ("visible", "hidden")
    result = import_table("table.xlsx", content, sheet_name="hidden")
    assert result.dataframe.iloc[0, 0] == 2


def test_empty_xlsx_sheet_fails() -> None:
    content = _xlsx_bytes({"empty": []})

    with pytest.raises(FileImportError, match="工作表.*为空"):
        import_table("empty.xlsx", content)


def test_missing_xlsx_sheet_fails() -> None:
    content = _xlsx_bytes({"data": [["value"], [1]]})

    with pytest.raises(FileImportError, match="不存在工作表"):
        import_table("table.xlsx", content, sheet_name="missing")


def test_corrupt_xlsx_fails_with_controlled_error() -> None:
    with pytest.raises(FileImportError, match="XLSX文件无法读取"):
        import_table("broken.xlsx", b"not an xlsx workbook")


def test_xlsx_without_sheet_names_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WorkbookWithoutSheets:
        sheet_names: tuple[str, ...] = ()

        def __enter__(self) -> "_WorkbookWithoutSheets":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "src.file_import.pd.ExcelFile",
        lambda *args, **kwargs: _WorkbookWithoutSheets(),
    )

    with pytest.raises(FileImportError, match="没有可读取的工作表"):
        get_xlsx_sheet_names("table.xlsx", b"placeholder")


def test_missing_openpyxl_dependency_uses_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_import_error(*args: object, **kwargs: object) -> None:
        raise ImportError("missing")

    monkeypatch.setattr("src.file_import.pd.ExcelFile", _raise_import_error)

    with pytest.raises(FileImportError, match="缺少Excel读取依赖openpyxl"):
        get_xlsx_sheet_names("table.xlsx", b"placeholder")


def test_file_size_limit_is_checked_before_upload_read() -> None:
    with pytest.raises(UploadLimitError, match="超过允许上限"):
        read_uploaded_bytes(_OversizedUpload())  # type: ignore[arg-type]


def test_row_limit_fails_without_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.file_import.MAX_ROWS_PER_FILE", 1)

    with pytest.raises(
        UploadLimitError,
        match="数据行数为 2.*允许上限 1 行",
    ):
        import_table("rows.csv", b"value\n1\n2\n")


def test_column_limit_fails_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.file_import.MAX_COLUMNS_PER_FILE", 2)

    with pytest.raises(
        UploadLimitError,
        match="数据列数为 3.*允许上限 2 列",
    ):
        import_table("columns.csv", b"a,b,c\n1,2,3\n")


def test_import_does_not_modify_input_bytes() -> None:
    content = b"a,b\n1,2\n"
    original = bytes(content)

    import_table("table.csv", content)

    assert content == original


def test_uploaded_name_is_sanitized_without_local_path_dependency() -> None:
    upload = _NamedUpload(b"a,b\n1,2\n", r"C:\private\folder\table.csv")

    file_name, content = read_uploaded_bytes(upload)
    result = import_table(file_name, content)

    assert result.file_name == "table.csv"
    assert "private" not in result.file_name


def test_import_does_not_write_to_data_directory() -> None:
    data_directory = Path("data")
    before = {path.relative_to(data_directory) for path in data_directory.rglob("*")}

    import_table("table.csv", b"a,b\n1,2\n")

    after = {path.relative_to(data_directory) for path in data_directory.rglob("*")}
    assert after == before


def test_returns_correct_shape_and_column_names() -> None:
    result = import_table("table.csv", b"alpha,beta\n1,2\n3,4\n")

    assert result.row_count == 2
    assert result.column_count == 2
    assert result.column_names == ("alpha", "beta")


def test_reports_duplicate_and_whitespace_column_names() -> None:
    result = import_table("table.csv", b"alpha, alpha,alpha\n1,2,3\n")

    assert result.whitespace_column_names == (" alpha",)
    assert result.duplicate_column_names == ("alpha",)
    assert result.dataframe.shape == (1, 3)
    assert any("重复字段" in warning for warning in result.warnings)


def test_reports_empty_unnamed_and_fully_empty_column_without_deleting_it() -> None:
    result = import_table("table.csv", b"alpha,,gamma\n1,,3\n2,,4\n")

    assert result.empty_column_names == ("",)
    assert result.unnamed_columns == ("Unnamed: 1",)
    assert result.fully_empty_columns == ("Unnamed: 1",)
    assert result.column_count == 3
    assert "Unnamed: 1" in result.dataframe.columns


def test_mixed_type_column_only_warns_and_preserves_values() -> None:
    content = _xlsx_bytes({"data": [["mixed"], [1], ["text"]]})

    result = import_table("table.xlsx", content)

    assert result.mixed_type_columns == ("mixed",)
    assert result.dataframe["mixed"].tolist() == [1, "text"]
    assert any("混合类型" in warning for warning in result.warnings)


def test_uploaded_stream_position_is_preserved() -> None:
    upload = _NamedUpload(b"a,b\n1,2\n", "table.csv")
    upload.seek(3)

    _, content = read_uploaded_bytes(upload)

    assert content == b"a,b\n1,2\n"
    assert upload.tell() == 3


def test_file_size_and_csv_metadata_are_returned() -> None:
    content = b"a;b\n1;2\n"

    result = import_table("table.csv", content)

    assert result.file_size_bytes == len(content)
    assert result.file_type == "CSV"
    assert result.sheet_name is None
    assert result.sheet_count is None
    assert result.encoding == "utf-8"
    assert result.delimiter == ";"


def test_dataframe_keeps_all_rows_beyond_twenty_row_preview_boundary() -> None:
    rows = "".join(f"{index}\n" for index in range(25))

    result = import_table("table.csv", f"value\n{rows}".encode())

    assert result.row_count == 25
    assert len(result.dataframe) == 25
