"""Quant Research Workbench 的 Streamlit 入口与公共导航。"""

import streamlit as st

from src.config import APP_NAME, APP_VERSION
from src.ui_common import (
    apply_app_styles,
    render_help_page,
    render_home_page,
    render_page_footer,
    render_sidebar_context,
)


st.set_page_config(
    page_title=APP_NAME,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": (
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "用于量化研究实验结果的字段核验、绩效分析与标准化导出。\n\n"
            "本工具用于研究记录和结果核验，不构成投资建议。"
        )
    },
)
apply_app_styles()
render_sidebar_context()

selected_page = st.sidebar.radio(
    "网站导航",
    options=("首页", "单实验分析", "多实验比较", "使用说明"),
    key="app_navigation",
    help="选择首页、分析工具或使用说明。",
)

try:
    if selected_page == "单实验分析":
        from src.ui_single import render_single_page

        render_single_page()
    elif selected_page == "多实验比较":
        from src.ui_comparison import render_comparison_page

        render_comparison_page()
    elif selected_page == "使用说明":
        render_help_page()
    else:
        render_home_page()
except ImportError:
    st.error(
        "页面模块未能完成加载。这通常是 Streamlit 仍保留旧版 Python 模块缓存导致的。"
    )
    st.info(
        "请完整停止旧服务，再根据当前运行环境重新执行 Streamlit 启动命令。"
    )

render_page_footer()
