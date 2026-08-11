"""上传文件大小和数据行数的通用保护。"""

from pathlib import Path
from typing import Any

import pandas as pd

BYTES_PER_MB = 1024 * 1024


class UploadLimitError(ValueError):
    """表示用户上传内容超过当前版本的资源限制。"""


def get_source_filename(source: object, fallback: str = "上传文件.csv") -> str:
    """取得用于中文错误提示的文件名，不暴露完整本地路径。"""
    if isinstance(source, (str, Path)):
        return Path(source).name or fallback
    source_name = getattr(source, "name", None)
    return Path(str(source_name)).name if source_name else fallback


def validate_file_size(source: object, filename: str, max_mb: int) -> None:
    """在读取 CSV 前检查可确定的文件字节数。"""
    size_bytes = _get_size_bytes(source)
    if size_bytes is None:
        return
    max_bytes = max_mb * BYTES_PER_MB
    if size_bytes > max_bytes:
        actual_mb = size_bytes / BYTES_PER_MB
        raise UploadLimitError(
            f"{filename}：文件大小为 {actual_mb:.2f} MB，超过允许上限 {max_mb} MB。"
        )


def validate_row_count(
    data: pd.DataFrame,
    filename: str,
    max_rows: int,
) -> None:
    """检查 CSV 数据行数，超限时不截断或抽样。"""
    row_count = len(data)
    if row_count > max_rows:
        raise UploadLimitError(f"{filename}：数据行数为 {row_count}，超过允许上限 {max_rows} 行。")


def _get_size_bytes(source: object) -> int | None:
    """在不消费文件内容的前提下取得大小，无法确定时返回 None。"""
    if isinstance(source, (str, Path)):
        try:
            return Path(source).stat().st_size
        except OSError:
            return None

    declared_size = getattr(source, "size", None)
    if isinstance(declared_size, int):
        return declared_size

    get_value = getattr(source, "getvalue", None)
    if callable(get_value):
        value: Any = get_value()
        if isinstance(value, str):
            return len(value.encode("utf-8"))
        if isinstance(value, (bytes, bytearray, memoryview)):
            return len(value)

    tell = getattr(source, "tell", None)
    seek = getattr(source, "seek", None)
    if callable(tell) and callable(seek):
        try:
            original_position = tell()
            seek(0, 2)
            size_bytes = int(tell())
            seek(original_position)
            return size_bytes
        except OSError, TypeError, ValueError:
            return None
    return None
