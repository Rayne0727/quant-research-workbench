"""Quant Research Workbench 的 Streamlit 入口页面。"""

import streamlit as st

from src.config import APP_NAME, APP_VERSION


st.set_page_config(page_title=APP_NAME, page_icon="📈")

st.title(APP_NAME)
st.caption(f"{APP_NAME} v{APP_VERSION}")
st.subheader("量化研究实验台")
st.write(
    "上传标准日频收益或每周调仓净值 CSV，完成字段验证、基础绩效计算和图表展示。"
)
st.caption(
    "上传文件仅在当前应用进程中处理，本项目不会主动将上传数据写入data目录。  \n"
    "当前版本用于本地研究记录和结果核验，不提供实时行情、自动交易或投资建议。"
)

main_mode = st.radio(
    "选择分析模式",
    options=("单实验分析", "多实验比较"),
    horizontal=True,
    key="main_analysis_mode",
)

try:
    if main_mode == "多实验比较":
        from src.ui_comparison import render_comparison_page

        render_comparison_page()
    else:
        from src.ui_single import render_single_page

        render_single_page()
except ImportError:
    st.error(
        "页面模块未能完成加载。这通常是 Streamlit 仍保留旧版 Python 模块缓存导致的。"
    )
    st.info(
        "请回到运行 Streamlit 的终端按 Ctrl+C 停止服务，"
        "然后重新执行 `.\\scripts\\run_app.bat`。"
    )
