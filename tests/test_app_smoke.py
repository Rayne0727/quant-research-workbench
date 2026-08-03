"""Streamlit 公共导航与示例流程烟雾测试。"""

import json
from pathlib import Path
import tomllib

import pytest
from streamlit.testing.v1 import AppTest

from src.config import APP_NAME, APP_VERSION
from src.ui_common import (
    PUBLIC_PRIVACY_NOTICE,
    RESEARCH_DISCLAIMER,
    SIDEBAR_PRIVACY_NOTICE,
)


SENSITIVE_WARNING_TERMS = (
    "请勿上传",
    "账号密码",
    "API密钥",
    "交易凭证",
    "个人敏感信息",
    "商业机密",
    "受限制数据",
)


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


def test_optional_experiment_information_is_collapsed_and_usable() -> None:
    app = _open_page(_load_app(), "单实验分析")
    experiment_expander = next(
        item for item in app.expander if item.label == "实验信息（可选）"
    )

    assert experiment_expander.proto.expanded is False
    assert app.text_input(key="experiment_name:sample").value == "示例日频收益实验"

    app.text_input(key="experiment_name:sample").set_value("折叠区域实验")
    app.text_input(key="strategy_name:sample").set_value("示例策略")
    app.text_area(key="research_notes:sample").set_value("表单仍可正常填写。")
    app.run()

    assert not app.exception
    assert app.text_input(key="experiment_name:sample").value == "折叠区域实验"
    assert app.text_input(key="strategy_name:sample").value == "示例策略"
    assert app.text_area(key="research_notes:sample").value == "表单仍可正常填写。"


def test_can_enter_comparison_and_sample_still_renders() -> None:
    app = _open_page(_load_app(), "多实验比较")

    assert not app.exception
    assert app.title[0].value == "多实验比较"
    assert app.radio(key="comparison_source_mode").value == "使用比较示例数据"
    assert len(app.get("plotly_chart")) == 2
    assert "下载标准化比较 CSV 模板" in _download_labels(app)


def test_comparison_drawdown_axis_uses_two_decimal_percentage() -> None:
    app = _open_page(_load_app(), "多实验比较")
    drawdown_spec = json.loads(app.get("plotly_chart")[1].proto.spec)

    assert not app.exception
    assert drawdown_spec["layout"]["yaxis"]["tickformat"] == ".2%"


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


def test_sidebar_uses_concise_privacy_notice() -> None:
    app = _load_app()
    sidebar_warnings = [warning.value for warning in app.sidebar.warning]

    assert sidebar_warnings == [SIDEBAR_PRIVACY_NOTICE]
    assert SIDEBAR_PRIVACY_NOTICE == (
        "公开云端版本会在云端应用进程中处理上传文件。"
        "请勿上传敏感或受限制数据。"
    )
    assert "云端应用进程" in SIDEBAR_PRIVACY_NOTICE
    assert "敏感或受限制数据" in SIDEBAR_PRIVACY_NOTICE
    detailed_terms = (
        "账号密码",
        "API密钥",
        "交易凭证",
        "个人敏感信息",
        "商业机密",
    )
    for term in detailed_terms:
        assert term not in SIDEBAR_PRIVACY_NOTICE


@pytest.mark.parametrize("page_name", ("首页", "使用说明"))
def test_main_privacy_pages_keep_complete_sensitive_data_warning(
    page_name: str,
) -> None:
    app = _load_app()
    if page_name != "首页":
        _open_page(app, page_name)
    main_text = _visible_text(app.main)

    assert PUBLIC_PRIVACY_NOTICE in main_text
    for term in SENSITIVE_WARNING_TERMS:
        assert term in main_text


@pytest.mark.parametrize(
    "page_name",
    ("首页", "单实验分析", "多实验比较", "使用说明"),
)
def test_all_pages_display_version_from_shared_config(page_name: str) -> None:
    app = _load_app()
    if page_name != "首页":
        _open_page(app, page_name)

    page_text = _visible_text(app)

    assert f"v{APP_VERSION}" in page_text
    assert f"V{APP_VERSION.upper()}" not in page_text


def test_quick_guide_version_keeps_configured_case() -> None:
    app = _open_page(_load_app(), "使用说明")
    kicker_markup = [
        item.value
        for item in app.markdown
        if 'class="qrw-kicker"' in str(item.value)
    ]
    style_markup = next(
        item.value for item in app.markdown if "<style>" in str(item.value)
    )

    assert kicker_markup == [
        f'<p class="qrw-kicker">快速指南 · v{APP_VERSION}</p>'
    ]
    assert "text-transform: none;" in style_markup
    assert "text-transform: uppercase;" not in style_markup


def test_ui_modules_do_not_hardcode_release_version() -> None:
    ui_paths = (
        Path("app.py"),
        Path("src/ui_common.py"),
        Path("src/ui_single.py"),
        Path("src/ui_comparison.py"),
    )

    assert all(
        "0.1.0-rc1" not in path.read_text(encoding="utf-8")
        for path in ui_paths
    )
    assert all(
        "APP_VERSION.upper()" not in path.read_text(encoding="utf-8")
        for path in ui_paths
    )


@pytest.mark.parametrize(
    "page_name",
    ("首页", "单实验分析", "多实验比较", "使用说明"),
)
def test_all_navigation_pages_have_no_uncaught_exception(page_name: str) -> None:
    app = _load_app()
    if page_name != "首页":
        _open_page(app, page_name)

    assert not app.exception
