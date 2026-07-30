# Quant Research Workbench

Quant Research Workbench（量化研究实验台）是一个用于分析量化研究实验结果的本地 Web 应用。

当前版本：**v0.1.0-rc1 Release Candidate**。`rc1` 表示第一个发布候选版；当前业务功能已经冻结，本阶段只完善本地质量门禁和使用体验，正式发布时再将版本调整为 `v0.1.0`。

当前支持两条完整工作流：

1. 单实验分析：读取标准日频收益或每周调仓净值 CSV，验证、计算、绘图并导出标准化结果；
2. 多实验比较：读取 2 至 6 份标准化分析 CSV，按真实共同交易日期重新计算并比较。

## 快速启动

在项目根目录打开 PowerShell：

```powershell
.\scripts\run_app.bat
```

浏览器访问 <http://localhost:8501>。停止网站时回到终端按 `Ctrl+C`。

## 使用文档

- [用户使用指南](docs/USER_GUIDE.md)
- [数据协议](docs/DATA_PROTOCOLS.md)
- [发布检查清单](docs/RELEASE_CHECKLIST.md)

## 数据隐私边界

上传文件仅在当前应用进程中处理，应用不会主动把上传数据或下载结果写入 `data/`。本地 `data/raw/` 中的真实验收数据被 Git 忽略。项目不提供实时行情、自动交易或投资建议。

## 当前功能

- 上传并读取标准日频策略收益或每周调仓净值 CSV；
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

资源限制：单实验文件和多实验中的每份文件最大 `20 MB`，每份 CSV 最多 `200000` 行，多实验最多 `6` 份文件。超限内容不会被截断、抽样或部分处理。

## 支持的数据格式

上传时必须明确选择格式，系统不会自动猜测、映射或切换格式。

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
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── limits.py
│   ├── templates.py
│   ├── sample_data.py
│   ├── data_loader.py
│   ├── adapters.py
│   ├── performance.py
│   ├── reporting.py
│   ├── comparison.py
│   ├── ui_single.py
│   └── ui_comparison.py
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
│   └── RELEASE_CHECKLIST.md
└── tests/
    ├── __init__.py
    ├── test_sample_data.py
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

如果 PowerShell 已允许执行本地脚本，也可以先激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

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

## 当前版本暂不支持

- 任意原始策略格式的批量适配和跨实验基准比较；
- 交易明细、模型预测文件和因子文件；
- 任意字段自动识别或映射；
- 数据库和用户登录；
- AI 摘要、外部 API 或实时股票数据；
- Docker、云端部署或其他部署功能。
