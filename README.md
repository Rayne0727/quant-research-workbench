# Quant Research Workbench

Quant Research Workbench（量化研究实验台）是一个用于分析量化研究实验结果的本地 Web 应用。

当前版本：**v0.2.0 公开功能版本**。这是首个包含完整通用文件导入工作流和参考文件库的公开功能版本；现有计算、数据协议、报告和导出口径保持不变。

当前支持三条受控工作流：

1. 单实验分析：读取标准日频收益或每周调仓净值 CSV，验证、计算、绘图并导出标准化结果；
2. 多实验比较：读取 2 至 6 份标准化分析 CSV，按真实共同交易日期重新计算并比较。
3. 通用文件导入：读取 CSV 或 XLSX，确认解析设置、工作表和字段映射，主动生成标准化预览；预检通过后还需执行现有严格协议验证、勾选最终确认并点击“开始绩效分析”，才会复用现有指标、图表、报告和导出。

公开 App 另提供独立“参考文件”页，集中展示 6 份正常参考文件和 5 份错误示例。所有文件均为确定性合成数据，只能由用户主动下载；下载不会自动上传、映射或分析。

公开导航共五页：首页、单实验分析、多实验比较、参考文件和使用说明。

## 快速启动

在项目根目录打开 PowerShell：

```powershell
.\scripts\run_app.bat
```

浏览器访问 <http://localhost:8501>。停止网站时回到终端按 `Ctrl+C`。

## 使用文档

- [用户使用指南](docs/USER_GUIDE.md)
- [v0.2.0 发行说明](docs/RELEASE_NOTES_v0.2.0.md)
- [版本记录](CHANGELOG.md)
- [数据协议](docs/DATA_PROTOCOLS.md)
- [发布检查清单](docs/RELEASE_CHECKLIST.md)
- [GitHub 与云部署准备](docs/DEPLOYMENT.md)
- [安全与数据隐私说明](docs/SECURITY_AND_PRIVACY.md)

## 数据隐私边界

本地运行时，上传文件在当前本地应用进程中处理；部署到云端后，上传文件将在云端应用进程中处理。当前代码不会主动把上传数据或下载结果永久写入 `data/`，但这不构成绝对安全保证，云端平台日志和基础设施不由本项目代码完全控制。

不要上传账号密码、API 密钥、交易凭证、个人敏感信息、商业机密或其他受限制内容。敏感研究数据应先脱敏；当前建议优先使用私人仓库和私人应用。

## 当前功能

- 上传并读取标准日频策略收益或每周调仓净值 CSV；
- 通用读取 CSV/XLSX，手动确认 CSV 分隔符或 Excel 工作表，并预览原始数据；
- 根据字段名和有界数据画像，为通用导入生成可解释、可重复的字段候选建议；
- 由用户选择收益率或净值主口径，并在当前会话中显式确认字段映射；
- 按确认映射创建新的内存 DataFrame，展示标准化候选结构、诊断字段和预检问题；
- 对通过预检的候选表执行独立的现有严格协议验证，并要求用户最终确认后才分析；
- 严格验证字段、日期、数值、缺失值和重复日期；
- 计算累计收益、年化收益、年化波动率、夏普比率、最大回撤和盈利日占比；
- 使用 Plotly 展示累计净值和回撤曲线；
- 支持可选基准收益，并提供固定示例数据；
- 对净值文件中的 `daily_ret` 进行一致性诊断；
- 生成确定性的中文分析摘要和 Markdown 报告；
- 下载标准化分析数据 CSV；
- 对 2 至 6 份标准化分析 CSV 按共同交易日期进行比较；
- 下载比较指标、共同日期对齐净值和确定性比较报告；
- 在当前会话中记录可选的实验名称、策略名称和研究备注；
- 预览清洗后的前 20 行数据。
- 下载经过文件大小和 SHA-256 完整性校验的确定性合成参考文件；
- 按正常参考文件和错误示例分组查看推荐入口、主口径、字段映射及预期结果。

资源限制：单实验文件和多实验中的每份文件最大 `20 MB`，每份表格最多 `200000` 行，通用导入最多 `500` 列，多实验最多 `6` 份文件。超限内容不会被截断、抽样或部分处理。

## 支持的数据格式

“按现有标准协议上传”仍要求明确选择格式，系统不会自动猜测、映射或切换格式。

### 通用 CSV/XLSX 读取与预览

“通用文件导入（CSV/XLSX）”仅支持 `.csv` 和 `.xlsx`。CSV 会按 UTF-8 BOM、UTF-8 和 GB18030 的有限规则读取，分隔符仅支持逗号、制表符、分号和竖线，并允许用户从固定选项中手动覆盖自动结果。

XLSX 只读取一个工作表：单工作表时自动选择，多工作表时必须由用户明确选择，包括需要时选择隐藏工作表。读取不执行宏、不加载外部链接内容、不合并多个工作表。当前默认第一行为字段名。

通用读取会报告原始字段、基础问题和前 20 行预览，并按固定规则为日期、策略收益率、策略净值、基准收益率、基准净值、逐日回撤和原始日收益率生成候选建议。规则只使用归一化后的字段名和最多 `10000` 个非空观察值的固定样本；评分、置信度、理由、风险和备选字段均可在页面查看。

字段识别建议与字段映射确认是两个阶段。高置信度、无相近候选且无冲突的字段可以预填，但仍必须由用户选择策略分析主口径、核对每个原始字段、勾选声明并点击“确认字段映射”。确认结果只与当前文件内容、解析设置、工作表、表头规则和有序字段列表绑定；来源变化会使旧确认失效。

字段建议、用户确认式字段映射和标准化数据质量预检是三个不同步骤。映射确认只保存字段引用；只有用户主动点击后，标准化流程才按照确认映射创建独立的新内存 DataFrame。原始 DataFrame、列名、索引、行数和顺序保持不变，不自动排序、去重、填充、删行、单位换算或净值归一化。

收益率主口径的分析候选结构为 `date`、`strategy_return` 和可选的已映射 `benchmark_return`；净值主口径为 `date`、由已映射 `strategy_nav` 改名得到的 `nav_strat`，以及可选的已映射 `daily_ret`。非主口径字段只进入诊断预览：`benchmark_nav` 不会推导 `benchmark_return`，`strategy_nav` 不会覆盖 `strategy_return`，`strategy_return` 也不会覆盖 `strategy_nav`，`drawdown` 只用于诊断。

标准化数据质量预检只执行确定性日期、数值、收益率、净值和诊断字段检查。普通数值字符串可以转换，但百分号、千分位、货币符号、中文单位等不会被猜测；数值 `1` 始终保留为 `1`，不会解释为 `1%`。预检通过不等于现有严格分析协议已经通过，也不会自动生成绩效、图表、报告或下载。

严格协议验证与绩效分析设置两道显式门禁。第一道由用户点击“执行严格协议验证”：收益率主口径把 `date`、`strategy_return` 和可选 `benchmark_return` 交给现有标准日收益协议；净值主口径把 `date`、`nav_strat` 和可选 `daily_ret` 交给现有净值适配器。严格验证通过后仍不计算绩效，用户必须核对单位、主口径和日期范围，勾选最终声明并点击“开始绩效分析”。之后才复用既有绩效、图表、摘要、Markdown 报告和标准化 CSV 导出；相同输入与现有直接上传采用同一计算口径。

通用路径不会自动除以 `100`、修复、排序、去重、填充或删除数据，也不会用 `benchmark_nav` 生成 `benchmark_return`。文件、编码、分隔符、工作表、字段顺序、确认映射、主口径、标准化结果或协议版本变化后，严格验证和分析结果立即失效。

### 参考文件库

“参考文件”页提供标准收益率、中文/英文通用收益率、中文通用净值和多工作表 XLSX，同时在默认折叠区域提供百分号收益率、重复日期、含糊日期、倒序日期和非正净值错误示例。文件全部位于 `assets/reference_files/`，不包含真实证券、账户、机构或投资结果。

App 只读取 `catalog.json` 明确列出的仓库静态文件，并在下载前按 `manifest.json` 复核文件大小和 SHA-256。路径必须是参考目录内的安全相对路径，不允许绝对路径、`..` 或符号链接逃逸。CSV 和 XLSX 均直接返回原始字节，不经过 DataFrame 重新导出，不生成临时文件，也不会自动切换分析页、建立映射或启动分析。

错误示例只用于验证系统的阻断机制，不是正常分析模板。即使下载正常参考文件，用户仍需主动上传并核对字段含义、收益率或净值单位、主口径和分析范围；云端上传的隐私边界保持不变。

### 标准日频收益 CSV

必需字段：

- `date`：交易日期，必须能转换为有效日期；
- `strategy_return`：当日策略收益率，必须为有限数值。

可选字段：

- `benchmark_return`：当日基准收益率，存在时必须为有限数值。

收益率必须使用小数形式：`0.01` 表示 `1%`，不能使用 `1` 表示 `1%`。当前阶段不会猜测或自动映射其他字段名。

示例：

```csv
date,strategy_return,benchmark_return
2026-01-05,0.004,0.002
2026-01-06,-0.002,-0.001
```

项目自带的 `data/example_daily_returns.csv` 仅用于功能演示，不代表任何真实投资结果。

### 每周调仓净值 CSV

必需字段：

- `date`：交易日期，必须能转换为有效日期；
- `nav_strat`：策略原始净值，必须为有限正数且不能缺失。

可选字段：

- `daily_ret`：文件原有的辅助日收益字段，存在时必须能够转换为有限数值。

净值格式使用以下方式标准化：

```text
strategy_nav = nav_strat / nav_strat.iloc[0]
strategy_return = nav_strat.pct_change()
```

第一条记录保留为净值曲线起点，但不作为真实收益观察值。累计收益和回撤直接基于标准化后的 `strategy_nav`；年化收益、年化波动率、夏普比率和盈利日占比基于非空的净值推导收益。

`daily_ret` 仅用于与净值推导收益进行一致性诊断。即使两者存在差异，分析也继续以 `nav_strat` 为准，因为净值是该格式中完整反映策略累计结果的主字段；应用不会猜测两者差异属于何种成本口径。

## 分析摘要和导出

分析摘要由固定规则生成，不使用 OpenAI API 或其他模型。摘要以中性方式记录数据概况、绩效结果、可选基准信息、数据限制和固定声明。

页面提供两种内存导出，不会把下载内容写入 `data/`：

- Markdown 分析报告：包含实验信息、核心指标、可选基准结果、适用的一致性诊断和固定声明；
- 标准化分析 CSV：包含 `date`、`strategy_return`、`strategy_nav`、`drawdown`，存在基准时还包含 `benchmark_return` 和 `benchmark_nav`。

每周调仓净值格式导出的第一行 `strategy_return` 为空，`strategy_nav` 第一行为 `1`，净值直接来自 `nav_strat` 标准化结果，不使用 `daily_ret` 重建。

## 多实验比较

多实验比较只接受本应用单实验模式导出的标准化分析 CSV，不直接接受标准日频收益、每周调仓净值或其他原始策略文件。准备数据时，先在“单实验分析”中逐份加载原始文件，再点击“下载标准化分析数据”；随后切换到“多实验比较”，一次上传 2 至 6 份标准化文件。

每份比较文件必须包含：

- `date`；
- `strategy_return`；
- `strategy_nav`；
- `drawdown`。

文件可额外包含 `benchmark_return` 和 `benchmark_nav`，但当前跨实验比较只使用策略字段，不比较基准。系统不会自动猜测、映射或修复其他字段。

系统使用所有实验真实交易日期集合的交集，不进行前向填充、后向填充或插值。每条曲线均以共同首日的 `strategy_nav` 重新归一为 `1`，再由共同区间净值计算收益、回撤和绩效指标。共同首日没有共同区间内的前一日净值，因此该日收益保持为空。

不同样本区间的累计收益受开始日期、结束日期和观察天数影响，不能直接公平比较；统一到共同日期交集后，页面中的各项结果才具有一致的时间范围和计算口径。

比较模式提供三种仅在内存中生成的下载：

- `multi_experiment_metrics.csv`：共同区间指标原始数值；
- `multi_experiment_aligned_nav.csv`：日期及各实验共同区间标准化净值宽表；
- `multi_experiment_comparison_report.md`：实验清单、覆盖范围、指标和确定性摘要。

## 指标计算口径

- 累计净值：`(1 + strategy_return).cumprod()`；
- 累计收益：最后一个累计净值减 `1`；
- 年化收益：最后一个累计净值的 `252 / 有效交易日数` 次方再减 `1`；
- 年化波动率：日收益样本标准差（`ddof=1`）乘以 `sqrt(252)`；
- 夏普比率：假设年化无风险利率为 `0`；
- 回撤：累计净值除以历史累计最高净值再减 `1`；
- 最大回撤：回撤序列的最小值；
- 盈利日占比：策略收益大于 `0` 的记录占比。

## 项目结构

```text
Quant_Research_Workbench/
├── AGENTS.md
├── README.md
├── app.py
├── requirements.txt
├── requirements-dev.txt
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── limits.py
│   ├── templates.py
│   ├── sample_data.py
│   ├── file_import.py
│   ├── field_detection.py
│   ├── field_mapping.py
│   ├── standardization.py
│   ├── analysis_bridge.py
│   ├── data_loader.py
│   ├── adapters.py
│   ├── performance.py
│   ├── reporting.py
│   ├── comparison.py
│   ├── reference_files.py
│   ├── ui_reference_files.py
│   ├── ui_single.py
│   └── ui_comparison.py
├── assets/
│   └── reference_files/
│       ├── catalog.json
│       ├── manifest.json
│       ├── expected_outcomes.csv
│       ├── README.md
│       ├── valid/
│       └── error_examples/
├── data/
│   ├── .gitkeep
│   ├── example_daily_returns.csv
│   └── raw/
│       └── .gitkeep
├── scripts/
│   ├── run_app.bat
│   └── check_release.bat
├── docs/
│   ├── USER_GUIDE.md
│   ├── DATA_PROTOCOLS.md
│   ├── RELEASE_CHECKLIST.md
│   ├── DEPLOYMENT.md
│   └── SECURITY_AND_PRIVACY.md
└── tests/
    ├── __init__.py
    ├── test_sample_data.py
    ├── test_file_import.py
    ├── test_field_detection.py
    ├── test_field_mapping.py
    ├── test_standardization.py
    ├── test_analysis_bridge.py
    ├── test_reference_files.py
    ├── test_data_loader.py
    ├── test_adapters.py
    ├── test_performance.py
    ├── test_reporting.py
    ├── test_comparison.py
    ├── test_release_support.py
    └── test_app_smoke.py
```

`data/raw/` 用于保存在本机验收的真实原始数据。该目录中的数据文件被 Git 忽略，只提交用于保留目录结构的 `.gitkeep`。应用不会修改或永久保存用户上传的原始文件。

## Windows 安装步骤

在 PowerShell 中进入项目目录，然后执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` 只包含应用运行所需的直接依赖。需要运行测试或参与开发时，改为安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` 会先安装运行依赖，再安装 pytest。当前已验证环境为 Python `3.14.2`；CI 使用相同的 `3.14` 主次版本。

如果 PowerShell 已允许执行本地脚本，也可以先激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如需运行测试，请将上面的安装文件替换为 `requirements-dev.txt`。

## 启动和停止应用

推荐在 PowerShell 中使用安全启动脚本：

```powershell
.\scripts\run_app.bat
```

脚本会自动切换到项目根目录、检查虚拟环境，并在启动前确认 8501 端口未被占用。脚本不会自动结束任何进程。

也可以直接执行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501
```

启动后，在浏览器中访问：<http://localhost:8501>

注意：

- Streamlit 启动后，运行终端中的进程会持续工作；
- 关闭浏览器标签页不会停止 Streamlit；
- 停止应用时，请回到运行终端并按 `Ctrl+C`；
- 不要反复执行多次启动命令，否则可能产生残留进程或端口冲突；
- 默认地址是 <http://localhost:8501>；
- URL 中的查询参数仅用于浏览器刷新或页面状态，不代表正式版本号。
- 更新 Python 模块后如果页面出现“无法导入名称”等错误，请先在原终端按
  `Ctrl+C` 完整停止旧服务，再重新执行 `.\scripts\run_app.bat`；仅刷新浏览器
  不能清除旧进程中的 Python 模块缓存。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 本地发布检查

在 Git 工作区干净时运行：

```powershell
.\scripts\check_release.bat
```

脚本依次显示版本、运行全部 pytest、编译 Python 文件并检查 Git 状态。任一步失败都会返回非零状态，不会启动网站或自动提交 Git。

## GitHub 持续集成与部署状态

仓库内的 `.github/workflows/ci.yml` 会在 push 到 `master`、面向 `master` 的 pull request，以及手动触发时运行 pytest 和 Python 编译检查。工作流只使用 GitHub 官方 checkout 与 setup-python action，不需要 Secrets，也不包含发布或部署步骤。

当前只完成 GitHub CI 和云部署文件准备，应用尚未上线，也没有配置 Git remote。未来部署建议先使用私人仓库和私人应用，并在上传前对敏感研究数据脱敏。这里暂不添加 CI 徽章，因为远程仓库地址尚未确定。

## 当前版本暂不支持

- 任意原始策略格式的批量适配、通用文件多实验导入和跨实验基准比较；
- 交易明细、模型预测文件和因子文件；
- 未经用户提交确认就自动应用、重命名或映射任意字段；
- 数据库和用户登录；
- AI 摘要、外部 API 或实时股票数据；
- Docker、自动部署和已经上线的云端服务；当前仅完成部署准备。
