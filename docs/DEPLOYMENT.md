# GitHub 与 Streamlit 云部署准备

本文档说明 `v0.2.0` 的本地启动、GitHub 集成、Streamlit Community Cloud 更新流程和部署验收边界。GitHub 远程仓库已经存在，`master` 是当前部署基线；Streamlit Community Cloud 已部署该应用，合并到 `master` 后由现有云端部署流程检测并更新。

## 1. GitHub 与部署基线

Streamlit Community Cloud 从 GitHub 仓库读取应用代码、入口文件和依赖清单。当前仓库为 `Rayne0727/quant-research-workbench`，部署分支为 `master`。功能变更必须先通过 Pull Request、CI 和本地发布门禁，再合并到 `master`；云端部署流程随后检测更新。

研究数据可能包含敏感信息。建议先使用私人 GitHub 仓库，并在平台能力允许时将测试应用设置为私人访问。公开仓库和公开应用会扩大代码、示例及页面的可见范围。

## 2. 当前部署参数

- 仓库：`Rayne0727/quant-research-workbench`；
- 分支：`master`；
- 入口文件：`app.py`；
- 本地 Python：`3.14.2`；
- CI Python：`3.14`；
- 运行依赖：根目录 `requirements.txt`；
- Secrets：当前业务不需要。

云端环境应优先选择与本地一致的 Python `3.14`。如果目标平台尚不支持该版本，应先在受支持版本上完整运行 pytest 和页面回归，再决定是否部署，不能静默改变版本假设。

## 3. Streamlit Community Cloud 基本流程

现有应用更新时，不需要重复创建 Streamlit 应用或修改 Sharing 设置。先完成本地验证、PR 和 CI，再把通过门禁的变更合并到 `master`，并在平台完成线上人工验收。

以下步骤仅供首次部署时人工使用：

1. 在 GitHub 创建或选择经过安全检查的仓库。
2. 确认准备部署的 `master` 已通过 CI 和发布门禁。
3. 登录 Streamlit Community Cloud，并授权它读取所选仓库。
4. 新建应用，选择仓库和 `master` 分支。
5. 将入口文件设置为 `app.py`。
6. 在可选的高级设置中选择与本地一致的 Python 版本。
7. 保持 Secrets 为空；当前项目不需要账号、API Key 或数据库凭证。
8. 开始构建，并在平台界面查看依赖安装和应用启动日志。

`requirements.txt` 只列出应用运行所需的直接依赖。云端构建会根据它安装 Streamlit、pandas、Plotly 和用于 XLSX 读取的 openpyxl；`requirements-dev.txt` 用于本地及 CI 测试，不是应用启动前提。

## 4. 凭证与日志

不要把 API Key、密码、交易凭证或其他秘密写入 Git、源码、CSV、文档或示例文件。当前项目不需要任何 Secret；未来若业务范围改变，应使用部署平台的 Secrets 管理能力，而不是硬编码。

构建失败时，在云端应用管理页面查看构建日志。日志可能包含依赖解析、Python 版本和异常堆栈，但代码不应主动打印上传的 DataFrame 内容。云端平台自身的日志和基础设施行为不由本项目代码完全控制。

## 5. 云端验收清单

- 页面显示 `Quant Research Workbench v0.2.0`；
- 首页、单实验分析、多实验比较、参考文件和使用说明版本一致；
- 单实验示例无需 `data/raw` 即可运行；
- 多实验固定示例正常；
- 两类模板可以下载；
- 指标、图表、摘要和内存下载正常；
- 可预期错误显示中文提示且不显示 traceback；
- 页面明确区分本地处理与云端处理；
- 构建日志中没有用户数据内容；
- 应用访问范围符合预期；
- 未配置不需要的 Secret。

## 6. 更新与应用管理

合并到 `master` 后，现有云端部署流程会检测仓库变化并更新应用。每次更新前应确保 CI 和本地发布检查通过；更新后仍要人工检查五页导航、上传流程、下载、错误阻断和控制台状态。

如需变更或删除应用，应由仓库和平台管理员在 Streamlit Community Cloud 管理界面人工操作。删除云端应用不会自动删除 GitHub 仓库，两者需要分别管理。

## 7. 发布控制

版本准备 Pull Request 只更新代码与文档，不创建 Git 标签或 GitHub Release，也不手动修改 Streamlit Sharing 设置。正式标签和 Release 必须等待合并后的 `master` 完成线上生产验收后再创建。
