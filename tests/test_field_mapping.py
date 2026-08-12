"""Tests for the user-confirmed generic field-mapping boundary."""

from dataclasses import fields

import pandas as pd
import pytest

import src.field_mapping as field_mapping_module
from src.field_detection import (
    ROLE_ORDER,
    ColumnProfile,
    DetectionResult,
    FieldCandidate,
    FieldSuggestion,
)
from src.field_mapping import (
    PRIMARY_BASIS_NAV,
    PRIMARY_BASIS_RETURN,
    ConfirmedMapping,
    MappingDraft,
    MappingImportIssues,
    build_mapping_source_key,
    build_suggested_mapping,
    confirm_mapping,
    is_confirmed_mapping_current,
    update_mapping_draft,
    validate_mapping,
)


def _confidence(score: int) -> str:
    if score >= 85:
        return "高置信度"
    if score >= 65:
        return "中置信度"
    if score >= 45:
        return "低置信度"
    return "未识别"


def _candidate(
    column_name: str,
    score: int,
    *,
    warnings: tuple[str, ...] = (),
) -> FieldCandidate:
    return FieldCandidate(
        column_name=column_name,
        score=score,
        confidence=_confidence(score),
        reasons=("测试规则证据",),
        warnings=warnings,
    )


def _profile(
    column_name: str,
    *,
    non_null_count: int = 3,
    numeric_ratio: float = 1.0,
    date_parse_ratio: float = 0.0,
) -> ColumnProfile:
    return ColumnProfile(
        column_name=column_name,
        normalized_name=column_name.strip().lower(),
        dtype="object",
        non_null_count=non_null_count,
        non_null_ratio=1.0 if non_null_count else 0.0,
        unique_count=non_null_count,
        unique_ratio=1.0 if non_null_count else 0.0,
        numeric_ratio=numeric_ratio,
        date_parse_ratio=date_parse_ratio,
        all_finite_numeric=True,
        numeric_min=0.0 if non_null_count else None,
        numeric_max=1.0 if non_null_count else None,
        positive_ratio=1.0 if non_null_count else 0.0,
        non_positive_ratio=0.0,
        negative_ratio=0.0,
        within_unit_ratio=1.0 if non_null_count else 0.0,
        numeric_abs_gt_one_ratio=0.0,
        monotonic_increasing=True,
        monotonic_decreasing=False,
        mixed_types=False,
        analyzed_count=non_null_count,
    )


def _detection(
    recommendations: dict[str, FieldCandidate] | None = None,
    *,
    alternatives: dict[str, tuple[FieldCandidate, ...]] | None = None,
    empty_columns: tuple[str, ...] = (),
) -> DetectionResult:
    recommendations = recommendations or {}
    alternatives = alternatives or {}
    suggestions: dict[str, FieldSuggestion] = {}
    profiles: dict[str, ColumnProfile] = {}
    for role in ROLE_ORDER:
        recommended = recommendations.get(role)
        role_alternatives = alternatives.get(role, ())
        status = recommended.confidence if recommended else "未识别"
        suggestions[role] = FieldSuggestion(
            role=role,
            recommended=recommended,
            alternatives=role_alternatives,
            status=status,
        )
        for candidate in ((recommended,) if recommended else ()) + role_alternatives:
            profiles.setdefault(candidate.column_name, _profile(candidate.column_name))
    for column_name in empty_columns:
        profiles[column_name] = _profile(column_name, non_null_count=0)
    return DetectionResult(
        suggestions=suggestions,
        column_profiles=profiles,
        global_warnings=(),
        cross_field_checks=0,
    )


def _frame() -> pd.DataFrame:
    returns = pd.Series([0.01, -0.02, 0.03, 0.01])
    nav = (1 + returns).cumprod()
    return pd.DataFrame(
        {
            "trade_date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "strategy_return": returns,
            "strategy_nav": nav,
            "benchmark_return": [0.005, -0.01, 0.02, 0.0],
            "benchmark_nav": (1 + pd.Series([0.005, -0.01, 0.02, 0.0])).cumprod(),
            "drawdown": nav / nav.cummax() - 1,
            "daily_ret": returns,
            "notes": ["a", "b", "c", "d"],
        }
    )


def _draft(
    frame: pd.DataFrame,
    *,
    basis: str | None = PRIMARY_BASIS_RETURN,
    choices: dict[str, str | None] | None = None,
    acknowledged: bool = True,
    recommended: dict[str, str | None] | None = None,
    scores: dict[str, dict[str, int]] | None = None,
) -> MappingDraft:
    role_to_column = {role: None for role in ROLE_ORDER}
    role_to_column.update(choices or {"date": "trade_date", "strategy_return": "strategy_return"})
    return MappingDraft(
        source_key="source-key",
        primary_basis=basis,
        role_to_column=role_to_column,
        recommended_by_role=recommended or {role: None for role in ROLE_ORDER},
        candidate_scores=scores or {role: {} for role in ROLE_ORDER},
        confirmation_acknowledged=acknowledged,
    )


def _profiles(frame: pd.DataFrame) -> dict[str, ColumnProfile]:
    return {
        str(column): _profile(str(column), non_null_count=int(frame[column].notna().sum()))
        for column in frame.columns
    }


def _validate(
    frame: pd.DataFrame,
    draft: MappingDraft,
    *,
    issues: MappingImportIssues | None = None,
):
    return validate_mapping(
        frame,
        draft,
        _profiles(frame),
        issues or MappingImportIssues(),
    )


def test_numeric_sample_preserves_non_default_index_and_position_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(field_mapping_module, "MAX_PROFILE_SAMPLE_SIZE", 4)
    series = pd.Series(
        [10, 20, 30, 40, 50, 60],
        index=[100, 90, 80, 70, 60, 50],
    )

    sample = field_mapping_module._numeric_sample(series)

    assert sample.index.tolist() == [100, 90, 70, 50]
    assert sample.tolist() == [10, 20, 40, 60]


def test_high_confidence_conflict_free_candidate_is_prefilled() -> None:
    detection = _detection({"date": _candidate("trade_date", 95)})

    draft = build_suggested_mapping(["trade_date"], detection)

    assert draft.role_to_column["date"] == "trade_date"


@pytest.mark.parametrize("score", [84, 64])
def test_non_high_confidence_candidate_is_not_prefilled(score: int) -> None:
    detection = _detection({"strategy_return": _candidate("return", score)})

    draft = build_suggested_mapping(["return"], detection)

    assert draft.role_to_column["strategy_return"] is None


def test_close_candidates_are_not_prefilled() -> None:
    warning = "strategy_return 存在多个相近候选：建议人工确认。"
    detection = _detection(
        {"strategy_return": _candidate("return_a", 90, warnings=(warning,))},
        alternatives={"strategy_return": (_candidate("return_b", 88),)},
    )

    draft = build_suggested_mapping(["return_a", "return_b"], detection)

    assert draft.role_to_column["strategy_return"] is None


def test_role_conflict_is_not_prefilled() -> None:
    warning = "字段“return”同时成为多个角色的首选候选。"
    detection = _detection({"strategy_return": _candidate("return", 95, warnings=(warning,))})

    draft = build_suggested_mapping(["return"], detection)

    assert draft.role_to_column["strategy_return"] is None


def test_fully_empty_high_candidate_is_not_prefilled() -> None:
    detection = _detection(
        {"strategy_return": _candidate("empty", 95)},
        empty_columns=("empty",),
    )

    draft = build_suggested_mapping(["empty"], detection)

    assert draft.role_to_column["strategy_return"] is None


def test_only_high_strategy_return_suggests_return_basis() -> None:
    detection = _detection({"strategy_return": _candidate("strategy_return", 95)})

    draft = build_suggested_mapping(["strategy_return"], detection)

    assert draft.primary_basis == PRIMARY_BASIS_RETURN


def test_only_high_strategy_nav_suggests_nav_basis() -> None:
    detection = _detection({"strategy_nav": _candidate("strategy_nav", 95)})

    draft = build_suggested_mapping(["strategy_nav"], detection)

    assert draft.primary_basis == PRIMARY_BASIS_NAV


def test_two_high_primary_roles_leave_basis_unselected() -> None:
    detection = _detection(
        {
            "strategy_return": _candidate("strategy_return", 95),
            "strategy_nav": _candidate("strategy_nav", 95),
        }
    )

    draft = build_suggested_mapping(["strategy_return", "strategy_nav"], detection)

    assert draft.primary_basis is None


def test_multiple_high_candidates_do_not_suggest_primary_basis() -> None:
    detection = _detection(
        {"strategy_return": _candidate("return_a", 95)},
        alternatives={"strategy_return": (_candidate("return_b", 87),)},
    )

    draft = build_suggested_mapping(["return_a", "return_b"], detection)

    assert draft.primary_basis is None


def test_missing_primary_basis_blocks_confirmation() -> None:
    validation = _validate(_frame(), _draft(_frame(), basis=None))

    assert not validation.is_valid
    assert "请选择策略分析主口径。" in validation.errors


def test_missing_date_blocks_confirmation() -> None:
    frame = _frame()
    draft = _draft(frame, choices={"strategy_return": "strategy_return"})

    validation = _validate(frame, draft)

    assert any("必须映射日期" in error for error in validation.errors)


def test_return_basis_requires_strategy_return() -> None:
    frame = _frame()
    draft = _draft(frame, choices={"date": "trade_date"})

    validation = _validate(frame, draft)

    assert any("收益率主口径" in error for error in validation.errors)


def test_nav_basis_requires_strategy_nav() -> None:
    frame = _frame()
    draft = _draft(
        frame,
        basis=PRIMARY_BASIS_NAV,
        choices={"date": "trade_date"},
    )

    validation = _validate(frame, draft)

    assert any("净值主口径" in error for error in validation.errors)


def test_same_column_cannot_fill_multiple_roles() -> None:
    frame = _frame()
    draft = _draft(
        frame,
        choices={
            "date": "trade_date",
            "strategy_return": "strategy_return",
            "daily_ret": "strategy_return",
        },
    )

    validation = _validate(frame, draft)

    assert any("被映射到多个角色" in error for error in validation.errors)


def test_missing_selected_column_blocks_confirmation() -> None:
    frame = _frame()
    draft = _draft(
        frame,
        choices={"date": "trade_date", "strategy_return": "missing"},
    )

    validation = _validate(frame, draft)

    assert any("不在当前表格中" in error for error in validation.errors)


def test_fully_empty_required_column_blocks_confirmation() -> None:
    frame = _frame().assign(empty=None)
    draft = _draft(
        frame,
        choices={"date": "trade_date", "strategy_return": "empty"},
    )

    validation = _validate(frame, draft)

    assert any("完全为空" in error for error in validation.errors)


def test_unparseable_date_blocks_confirmation() -> None:
    frame = _frame().assign(bad_date=["x", "y", "z", "q"])
    draft = _draft(
        frame,
        choices={"date": "bad_date", "strategy_return": "strategy_return"},
    )

    validation = _validate(frame, draft)

    assert any("没有任何可解析日期值" in error for error in validation.errors)


def test_non_numeric_role_blocks_confirmation() -> None:
    frame = _frame()
    draft = _draft(
        frame,
        choices={"date": "trade_date", "strategy_return": "notes"},
    )

    validation = _validate(frame, draft)

    assert any("没有任何可转换数值" in error for error in validation.errors)


def test_partially_unparseable_date_warns() -> None:
    frame = _frame().assign(mixed_date=["2026-01-01", "bad", "2026-01-03", None])
    draft = _draft(
        frame,
        choices={"date": "mixed_date", "strategy_return": "strategy_return"},
    )

    validation = _validate(frame, draft)

    assert validation.is_valid
    assert any("日期字段" in warning and "无法解析" in warning for warning in validation.warnings)


def test_partially_non_numeric_value_warns() -> None:
    frame = _frame().assign(mixed_return=[0.1, "bad", -0.1, None])
    draft = _draft(
        frame,
        choices={"date": "trade_date", "strategy_return": "mixed_return"},
    )

    validation = _validate(frame, draft)

    assert validation.is_valid
    assert any("无法转换" in warning for warning in validation.warnings)


def test_large_return_values_warn_without_conversion() -> None:
    frame = _frame().assign(percent_return=[2.0, -3.0, 1.5, 0.5])
    before = frame.copy(deep=True)
    draft = _draft(
        frame,
        choices={"date": "trade_date", "strategy_return": "percent_return"},
    )

    validation = _validate(frame, draft)

    assert any("百分数单位风险" in warning for warning in validation.warnings)
    pd.testing.assert_frame_equal(frame, before)


def test_all_positive_return_values_warn() -> None:
    frame = _frame().assign(positive_return=[0.01, 0.02, 0.03, 0.04])
    draft = _draft(
        frame,
        choices={"date": "trade_date", "strategy_return": "positive_return"},
    )

    validation = _validate(frame, draft)

    assert any("全部为正" in warning for warning in validation.warnings)


def test_non_positive_nav_values_warn() -> None:
    frame = _frame().assign(bad_nav=[1.0, 0.0, -0.1, 1.1])
    draft = _draft(
        frame,
        basis=PRIMARY_BASIS_NAV,
        choices={"date": "trade_date", "strategy_nav": "bad_nav"},
    )

    validation = _validate(frame, draft)

    assert validation.is_valid
    assert any("包含非正数" in warning for warning in validation.warnings)


def test_low_confidence_selected_candidate_warns() -> None:
    frame = _frame()
    draft = _draft(
        frame,
        scores={
            **{role: {} for role in ROLE_ORDER},
            "strategy_return": {"strategy_return": 55},
        },
    )

    validation = _validate(frame, draft)

    assert any("B.2 低置信度" in warning for warning in validation.warnings)


def test_deviation_from_b2_preference_warns() -> None:
    frame = _frame()
    draft = _draft(
        frame,
        recommended={
            **{role: None for role in ROLE_ORDER},
            "strategy_return": "daily_ret",
        },
    )

    validation = _validate(frame, draft)

    assert any("与 B.2 首选建议" in warning for warning in validation.warnings)


def test_mapping_both_return_and_nav_preserves_explicit_basis() -> None:
    frame = _frame()
    draft = _draft(
        frame,
        choices={
            "date": "trade_date",
            "strategy_return": "strategy_return",
            "strategy_nav": "strategy_nav",
        },
    )

    validation = _validate(frame, draft)
    confirmed = confirm_mapping(draft, validation)

    assert confirmed.primary_basis == PRIMARY_BASIS_RETURN
    assert any("明确以策略收益率为主口径" in warning for warning in validation.warnings)


def test_validation_and_confirmation_do_not_modify_dataframe() -> None:
    frame = _frame()
    before = frame.copy(deep=True)
    draft = _draft(frame)

    validation = _validate(frame, draft)
    confirm_mapping(draft, validation)

    pd.testing.assert_frame_equal(frame, before)


def test_confirmed_mapping_only_stores_references_and_metadata() -> None:
    frame = _frame()
    draft = _draft(frame)

    confirmed = confirm_mapping(draft, _validate(frame, draft))

    assert {field.name for field in fields(ConfirmedMapping)} == {
        "source_key",
        "primary_basis",
        "role_to_column",
        "warnings",
    }
    assert not any(isinstance(value, pd.DataFrame) for value in confirmed.__dict__.values())


def _source_key(**overrides: object) -> str:
    arguments: dict[str, object] = {
        "content": b"date,return\n2026-01-01,0.01\n",
        "file_type": "CSV",
        "sheet_name": None,
        "encoding": "utf-8",
        "delimiter": ",",
        "header_rule": "first_row",
        "columns": ("date", "return"),
    }
    arguments.update(overrides)
    return build_mapping_source_key(**arguments)  # type: ignore[arg-type]


def test_same_source_builds_same_source_key() -> None:
    assert _source_key() == _source_key()


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": b"date,return\n2026-01-01,0.02\n"},
        {"sheet_name": "Sheet2", "file_type": "XLSX"},
        {"delimiter": ";"},
        {"encoding": "gb18030"},
        {"columns": ("return", "date")},
    ],
)
def test_source_key_changes_with_source_or_parse_settings(
    overrides: dict[str, object],
) -> None:
    assert _source_key() != _source_key(**overrides)


def test_source_key_does_not_contain_file_content_or_path() -> None:
    source_key = _source_key()

    assert "2026-01-01" not in source_key
    assert "Rayne" not in source_key
    assert len(source_key) == 64


def test_source_key_change_invalidates_old_confirmation() -> None:
    frame = _frame()
    draft = _draft(frame)
    confirmed = confirm_mapping(draft, _validate(frame, draft))

    assert is_confirmed_mapping_current(confirmed, "source-key")
    assert not is_confirmed_mapping_current(confirmed, "different-source")


def test_unchecked_confirmation_statement_blocks_confirmation() -> None:
    frame = _frame()
    draft = _draft(frame, acknowledged=False)

    validation = _validate(frame, draft)

    assert not validation.is_valid
    assert any("确认声明" in error for error in validation.errors)
    with pytest.raises(ValueError, match="验证未通过"):
        confirm_mapping(draft, validation)


def test_valid_return_basis_mapping_confirms() -> None:
    frame = _frame()
    draft = _draft(frame)

    confirmed = confirm_mapping(draft, _validate(frame, draft))

    assert confirmed.role_to_column["date"] == "trade_date"
    assert confirmed.role_to_column["strategy_return"] == "strategy_return"


def test_valid_nav_basis_mapping_confirms() -> None:
    frame = _frame()
    draft = _draft(
        frame,
        basis=PRIMARY_BASIS_NAV,
        choices={"date": "trade_date", "strategy_nav": "strategy_nav"},
    )

    confirmed = confirm_mapping(draft, _validate(frame, draft))

    assert confirmed.primary_basis == PRIMARY_BASIS_NAV


def test_optional_roles_can_remain_unmapped() -> None:
    frame = _frame()
    draft = _draft(frame)

    validation = _validate(frame, draft)

    assert validation.is_valid
    assert draft.role_to_column["benchmark_return"] is None


def test_raw_duplicate_headers_block_confirmation() -> None:
    frame = _frame()
    validation = _validate(
        frame,
        _draft(frame),
        issues=MappingImportIssues(duplicate_column_names=("return",)),
    )

    assert any("重复字段名" in error for error in validation.errors)


def test_empty_field_name_blocks_confirmation() -> None:
    frame = _frame().copy()
    frame[""] = frame["strategy_return"]
    draft = _draft(
        frame,
        choices={"date": "trade_date", "strategy_return": ""},
    )

    validation = _validate(frame, draft)

    assert any("必须映射策略收益率" in error or "空字段名" in error for error in validation.errors)


def test_unnamed_required_header_blocks_confirmation() -> None:
    frame = _frame().rename(columns={"trade_date": "Unnamed: 0"})
    draft = _draft(
        frame,
        choices={"date": "Unnamed: 0", "strategy_return": "strategy_return"},
    )

    validation = _validate(
        frame,
        draft,
        issues=MappingImportIssues(unnamed_columns=("Unnamed: 0",)),
    )

    assert any("自动生成的空表头" in error for error in validation.errors)


def test_whitespace_field_name_warns() -> None:
    frame = _frame().rename(columns={"trade_date": " trade_date "})
    draft = _draft(
        frame,
        choices={"date": " trade_date ", "strategy_return": "strategy_return"},
    )

    validation = _validate(frame, draft)

    assert any("首尾包含空格" in warning for warning in validation.warnings)


def test_inconsistent_strategy_nav_and_return_warn() -> None:
    frame = _frame().assign(strategy_nav=[1.0, 2.0, 1.0, 2.0])
    draft = _draft(
        frame,
        choices={
            "date": "trade_date",
            "strategy_return": "strategy_return",
            "strategy_nav": "strategy_nav",
        },
    )

    validation = _validate(frame, draft)

    assert any("推导收益存在明显差异" in warning for warning in validation.warnings)


def test_inconsistent_benchmark_nav_and_return_warn() -> None:
    frame = _frame().assign(benchmark_nav=[1.0, 2.0, 1.0, 2.0])
    draft = _draft(
        frame,
        choices={
            "date": "trade_date",
            "strategy_return": "strategy_return",
            "benchmark_return": "benchmark_return",
            "benchmark_nav": "benchmark_nav",
        },
    )

    validation = _validate(frame, draft)

    assert any("基准收益率与基准净值" in warning for warning in validation.warnings)


def test_inconsistent_drawdown_and_nav_warn() -> None:
    frame = _frame().assign(drawdown=[0.0, -0.5, -0.5, -0.5])
    draft = _draft(
        frame,
        choices={
            "date": "trade_date",
            "strategy_return": "strategy_return",
            "strategy_nav": "strategy_nav",
            "drawdown": "drawdown",
        },
    )

    validation = _validate(frame, draft)

    assert any("回撤序列与策略净值" in warning for warning in validation.warnings)


def test_confirmation_does_not_call_performance_or_reporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.performance as performance
    import src.reporting as reporting

    def _unexpected_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("通用字段确认不得调用分析或报告模块")

    monkeypatch.setattr(performance, "calculate_performance_metrics", _unexpected_call)
    monkeypatch.setattr(reporting, "generate_markdown_report", _unexpected_call)
    frame = _frame()
    draft = _draft(frame)

    confirmed = confirm_mapping(draft, _validate(frame, draft))

    assert confirmed.source_key == "source-key"


def test_same_mapping_input_is_deterministic() -> None:
    frame = _frame()
    draft = _draft(frame)

    first = _validate(frame, draft)
    second = _validate(frame, draft)

    assert first == second


def test_update_mapping_draft_keeps_b2_evidence_read_only() -> None:
    detection = _detection({"date": _candidate("trade_date", 95)})
    suggested = build_suggested_mapping(["trade_date"], detection, source_key="abc")

    edited = update_mapping_draft(
        suggested,
        primary_basis=PRIMARY_BASIS_RETURN,
        role_to_column={"date": "trade_date"},
        confirmation_acknowledged=True,
    )

    assert edited.source_key == "abc"
    assert edited.recommended_by_role == suggested.recommended_by_role
    assert edited.role_to_column["strategy_return"] is None
