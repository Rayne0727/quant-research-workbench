"""不联网验证 CI、依赖和云端运行准备。"""

from pathlib import Path
import re

from streamlit.testing.v1 import AppTest

from src.templates import (
    generate_comparison_template_csv,
    generate_daily_returns_template_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_PATH = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def _application_python_text() -> str:
    paths = [PROJECT_ROOT / "app.py", *(PROJECT_ROOT / "src").glob("*.py")]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_application_has_no_user_absolute_path_dependency() -> None:
    application_text = _application_python_text()

    assert not re.search(
        r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]",
        application_text,
        flags=re.IGNORECASE,
    )
    assert "C:\\Users\\Rayne" not in application_text


def test_example_mode_does_not_depend_on_raw_data_or_batch_scripts() -> None:
    application_text = _application_python_text().lower()
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=20).run()

    assert "data/raw" not in application_text
    assert "data\\raw" not in application_text
    assert ".bat" not in application_text
    assert not app.exception
    assert app.radio(key="app_navigation").value == "首页"
    app.radio(key="app_navigation").set_value("单实验分析").run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 2


def test_template_generation_does_not_depend_on_working_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert generate_daily_returns_template_csv()
    assert generate_comparison_template_csv()
    assert list(tmp_path.iterdir()) == []


def test_page_privacy_notice_distinguishes_local_and_cloud_processing() -> None:
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=20).run()
    page_text = "\n".join(
        str(item.value)
        for element_type in ("caption", "info", "markdown", "warning")
        for item in app.get(element_type)
    )

    assert "本地运行时" in page_text
    assert "当前电脑的应用进程" in page_text
    assert "公开云端版本" in page_text
    assert "云端应用进程" in page_text
    sensitive_warning_terms = (
        "请勿上传",
        "账号密码",
        "API密钥",
        "交易凭证",
        "个人敏感信息",
        "商业机密",
        "受限制数据",
    )
    for term in sensitive_warning_terms:
        assert term in page_text


def test_runtime_and_development_requirements_are_separated() -> None:
    runtime_lines = {
        line.strip()
        for line in (PROJECT_ROOT / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    development_lines = {
        line.strip()
        for line in (PROJECT_ROOT / "requirements-dev.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }

    assert runtime_lines == {
        "streamlit==1.60.0",
        "pandas==3.0.5",
        "plotly==6.9.0",
    }
    assert "-r requirements.txt" in development_lines
    assert "pytest==9.1.1" in development_lines


def test_ci_workflow_runs_tests_and_compile_without_deployment_or_secrets() -> None:
    ci_text = CI_PATH.read_text(encoding="utf-8")
    ci_lower = ci_text.lower()

    assert "name: CI" in ci_text
    assert "actions/checkout@v4" in ci_text
    assert "actions/setup-python@v5" in ci_text
    assert 'python-version: "3.14"' in ci_text
    assert "push:" in ci_text and "pull_request:" in ci_text
    assert "workflow_dispatch:" in ci_text
    assert "- master" in ci_text
    assert "python -m pip install -r requirements-dev.txt" in ci_text
    assert "python -m pytest" in ci_text
    assert "python -m compileall app.py src tests" in ci_text
    assert "secrets" not in ci_lower
    assert "deploy" not in ci_lower
    assert "streamlit run" not in ci_lower


def test_deployment_document_does_not_invent_repository_url() -> None:
    deployment_text = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text(
        encoding="utf-8"
    )

    assert "https://github.com/" not in deployment_text
    assert "github.com/" not in deployment_text.lower()
    assert "入口文件：`app.py`" in deployment_text
    assert "分支：`master`" in deployment_text
