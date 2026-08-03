"""CSV/XLSX 通用文件读取、元数据和基础字段提示。"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO, StringIO
from numbers import Number
from pathlib import PureWindowsPath
from typing import BinaryIO

import pandas as pd

from src.config import MAX_COLUMNS_PER_FILE, MAX_ROWS_PER_FILE, SINGLE_FILE_MAX_MB
from src.limits import (
    UploadLimitError,
    get_source_filename,
    validate_file_size,
    validate_row_count,
)


SUPPORTED_EXTENSIONS = (".csv", ".xlsx")
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")
CSV_DELIMITERS = (",", "\t", ";", "|")
CSV_DELIMITER_LABELS = {
    "自动识别": None,
    "逗号": ",",
    "制表符": "\t",
    "分号": ";",
    "竖线": "|",
}
CSV_DELIMITER_DISPLAY = {
    ",": "逗号（,）",
    "\t": "制表符（Tab）",
    ";": "分号（;）",
    "|": "竖线（|）",
}
CSV_ENCODING_ERROR = (
    "无法识别CSV文本编码。当前支持UTF-8、UTF-8 BOM和GB18030，"
    "请将文件另存为这些编码后重试。"
)


class FileImportError(ValueError):
    """表示用户可通过修正文件或解析设置解决的导入问题。"""


@dataclass
class ImportedTable:
    """保存通用读取结果、文件元数据和不修改数据的基础提示。"""

    file_name: str
    file_type: str
    file_size_bytes: int
    sheet_name: str | None
    sheet_count: int | None
    encoding: str | None
    delimiter: str | None
    row_count: int
    column_count: int
    column_names: tuple[str, ...]
    original_column_names: tuple[str, ...]
    duplicate_column_names: tuple[str, ...]
    empty_column_names: tuple[str, ...]
    whitespace_column_names: tuple[str, ...]
    unnamed_columns: tuple[str, ...]
    fully_empty_columns: tuple[str, ...]
    mixed_type_columns: tuple[str, ...]
    warnings: tuple[str, ...]
    dataframe: pd.DataFrame


def read_uploaded_bytes(source: BinaryIO) -> tuple[str, bytes]:
    """在读取前检查上传大小，并返回不含本地路径的文件名和字节。"""
    filename = _safe_filename(
        get_source_filename(source, fallback="上传文件")
    )
    _validate_extension(filename)
    validate_file_size(source, filename, SINGLE_FILE_MAX_MB)

    get_value = getattr(source, "getvalue", None)
    if callable(get_value):
        value = get_value()
        content = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    else:
        original_position = source.tell() if hasattr(source, "tell") else None
        if hasattr(source, "seek"):
            source.seek(0)
        content = bytes(source.read())
        if original_position is not None and hasattr(source, "seek"):
            source.seek(original_position)

    if not content:
        raise FileImportError("上传文件为空，请选择包含表头和数据的文件。")
    return filename, content


def get_xlsx_sheet_names(file_name: str, content: bytes) -> tuple[str, ...]:
    """安全取得 XLSX 工作表名称，不执行宏或加载外部链接。"""
    safe_name = _prepare_content(file_name, content, expected_extension=".xlsx")
    try:
        with pd.ExcelFile(BytesIO(content), engine="openpyxl") as workbook:
            sheet_names = tuple(str(name) for name in workbook.sheet_names)
    except ImportError as exc:
        raise FileImportError(
            "缺少Excel读取依赖openpyxl，请安装项目requirements.txt后重试。"
        ) from exc
    except Exception as exc:
        raise FileImportError(
            f"{safe_name}：XLSX文件无法读取，请确认文件有效且未损坏。"
        ) from exc

    if not sheet_names:
        raise FileImportError(f"{safe_name}：XLSX文件没有可读取的工作表。")
    return sheet_names


def import_table(
    file_name: str,
    content: bytes,
    *,
    delimiter: str | None = None,
    sheet_name: str | None = None,
) -> ImportedTable:
    """读取 CSV 或指定 XLSX 工作表，返回统一预览结果。"""
    safe_name = _prepare_content(file_name, content)
    extension = PureWindowsPath(safe_name).suffix.lower()
    if extension == ".csv":
        return _import_csv(safe_name, content, delimiter)
    return _import_xlsx(safe_name, content, sheet_name)


def _prepare_content(
    file_name: str,
    content: bytes,
    expected_extension: str | None = None,
) -> str:
    """验证扩展名、空内容和解析前文件大小。"""
    safe_name = _safe_filename(file_name)
    extension = _validate_extension(safe_name)
    if expected_extension is not None and extension != expected_extension:
        raise FileImportError(f"{safe_name}：当前操作仅支持XLSX文件。")
    if not content:
        raise FileImportError("上传文件为空，请选择包含表头和数据的文件。")

    source = BytesIO(content)
    validate_file_size(source, safe_name, SINGLE_FILE_MAX_MB)
    return safe_name


def _validate_extension(file_name: str) -> str:
    """只允许 CSV 和 XLSX，拒绝其他相近或压缩格式。"""
    safe_name = _safe_filename(file_name)
    extension = PureWindowsPath(safe_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise FileImportError(
            f"{safe_name}：不支持的文件类型。"
            "当前通用导入仅支持CSV和XLSX。"
        )
    return extension


def _safe_filename(file_name: str) -> str:
    """同时剥离 Windows 和 POSIX 风格路径，避免在页面显示本地目录。"""
    return PureWindowsPath(str(file_name)).name or "上传文件"


def _import_csv(
    file_name: str,
    content: bytes,
    delimiter_override: str | None,
) -> ImportedTable:
    """按有限编码和分隔符规则读取 CSV。"""
    text, encoding = _decode_csv(content)
    delimiter = _select_delimiter(text, delimiter_override)
    original_headers = _read_csv_header(text, delimiter)
    try:
        data = pd.read_csv(StringIO(text), sep=delimiter)
    except pd.errors.EmptyDataError as exc:
        raise FileImportError(
            "CSV文件为空，请提供第一行字段名和至少一行数据。"
        ) from exc
    except pd.errors.ParserError as exc:
        raise FileImportError(
            "CSV文件无法解析，请检查当前分隔符和每行字段数量。"
        ) from exc
    except (OSError, TypeError, ValueError) as exc:
        raise FileImportError("CSV文件读取失败，请确认内容有效且未损坏。") from exc

    return _build_result(
        file_name=file_name,
        file_type="CSV",
        content=content,
        data=data,
        original_headers=original_headers,
        encoding=encoding,
        delimiter=delimiter,
    )


def _decode_csv(content: bytes) -> tuple[str, str]:
    """按明确顺序解码 CSV，绝不忽略无效字节。"""
    candidates = (
        CSV_ENCODINGS if content.startswith(b"\xef\xbb\xbf") else CSV_ENCODINGS[1:]
    )
    for encoding in candidates:
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise FileImportError(CSV_ENCODING_ERROR)


def _select_delimiter(text: str, delimiter_override: str | None) -> str:
    """验证手动分隔符或从四种有限候选中自动识别。"""
    if delimiter_override is not None:
        if delimiter_override not in CSV_DELIMITERS:
            raise FileImportError("CSV分隔符设置无效，请使用页面提供的固定选项。")
        return delimiter_override

    sample = text[:65_536]
    try:
        detected = csv.Sniffer().sniff(sample, delimiters="".join(CSV_DELIMITERS))
        if detected.delimiter in CSV_DELIMITERS:
            return detected.delimiter
    except csv.Error:
        pass

    first_line = next((line for line in text.splitlines() if line.strip()), "")
    counts = {candidate: first_line.count(candidate) for candidate in CSV_DELIMITERS}
    best_delimiter = max(counts, key=counts.get)
    return best_delimiter if counts[best_delimiter] > 0 else ","


def _read_csv_header(text: str, delimiter: str) -> tuple[str, ...]:
    """读取原始首行字段名，以便报告 pandas 自动重命名前的问题。"""
    try:
        header = next(csv.reader(StringIO(text), delimiter=delimiter))
    except (csv.Error, StopIteration) as exc:
        raise FileImportError(
            "CSV文件没有可读取的表头，当前版本默认第一行为字段名。"
        ) from exc
    return tuple(str(value) for value in header)


def _import_xlsx(
    file_name: str,
    content: bytes,
    sheet_name: str | None,
) -> ImportedTable:
    """读取用户明确选择的 XLSX 工作表。"""
    sheet_names = get_xlsx_sheet_names(file_name, content)
    if sheet_name is None:
        if len(sheet_names) > 1:
            raise FileImportError("XLSX包含多个工作表，请先明确选择一个工作表。")
        selected_sheet = sheet_names[0]
    else:
        selected_sheet = sheet_name
        if selected_sheet not in sheet_names:
            raise FileImportError(f"XLSX中不存在工作表：{selected_sheet}。")

    try:
        raw_header = pd.read_excel(
            BytesIO(content),
            sheet_name=selected_sheet,
            header=None,
            nrows=1,
            engine="openpyxl",
        )
        data = pd.read_excel(
            BytesIO(content),
            sheet_name=selected_sheet,
            engine="openpyxl",
        )
    except ImportError as exc:
        raise FileImportError(
            "缺少Excel读取依赖openpyxl，请安装项目requirements.txt后重试。"
        ) from exc
    except Exception as exc:
        raise FileImportError(
            f"{file_name}：工作表“{selected_sheet}”无法读取，"
            "请确认XLSX文件有效且未损坏。"
        ) from exc

    if raw_header.empty:
        original_headers: tuple[str, ...] = ()
    else:
        original_headers = tuple(
            "" if pd.isna(value) else str(value) for value in raw_header.iloc[0]
        )
    return _build_result(
        file_name=file_name,
        file_type="XLSX",
        content=content,
        data=data,
        original_headers=original_headers,
        sheet_name=selected_sheet,
        sheet_count=len(sheet_names),
    )


def _build_result(
    *,
    file_name: str,
    file_type: str,
    content: bytes,
    data: pd.DataFrame,
    original_headers: tuple[str, ...],
    sheet_name: str | None = None,
    sheet_count: int | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
) -> ImportedTable:
    """执行通用资源检查并汇总不修改数据的字段提示。"""
    if data.empty:
        location = f"工作表“{sheet_name}”" if sheet_name else "CSV文件"
        raise FileImportError(f"{location}为空，请至少提供一行数据。")
    if len(data.columns) < 1:
        raise FileImportError("文件没有可读取的字段，请至少提供一列。")

    validate_row_count(data, file_name, MAX_ROWS_PER_FILE)
    if len(data.columns) > MAX_COLUMNS_PER_FILE:
        raise UploadLimitError(
            f"{file_name}：数据列数为 {len(data.columns)}，"
            f"超过允许上限 {MAX_COLUMNS_PER_FILE} 列。"
        )

    column_names = tuple(str(column) for column in data.columns)
    header_counts = Counter(original_headers)
    duplicate_names = tuple(
        name for name, count in header_counts.items() if count > 1
    )
    empty_names = tuple(name for name in original_headers if not name.strip())
    whitespace_names = tuple(
        name for name in original_headers if name and name != name.strip()
    )
    unnamed_columns = tuple(
        name for name in column_names if name.startswith("Unnamed:")
    )
    fully_empty_columns = tuple(
        str(column) for column in data.columns if data[column].isna().all()
    )
    mixed_type_columns = tuple(
        str(column) for column in data.columns if _has_mixed_types(data[column])
    )
    warnings = _build_warnings(
        duplicate_names=duplicate_names,
        empty_names=empty_names,
        whitespace_names=whitespace_names,
        unnamed_columns=unnamed_columns,
        fully_empty_columns=fully_empty_columns,
        mixed_type_columns=mixed_type_columns,
    )
    return ImportedTable(
        file_name=file_name,
        file_type=file_type,
        file_size_bytes=len(content),
        sheet_name=sheet_name,
        sheet_count=sheet_count,
        encoding=encoding,
        delimiter=delimiter,
        row_count=len(data),
        column_count=len(data.columns),
        column_names=column_names,
        original_column_names=original_headers,
        duplicate_column_names=duplicate_names,
        empty_column_names=empty_names,
        whitespace_column_names=whitespace_names,
        unnamed_columns=unnamed_columns,
        fully_empty_columns=fully_empty_columns,
        mixed_type_columns=mixed_type_columns,
        warnings=warnings,
        dataframe=data,
    )


def _has_mixed_types(series: pd.Series) -> bool:
    """保守识别同列中的数值、文本、日期等混合值，仅用于提示。"""
    value_kinds = {
        _value_kind(value) for value in series.dropna().tolist() if str(value).strip()
    }
    return len(value_kinds) > 1


def _value_kind(value: object) -> str:
    """为基础提示归类单元格值，不改变原始 DataFrame。"""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Number):
        return "number"
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return "datetime"
    if isinstance(value, str):
        numeric_value = pd.to_numeric(value, errors="coerce")
        return "number" if pd.notna(numeric_value) else "text"
    return type(value).__name__


def _build_warnings(
    *,
    duplicate_names: tuple[str, ...],
    empty_names: tuple[str, ...],
    whitespace_names: tuple[str, ...],
    unnamed_columns: tuple[str, ...],
    fully_empty_columns: tuple[str, ...],
    mixed_type_columns: tuple[str, ...],
) -> tuple[str, ...]:
    """生成中文基础字段提示，不修复或删除任何行列。"""
    warnings: list[str] = []
    if whitespace_names:
        warnings.append(
            f"字段名称首尾包含空格：{'、'.join(whitespace_names)}。"
        )
    if duplicate_names:
        warnings.append(
            "存在重复字段名称："
            f"{'、'.join(name or '（空字段名）' for name in duplicate_names)}。"
            "读取库可能为展示自动添加序号，原始数据未被删除。"
        )
    if empty_names:
        warnings.append("存在空字段名；当前版本不会自动命名或删除对应列。")
    if unnamed_columns:
        warnings.append(
            f"发现自动生成的Unnamed字段：{'、'.join(unnamed_columns)}；"
            "当前版本不会自动删除。"
        )
    if fully_empty_columns:
        warnings.append(
            f"完全为空的字段：{'、'.join(fully_empty_columns)}；"
            "当前版本只提示，不会删除。"
        )
    if mixed_type_columns:
        warnings.append(
            f"可能包含混合类型的字段：{'、'.join(mixed_type_columns)}；"
            "请在后续字段映射前核对，当前数据保持不变。"
        )
    return tuple(warnings)
