# Quant Research Workbench

Quant Research Workbench（量化研究实验台）是一个用于分析量化研究实验结果的本地 Web 应用。本项目面向零基础学习者，当前支持标准日频收益和每周调仓净值两种明确的 CSV 格式。

## 当前功能

- 上传并读取标准日频策略收益或每周调仓净值 CSV；
- 严格验证字段、日期、数值、缺失值和重复日期；
- 计算累计收益、年化收益、年化波动率、夏普比率、最大回撤和盈利日占比；
- 使用 Plotly 展示累计净值和回撤曲线；
- 支持可选基准收益，并提供固定示例数据；
- 对净值文件中的 `daily_ret` 进行一致性诊断；
- 预览清洗后的前 20 行数据。

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
│   ├── sample_data.py
│   ├── data_loader.py
│   ├── adapters.py
│   └── performance.py
├── data/
│   ├── .gitkeep
│   ├── example_daily_returns.csv
│   └── raw/
│       └── .gitkeep
└── tests/
    ├── __init__.py
    ├── test_sample_data.py
    ├── test_data_loader.py
    ├── test_adapters.py
    └── test_performance.py
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

## 启动应用

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

启动后，在浏览器中访问：<http://localhost:8501>

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 当前版本暂不支持

- 多文件或多策略对比；
- 交易明细、模型预测文件和因子文件；
- 任意字段自动识别或映射；
- 数据库和用户登录；
- AI 摘要、外部 API 或实时股票数据；
- Docker、云端部署或其他部署功能。
