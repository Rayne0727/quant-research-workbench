# Engineering Quality

本项目的工程质量门禁用于在不改变业务公式、数据协议和公开行为的前提下，尽早发现代码风格、测试、覆盖率、依赖和发布准备问题。质量失败必须修复根因，不得通过降低门禁或排除核心代码解决。

## A.1a：Ruff style baseline

A.1a 固定使用 `ruff==0.16.2`，目标 Python 为 3.14，行宽为 100。启用的规则族为 `E`、`F`、`I`、`B`、`UP` 和 `RUF`，并使用 Ruff formatter 统一 Python 格式。

项目保留中文 UI 文本和文档字符串中经过审计的全角标点。`allowed-confusables` 只允许 `（`、`）`、`，`、`：`、`；`、`？`；`RUF001`、`RUF002` 和 `RUF003` 对其他混淆字符仍然生效。

## A.1b：pytest 与 branch coverage

测试使用 `pytest==9.1.1` 和 `pytest-cov==7.1.0`。A.1a 测得的 branch coverage 基线为 `89.4532%`。根据既定决策规则，CI 的正式 `fail_under` 为 `85`，而工程改进目标约为 `90%`。

门禁设为 85 是为了在当前可靠基线上提供稳定、明确的最低约束；实际目标约 90 是为了通过真实高风险边界测试持续改善，而不是把短期测量波动变成不必要的 CI 噪声。两者用途不同，不能通过降低 85 的门禁处理失败。

禁止使用以下方式提高覆盖率：

- 对核心模块增加 coverage omit 或大面积 `pragma: no cover`；
- 编写无断言测试，或仅调用函数刷行数；
- monkeypatch 掉核心逻辑后只断言调用发生；
- 删除异常分支、修改业务公式或迁就实现修改期望值。

A.1b 新增 coverage exclusion 为 0。

## 本地质量检查

安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

运行完整工程质量门禁：

```powershell
.\scripts\check_quality.bat
```

脚本自动定位仓库根目录并明确使用 `.venv\Scripts\python.exe`，依次执行：

1. Ruff lint；
2. Ruff format check；
3. pytest 与 branch coverage；
4. pip check。

脚本不修改文件，任一步失败都会返回非零状态。

发布前在干净工作区运行：

```powershell
.\scripts\check_release.bat
```

发布检查只运行一次 pytest：它先调用 `check_quality.bat`，再执行 compileall、版本与发布文件检查以及 clean-worktree 门禁。

## GitHub Actions

GitHub Actions 在 push 到 `master`、面向 `master` 的 pull request 和手动触发时运行同等门禁：安装运行与开发依赖、Ruff lint、formatter check、pytest branch coverage、pip check、compileall 和发布准备静态检查。CI 不自动修复、不提交文件，也不上传第三方 coverage 平台。

CI 失败时应在本地复现对应命令并修复根因。不得降低 coverage、弱化 Ruff、跳过测试或修改业务期望来换取绿色状态。

## 范围与不变量

A.1b 不包含 mypy、CodeQL、Dependabot、性能 benchmark 或新业务功能。这些工作属于后续阶段。

工程质量改动不得改变 `APP_VERSION`、v0.2.0 Tag/Release、参考文件字节与 SHA-256、业务计算公式、benchmark/NAV 边界、字段映射确认语义，或 standardization/analysis key 的失效语义。
