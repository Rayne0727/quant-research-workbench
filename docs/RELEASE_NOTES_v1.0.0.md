# Quant Research Workbench v1.0.0

## Overview

v1.0.0 是 Quant Research Workbench 第一阶段稳定 release。它把量化研究结果的导入、字段核验、标准化、Return/NAV 分析、多实验比较和可复现归档组织为一个公开 Streamlit 工作台。

## Highlights

- 受控 CSV/XLSX 导入和可解释字段候选；
- 用户确认式 mapping、标准化预检与严格分析门禁；
- Return/NAV 绩效、图表、报告与标准化导出；
- 多实验共同交易日期比较；
- Run Manifest 与 Research Bundle；
- reference files、自动化质量门禁和公开部署。

## Research workflows

单实验支持 Direct Standard Return、Direct Standard NAV、Generic Return 和 Generic NAV。Comparison 接受 2 至 6 份由单实验导出的标准化 CSV，在真实共同日期交集上重新归一并计算指标。系统不会静默确认字段、猜测收益率单位、排序、去重、填充或修复输入。

## Reproducibility

`analysis_id` 绑定规范化研究内容与计算语义，`run_id` 进一步绑定来源、解析、mapping 和 transformation provenance。Run Manifest 记录身份、来源指纹、数据摘要和运行环境。Research Bundle 固定归档报告、标准化 CSV、Manifest 和 exact-byte 完整性索引，默认不包含 raw upload。

## Engineering quality

v1.0 release candidate 通过 669 tests、`91.19%` branch coverage、16-module strict mypy、Ruff、formatter、`pip check`、`compileall`、GitHub Actions 和本地 release gate。

## Security and reliability

上传与 Comparison 受文件、行数、列数和 aggregate limits 约束；XLSX 在解析前检查 archive resources，并采用有界 worksheet 读取。Comparison CSV 导出中和用户控制的 spreadsheet formula 前缀。CI 使用只读权限并执行 runtime dependency audit。成功 XLSX 结果只在当前 session 内复用，失败或部分结果不会缓存。

## Deployment

公开 Demo 部署在 Streamlit Community Cloud：<https://rayne-quant-research-workbench.streamlit.app>。云端上传会把内容传输到云端应用进程；项目不保证平台 uptime、资源配额或永久可用性。

## Known boundaries

本项目用于研究记录和结果核验，不构成投资建议，也不是 production trading engine 或 institutional certification。导出的报告、标准化数据、Manifest 元数据和 Bundle 仍可能包含敏感研究信息，分享前必须核对。

## Deferred scope

v1.0 不包含用户账号、数据库、认证、云端研究存储、协作、API server、券商接入、实时行情、回测引擎、组合优化、LLM assistant、分布式计算或移动应用。后续改动仅由 bug、安全维护和真实用户反馈驱动。
