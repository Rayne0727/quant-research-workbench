"""公开参考文件页面。"""

from __future__ import annotations

from collections.abc import Mapping

import streamlit as st

from src.reference_files import (
    ManifestEntry,
    ReferenceCatalog,
    ReferenceFileEntry,
    ReferenceFileError,
    load_reference_catalog,
    load_reference_file_bytes,
    load_reference_manifest,
)
from src.ui_common import PUBLIC_PRIVACY_NOTICE, render_page_header

LIBRARY_ERROR_MESSAGE = "参考文件清单或完整性校验失败，所有下载已禁用。"
ERROR_EXAMPLES_WARNING = (
    "以下文件故意包含不明确或不安全的数据，用于演示系统的阻断行为，不应作为正常分析模板。"
)


def _mapping_text(entry: ReferenceFileEntry) -> str:
    return "；".join(
        f"{column_name} → {role}" for role, column_name in entry.recommended_mapping.items()
    )


def _render_file_details(entry: ReferenceFileEntry) -> None:
    left_column, right_column = st.columns(2, gap="large")
    with left_column:
        st.markdown(f"**文件名：** `{entry.filename}`")
        st.markdown(f"**文件类型：** {entry.file_type}")
        st.markdown(f"**用途：** {entry.description}")
        st.markdown(f"**推荐入口：** {entry.recommended_entry}")
    with right_column:
        st.markdown(f"**推荐主口径：** {entry.recommended_primary_basis}")
        st.markdown(f"**推荐字段映射：** {_mapping_text(entry)}")
        st.markdown(f"**包含基准：** {'是' if entry.contains_benchmark else '否'}")
        st.markdown(f"**预期阶段：** {entry.expected_stage}")
    st.markdown(f"**预期结果：** {entry.expected_message}")
    st.caption(entry.safety_note)


def _render_download(
    entry: ReferenceFileEntry,
    manifest: Mapping[str, ManifestEntry],
    *,
    error_example: bool,
) -> None:
    try:
        file_bytes = load_reference_file_bytes(entry, manifest)
    except ReferenceFileError:
        st.error("该参考文件完整性校验失败，下载已禁用。")
        return
    label_prefix = "下载错误示例：" if error_example else "下载"
    st.download_button(
        f"{label_prefix}{entry.title}",
        data=file_bytes,
        file_name=entry.filename,
        mime=entry.mime_type,
        key=f"reference_download_{entry.id}",
        help="下载仓库中经过大小和 SHA-256 校验的原始静态文件。",
    )
    st.caption("下载内容为仓库静态原始字节；不会自动上传、映射或启动分析。")


def _render_valid_file(
    entry: ReferenceFileEntry,
    manifest: Mapping[str, ManifestEntry],
) -> None:
    with st.expander(entry.title, expanded=False):
        _render_file_details(entry)
        _render_download(entry, manifest, error_example=False)


def _render_error_file(
    entry: ReferenceFileEntry,
    manifest: Mapping[str, ManifestEntry],
) -> None:
    st.markdown(f"#### {entry.title}")
    _render_file_details(entry)
    st.markdown(f"**系统不应执行的自动修复：** {entry.prohibited_automatic_action}")
    _render_download(entry, manifest, error_example=True)


def _load_library() -> tuple[ReferenceCatalog, Mapping[str, ManifestEntry]] | None:
    try:
        catalog = load_reference_catalog()
        manifest = load_reference_manifest(catalog)
    except ReferenceFileError:
        return None
    return catalog, manifest


def render_reference_files_page() -> None:
    """渲染只读参考文件目录和原始静态下载按钮。"""

    render_page_header(
        "参考文件",
        "这里提供用于学习、格式参考和线上功能验证的确定性合成文件。"
        "文件不包含真实证券、账户、机构或投资结果。",
        "学习与线上回归",
    )
    st.info(
        "全部文件均为确定性合成数据，仅用于学习和测试，不代表真实投资结果。"
        "下载不会自动上传、建立字段映射或执行分析。"
    )
    st.warning(PUBLIC_PRIVACY_NOTICE)

    library = _load_library()
    if library is None:
        st.error(LIBRARY_ERROR_MESSAGE)
        st.info("请联系项目维护者核对 catalog、manifest 和仓库静态文件。")
        return
    catalog, manifest = library

    st.subheader("快速选择")
    st.table(
        [
            {"使用目的": "标准 CSV 直接分析", "推荐文件": "标准收益率（含基准）"},
            {"使用目的": "无基准分析", "推荐文件": "标准收益率（无基准）"},
            {"使用目的": "中文字段通用导入", "推荐文件": "中文通用收益率示例"},
            {"使用目的": "净值主口径", "推荐文件": "中文通用净值示例"},
            {"使用目的": "英文字段识别", "推荐文件": "英文通用收益率示例"},
            {"使用目的": "多工作表测试", "推荐文件": "多工作表线上回归 XLSX"},
        ]
    )

    st.subheader("参考文件")
    st.write(
        "选择文件前先核对推荐入口、主口径和字段映射。下载完成后，请由你主动前往相应分析入口上传。"
    )
    for entry in catalog.by_group("valid"):
        _render_valid_file(entry, manifest)

    with st.expander("错误示例与预检说明", expanded=False):
        st.warning(ERROR_EXAMPLES_WARNING)
        for index, entry in enumerate(catalog.by_group("error_examples")):
            if index:
                st.divider()
            _render_error_file(entry, manifest)

    st.subheader("线上生产回归怎么使用")
    st.markdown(
        "1. 下载需要验证的参考文件。  \n"
        "2. 主动前往推荐入口上传，并按页面说明确认字段、单位和主口径。  \n"
        "3. 有效文件应按清单完成对应流程；错误示例应在标明的阶段被阻断。  \n"
        "4. 下载文件只用于验证当前公开版本，不替代对真实数据定义和单位的核对。"
    )
    st.caption(f"参考包：{catalog.pack_version} · 文件下载前均校验大小与 SHA-256。")
