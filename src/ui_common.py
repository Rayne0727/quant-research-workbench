"""公共页面结构、导航说明与稳定样式。"""

import streamlit as st

from src.config import APP_NAME, APP_VERSION


PUBLIC_PRIVACY_NOTICE = (
    "公开云端版本会在云端应用进程中处理上传文件。请勿上传账号密码、"
    "API密钥、交易凭证、个人敏感信息、商业机密或其他受限制数据。"
)
SIDEBAR_PRIVACY_NOTICE = (
    "公开云端版本会在云端应用进程中处理上传文件。"
    "请勿上传敏感或受限制数据。"
)
RESEARCH_DISCLAIMER = "本工具用于研究记录和结果核验，不构成投资建议。"


def apply_app_styles() -> None:
    """注入只依赖项目自有 class 的少量稳定样式。"""
    st.markdown(
        """
        <style>
        .qrw-kicker {
            color: #0f766e;
            font-size: 0.82rem;
            font-weight: 700;
            margin: 0 0 0.35rem 0;
            text-transform: uppercase;
        }
        .qrw-lead {
            color: #465451;
            font-size: 1.05rem;
            line-height: 1.65;
            margin: 0.25rem 0 1.5rem 0;
            max-width: 54rem;
        }
        .qrw-step {
            border-left: 3px solid #0f766e;
            padding: 0.15rem 0 0.15rem 0.8rem;
            margin: 0.45rem 0 1rem 0;
        }
        .qrw-step strong { color: #17211f; }
        .qrw-step span { color: #53625f; }
        .qrw-sidebar-brand {
            color: #17211f;
            font-size: 1rem;
            font-weight: 750;
            line-height: 1.35;
            margin-bottom: 0.15rem;
        }
        .qrw-sidebar-version {
            color: #60706c;
            font-size: 0.78rem;
            margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_context() -> None:
    """在侧边栏持续展示版本、隐私边界和用途声明。"""
    st.sidebar.markdown(
        f'<div class="qrw-sidebar-brand">{APP_NAME}</div>'
        f'<div class="qrw-sidebar-version">量化研究实验台 · v{APP_VERSION}</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.divider()
    st.sidebar.warning(SIDEBAR_PRIVACY_NOTICE)
    st.sidebar.caption(RESEARCH_DISCLAIMER)


def render_page_header(title: str, purpose: str, kicker: str) -> None:
    """渲染每页唯一主标题及一句用途说明。"""
    st.markdown(f'<p class="qrw-kicker">{kicker}</p>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="qrw-lead">{purpose}</p>', unsafe_allow_html=True)


def render_home_page() -> None:
    """渲染公共首页，不加载分析指标或图表。"""
    render_page_header(
        APP_NAME,
        "上传受支持的量化实验结果，完成字段核验、绩效分析、可视化与标准化导出。",
        f"量化研究实验台 · v{APP_VERSION}",
    )

    st.subheader("从一个清晰入口开始")
    single_column, comparison_column = st.columns(2, gap="large")
    with single_column:
        st.markdown("#### 单实验分析")
        st.write(
            "分析标准日频收益或每周调仓净值 CSV，查看核心指标、净值、"
            "回撤和确定性摘要，并导出标准化结果。"
        )
        st.button(
            "进入单实验分析",
            type="primary",
            icon=":material/analytics:",
            key="home_open_single",
            help="进入单份策略结果的上传、检查和分析流程。",
            on_click=_select_page,
            args=("单实验分析",),
        )
    with comparison_column:
        st.markdown("#### 多实验比较")
        st.write(
            "比较 2 至 6 份由本工具导出的标准化 CSV，在真实共同交易日期上"
            "重新计算并对照结果。"
        )
        st.button(
            "进入多实验比较",
            icon=":material/compare_arrows:",
            key="home_open_comparison",
            help="进入多份标准化分析结果的共同区间比较流程。",
            on_click=_select_page,
            args=("多实验比较",),
        )

    st.divider()
    st.subheader("如何使用")
    steps = (
        ("1. 上传数据", "选择明确的数据来源和受支持的 CSV 格式。"),
        ("2. 检查字段", "根据页面提示核对字段、日期、数值和样本范围。"),
        ("3. 查看分析", "阅读核心指标、净值、回撤和确定性摘要。"),
        ("4. 下载结果", "按需下载报告、标准化数据或比较结果。"),
    )
    step_columns = st.columns(4)
    for column, (title, detail) in zip(step_columns, steps, strict=True):
        column.markdown(
            f'<div class="qrw-step"><strong>{title}</strong><br>'
            f'<span>{detail}</span></div>',
            unsafe_allow_html=True,
        )

    st.subheader("当前支持的数据格式")
    st.markdown(
        "- **标准日频收益 CSV**：`date`、`strategy_return`，可选 `benchmark_return`。  \n"
        "- **每周调仓净值 CSV**：`date`、`nav_strat`，可选 `daily_ret`。  \n"
        "- **标准化分析 CSV**：由单实验分析导出，用于多实验比较。"
    )
    st.info(
        "系统不会自动猜测、重命名或映射字段。收益率使用小数格式，"
        "例如 0.01 表示 1%。"
    )

    st.subheader("隐私与使用边界")
    st.warning(PUBLIC_PRIVACY_NOTICE)
    st.write(
        "本地运行时，文件在当前电脑的应用进程中处理；公开云端版本中，"
        "文件会传输到云端应用进程。当前代码不会主动把上传文件永久写入 data 目录，"
        "但这不构成绝对安全保证。"
    )
    st.info(RESEARCH_DISCLAIMER)


def render_help_page() -> None:
    """渲染面向零基础用户的精简使用说明。"""
    render_page_header(
        "使用说明",
        "按下面的流程准备文件；系统严格按已选择的协议检查，不会猜测字段。",
        f"快速指南 · v{APP_VERSION}",
    )

    single_tab, comparison_tab, errors_tab, privacy_tab = st.tabs(
        ("单实验", "多实验", "常见错误", "数据处理")
    )
    with single_tab:
        st.subheader("完成一次单实验分析")
        st.markdown(
            "1. 选择示例数据，或选择上传 CSV。  \n"
            "2. 上传时明确选择标准日频收益或每周调仓净值格式。  \n"
            "3. 按页面字段说明检查文件，并阅读数据检查结果。  \n"
            "4. 查看指标、图表和摘要，再下载报告及标准化数据。"
        )
        st.info("收益率必须使用小数格式：0.01 表示 1%，不能用 1 表示 1%。")
    with comparison_tab:
        st.subheader("完成一次多实验比较")
        st.markdown(
            "1. 先在单实验分析中逐份处理原始文件。  \n"
            "2. 下载每个实验的标准化分析 CSV。  \n"
            "3. 在多实验比较中上传 2 至 6 份标准化 CSV。  \n"
            "4. 核对实验名称与共同区间，再查看比较结果并下载。"
        )
        st.caption(
            "标准化 CSV 统一包含 date、strategy_return、strategy_nav 和 drawdown，"
            "用于确保多份实验按相同字段协议和共同交易日期比较。"
        )
    with errors_tab:
        st.subheader("常见错误和解决方法")
        st.markdown(
            "- **缺少必需字段**：核对所选格式及字段名，不要依赖自动映射。  \n"
            "- **日期无法识别或重复**：修正日期，并确保每个日期只出现一次。  \n"
            "- **收益或净值不是数值**：检查空值、文本和无穷大。  \n"
            "- **比较文件不足**：多实验比较至少需要 2 份标准化 CSV。  \n"
            "- **更新后无法导入名称**：完整停止旧服务，再重新启动应用。"
        )
    with privacy_tab:
        st.subheader("本地与云端处理区别")
        st.write(
            "本地运行时，上传文件在当前电脑的 Streamlit 进程中处理。"
            "云端运行时，上传文件会传输到并在云端应用进程中处理；"
            "平台日志和基础设施不由本项目代码完全控制。"
        )
        st.warning(PUBLIC_PRIVACY_NOTICE)
        st.info(RESEARCH_DISCLAIMER)


def render_page_footer() -> None:
    """在主内容底部重复必要的公共使用边界。"""
    st.divider()
    st.caption(f"{APP_NAME} v{APP_VERSION} · {RESEARCH_DISCLAIMER}")


def _select_page(page_name: str) -> None:
    """从首页入口更新侧边栏导航状态。"""
    st.session_state["app_navigation"] = page_name
