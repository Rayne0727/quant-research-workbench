"""Streamlit 页面基础烟雾测试。"""

from streamlit.testing.v1 import AppTest

from src.config import APP_NAME, APP_VERSION


def _load_app() -> AppTest:
    return AppTest.from_file("app.py", default_timeout=20).run()


def _download_labels(app: AppTest) -> list[str]:
    return [button.label for button in app.get("download_button")]


def test_initial_page_loads_without_exception_in_single_mode() -> None:
    app = _load_app()

    assert not app.exception
    assert app.radio(key="main_analysis_mode").value == "单实验分析"
    assert app.title[0].value == APP_NAME


def test_page_displays_version_and_privacy_scope_notice() -> None:
    app = _load_app()
    captions = "\n".join(item.value for item in app.caption)

    assert APP_VERSION in captions
    assert "不会主动将上传数据写入data目录" in captions
    assert "不提供实时行情、自动交易或投资建议" in captions


def test_single_sample_mode_renders_and_has_template_download() -> None:
    app = _load_app()

    assert not app.exception
    assert len(app.get("plotly_chart")) == 2
    assert "下载标准日频收益CSV模板" in _download_labels(app)


def test_comparison_sample_mode_renders_and_has_template_download() -> None:
    app = _load_app()
    app.radio(key="main_analysis_mode").set_value("多实验比较").run()

    assert not app.exception
    assert app.radio(key="main_analysis_mode").value == "多实验比较"
    assert len(app.get("plotly_chart")) == 2
    assert "下载标准化比较CSV模板" in _download_labels(app)
