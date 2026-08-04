"""公开版本配置、发布文档、模板和上传限制测试。"""

from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
import pytest

from src.comparison import (
    load_and_compare_standardized_files,
    validate_standardized_data,
)
from src.config import (
    APP_VERSION,
    COMPARISON_FILE_MAX_MB,
    MAX_COLUMNS_PER_FILE,
    MAX_COMPARISON_FILES,
    MAX_ROWS_PER_FILE,
    SINGLE_FILE_MAX_MB,
)
from src.data_loader import load_returns_csv
from src.limits import BYTES_PER_MB, UploadLimitError
from src.templates import (
    build_comparison_template_data,
    generate_comparison_template_csv,
    generate_daily_returns_template_csv,
)
from src import ui_comparison, ui_single


class OversizedUpload:
    """只暴露元数据，确保超限文件不会进入读取阶段。"""

    def __init__(self, name: str, size: int) -> None:
        self.name = name
        self.size = size

    def read(self, *args: object, **kwargs: object) -> bytes:
        raise AssertionError("超限文件不应被读取")


def test_public_release_config_values_are_valid() -> None:
    assert APP_VERSION == "0.2.0"
    assert f"v{APP_VERSION}" == "v0.2.0"
    assert SINGLE_FILE_MAX_MB > 0
    assert COMPARISON_FILE_MAX_MB > 0
    assert isinstance(MAX_ROWS_PER_FILE, int) and MAX_ROWS_PER_FILE > 0
    assert MAX_COLUMNS_PER_FILE == 500
    assert MAX_COMPARISON_FILES == 6


def test_v020_release_documents_are_present_and_current() -> None:
    changelog = Path("CHANGELOG.md")
    release_notes = Path("docs/RELEASE_NOTES_v0.2.0.md")
    readme_text = Path("README.md").read_text(encoding="utf-8")
    checklist_text = Path("docs/RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    protocol_text = Path("docs/DATA_PROTOCOLS.md").read_text(encoding="utf-8")
    deployment_text = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")

    assert changelog.is_file()
    assert release_notes.is_file()
    assert "## v0.2.0 — 2026-08-04" in changelog.read_text(encoding="utf-8")
    assert "# Quant Research Workbench v0.2.0" in release_notes.read_text(
        encoding="utf-8"
    )
    assert "当前版本：**v0.2.0 公开功能版本**" in readme_text
    assert checklist_text.startswith(
        "# Quant Research Workbench v0.2.0 发布检查清单"
    )
    assert "本文档对应 `v0.2.0`" in protocol_text
    assert "当前尚未创建远程仓库" not in deployment_text
    assert "GitHub 远程仓库已经存在" in deployment_text


def test_daily_returns_template_contains_expected_fields() -> None:
    template = pd.read_csv(BytesIO(generate_daily_returns_template_csv()))

    assert list(template.columns) == [
        "date",
        "strategy_return",
        "benchmark_return",
    ]
    assert 3 <= len(template) <= 5


def test_comparison_template_contains_expected_fields() -> None:
    template = pd.read_csv(BytesIO(generate_comparison_template_csv()))

    assert list(template.columns) == [
        "date",
        "strategy_return",
        "strategy_nav",
        "drawdown",
    ]
    assert len(template) >= 4


def test_comparison_template_first_row_protocol() -> None:
    template = build_comparison_template_data()

    assert pd.isna(template["strategy_return"].iloc[0])
    assert template["strategy_nav"].iloc[0] == pytest.approx(1.0)


def test_comparison_template_return_and_drawdown_are_consistent() -> None:
    template = build_comparison_template_data()
    expected_return = template["strategy_nav"].pct_change(fill_method=None)
    expected_drawdown = (
        template["strategy_nav"] / template["strategy_nav"].cummax() - 1
    )

    pd.testing.assert_series_equal(
        template["strategy_return"], expected_return, check_names=False
    )
    pd.testing.assert_series_equal(
        template["drawdown"], expected_drawdown, check_names=False
    )


def test_comparison_template_passes_existing_validation() -> None:
    experiment = validate_standardized_data(
        build_comparison_template_data(), "template.csv"
    )

    assert len(experiment.data) == 4


def test_single_file_size_limit_fails_before_reading() -> None:
    upload = OversizedUpload(
        "large_single.csv", (SINGLE_FILE_MAX_MB + 1) * BYTES_PER_MB
    )

    with pytest.raises(
        UploadLimitError,
        match=rf"large_single.csv.*允许上限 {SINGLE_FILE_MAX_MB} MB",
    ):
        load_returns_csv(upload)  # type: ignore[arg-type]


def test_oversized_file_in_comparison_fails_with_filename() -> None:
    valid_csv = generate_comparison_template_csv()
    oversized = OversizedUpload(
        "large_comparison.csv", (COMPARISON_FILE_MAX_MB + 1) * BYTES_PER_MB
    )

    with pytest.raises(
        UploadLimitError,
        match=rf"large_comparison.csv.*允许上限 {COMPARISON_FILE_MAX_MB} MB",
    ):
        load_and_compare_standardized_files(
            [
                ("valid.csv", BytesIO(valid_csv)),
                ("large_comparison.csv", oversized),  # type: ignore[arg-type]
            ]
        )


def test_row_limit_fails_with_actual_count_filename_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.data_loader.MAX_ROWS_PER_FILE", 2)
    csv_text = StringIO(
        "date,strategy_return\n"
        "2026-01-01,0.01\n"
        "2026-01-02,0.02\n"
        "2026-01-03,0.03\n"
    )
    csv_text.name = "too_many_rows.csv"  # type: ignore[attr-defined]

    with pytest.raises(
        UploadLimitError,
        match="too_many_rows.csv.*数据行数为 3.*允许上限 2 行",
    ):
        load_returns_csv(csv_text)


@pytest.mark.parametrize(
    ("module", "render_name", "entry_name"),
    [
        (ui_single, "_render_single_page", "render_single_page"),
        (ui_comparison, "_render_comparison_page", "render_comparison_page"),
    ],
)
def test_unexpected_page_errors_use_controlled_message(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    render_name: str,
    entry_name: str,
) -> None:
    messages: list[str] = []

    def raise_unexpected_error() -> None:
        raise RuntimeError("internal details")

    monkeypatch.setattr(module, render_name, raise_unexpected_error)
    monkeypatch.setattr(module.st, "error", messages.append)

    getattr(module, entry_name)()

    assert messages == [module.UNEXPECTED_ERROR_MESSAGE]
    assert "internal details" not in messages[0]
