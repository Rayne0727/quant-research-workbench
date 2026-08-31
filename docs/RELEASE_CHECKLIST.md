# Quant Research Workbench v1.0.0 发布检查清单

本清单用于完成第一阶段稳定 release。Tag 和 GitHub Release 只能在合并后的 `master` 通过 CI 与公开部署验收后创建。

1. [ ] 本地 `master`、`origin/master` 和 GitHub `master` 一致，worktree clean。
2. [ ] `APP_VERSION == 1.0.0`，五页 UI、README、CHANGELOG、协议、部署文档和 release notes 版本一致。
3. [ ] README 的 Live Demo、v1.0.0 Release、文档和 MIT License 链接正确；GitHub Homepage 与 Topics 已设置。
4. [ ] `ruff check` 通过。
5. [ ] `ruff format --check` 通过。
6. [ ] 16-module `mypy --strict` 通过，未用新 ignore、cast 或 Any 隐藏问题。
7. [ ] full pytest 与 branch coverage gate 通过，README 中的测试数字与最终结果一致。
8. [ ] `pip check` 与 `compileall app.py src tests` 通过。
9. [ ] `scripts/check_quality.bat` 与 clean-worktree `scripts/check_release.bat` 通过。
10. [ ] GitHub Actions CI 与 runtime `pip-audit` 通过，workflow 保持 `contents: read` 和 `persist-credentials: false`。
11. [ ] 公开 Streamlit 页面显示 v1.0.0，无 visible traceback；隐私提示与非投资建议声明完整。
12. [ ] Standard Return、Standard NAV、Generic Return、Generic NAV、XLSX reference workflows 通过，已有 reference bytes 未改变。
13. [ ] Comparison 示例与上传流程正常，指标、对齐数据和 Markdown 报告可下载。
14. [ ] 四条单实验路径均可下载 Manifest 与固定四成员 Research Bundle；identity、provenance、index SHA 和无 raw-source 边界正确。
15. [ ] 合并后完成 production smoke，再创建 `v1.0.0` Tag 和 GitHub Release；此后只接受 bug、安全维护和真实反馈驱动的改动。

本地发布检查：

```powershell
.\scripts\check_release.bat
```

脚本不会启动 Streamlit、提交 Git、创建 Tag 或发布 Release。
