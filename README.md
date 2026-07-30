# Quant Research Workbench

Quant Research Workbench（量化研究实验台）是一个用于分析量化研究实验结果的本地 Web 应用。本项目面向零基础学习者，第一阶段专注于搭建一个简单、可运行的原型。

## 当前功能

- 使用 Streamlit 展示本地 Web 页面；
- 展示三个基于模拟数据的示例指标；
- 使用固定、可重复的模拟日收益数据；
- 使用 Plotly 绘制累计收益折线图；
- 使用 pytest 验证模拟数据。

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
│   └── sample_data.py
├── data/
│   └── .gitkeep
└── tests/
    ├── __init__.py
    └── test_sample_data.py
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

- 上传或分析策略结果 CSV；
- 计算真实策略绩效指标；
- 数据库和用户登录；
- AI 摘要、外部 API 或实时股票数据；
- Docker、云端部署或其他部署功能。
