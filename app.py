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
    "本地运行时，上传文件在当前本地应用进程中处理；部署到云端后，"
    "上传文件将在云端应用进程中处理。请勿上传敏感信息或其他受限制内容。  \n"
    "当前代码不会主动将上传数据永久写入data目录。  \n"
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
        "请完整停止旧服务，再根据当前运行环境重新执行 Streamlit 启动命令。"
    )
