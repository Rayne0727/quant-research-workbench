"""User-confirmed field mappings for generic CSV/XLSX imports.

This module keeps mapping suggestions, validation, and confirmation separate
from normalization and performance analysis.  Every function is deterministic
and treats the source DataFrame as read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from types import MappingProxyType
from typing import Final, Mapping, Sequence

import pandas as pd

from src.field_detection import (
    MAX_PROFILE_SAMPLE_SIZE,
    ROLE_ORDER,
    ColumnProfile,
    DetectionResult,
    FieldCandidate,
)


PRIMARY_BASIS_RETURN: Final = "strategy_return"
PRIMARY_BASIS_NAV: Final = "strategy_nav"
PRIMARY_BASIS_OPTIONS: Final = (PRIMARY_BASIS_RETURN, PRIMARY_BASIS_NAV)
HIGH_CONFIDENCE_SCORE: Final = 85

NUMERIC_ROLES: Final = {
    "strategy_return",
    "strategy_nav",
    "benchmark_return",
    "benchmark_nav",
    "drawdown",
    "daily_ret",
}
RETURN_ROLES: Final = {
    "strategy_return",
    "benchmark_return",
    "daily_ret",
}
NAV_ROLES: Final = {"strategy_nav", "benchmark_nav"}


@dataclass(frozen=True)
class MappingImportIssues:
    """Header issues retained from the generic import layer."""

    duplicate_column_names: tuple[str, ...] = ()
    empty_column_names: tuple[str, ...] = ()
    whitespace_column_names: tuple[str, ...] = ()
    unnamed_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class MappingDraft:
    """Editable mapping choices plus read-only B.2 evidence."""

    source_key: str
    primary_basis: str | None
    role_to_column: Mapping[str, str | None]
    recommended_by_role: Mapping[str, str | None]
    candidate_scores: Mapping[str, Mapping[str, int]]
    confirmation_acknowledged: bool = False


@dataclass(frozen=True)
class MappingValidation:
    """Blocking errors and non-blocking warnings for a mapping draft."""

    is_valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ConfirmedMapping:
    """Confirmed field references only; no transformed data is stored."""

    source_key: str
    primary_basis: str
    role_to_column: Mapping[str, str | None]
    warnings: tuple[str, ...]


def _freeze_mapping(
    values: Mapping[str, str | None],
) -> Mapping[str, str | None]:
    return MappingProxyType(dict(values))


def _freeze_scores(
    values: Mapping[str, Mapping[str, int]],
) -> Mapping[str, Mapping[str, int]]:
    return MappingProxyType(
        {
            role: MappingProxyType(dict(scores))
            for role, scores in values.items()
        }
    )


def build_mapping_source_key(
    *,
    content: bytes | None = None,
    content_digest: str | None = None,
    file_type: str,
    sheet_name: str | None,
    encoding: str | None,
    delimiter: str | None,
    header_rule: str,
    columns: Sequence[object],
) -> str:
    """Build a SHA-256 source identity without paths or source row values."""

    if content_digest is None:
        if content is None:
            raise ValueError("content 和 content_digest 至少需要提供一项")
        content_digest = hashlib.sha256(content).hexdigest()
    normalized_digest = str(content_digest).strip().lower()
    if not normalized_digest:
        raise ValueError("content_digest 不能为空")

    source_metadata = {
        "content_sha256": normalized_digest,
        "file_type": str(file_type).upper(),
        "sheet_name": sheet_name or "",
        "encoding": encoding or "",
        "delimiter": delimiter or "",
        "header_rule": str(header_rule),
        "columns": [str(column) for column in columns],
    }
    serialized = json.dumps(
        source_metadata,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _all_candidates(detection_result: DetectionResult, role: str) -> tuple[FieldCandidate, ...]:
    suggestion = detection_result.suggestions[role]
    candidates: list[FieldCandidate] = []
    if suggestion.recommended is not None:
        candidates.append(suggestion.recommended)
    candidates.extend(suggestion.alternatives)
    return tuple(candidates)


def _has_close_candidate(candidate: FieldCandidate) -> bool:
    return any("多个相近候选" in warning for warning in candidate.warnings)


def _has_role_conflict(candidate: FieldCandidate) -> bool:
    return any("同时成为多个角色" in warning for warning in candidate.warnings)


def _eligible_for_prefill(
    role: str,
    detection_result: DetectionResult,
    valid_columns: set[str],
) -> bool:
    suggestion = detection_result.suggestions[role]
    candidate = suggestion.recommended
    if candidate is None:
        return False
    profile = detection_result.column_profiles.get(candidate.column_name)
    return bool(
        candidate.column_name in valid_columns
        and candidate.column_name.strip()
        and candidate.score >= HIGH_CONFIDENCE_SCORE
        and candidate.confidence == "高置信度"
        and suggestion.status == "高置信度"
        and not _has_close_candidate(candidate)
        and not _has_role_conflict(candidate)
        and profile is not None
        and profile.non_null_count > 0
    )


def _has_unique_high_candidate(
    role: str,
    detection_result: DetectionResult,
    valid_columns: set[str],
) -> bool:
    if not _eligible_for_prefill(role, detection_result, valid_columns):
        return False
    high_candidates = [
        candidate
        for candidate in _all_candidates(detection_result, role)
        if candidate.column_name in valid_columns
        and candidate.score >= HIGH_CONFIDENCE_SCORE
        and candidate.confidence == "高置信度"
    ]
    return len(high_candidates) == 1


def build_suggested_mapping(
    columns: Sequence[object],
    detection_result: DetectionResult,
    *,
    source_key: str = "",
) -> MappingDraft:
    """Prefill only unambiguous, conflict-free high-confidence suggestions."""

    ordered_columns = tuple(str(column) for column in columns)
    valid_columns = set(ordered_columns)
    role_to_column: dict[str, str | None] = {
        role: None for role in ROLE_ORDER
    }
    recommended_by_role: dict[str, str | None] = {}
    candidate_scores: dict[str, dict[str, int]] = {}
    reserved_columns: set[str] = set()

    for role in ROLE_ORDER:
        suggestion = detection_result.suggestions[role]
        recommended = suggestion.recommended
        recommended_by_role[role] = (
            recommended.column_name if recommended is not None else None
        )
        candidate_scores[role] = {
            candidate.column_name: candidate.score
            for candidate in _all_candidates(detection_result, role)
        }
        if not _eligible_for_prefill(role, detection_result, valid_columns):
            continue
        assert recommended is not None
        if recommended.column_name in reserved_columns:
            continue
        role_to_column[role] = recommended.column_name
        reserved_columns.add(recommended.column_name)

    return_is_unique = _has_unique_high_candidate(
        "strategy_return", detection_result, valid_columns
    )
    nav_is_unique = _has_unique_high_candidate(
        "strategy_nav", detection_result, valid_columns
    )
    primary_basis: str | None = None
    if return_is_unique and not nav_is_unique:
        primary_basis = PRIMARY_BASIS_RETURN
    elif nav_is_unique and not return_is_unique:
        primary_basis = PRIMARY_BASIS_NAV

    return MappingDraft(
        source_key=source_key,
        primary_basis=primary_basis,
        role_to_column=_freeze_mapping(role_to_column),
        recommended_by_role=_freeze_mapping(recommended_by_role),
        candidate_scores=_freeze_scores(candidate_scores),
    )


def update_mapping_draft(
    suggested_draft: MappingDraft,
    *,
    primary_basis: str | None,
    role_to_column: Mapping[str, str | None],
    confirmation_acknowledged: bool,
) -> MappingDraft:
    """Create a user-edited draft without mutating the original suggestion."""

    choices = {
        role: role_to_column.get(role)
        for role in ROLE_ORDER
    }
    return MappingDraft(
        source_key=suggested_draft.source_key,
        primary_basis=primary_basis,
        role_to_column=_freeze_mapping(choices),
        recommended_by_role=suggested_draft.recommended_by_role,
        candidate_scores=suggested_draft.candidate_scores,
        confirmation_acknowledged=confirmation_acknowledged,
    )


def _required_roles(primary_basis: str | None) -> tuple[str, ...]:
    if primary_basis == PRIMARY_BASIS_RETURN:
        return ("date", "strategy_return")
    if primary_basis == PRIMARY_BASIS_NAV:
        return ("date", "strategy_nav")
    return ("date",)


def _column_series(dataframe: pd.DataFrame, column_name: str) -> pd.Series | None:
    positions = [
        position
        for position, current_name in enumerate(dataframe.columns)
        if str(current_name) == column_name
    ]
    if len(positions) != 1:
        return None
    return dataframe.iloc[:, positions[0]]


def _numeric_sample(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    numeric = numeric[numeric.map(lambda value: math.isfinite(float(value)))]
    if len(numeric) <= MAX_PROFILE_SAMPLE_SIZE:
        return numeric
    positions = [
        (index * (len(numeric) - 1)) // (MAX_PROFILE_SAMPLE_SIZE - 1)
        for index in range(MAX_PROFILE_SAMPLE_SIZE)
    ]
    return numeric.iloc[positions]


def _agreement_ratio(left: pd.Series, right: pd.Series) -> tuple[float, int]:
    paired = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(paired) > MAX_PROFILE_SAMPLE_SIZE:
        paired = paired.iloc[:MAX_PROFILE_SAMPLE_SIZE]
    if paired.empty:
        return 0.0, 0
    matches = 0
    for left_value, right_value in paired.itertuples(index=False, name=None):
        tolerance = 1e-6 + 1e-4 * max(abs(float(left_value)), abs(float(right_value)))
        if abs(float(left_value) - float(right_value)) <= tolerance:
            matches += 1
    return matches / len(paired), len(paired)


def _cross_field_warnings(
    dataframe: pd.DataFrame,
    role_to_column: Mapping[str, str | None],
) -> list[str]:
    warnings: list[str] = []
    pairs = (
        ("strategy_nav", "strategy_return", "策略"),
        ("benchmark_nav", "benchmark_return", "基准"),
    )
    for nav_role, return_role, label in pairs:
        nav_name = role_to_column.get(nav_role)
        return_name = role_to_column.get(return_role)
        if not nav_name or not return_name:
            continue
        nav_source = _column_series(dataframe, nav_name)
        return_source = _column_series(dataframe, return_name)
        if nav_source is None or return_source is None:
            continue
        nav = pd.to_numeric(nav_source, errors="coerce")
        observed_return = pd.to_numeric(return_source, errors="coerce")
        agreement, count = _agreement_ratio(
            nav.pct_change(fill_method=None), observed_return
        )
        if count >= 3 and agreement < 0.5:
            warnings.append(
                f"{label}收益率与{label}净值推导收益存在明显差异，请人工核对口径和单位。"
            )

    nav_name = role_to_column.get("strategy_nav")
    drawdown_name = role_to_column.get("drawdown")
    if nav_name and drawdown_name:
        nav_source = _column_series(dataframe, nav_name)
        drawdown_source = _column_series(dataframe, drawdown_name)
        if nav_source is not None and drawdown_source is not None:
            nav = pd.to_numeric(nav_source, errors="coerce")
            observed_drawdown = pd.to_numeric(drawdown_source, errors="coerce")
            agreement, count = _agreement_ratio(
                nav / nav.cummax() - 1,
                observed_drawdown,
            )
            if count >= 3 and agreement < 0.5:
                warnings.append(
                    "回撤序列与策略净值推导结果存在明显差异，请人工核对定义。"
                )
    return warnings


def validate_mapping(
    dataframe: pd.DataFrame,
    mapping_draft: MappingDraft,
    column_profiles: Mapping[str, ColumnProfile],
    import_issues: MappingImportIssues,
) -> MappingValidation:
    """Validate a draft without renaming, converting, or mutating source data."""

    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("dataframe 必须是 pandas.DataFrame")

    errors: list[str] = []
    warnings: list[str] = []
    basis = mapping_draft.primary_basis
    if basis not in PRIMARY_BASIS_OPTIONS:
        errors.append("请选择策略分析主口径。")

    if import_issues.duplicate_column_names:
        duplicate_names = "、".join(
            name or "（空字段名）"
            for name in import_issues.duplicate_column_names
        )
        errors.append(
            f"原始文件存在无法可靠区分的重复字段名：{duplicate_names}。"
        )

    dataframe_names = tuple(str(column) for column in dataframe.columns)
    duplicate_dataframe_names = sorted(
        {name for name in dataframe_names if dataframe_names.count(name) > 1}
    )
    if duplicate_dataframe_names:
        errors.append(
            "当前读取结果仍包含重复字段名："
            f"{'、'.join(duplicate_dataframe_names)}。"
        )

    required_roles = _required_roles(basis)
    for role in required_roles:
        if not mapping_draft.role_to_column.get(role):
            if role == "date":
                errors.append("必须映射日期字段 date。")
            elif role == "strategy_return":
                errors.append("收益率主口径必须映射策略收益率 strategy_return。")
            else:
                errors.append("净值主口径必须映射策略净值 strategy_nav。")

    selected_by_column: dict[str, list[str]] = {}
    selected_series: dict[str, pd.Series] = {}
    for role in ROLE_ORDER:
        column_name = mapping_draft.role_to_column.get(role)
        if column_name is None:
            continue
        if not str(column_name).strip():
            errors.append(f"{role} 选择了空字段名，不能建立映射。")
            continue
        selected_by_column.setdefault(column_name, []).append(role)
        series = _column_series(dataframe, column_name)
        if series is None:
            errors.append(f"{role} 选择的字段“{column_name}”不在当前表格中。")
            continue
        selected_series[role] = series
        profile = column_profiles.get(column_name)
        if series.isna().all() or (
            profile is not None and profile.non_null_count == 0
        ):
            errors.append(f"{role} 选择的字段“{column_name}”完全为空。")
        if column_name != column_name.strip():
            warnings.append(f"字段“{column_name}”首尾包含空格，请人工核对。")
        if column_name in import_issues.unnamed_columns or column_name.startswith("Unnamed:"):
            if role in required_roles:
                errors.append(
                    f"必需角色 {role} 不能使用自动生成的空表头字段“{column_name}”。"
                )
            else:
                warnings.append(
                    f"{role} 使用了自动生成的 Unnamed 字段“{column_name}”。"
                )

    for column_name, roles in selected_by_column.items():
        if len(roles) > 1:
            errors.append(
                f"原始字段“{column_name}”被映射到多个角色："
                f"{', '.join(roles)}。"
            )

    for role, series in selected_series.items():
        column_name = mapping_draft.role_to_column[role]
        non_null = series.dropna()
        score = mapping_draft.candidate_scores.get(role, {}).get(column_name)
        if score is not None and 45 <= score < 65:
            warnings.append(
                f"{role} 选择了 B.2 低置信度候选“{column_name}”（{score} 分）。"
            )
        recommended = mapping_draft.recommended_by_role.get(role)
        if recommended is not None and column_name != recommended:
            warnings.append(
                f"{role} 选择的“{column_name}”与 B.2 首选建议“{recommended}”不同。"
            )
        if role == "date":
            parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
            valid_count = int(parsed.notna().sum())
            if valid_count == 0:
                errors.append(f"日期字段“{column_name}”没有任何可解析日期值。")
            elif valid_count < len(non_null):
                warnings.append(
                    f"日期字段“{column_name}”存在无法解析的值。"
                )
            continue

        if role not in NUMERIC_ROLES:
            continue
        numeric = pd.to_numeric(non_null, errors="coerce")
        valid_count = int(numeric.notna().sum())
        if valid_count == 0:
            errors.append(f"数值角色 {role} 的字段“{column_name}”没有任何可转换数值。")
            continue
        if valid_count < len(non_null):
            warnings.append(
                f"数值字段“{column_name}”存在无法转换的值。"
            )
        finite = _numeric_sample(series)
        if role in RETURN_ROLES and not finite.empty:
            large_ratio = float((finite.abs() > 1).mean())
            if large_ratio >= 0.2:
                warnings.append(
                    f"收益字段“{column_name}”较多值绝对值大于 1，"
                    "可能存在百分数单位风险；系统不会自动换算。"
                )
            if bool((finite > 0).all()):
                warnings.append(
                    f"收益字段“{column_name}”全部为正，请确认业务含义。"
                )
        if role in NAV_ROLES and not finite.empty and bool((finite <= 0).any()):
            warnings.append(
                f"净值字段“{column_name}”包含非正数，请确认数据定义。"
            )

    if (
        mapping_draft.role_to_column.get("strategy_return")
        and mapping_draft.role_to_column.get("strategy_nav")
        and basis in PRIMARY_BASIS_OPTIONS
    ):
        basis_label = "策略收益率" if basis == PRIMARY_BASIS_RETURN else "策略净值"
        warnings.append(
            f"同时映射了策略收益率和策略净值；当前明确以{basis_label}为主口径，"
            "另一字段仅用于后续一致性检查。"
        )

    warnings.extend(_cross_field_warnings(dataframe, mapping_draft.role_to_column))

    if not mapping_draft.confirmation_acknowledged:
        errors.append("请勾选字段含义与处理边界确认声明。")

    return MappingValidation(
        is_valid=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def confirm_mapping(
    mapping_draft: MappingDraft,
    validation: MappingValidation,
) -> ConfirmedMapping:
    """Create a confirmed reference mapping only after successful validation."""

    if not validation.is_valid:
        raise ValueError("字段映射验证未通过，不能确认。")
    if mapping_draft.primary_basis not in PRIMARY_BASIS_OPTIONS:
        raise ValueError("策略分析主口径无效，不能确认。")
    return ConfirmedMapping(
        source_key=mapping_draft.source_key,
        primary_basis=mapping_draft.primary_basis,
        role_to_column=_freeze_mapping(mapping_draft.role_to_column),
        warnings=validation.warnings,
    )


def is_confirmed_mapping_current(
    confirmed_mapping: ConfirmedMapping | None,
    source_key: str,
) -> bool:
    """Return whether a session-only confirmation belongs to this source."""

    return bool(
        confirmed_mapping is not None
        and confirmed_mapping.source_key == source_key
    )
