"""Quant Research Workbench 的 Streamlit 原型页面。"""

import plotly.express as px
import streamlit as st

from src.sample_data import generate_sample_data


st.set_page_config(page_title="Quant Research Workbench", page_icon="📈")

st.title("Quant Research Workbench")
st.subheader("量化研究实验台")
st.write(
    "本项目未来将支持上传策略结果 CSV、计算绩效指标和绘制分析图表。"
    "目前先使用一组固定的模拟数据验证网站能够正常运行。"
)
st.info("当前为原型版本：尚未实现 CSV 上传和真实策略分析功能。")

sample_data = generate_sample_data()
total_return = sample_data["cumulative_return"].iloc[-1]
best_daily_return = sample_data["daily_return"].max()

metric_total, metric_days, metric_best_day = st.columns(3)
metric_total.metric("模拟累计收益", f"{total_return:.2%}")
metric_days.metric("模拟交易日", f"{len(sample_data)}")
metric_best_day.metric("最佳单日收益", f"{best_daily_return:.2%}")

st.markdown("### 模拟累计收益曲线")
figure = px.line(
    sample_data,
    x="date",
    y="cumulative_return",
    labels={"date": "日期", "cumulative_return": "累计收益"},
)
figure.update_traces(line_width=3)
figure.update_yaxes(tickformat=".1%")
figure.update_layout(hovermode="x unified")
st.plotly_chart(figure, width="stretch")
