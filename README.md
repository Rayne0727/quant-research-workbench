# Quant Research Workbench

Quant Research Workbench（量化研究实验台）是一个用于分析量化研究实验结果的本地 Web 应用。本项目面向零基础学习者，当前版本支持标准日频策略收益 CSV 的基础绩效分析。

## 当前功能

- 上传并读取一份标准日频策略收益 CSV；
- 严格验证字段、日期、数值、缺失值和重复日期；
- 计算累计收益、年化收益、年化波动率、夏普比率、最大回撤和盈利日占比；
- 使用 Plotly 展示累计净值和回撤曲线；
- 支持可选基准收益，并提供固定示例数据；
- 预览清洗后的前 20 行数据。

## CSV 字段协议

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
│   └── performance.py
├── data/
│   ├── .gitkeep
│   └── example_daily_returns.csv
└── tests/
    ├── __init__.py
    ├── test_sample_data.py
    ├── test_data_loader.py
    └── test_performance.py
```

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
