# Quant Research Workbench v0.3.0

v0.3.0 为单实验分析增加 Reproducible Run Manifest。完成 Direct Standard Return、Direct NAV、Generic Return 或 Generic NAV 分析后，用户可以在既有报告和标准化 CSV 之后下载运行清单 JSON。

## 用途

Run Manifest 用于：

- reproduction：确认复现使用了相同分析内容与语义；
- traceability：追踪原始来源、文件解释、字段映射和转换路径；
- verification：核验来源和规范化数据指纹以及运行环境。

## 清单内容

- `analysis_id`：规范化分析内容与计算语义的完整身份；
- `run_id`：来源和转换 provenance 的完整运行身份；
- 原始来源 SHA-256 与规范化数据 SHA-256；
- Direct/Generic、Return/NAV 对应的协议、映射与 adapter provenance；
- Python、pandas、NumPy、Streamlit 和 openpyxl 运行环境信息。

Manifest 不包含原始数据行、绝对路径、浏览器状态、widget 或 session state。文件在内存中生成，应用不会主动把它写入项目目录。

## 工程质量

Manifest core 与 integration orchestration 均进入 strict mypy gate，正式 typed boundary 为 15 个模块。自动化测试覆盖四条路径、缓存失效、身份关系、隐私边界和原有报告/标准化 CSV bytes 回归。

## 范围边界

v0.3.0 不改变绩效、NAV、benchmark、报告或标准化 CSV 口径，也不包含 B.2 Research Bundle。v0.3.0 Tag 和 GitHub Release 仅在合并后的线上验收通过后创建。
