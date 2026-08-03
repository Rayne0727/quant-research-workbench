"""Streamlit 公共导航与示例流程烟雾测试。"""

from pathlib import Path
import tomllib

import pytest
from streamlit.testing.v1 import AppTest

from src.config import APP_NAME, APP_VERSION
from src.ui_common import PUBLIC_PRIVACY_NOTICE, RESEARCH_DISCLAIMER


def _load_app() -> AppTest:
    return AppTest.from_file("app.py", default_timeout=20).run()


def _open_page(app: AppTest, page_name: str) -> AppTest:
    app.radio(key="app_navigation").set_value(page_name).run()
    return app


def _download_labels(app: AppTest) -> list[str]:
    return [button.label for button in app.get("download_button")]


def _visible_text(app: AppTest) -> str:
    element_types = ("caption", "info", "markdown", "title", "warning", "text")
    values: list[str] = []
    for element_type in element_types:
        values.extend(str(element.value) for element in app.get(element_type))
    return "\n".join(values)


def test_home_page_is_default_and_has_no_analysis_charts() -> None:
    app = _load_app()

    assert not app.exception
    assert app.radio(key="app_navigation").value == "首页"
    assert app.title[0].value == APP_NAME
    assert len(app.get("plotly_chart")) == 0


def test_home_page_explains_product_and_main_workflows() -> None:
    app = _load_app()
    page_text = _visible_text(app)

    assert APP_NAME in page_text
    assert "量化研究实验台" in page_text
    assert "字段核验、绩效分析、可视化与标准化导出" in page_text
    assert "单实验分析" in page_text
    assert "多实验比较" in page_text
    assert "1. 上传数据" in page_text
    assert "4. 下载结果" in page_text


@pytest.mark.parametrize(
    ("button_key", "expected_page"),
    (
        ("home_open_single", "单实验分析"),
        ("home_open_comparison", "多实验比较"),
    ),
)
def test_home_entry_buttons_open_expected_page(
    button_key: str,
    expected_page: str,
) -> None:
    app = _load_app()

    app.button(key=button_key).click().run()

    assert not app.exception
    assert app.radio(key="app_navigation").value == expected_page
    assert app.title[0].value == expected_page


def test_public_streamlit_configuration_is_valid() -> None:
    config_path = Path(".streamlit/config.toml")
    with config_path.open("rb") as config_file:
        config = tomllib.load(config_file)

    assert config["client"]["toolbarMode"] == "minimal"
    assert config["theme"]["base"] == "light"
    assert config["theme"]["primaryColor"] == "#0F766E"


def test_can_enter_single_analysis_and_sample_still_renders() -> None:
    app = _open_page(_load_app(), "单实验分析")

    assert not app.exception
    assert app.title[0].value == "单实验分析"
    assert app.radio(key="single_data_mode").value == "使用示例数据"
    assert len(app.get("plotly_chart")) == 2
    assert "下载标准日频收益 CSV 模板" in _download_labels(app)


def test_can_enter_comparison_and_sample_still_renders() -> None:
    app = _open_page(_load_app(), "多实验比较")

    assert not app.exception
    assert app.title[0].value == "多实验比较"
    assert app.radio(key="comparison_source_mode").value == "使用比较示例数据"
    assert len(app.get("plotly_chart")) == 2
    assert "下载标准化比较 CSV 模板" in _download_labels(app)


def test_can_enter_usage_guide() -> None:
    app = _open_page(_load_app(), "使用说明")
    tab_labels = [tab.label for tab in app.tabs]

    assert not app.exception
    assert app.title[0].value == "使用说明"
    assert tab_labels == ["单实验", "多实验", "常见错误", "数据处理"]
    assert "0.01 表示 1%" in _visible_text(app)


def test_page_displays_version_privacy_notice_and_disclaimer() -> None:
    app = _load_app()
    page_text = _visible_text(app)

    assert APP_VERSION in page_text
    assert PUBLIC_PRIVACY_NOTICE in page_text
    assert RESEARCH_DISCLAIMER in page_text


@pytest.mark.parametrize(
    "page_name",
    ("首页", "单实验分析", "多实验比较", "使用说明"),
)
def test_all_navigation_pages_have_no_uncaught_exception(page_name: str) -> None:
    app = _load_app()
    if page_name != "首页":
        _open_page(app, page_name)

    assert not app.exception
