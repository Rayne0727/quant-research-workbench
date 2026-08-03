"""单实验分析模式的 Streamlit 页面组织。"""

import logging
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.adapters import WeeklyNavValidationError, load_weekly_nav_csv
from src.config import MAX_COLUMNS_PER_FILE, MAX_ROWS_PER_FILE, SINGLE_FILE_MAX_MB
from src.data_loader import DataValidationError, load_returns_csv
from src.file_import import (
    CSV_DELIMITER_DISPLAY,
    CSV_DELIMITER_LABELS,
    FileImportError,
    ImportedTable,
    get_xlsx_sheet_names,
    import_table,
    read_uploaded_bytes,
)
from src.field_detection import (
    MAX_PROFILE_SAMPLE_SIZE,
    ROLE_LABELS,
    ROLE_ORDER,
    DetectionResult,
    FieldCandidate,
    detect_field_candidates,
)
from src.field_mapping import (
    PRIMARY_BASIS_NAV,
    PRIMARY_BASIS_RETURN,
    ConfirmedMapping,
    MappingImportIssues,
    build_mapping_source_key,
    build_suggested_mapping,
    confirm_mapping,
    is_confirmed_mapping_current,
    update_mapping_draft,
    validate_mapping,
)
from src.limits import UploadLimitError
from src.performance import (
    PerformanceCalculationError,
    add_nav_performance_series,
    add_performance_series,
    calculate_nav_performance_metrics,
    calculate_performance_metrics,
)
from src.reporting import (
    ReportContext,
    generate_analysis_summary,
    generate_markdown_report,
    generate_standardized_csv,
    make_report_filename,
    make_standardized_data_filename,
)
from src.templates import generate_daily_returns_template_csv
from src.ui_common import render_page_header


LOGGER = logging.getLogger(__name__)
STANDARD_RETURN_FORMAT = "标准日频收益 CSV"
WEEKLY_NAV_FORMAT = "每周调仓净值 CSV"
UNEXPECTED_ERROR_MESSAGE = (
    "应用处理过程中出现未预期错误。请检查文件格式；"
    "若问题持续存在，请重新启动应用并保留错误发生步骤。"
)
FIELD_SUGGESTION_NOTICE = (
    "字段识别结果仅为确定性规则生成的建议。"
    "系统尚未建立字段映射，也不会使用当前文件计算绩效。"
)
FIELD_SUGGESTION_BOUNDARY = (
    "当前结果仅用于帮助确认字段。系统尚未建立字段映射，"
    "不会基于这些建议计算收益、净值、回撤或其他绩效指标。"
)
MAPPING_STATE_PREFIX = "qrw_field_mapping"
MAPPING_SOURCE_KEY = f"{MAPPING_STATE_PREFIX}:source_key"
MAPPING_CONFIRMED_KEY = f"{MAPPING_STATE_PREFIX}:confirmed"
MAPPING_INVALIDATED_KEY = f"{MAPPING_STATE_PREFIX}:invalidation_pending"
PRIMARY_BASIS_LABELS = {
    "请选择": None,
    "策略收益率为主": PRIMARY_BASIS_RETURN,
    "策略净值为主": PRIMARY_BASIS_NAV,
}
PRIMARY_BASIS_VALUE_LABELS = {
    value: label for label, value in PRIMARY_BASIS_LABELS.items()
}
ROLE_MAPPING_LABELS = {
    "date": "日期",
    "strategy_return": "策略收益率",
    "strategy_nav": "策略净值",
    "benchmark_return": "基准收益率",
    "benchmark_nav": "基准净值",
    "drawdown": "回撤序列",
    "daily_ret": "辅助日收益 daily_ret",
}
UNMAPPED_OPTION = "不映射"


def render_single_page() -> None:
    """渲染单实验页面，并统一处理预期及未预期异常。"""
    try:
        _render_single_page()
    except (
        DataValidationError,
        WeeklyNavValidationError,
        FileImportError,
        UploadLimitError,
    ) as exc:
        st.error(str(exc))
    except PerformanceCalculationError as exc:
        st.error(f"绩效计算失败：{exc}")
    except Exception as exc:
        LOGGER.exception("单实验页面发生未预期错误：%s", type(exc).__name__)
        st.error(UNEXPECTED_ERROR_MESSAGE)


def _render_single_page() -> None:
    """组织单实验输入、指标、图表、摘要和导出。"""
    render_page_header(
        "单实验分析",
        "上传一份受支持的策略结果，完成字段检查、绩效分析、图表展示与标准化导出。",
        "分析工作台",
    )

    st.markdown("### 1. 选择数据来源")
    st.caption(
        f"上传限制：单文件最大 {SINGLE_FILE_MAX_MB} MB，"
        f"每份表格最多 {MAX_ROWS_PER_FILE} 行、"
        f"{MAX_COLUMNS_PER_FILE} 列。"
    )
    data_mode = st.radio(
        "选择数据来源",
        options=(
            "使用示例数据",
            "按现有标准协议上传",
            "通用文件导入（CSV/XLSX）",
        ),
        horizontal=True,
        key="single_data_mode",
        help=(
            "标准协议路径会直接分析已符合协议的 CSV；"
            "通用导入只读取 CSV/XLSX 并预览，不计算绩效。"
        ),
    )

    if data_mode == "通用文件导入（CSV/XLSX）":
        _render_general_file_import()
        return

    st.markdown("### 2. 选择数据格式")
    selected_format = STANDARD_RETURN_FORMAT
    uploaded_file = None
    if data_mode == "按现有标准协议上传":
        selected_format = st.radio(
            "选择数据格式",
            options=(STANDARD_RETURN_FORMAT, WEEKLY_NAV_FORMAT),
            horizontal=True,
            key="single_data_format",
            help="请按文件真实字段选择；系统不会自动识别或切换格式。",
        )
        current_mode = "用户上传数据模式"
    else:
        st.write("固定示例采用 **标准日频收益 CSV** 格式。")
        current_mode = "示例数据模式"

    primary_field = (
        "nav_strat" if selected_format == WEEKLY_NAV_FORMAT else "strategy_return"
    )
    st.info(
        f"当前数据模式：{current_mode}  ·  当前格式：{selected_format}  ·  "
        f"计算主字段：{primary_field}"
    )
    if selected_format == WEEKLY_NAV_FORMAT:
        st.caption("当前绩效以 nav_strat 推导结果为准。")

    st.markdown("### 3. 上传与字段说明")
    if data_mode == "按现有标准协议上传":
        uploaded_file = st.file_uploader(
            "上传 1 份 CSV 文件",
            type=("csv",),
            key="single_uploaded_file",
            help=(
                f"仅接受 CSV；文件最大 {SINGLE_FILE_MAX_MB} MB、"
                f"最多 {MAX_ROWS_PER_FILE} 行。"
            ),
            max_upload_size=SINGLE_FILE_MAX_MB,
        )
    if selected_format == STANDARD_RETURN_FORMAT:
        st.markdown(
            "必需字段：`date`、`strategy_return`；可选字段：`benchmark_return`。  "
            "收益率必须使用小数格式，例如 `0.01` 代表 `1%`，"
            "不能用 `1` 代表 `1%`。"
        )
    else:
        st.markdown(
            "必需字段：`date`、`nav_strat`；可选字段：`daily_ret`。  "
            "绩效以 `nav_strat` 标准化净值及其 `pct_change()` 推导收益为准；"
            "`daily_ret` 仅用于一致性诊断。"
        )
    st.caption(
        "标准日频模板中的 benchmark_return 可删除；0.01 代表 1%。"
        "模板数据仅用于格式演示，不代表真实策略结果。"
    )
    st.download_button(
        "下载标准日频收益 CSV 模板",
        data=generate_daily_returns_template_csv(),
        file_name="daily_returns_template.csv",
        mime="text/csv; charset=utf-8",
        key="daily_returns_template_download",
        help="下载只演示字段名称和收益率小数格式的示例模板。",
        icon=":material/download:",
        type="secondary",
    )

    if data_mode == "按现有标准协议上传" and uploaded_file is None:
        st.info("请上传一份符合字段协议的 CSV 文件后开始分析。")
        return

    data_source = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "example_daily_returns.csv"
        if data_mode == "使用示例数据"
        else uploaded_file
    )

    diagnostics = None
    if selected_format == WEEKLY_NAV_FORMAT:
        adapter_result = load_weekly_nav_csv(data_source)
        cleaned_data = adapter_result.data
        diagnostics = adapter_result.diagnostics
        performance_data = add_nav_performance_series(cleaned_data)
        metrics = calculate_nav_performance_metrics(cleaned_data)
    else:
        cleaned_data = load_returns_csv(data_source)
        performance_data = add_performance_series(cleaned_data)
        metrics = calculate_performance_metrics(cleaned_data)

    st.markdown("### 4. 数据检查结果")
    st.success("字段、日期、数值和样本数量检查通过，可以继续分析。")
    check_columns = st.columns(3)
    check_columns[0].metric("数据记录数", str(len(cleaned_data)))
    check_columns[1].write(f"**数据模式**  \n{current_mode}")
    check_columns[2].write(f"**计算主字段**  \n`{primary_field}`")

    if diagnostics is not None:
        _render_diagnostics(diagnostics)

    default_experiment_name = (
        "示例日频收益实验"
        if data_mode == "使用示例数据"
        else Path(uploaded_file.name).stem
    )
    input_identity = (
        "sample"
        if data_mode == "使用示例数据"
        else f"{selected_format}:{uploaded_file.name}"
    )
    with st.expander("实验信息（可选）", expanded=False):
        experiment_name = st.text_input(
            "实验名称",
            value=default_experiment_name,
            max_chars=100,
            key=f"experiment_name:{input_identity}",
        )
        strategy_name = st.text_input(
            "策略名称",
            value="",
            max_chars=100,
            key=f"strategy_name:{input_identity}",
        )
        research_notes = st.text_area(
            "研究备注",
            value="",
            max_chars=1000,
            key=f"research_notes:{input_identity}",
        )

    st.markdown("### 5. 核心指标")
    metric_row_one = st.columns(4)
    metric_row_one[0].metric(
        "累计收益", _format_percentage(metrics["cumulative_return"])
    )
    metric_row_one[1].metric(
        "年化收益", _format_percentage(metrics["annualized_return"])
    )
    metric_row_one[2].metric(
        "年化波动率", _format_percentage(metrics["annualized_volatility"])
    )
    metric_row_one[3].metric("夏普比率", _format_number(metrics["sharpe_ratio"]))

    is_nav_format = selected_format == WEEKLY_NAV_FORMAT
    has_benchmark = "benchmark_cumulative_return" in metrics
    metric_row_two = st.columns(4 if has_benchmark or is_nav_format else 3)
    metric_row_two[0].metric(
        "最大回撤", _format_percentage(metrics["max_drawdown"])
    )
    metric_row_two[1].metric(
        "盈利日占比", _format_percentage(metrics["positive_day_ratio"])
    )
    if is_nav_format:
        metric_row_two[2].metric("净值观察日数", str(metrics["nav_observations"]))
        metric_row_two[3].metric("有效收益日数", str(metrics["n_days"]))
    else:
        metric_row_two[2].metric("有效交易日数", str(metrics["n_days"]))
    if has_benchmark and not is_nav_format:
        metric_row_two[3].metric(
            "基准累计收益",
            _format_percentage(metrics["benchmark_cumulative_return"]),
        )

    st.markdown("**数据起止日期**")
    date_columns = st.columns(2)
    date_columns[0].write(f"开始日期：{_format_date(metrics['start_date'])}")
    date_columns[1].write(f"结束日期：{_format_date(metrics['end_date'])}")

    if int(metrics["n_days"]) < 60:
        st.warning(
            "当前样本交易日较少，年化收益、年化波动率和夏普比率"
            "对短期表现较敏感，仅供参考。"
        )

    st.markdown("### 6. 图表")
    nav_figure = go.Figure()
    nav_figure.add_trace(
        go.Scatter(
            x=performance_data["date"],
            y=performance_data["strategy_nav"],
            mode="lines",
            name="策略标准化净值" if is_nav_format else "策略净值",
        )
    )
    if "benchmark_nav" in performance_data.columns:
        nav_figure.add_trace(
            go.Scatter(
                x=performance_data["date"],
                y=performance_data["benchmark_nav"],
                mode="lines",
                name="基准净值",
            )
        )
    nav_figure.update_layout(
        title="累计净值曲线",
        xaxis_title="日期",
        yaxis_title="累计净值",
        hovermode="x unified",
    )
    st.plotly_chart(nav_figure, width="stretch")

    drawdown_figure = go.Figure()
    drawdown_figure.add_trace(
        go.Scatter(
            x=performance_data["date"],
            y=performance_data["drawdown"],
            mode="lines",
            name="策略回撤",
            fill="tozeroy",
        )
    )
    drawdown_figure.update_layout(
        title="回撤曲线",
        xaxis_title="日期",
        yaxis_title="回撤",
        hovermode="x unified",
    )
    drawdown_figure.update_yaxes(tickformat=".1%")
    st.plotly_chart(drawdown_figure, width="stretch")

    report_context = ReportContext(
        experiment_name=experiment_name.strip() or "未命名实验",
        strategy_name=strategy_name.strip(),
        research_notes=research_notes.strip(),
        data_format=selected_format,
        primary_field=primary_field,
        start_date=pd.Timestamp(metrics["start_date"]),
        end_date=pd.Timestamp(metrics["end_date"]),
        observation_count=(
            int(metrics["nav_observations"]) if is_nav_format else len(cleaned_data)
        ),
        valid_return_count=int(metrics["n_days"]),
        metrics=metrics,
        has_benchmark=has_benchmark,
        diagnostics=diagnostics,
    )
    analysis_summary = generate_analysis_summary(report_context)
    markdown_report = generate_markdown_report(report_context)
    standardized_csv = generate_standardized_csv(performance_data)

    st.markdown("### 7. 分析摘要")
    st.markdown(analysis_summary)

    st.markdown("### 8. 结果导出")
    st.caption("下载内容在内存中生成，不会由应用主动写入 data 目录。")
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "下载分析报告",
        data=markdown_report.encode("utf-8"),
        file_name=make_report_filename(experiment_name),
        mime="text/markdown; charset=utf-8",
        help="下载包含实验信息、指标、诊断与固定声明的 Markdown 报告。",
        icon=":material/download:",
        type="primary",
    )
    download_columns[1].download_button(
        "下载标准化分析数据",
        data=standardized_csv,
        file_name=make_standardized_data_filename(experiment_name),
        mime="text/csv; charset=utf-8",
        help="下载可用于多实验比较的标准化分析 CSV。",
        icon=":material/download:",
    )

    st.markdown("### 9. 数据预览")
    with st.expander("查看清洗后的数据（前 20 行）"):
        st.caption(f"字段：{', '.join(cleaned_data.columns)}")
        st.caption(f"记录数量：{len(cleaned_data)}")
        st.dataframe(cleaned_data.head(20), width="stretch")


def _render_general_file_import() -> None:
    """读取通用 CSV/XLSX 并展示原始预览，不进入业务分析。"""
    st.info(
        "此入口只负责文件读取、字段建议和用户确认式字段映射。"
        "映射确认后仍不会进入现有绩效分析流程。"
    )

    st.markdown("### 2. 上传文件")
    uploaded_file = st.file_uploader(
        "上传 1 份 CSV 或 XLSX 文件",
        type=("csv", "xlsx"),
        key="general_import_file",
        help=(
            f"仅接受 .csv 和 .xlsx；文件最大 {SINGLE_FILE_MAX_MB} MB。"
            "暂不支持 .xls、.xlsm、.ods、ZIP、Parquet 或 JSON。"
        ),
        max_upload_size=SINGLE_FILE_MAX_MB,
    )
    if uploaded_file is None:
        _clear_mapping_session_state()
        st.caption(
            "请选择 CSV 或 XLSX 文件。上传后将先确认解析设置，"
            "再显示字段和前 20 行原始预览。"
        )
        st.warning(
            "文件尚未读取。当前尚未进行字段映射确认或绩效计算。"
        )
        return

    file_name, content = read_uploaded_bytes(uploaded_file)
    extension = Path(file_name).suffix.lower()

    st.markdown("### 3. 文件解析设置")
    if extension == ".csv":
        delimiter_label = st.selectbox(
            "CSV 分隔符",
            options=tuple(CSV_DELIMITER_LABELS),
            key="general_csv_delimiter",
            help=(
                "自动识别仅会在逗号、制表符、分号和竖线中选择；"
                "如果结果不符，请手动指定。"
            ),
        )
        result = import_table(
            file_name,
            content,
            delimiter=CSV_DELIMITER_LABELS[delimiter_label],
        )
        st.write(f"**当前编码：** `{result.encoding}`")
        st.write(
            "**当前分隔符：** "
            f"{CSV_DELIMITER_DISPLAY.get(result.delimiter or '', result.delimiter)}"
        )
    else:
        sheet_names = get_xlsx_sheet_names(file_name, content)
        if len(sheet_names) == 1:
            selected_sheet = sheet_names[0]
            st.write(f"**当前工作表：** {selected_sheet}（唯一工作表，已自动选择）")
        else:
            selected_sheet = st.selectbox(
                "选择 Excel 工作表",
                options=sheet_names,
                index=None,
                placeholder="请选择一个工作表",
                key="general_xlsx_sheet",
                help="必须明确选择一个工作表；系统不会合并或猜测工作表。",
            )
            if selected_sheet is None:
                st.info("该 XLSX 包含多个工作表，请明确选择后再读取预览。")
                return
        result = import_table(file_name, content, sheet_name=selected_sheet)

    _render_import_result(result, content)


def _render_import_result(result: ImportedTable, content: bytes) -> None:
    """展示通用读取结果，不修改或删除任何数据。"""
    st.markdown("### 4. 文件基础信息")
    info_columns = st.columns(2)
    info_columns[0].write(f"**文件名：** {result.file_name}")
    info_columns[0].write(f"**文件类型：** {result.file_type}")
    info_columns[0].write(
        f"**文件大小：** {result.file_size_bytes / 1024:.2f} KB"
    )
    info_columns[1].write(f"**数据行数：** {result.row_count}")
    info_columns[1].write(f"**数据列数：** {result.column_count}")
    if result.file_type == "XLSX":
        info_columns[0].write(f"**当前工作表：** {result.sheet_name}")
        info_columns[1].write(f"**工作表数量：** {result.sheet_count}")

    st.markdown("### 5. 字段检查")
    st.caption("当前版本默认第一行为字段名；表头行选择将在后续版本完善。")
    original_headers = (
        f"{index}. {name if name else '（空字段名）'}"
        for index, name in enumerate(result.original_column_names, start=1)
    )
    st.write("**原始首行字段名称：**")
    st.code("\n".join(original_headers), language=None)
    st.write("**读取库展示的字段名称：**")
    st.code("\n".join(result.column_names), language=None)
    st.write(f"**重复字段名数量：** {len(result.duplicate_column_names)}")
    st.write(f"**完全为空的字段数量：** {len(result.fully_empty_columns)}")
    if result.warnings:
        for warning in result.warnings:
            st.warning(warning)
    else:
        st.success("未发现重复、空字段名、全空列或混合类型等基础问题。")

    st.markdown("### 6. 原始数据预览")
    st.caption("仅显示前 20 行；读取结果中保留完整数据，未截断、抽样或删列。")
    st.dataframe(result.dataframe.head(20), width="stretch")
    st.success("文件已成功读取；请继续核对字段建议并确认字段映射。")

    detection = detect_field_candidates(result.dataframe)
    _render_field_detection(detection)

    source_key = build_mapping_source_key(
        content=content,
        file_type=result.file_type,
        sheet_name=result.sheet_name,
        encoding=result.encoding,
        delimiter=result.delimiter,
        header_rule="first_row",
        columns=result.column_names,
    )
    _render_field_mapping(result, detection, source_key)

    st.markdown("### 9. 下一阶段说明")
    st.info(
        "尚未执行数据标准化、收益率单位转换、绩效计算、"
        "图表生成或结果导出。"
    )
    st.caption("B.4 才会按照已确认映射执行标准化和严格数据验证。")


def _candidate_rows(
    detection: DetectionResult,
) -> list[dict[str, object]]:
    """整理每个角色最多三个候选，供折叠区展示。"""
    rows: list[dict[str, object]] = []
    for role in ROLE_ORDER:
        suggestion = detection.suggestions[role]
        candidates: list[FieldCandidate] = []
        if suggestion.recommended is not None:
            candidates.append(suggestion.recommended)
        candidates.extend(suggestion.alternatives)
        for rank, candidate in enumerate(candidates[:3], start=1):
            rows.append(
                {
                    "业务角色": f"{role}（{ROLE_LABELS[role]}）",
                    "排名": rank,
                    "字段": candidate.column_name,
                    "置信度": candidate.confidence,
                    "评分": candidate.score,
                    "判断理由": "；".join(candidate.reasons) or "无明确支持理由",
                    "风险提示": "；".join(candidate.warnings) or "—",
                }
            )
    return rows


def _profile_rows(detection: DetectionResult) -> list[dict[str, object]]:
    """将字段画像转换为只读表格行。"""
    rows: list[dict[str, object]] = []
    for profile in detection.column_profiles.values():
        rows.append(
            {
                "原始字段": profile.column_name,
                "归一化名称": profile.normalized_name,
                "数据类型": profile.dtype,
                "非空数": profile.non_null_count,
                "非空比例": f"{profile.non_null_ratio:.1%}",
                "样本唯一值数": profile.unique_count,
                "数值比例": f"{profile.numeric_ratio:.1%}",
                "日期解析比例": f"{profile.date_parse_ratio:.1%}",
                "有限数值": "是" if profile.all_finite_numeric else "否",
                "最小值": profile.numeric_min,
                "最大值": profile.numeric_max,
                "单调递增": "是" if profile.monotonic_increasing else "否",
                "单调递减": "是" if profile.monotonic_decreasing else "否",
                "混合类型": "是" if profile.mixed_types else "否",
                "画像样本数": profile.analyzed_count,
            }
        )
    return rows


def _render_field_detection(detection: DetectionResult) -> None:
    """在原始预览下展示建议，但不建立映射或触发计算。"""
    st.markdown("### 7. 字段识别建议")
    st.warning(FIELD_SUGGESTION_NOTICE)

    summary_rows: list[dict[str, object]] = []
    for role in ROLE_ORDER:
        suggestion = detection.suggestions[role]
        candidate = suggestion.recommended
        summary_rows.append(
            {
                "业务角色": f"{role}（{ROLE_LABELS[role]}）",
                "推荐字段": candidate.column_name if candidate else "未识别",
                "置信度": candidate.confidence if candidate else "未识别",
                "评分": str(candidate.score) if candidate else "未识别",
                "主要理由": (
                    "；".join(candidate.reasons[:2])
                    if candidate and candidate.reasons
                    else "没有达到最低建议阈值"
                ),
                "风险提示": (
                    "；".join(candidate.warnings)
                    if candidate and candidate.warnings
                    else "—"
                ),
            }
        )
    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")

    for warning in detection.global_warnings:
        st.warning(warning)

    with st.expander("查看备选字段和字段画像", expanded=False):
        st.caption(
            f"每个字段画像最多分析 {MAX_PROFILE_SAMPLE_SIZE:,} 个非空观察值；"
            "抽样位置固定，不使用随机数。"
        )
        st.write("**每个角色最多三个候选**")
        candidate_rows = _candidate_rows(detection)
        if candidate_rows:
            st.dataframe(
                pd.DataFrame(candidate_rows),
                hide_index=True,
                width="stretch",
            )
        else:
            st.write("没有字段达到候选展示阈值。")
        st.write("**字段画像**")
        st.dataframe(
            pd.DataFrame(_profile_rows(detection)),
            hide_index=True,
            width="stretch",
        )


def _mapping_source_state_prefix(source_key: str) -> str:
    return f"{MAPPING_STATE_PREFIX}:source:{source_key}"


def _mapping_widget_key(role: str, source_key: str) -> str:
    return f"{_mapping_source_state_prefix(source_key)}:role:{role}"


def _mapping_basis_widget_key(source_key: str) -> str:
    return f"{_mapping_source_state_prefix(source_key)}:primary_basis"


def _mapping_acknowledgement_widget_key(source_key: str) -> str:
    return f"{_mapping_source_state_prefix(source_key)}:acknowledgement"


def _clear_mapping_session_state() -> None:
    """清除当前会话中的映射选择和确认，不影响上传数据。"""
    had_confirmed_mapping = isinstance(
        st.session_state.get(MAPPING_CONFIRMED_KEY),
        ConfirmedMapping,
    )
    for key in tuple(st.session_state):
        if key.startswith(MAPPING_STATE_PREFIX) and key != MAPPING_INVALIDATED_KEY:
            st.session_state.pop(key, None)
    if had_confirmed_mapping:
        st.session_state[MAPPING_INVALIDATED_KEY] = True


def _prepare_mapping_session_state(source_key: str) -> bool:
    """来源变化时使旧确认失效，并返回是否需要显示失效提示。"""
    previous_source_key = st.session_state.get(MAPPING_SOURCE_KEY)
    confirmed = st.session_state.get(MAPPING_CONFIRMED_KEY)
    source_changed = (
        previous_source_key is not None
        and previous_source_key != source_key
    )
    invalidation_pending = bool(
        st.session_state.pop(MAPPING_INVALIDATED_KEY, False)
    )
    invalidated = bool(
        invalidation_pending or (source_changed and confirmed is not None)
    )
    if previous_source_key != source_key:
        previous_prefix = (
            _mapping_source_state_prefix(previous_source_key)
            if isinstance(previous_source_key, str)
            else None
        )
        for key in tuple(st.session_state):
            if key == MAPPING_CONFIRMED_KEY or (
                previous_prefix is not None and key.startswith(previous_prefix)
            ):
                st.session_state.pop(key, None)
        st.session_state[MAPPING_SOURCE_KEY] = source_key
    return invalidated


def _role_requirement(role: str, primary_basis: str | None) -> str:
    if role == "date":
        return "必需"
    if role == primary_basis:
        return "主口径必需"
    if role in {"drawdown", "daily_ret"}:
        return "可选 · 诊断用途"
    if role in {"strategy_return", "strategy_nav"}:
        return "可选 · 一致性检查候选"
    return "可选"


def _role_purpose(role: str, primary_basis: str) -> str:
    if role == "date":
        return "后续严格验证的日期字段"
    if role == primary_basis:
        return "用户选定的策略分析主口径"
    if role in {"strategy_return", "strategy_nav", "daily_ret"}:
        return "辅助字段，仅供后续一致性检查"
    if role == "drawdown":
        return "诊断用途，不覆盖主口径"
    return "可选基准字段，等待后续严格验证"


def _candidate_score(
    detection: DetectionResult,
    role: str,
    column_name: str | None,
) -> int | None:
    if column_name is None:
        return None
    suggestion = detection.suggestions[role]
    candidates: list[FieldCandidate] = []
    if suggestion.recommended is not None:
        candidates.append(suggestion.recommended)
    candidates.extend(suggestion.alternatives)
    for candidate in candidates:
        if candidate.column_name == column_name:
            return candidate.score
    return None


def _render_confirmed_mapping_summary(
    confirmed: ConfirmedMapping,
    detection: DetectionResult,
) -> None:
    """展示会话内确认结果，不生成标准化数据或分析结果。"""
    st.markdown("### 8.1 已确认映射摘要")
    st.success("字段映射已确认。")
    summary_rows: list[dict[str, object]] = []
    for role in ROLE_ORDER:
        column_name = confirmed.role_to_column.get(role)
        recommended = detection.suggestions[role].recommended_field
        score = _candidate_score(detection, role, column_name)
        summary_rows.append(
            {
                "业务角色": f"{role}（{ROLE_MAPPING_LABELS[role]}）",
                "原始字段": column_name or "不映射",
                "是否为主口径字段": "是" if role == confirmed.primary_basis else "否",
                "B.2建议分数": str(score) if score is not None else "无候选分数",
                "与系统首选建议是否一致": (
                    "是"
                    if column_name is not None and column_name == recommended
                    else "否" if column_name is not None else "不适用"
                ),
                "当前用途": _role_purpose(role, confirmed.primary_basis),
            }
        )
    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")
    if confirmed.warnings:
        st.write("**确认时保留的风险提示：**")
        for warning in confirmed.warnings:
            st.warning(warning)
    st.info(
        "字段映射已确认，但当前尚未执行数据标准化或绩效计算。"
        "下一阶段将按照确认的映射进行严格验证。"
    )
    st.caption(
        "尚未执行数据标准化、收益率单位转换、绩效计算、"
        "图表生成或结果导出。"
    )


def _render_field_mapping(
    result: ImportedTable,
    detection: DetectionResult,
    source_key: str,
) -> None:
    """收集并显式确认字段引用，确认后仍不进入业务分析。"""
    st.markdown("### 8. 确认字段映射")
    st.warning(
        "高置信度建议仍需用户核对。系统不会自动判断收益率单位，"
        "也不会修改原始数据。"
    )
    if _prepare_mapping_session_state(source_key):
        st.warning("文件或解析设置已变化，请重新确认字段映射。")

    suggested = build_suggested_mapping(
        result.column_names,
        detection,
        source_key=source_key,
    )
    import_issues = MappingImportIssues(
        duplicate_column_names=result.duplicate_column_names,
        empty_column_names=result.empty_column_names,
        whitespace_column_names=result.whitespace_column_names,
        unnamed_columns=result.unnamed_columns,
    )
    basis_default_label = PRIMARY_BASIS_VALUE_LABELS[suggested.primary_basis]

    with st.form(f"{_mapping_source_state_prefix(source_key)}:form"):
        basis_label = st.selectbox(
            "策略分析主口径",
            options=tuple(PRIMARY_BASIS_LABELS),
            index=tuple(PRIMARY_BASIS_LABELS).index(basis_default_label),
            key=_mapping_basis_widget_key(source_key),
            help=(
                "即使策略收益率和策略净值同时存在，也必须由用户明确选择。"
                "系统不会静默决定最终主口径。"
            ),
        )
        primary_basis = PRIMARY_BASIS_LABELS[basis_label]
        st.caption(
            "收益率主口径必须映射 date 和 strategy_return；"
            "净值主口径必须映射 date 和 strategy_nav。"
        )

        role_to_column: dict[str, str | None] = {}
        options = (UNMAPPED_OPTION, *result.column_names)
        for role in ROLE_ORDER:
            suggestion = detection.suggestions[role]
            recommended = suggestion.recommended
            prefilled = suggested.role_to_column.get(role)
            index = options.index(prefilled) if prefilled in options else 0
            selected_option = st.selectbox(
                f"{role} · {ROLE_MAPPING_LABELS[role]}",
                options=options,
                index=index,
                key=_mapping_widget_key(role, source_key),
                help="请选择原始字段名称；同一个原始字段不能承担多个角色。",
            )
            role_to_column[role] = (
                None if selected_option == UNMAPPED_OPTION else selected_option
            )
            if recommended is None:
                recommendation_text = "B.2 首选建议：未识别"
            else:
                recommendation_text = (
                    f"B.2 首选建议：{recommended.column_name} · "
                    f"{recommended.confidence} · {recommended.score} 分"
                )
            st.caption(
                f"{_role_requirement(role, primary_basis)} · {recommendation_text}"
            )

        acknowledgement = st.checkbox(
            "我已核对字段含义，并理解系统不会自动判断收益率单位、"
            "不会自动修改原始数据，当前确认也不会立即计算绩效。",
            key=_mapping_acknowledgement_widget_key(source_key),
        )
        draft = update_mapping_draft(
            suggested,
            primary_basis=primary_basis,
            role_to_column=role_to_column,
            confirmation_acknowledged=acknowledgement,
        )
        validation = validate_mapping(
            result.dataframe,
            draft,
            detection.column_profiles,
            import_issues,
        )
        st.write("**当前验证错误：**")
        if validation.errors:
            for error in validation.errors:
                st.error(error)
        else:
            st.success("当前选择没有阻断性错误。")
        st.write("**当前风险提示：**")
        if validation.warnings:
            for warning in validation.warnings:
                st.warning(warning)
        else:
            st.caption("当前没有额外风险提示；确认仍不等于数据协议验证通过。")
        submitted = st.form_submit_button(
            "确认字段映射",
            type="primary",
            help="仅保存当前会话中的字段引用，不会启动分析。",
        )

    if submitted:
        if validation.is_valid:
            st.session_state[MAPPING_CONFIRMED_KEY] = confirm_mapping(
                draft,
                validation,
            )
        else:
            st.error("字段映射存在阻断性错误，尚未建立确认状态。")

    confirmed = st.session_state.get(MAPPING_CONFIRMED_KEY)
    if isinstance(confirmed, ConfirmedMapping) and is_confirmed_mapping_current(
        confirmed,
        source_key,
    ):
        _render_confirmed_mapping_summary(confirmed, detection)
    else:
        st.info(FIELD_SUGGESTION_BOUNDARY)


def _render_diagnostics(diagnostics: object) -> None:
    """展示 daily_ret 一致性诊断，不默认展开具体记录。"""
    mismatch_ratio = (
        diagnostics.mismatch_count / diagnostics.comparison_count
        if diagnostics.comparison_count > 0
        else 0.0
    )
    st.markdown("#### daily_ret 一致性诊断")
    diagnostic_columns = st.columns(3)
    diagnostic_columns[0].metric("有效比较数量", str(diagnostics.comparison_count))
    diagnostic_columns[1].metric("不一致日期数量", str(diagnostics.mismatch_count))
    diagnostic_columns[2].metric("不一致比例", f"{mismatch_ratio:.2%}")
    difference_columns = st.columns(2)
    difference_columns[0].write(
        "**最大绝对差异（BP）**  \n"
        f"{_format_basis_points(diagnostics.max_absolute_difference)}"
    )
    difference_columns[1].write(
        "**平均绝对差异（BP）**  \n"
        f"{_format_basis_points(diagnostics.mean_absolute_difference)}"
    )
    if diagnostics.mismatch_count > 0:
        st.warning(
            "文件中的 daily_ret 与 nav_strat 推导收益存在不一致。"
            "当前绩效指标以 nav_strat 为准，daily_ret 仅用于一致性检查。"
        )
        with st.expander("查看前 10 条不一致记录"):
            mismatch_preview = diagnostics.mismatches.head(10).copy()
            mismatch_preview["difference_bps"] = (
                mismatch_preview["difference"] * 10000
            )
            st.dataframe(mismatch_preview, width="stretch")
    else:
        st.success("daily_ret 与 nav_strat 推导收益在容差 1e-8 内一致。")


def _format_percentage(value: object) -> str:
    """将有效数值显示为保留两位小数的百分比。"""
    if value is None or not pd.notna(value):
        return "不可用"
    return f"{float(value):.2%}"


def _format_number(value: object) -> str:
    """将有效数值显示为保留两位小数的普通数字。"""
    if value is None or not pd.notna(value):
        return "不可用"
    return f"{float(value):.2f}"


def _format_date(value: object) -> str:
    """将日期指标显示为 YYYY-MM-DD。"""
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _format_basis_points(value: float | None) -> str:
    """将原始小数差异转换为保留两位小数的基点。"""
    return "不可用" if value is None else f"{value * 10000:.2f} BP"
