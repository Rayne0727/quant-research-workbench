"""Deterministic field suggestions for generic CSV/XLSX previews.

The rules in this module are intentionally conservative. They inspect column
names and bounded samples, but never rename columns, mutate the input frame, or
turn a suggestion into an established field mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
import unicodedata
from typing import Final, Mapping

import pandas as pd


MAX_PROFILE_SAMPLE_SIZE: Final = 10_000
MAX_CROSS_FIELD_CHECKS: Final = 3
MIN_RECOMMENDATION_SCORE: Final = 45
CLOSE_SCORE_GAP: Final = 5

ROLE_ORDER: Final = (
    "date",
    "strategy_return",
    "strategy_nav",
    "benchmark_return",
    "benchmark_nav",
    "drawdown",
    "daily_ret",
)

ROLE_LABELS: Final = {
    "date": "日期",
    "strategy_return": "策略收益率",
    "strategy_nav": "策略净值",
    "benchmark_return": "基准收益率",
    "benchmark_nav": "基准净值",
    "drawdown": "逐日回撤",
    "daily_ret": "原始日收益率",
}

_ROLE_ALIASES: Final[dict[str, dict[str, int]]] = {
    "date": {
        "date": 65,
        "trade_date": 70,
        "trading_date": 70,
        "datetime": 60,
        "timestamp": 60,
        "time": 50,
        "日期": 70,
        "交易日期": 70,
        "交易日": 70,
        "时间": 50,
        "日期时间": 65,
    },
    "strategy_return": {
        "strategy_return": 70,
        "strategy_ret": 70,
        "portfolio_return": 70,
        "portfolio_ret": 70,
        "daily_return": 55,
        "return": 40,
        "ret": 40,
        "策略收益率": 70,
        "策略收益": 65,
        "组合收益率": 70,
        "组合收益": 65,
        "日收益": 60,
        "日收益率": 60,
        "当日收益": 60,
    },
    "strategy_nav": {
        "strategy_nav": 70,
        "nav_strat": 70,
        "portfolio_nav": 70,
        "cumulative_nav": 70,
        "net_value": 65,
        "netvalue": 65,
        "nav": 45,
        "equity": 55,
        "策略净值": 70,
        "组合净值": 70,
        "单位净值": 65,
        "累计净值": 70,
        "权益曲线": 65,
        "净值": 55,
    },
    "benchmark_return": {
        "benchmark_return": 70,
        "benchmark_ret": 70,
        "index_return": 70,
        "index_ret": 70,
        "market_return": 70,
        "基准收益率": 70,
        "基准收益": 65,
        "指数收益率": 70,
        "指数收益": 65,
        "市场收益": 65,
    },
    "benchmark_nav": {
        "benchmark_nav": 70,
        "benchmark_value": 70,
        "benchmark_net_value": 70,
        "index_nav": 70,
        "index_net_value": 70,
        "market_nav": 70,
        "基准净值": 70,
        "指数净值": 70,
        "市场净值": 70,
    },
    "drawdown": {
        "drawdown": 70,
        "drawdown_series": 70,
        "max_drawdown_series": 70,
        "dd": 55,
        "underwater": 65,
        "underwater_curve": 70,
        "回撤": 70,
        "回撤率": 70,
        "回撤序列": 70,
        "逐日回撤": 75,
        "净值回撤": 70,
    },
    "daily_ret": {
        "daily_ret": 80,
        "raw_daily_ret": 80,
        "raw_return": 75,
        "original_return": 75,
        "original_daily_return": 80,
        "daily_return": 40,
        "原始日收益率": 80,
        "原始日收益": 80,
        "原始收益率": 75,
        "原始收益": 70,
        "辅助日收益": 75,
    },
}

_GENERIC_RETURN_NAMES: Final = {"return", "ret", "daily_return"}
_GENERIC_NAV_NAMES: Final = {"nav", "net_value", "netvalue", "equity", "净值"}
_IDENTIFIER_HINTS: Final = ("code", "id", "代码", "编号", "证券", "股票")
_RETURN_HINTS: Final = ("return", "ret", "收益", "回报")
_NAV_HINTS: Final = ("nav", "net_value", "netvalue", "净值", "equity", "price")
_DRAWDOWN_HINTS: Final = ("drawdown", "underwater", "回撤")


@dataclass(frozen=True)
class ColumnProfile:
    """Bounded, deterministic profile for one original column."""

    column_name: str
    normalized_name: str
    dtype: str
    non_null_count: int
    non_null_ratio: float
    unique_count: int
    unique_ratio: float
    numeric_ratio: float
    date_parse_ratio: float
    all_finite_numeric: bool
    numeric_min: float | None
    numeric_max: float | None
    positive_ratio: float
    non_positive_ratio: float
    negative_ratio: float
    within_unit_ratio: float
    numeric_abs_gt_one_ratio: float
    monotonic_increasing: bool
    monotonic_decreasing: bool
    mixed_types: bool
    analyzed_count: int


@dataclass(frozen=True)
class FieldCandidate:
    """One scored column candidate for a business role."""

    column_name: str
    score: int
    confidence: str
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FieldSuggestion:
    """Recommended field and bounded alternatives for one business role."""

    role: str
    recommended: FieldCandidate | None
    alternatives: tuple[FieldCandidate, ...]
    status: str

    @property
    def recommended_field(self) -> str | None:
        """Return the original recommended column name, if any."""
        return self.recommended.column_name if self.recommended else None

    @property
    def score(self) -> int | None:
        """Return the recommended score without inventing a score for no match."""
        return self.recommended.score if self.recommended else None

    @property
    def confidence(self) -> str:
        """Return the recommended confidence or the unrecognized status."""
        return self.recommended.confidence if self.recommended else "未识别"

    @property
    def reasons(self) -> tuple[str, ...]:
        """Return reasons attached to the recommendation."""
        return self.recommended.reasons if self.recommended else ()

    @property
    def warnings(self) -> tuple[str, ...]:
        """Return warnings attached to the recommendation."""
        return self.recommended.warnings if self.recommended else ()


@dataclass(frozen=True)
class DetectionResult:
    """Complete deterministic suggestion result without an established mapping."""

    suggestions: Mapping[str, FieldSuggestion]
    column_profiles: Mapping[str, ColumnProfile]
    global_warnings: tuple[str, ...]
    cross_field_checks: int


@dataclass(frozen=True)
class _ColumnContext:
    profile: ColumnProfile
    series: pd.Series


def normalize_field_name(value: object) -> str:
    """Normalize a field name for rules while preserving its original display."""

    normalized = unicodedata.normalize("NFKC", str(value)).replace("\ufeff", "")
    normalized = normalized.strip().lower()
    normalized = re.sub(r"[\s.\-]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _bounded_non_null_sample(series: pd.Series) -> pd.Series:
    non_null = series.dropna()
    count = len(non_null)
    if count <= MAX_PROFILE_SAMPLE_SIZE:
        return non_null.copy(deep=False)
    denominator = MAX_PROFILE_SAMPLE_SIZE - 1
    positions = [
        index * (count - 1) // denominator
        for index in range(MAX_PROFILE_SAMPLE_SIZE)
    ]
    return non_null.iloc[positions].copy(deep=False)


def _semantic_kind(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (pd.Timestamp,)):
        return "datetime"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "numeric"
    text = str(value).strip()
    if not text:
        return "empty"
    try:
        float(text.replace(",", ""))
    except ValueError:
        return "text"
    return "numeric_text"


def _parse_dates(sample: pd.Series) -> pd.Series:
    if sample.empty:
        return pd.Series(dtype="datetime64[ns, UTC]")
    text = sample.astype("string").str.strip()
    return pd.to_datetime(text, errors="coerce", format="mixed", utc=True)


def _build_profile(column_name: str, series: pd.Series) -> ColumnProfile:
    sample = _bounded_non_null_sample(series)
    analyzed_count = len(sample)
    row_count = len(series)
    non_null_count = int(series.notna().sum())
    non_null_ratio = non_null_count / row_count if row_count else 0.0

    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        numeric = pd.Series(float("nan"), index=sample.index, dtype="float64")
    else:
        numeric = pd.to_numeric(sample, errors="coerce")
    numeric_count = int(numeric.notna().sum())
    numeric_ratio = numeric_count / analyzed_count if analyzed_count else 0.0
    finite_values = [
        float(value)
        for value in numeric.dropna().tolist()
        if math.isfinite(float(value))
    ]
    finite_count = len(finite_values)
    all_finite_numeric = bool(analyzed_count) and finite_count == analyzed_count
    numeric_min = min(finite_values) if finite_values else None
    numeric_max = max(finite_values) if finite_values else None
    positive_count = sum(value > 0 for value in finite_values)
    negative_count = sum(value < 0 for value in finite_values)
    non_positive_count = sum(value <= 0 for value in finite_values)
    within_unit_count = sum(abs(value) <= 1 for value in finite_values)
    abs_gt_one_count = sum(abs(value) > 1 for value in finite_values)

    parsed_dates = _parse_dates(sample)
    date_count = int(parsed_dates.notna().sum())
    date_parse_ratio = date_count / analyzed_count if analyzed_count else 0.0
    unique_count = int(sample.nunique(dropna=True))
    unique_ratio = unique_count / analyzed_count if analyzed_count else 0.0

    numeric_valid = numeric.dropna()
    date_valid = parsed_dates.dropna()
    if numeric_ratio >= 0.9 and len(numeric_valid) >= 2:
        monotonic_increasing = bool(numeric_valid.is_monotonic_increasing)
        monotonic_decreasing = bool(numeric_valid.is_monotonic_decreasing)
    elif date_parse_ratio >= 0.9 and len(date_valid) >= 2:
        monotonic_increasing = bool(date_valid.is_monotonic_increasing)
        monotonic_decreasing = bool(date_valid.is_monotonic_decreasing)
    else:
        monotonic_increasing = False
        monotonic_decreasing = False

    semantic_kinds = {
        _semantic_kind(value) for value in sample.tolist() if str(value).strip()
    }
    numeric_kinds = {"numeric", "numeric_text"}
    mixed_types = len(semantic_kinds) > 1 and not semantic_kinds.issubset(numeric_kinds)

    return ColumnProfile(
        column_name=column_name,
        normalized_name=normalize_field_name(column_name),
        dtype=str(series.dtype),
        non_null_count=non_null_count,
        non_null_ratio=non_null_ratio,
        unique_count=unique_count,
        unique_ratio=unique_ratio,
        numeric_ratio=numeric_ratio,
        date_parse_ratio=date_parse_ratio,
        all_finite_numeric=all_finite_numeric,
        numeric_min=numeric_min,
        numeric_max=numeric_max,
        positive_ratio=positive_count / finite_count if finite_count else 0.0,
        non_positive_ratio=non_positive_count / finite_count if finite_count else 0.0,
        negative_ratio=negative_count / finite_count if finite_count else 0.0,
        within_unit_ratio=within_unit_count / finite_count if finite_count else 0.0,
        numeric_abs_gt_one_ratio=abs_gt_one_count / finite_count if finite_count else 0.0,
        monotonic_increasing=monotonic_increasing,
        monotonic_decreasing=monotonic_decreasing,
        mixed_types=mixed_types,
        analyzed_count=analyzed_count,
    )


def _confidence(score: int) -> str:
    if score >= 85:
        return "高置信度"
    if score >= 65:
        return "中置信度"
    if score >= 45:
        return "低置信度"
    return "未识别"


def _clamp_score(score: int) -> int:
    return max(0, min(100, int(score)))


def _contains_any(value: str, hints: tuple[str, ...]) -> bool:
    return any(hint in value for hint in hints)


def _name_score(role: str, profile: ColumnProfile) -> int:
    return _ROLE_ALIASES[role].get(profile.normalized_name, 0)


def _base_messages(
    role: str,
    profile: ColumnProfile,
) -> tuple[int, list[str], list[str]]:
    score = _name_score(role, profile)
    reasons: list[str] = []
    warnings: list[str] = []
    if score:
        reasons.append(
            f"字段名“{profile.column_name}”与 {role} 的确定性别名规则匹配。"
        )
    if profile.mixed_types:
        warnings.append("样本中存在混合类型，建议人工核对原始字段。")
    if profile.non_null_ratio < 0.5:
        warnings.append("非空比例低于 50%，字段完整性有限。")
    if profile.numeric_ratio >= 0.8 and not profile.all_finite_numeric:
        warnings.append("数值样本包含 NaN 或无穷值等非有限数值，需人工处理。")
    return score, reasons, warnings


def _score_date(profile: ColumnProfile) -> tuple[int, list[str], list[str]]:
    score, reasons, warnings = _base_messages("date", profile)
    if profile.date_parse_ratio >= 0.95:
        score += 15
        reasons.append("至少 95% 的非空样本可解析为日期。")
    elif profile.date_parse_ratio >= 0.8:
        score += 10
        reasons.append("多数非空样本可解析为日期。")
    elif profile.date_parse_ratio < 0.5:
        warnings.append("日期解析比例低于 50%，不能仅凭字段名确认日期。")
        score -= 15
    if profile.unique_ratio >= 0.9:
        score += 5
        reasons.append("日期样本具有较高唯一性。")
    if profile.monotonic_increasing or profile.monotonic_decreasing:
        score += 5
        reasons.append("样本按时间或数值呈单调顺序。")

    normalized = profile.normalized_name
    integer_like = (
        profile.numeric_ratio >= 0.95
        and "datetime" not in profile.dtype.lower()
        and profile.numeric_min is not None
        and profile.numeric_max is not None
        and float(profile.numeric_min).is_integer()
        and float(profile.numeric_max).is_integer()
    )
    if integer_like:
        warnings.append("纯整数值也可能是日期编码或证券代码，需要人工确认。")
        score = min(score, 84)
    if normalized in {"datetime", "timestamp", "time", "时间", "日期时间"} or "," in profile.dtype:
        warnings.append("时间戳或日期值可能包含时区，后续需人工确认时区口径。")
    if _contains_any(normalized, _IDENTIFIER_HINTS) and not _contains_any(
        normalized, ("date", "日期", "时间")
    ):
        warnings.append("字段名更像代码或标识符，不建议自动视为日期。")
        score = min(score, 44)
    return score, reasons, warnings


def _score_return(
    role: str,
    profile: ColumnProfile,
) -> tuple[int, list[str], list[str]]:
    score, reasons, warnings = _base_messages(role, profile)
    normalized = profile.normalized_name
    if _contains_any(normalized, _NAV_HINTS) or _contains_any(
        normalized, _DRAWDOWN_HINTS
    ):
        warnings.append("字段名包含净值、价格或回撤含义，与收益率角色冲突。")
        score -= 30
    if profile.numeric_ratio >= 0.95:
        score += 10
        reasons.append("至少 95% 的非空样本可转换为数值。")
    elif profile.numeric_ratio < 0.8:
        warnings.append("数值转换比例不足 80%，不适合作为收益率字段。")
        score -= 15
    if profile.positive_ratio > 0 and profile.negative_ratio > 0:
        score += 8
        reasons.append("样本同时包含正收益和负收益。")
    elif profile.positive_ratio >= 0.95:
        warnings.append("样本几乎全部为正值，需确认是否确为收益率。")
        score -= 5
    if profile.numeric_min is not None and profile.numeric_min > -1:
        score += 5
        reasons.append("样本最小值大于 -1，符合常见小数收益率边界。")
    if profile.within_unit_ratio >= 0.9:
        score += 5
        reasons.append("至少 90% 的数值样本位于 [-1, 1]。")
    if profile.numeric_abs_gt_one_ratio >= 0.2:
        warnings.append("较多样本绝对值大于 1，可能使用百分数单位；系统不会自动换算。")
        score -= 15
    if normalized in _GENERIC_RETURN_NAMES:
        warnings.append("字段名较通用，可能对应策略收益率或原始日收益率。")
        score = min(score, 84 if normalized == "daily_return" else 74)
    return score, reasons, warnings


def _score_nav(
    role: str,
    profile: ColumnProfile,
) -> tuple[int, list[str], list[str]]:
    score, reasons, warnings = _base_messages(role, profile)
    normalized = profile.normalized_name
    if _contains_any(normalized, _RETURN_HINTS) or _contains_any(
        normalized, _DRAWDOWN_HINTS
    ):
        warnings.append("字段名包含收益或回撤含义，与净值角色冲突。")
        score -= 35
    if "累计收益" in normalized:
        warnings.append("“累计收益”不是净值的确定性同义词，不能据此建立净值建议。")
        score = min(score, 20)
    if profile.numeric_ratio >= 0.95:
        score += 10
        reasons.append("至少 95% 的非空样本可转换为数值。")
    elif profile.numeric_ratio < 0.8:
        warnings.append("数值转换比例不足 80%，不适合作为净值字段。")
        score -= 15
    if profile.numeric_min is not None and profile.numeric_min > 0:
        score += 10
        reasons.append("数值样本均为正值，符合常见净值序列特征。")
    else:
        warnings.append("样本包含非正值，需确认是否确为净值。")
    if profile.unique_ratio >= 0.5:
        score += 5
        reasons.append("样本具有足够变化，不像单一汇总值。")
    if profile.unique_count >= 3:
        score += 3
    if normalized in _GENERIC_NAV_NAMES:
        warnings.append("字段名较通用，不能仅凭名称确认净值含义。")
        score = min(score, 84)
    return score, reasons, warnings


def _score_drawdown(profile: ColumnProfile) -> tuple[int, list[str], list[str]]:
    score, reasons, warnings = _base_messages("drawdown", profile)
    if profile.numeric_ratio >= 0.95:
        score += 10
        reasons.append("至少 95% 的非空样本可转换为数值。")
    elif profile.numeric_ratio < 0.8:
        warnings.append("数值转换比例不足 80%，不适合作为逐日回撤。")
        score -= 15
    mostly_in_drawdown_range = (
        profile.numeric_min is not None
        and profile.numeric_min >= -1
        and profile.non_positive_ratio >= 0.8
    )
    if mostly_in_drawdown_range:
        score += 15
        reasons.append("至少 80% 的数值样本位于 [-1, 0]。")
        if profile.numeric_max is not None and profile.numeric_max == 0:
            score += 5
            reasons.append("序列包含 0，符合回到历史高点时的回撤特征。")
    elif profile.positive_ratio > 0.2:
        warnings.append("较多回撤样本为正值，与常见逐日回撤定义不符。")
        score -= 25
    if profile.unique_count >= 3 and profile.analyzed_count >= 3:
        score += 5
        reasons.append("字段包含多个观察值和多个状态，具备序列特征。")
    normalized = profile.normalized_name
    aggregate_hint = "最大" in normalized or "max" in normalized
    if aggregate_hint:
        warnings.append("字段名包含“最大回撤”含义，需区分汇总指标与逐日序列。")
    if aggregate_hint and (profile.analyzed_count < 3 or profile.unique_count <= 1):
        warnings.append("该字段更像最大回撤汇总值，不能作为逐日回撤建议。")
        score = min(score, 44)
    return score, reasons, warnings


def _score_daily_ret(profile: ColumnProfile) -> tuple[int, list[str], list[str]]:
    score, reasons, warnings = _base_messages("daily_ret", profile)
    if profile.numeric_ratio >= 0.95:
        score += 10
        reasons.append("至少 95% 的非空样本可转换为数值。")
    elif profile.numeric_ratio < 0.8:
        warnings.append("数值转换比例不足 80%，不适合作为原始日收益率。")
        score -= 15
    if profile.numeric_abs_gt_one_ratio >= 0.2:
        warnings.append("较多样本绝对值大于 1，系统不会自动判断或转换单位。")
    if profile.normalized_name == "daily_return":
        warnings.append("daily_return 也可能表示策略收益率，角色存在歧义。")
        score = min(score, 64)
    return score, reasons, warnings


def _score_candidate(role: str, context: _ColumnContext) -> FieldCandidate:
    profile = context.profile
    if role == "date":
        score, reasons, warnings = _score_date(profile)
    elif role in {"strategy_return", "benchmark_return"}:
        score, reasons, warnings = _score_return(role, profile)
    elif role in {"strategy_nav", "benchmark_nav"}:
        score, reasons, warnings = _score_nav(role, profile)
    elif role == "drawdown":
        score, reasons, warnings = _score_drawdown(profile)
    else:
        score, reasons, warnings = _score_daily_ret(profile)
    final_score = _clamp_score(score)
    return FieldCandidate(
        column_name=profile.column_name,
        score=final_score,
        confidence=_confidence(final_score),
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _add_candidate_message(
    candidate: FieldCandidate,
    *,
    reason: str | None = None,
    warning: str | None = None,
    score_delta: int = 0,
) -> FieldCandidate:
    score = _clamp_score(candidate.score + score_delta)
    reasons = candidate.reasons + ((reason,) if reason else ())
    warnings = candidate.warnings + ((warning,) if warning else ())
    return replace(
        candidate,
        score=score,
        confidence=_confidence(score),
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _build_suggestion(
    role: str,
    candidates: list[FieldCandidate],
) -> tuple[FieldSuggestion, str | None]:
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (-item[1].score, item[0]),
    )
    ordered = [candidate for _, candidate in ranked]
    recommended = ordered[0] if ordered and ordered[0].score >= MIN_RECOMMENDATION_SCORE else None
    close_warning: str | None = None
    if recommended is not None:
        alternatives = tuple(
            candidate for candidate in ordered[1:3] if candidate.score >= 25
        )
        if (
            alternatives
            and alternatives[0].score >= MIN_RECOMMENDATION_SCORE
            and recommended.score - alternatives[0].score <= CLOSE_SCORE_GAP
        ):
            close_warning = (
                f"{role} 存在多个相近候选：前两名候选分差不超过 "
                f"{CLOSE_SCORE_GAP} 分，建议人工确认。"
            )
            recommended = _add_candidate_message(
                recommended,
                warning=close_warning,
            )
        status = recommended.confidence
    else:
        alternatives = tuple(candidate for candidate in ordered[:3] if candidate.score >= 25)
        status = "未识别"
    return (
        FieldSuggestion(
            role=role,
            recommended=recommended,
            alternatives=alternatives,
            status=status,
        ),
        close_warning,
    )


def _numeric_series(frame: pd.DataFrame, column_name: str) -> pd.Series:
    for position, original_name in enumerate(frame.columns):
        if str(original_name) == column_name:
            return pd.to_numeric(frame.iloc[:, position], errors="coerce")
    return pd.Series(float("nan"), index=frame.index, dtype="float64")


def _bounded_pair(left: pd.Series, right: pd.Series) -> pd.DataFrame:
    paired = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(paired) <= MAX_PROFILE_SAMPLE_SIZE:
        return paired
    return paired.iloc[:MAX_PROFILE_SAMPLE_SIZE]


def _agreement_ratio(left: pd.Series, right: pd.Series) -> tuple[float, int]:
    paired = _bounded_pair(left, right)
    if paired.empty:
        return 0.0, 0
    matches = 0
    for left_value, right_value in paired.itertuples(index=False, name=None):
        tolerance = 1e-6 + 1e-4 * max(abs(float(left_value)), abs(float(right_value)))
        if abs(float(left_value) - float(right_value)) <= tolerance:
            matches += 1
    return matches / len(paired), len(paired)


def _replace_recommended(
    suggestions: dict[str, FieldSuggestion],
    role: str,
    candidate: FieldCandidate,
) -> None:
    suggestion = suggestions[role]
    suggestions[role] = replace(
        suggestion,
        recommended=candidate,
        status=candidate.confidence,
    )


def _check_nav_return(
    frame: pd.DataFrame,
    suggestions: dict[str, FieldSuggestion],
    nav_role: str,
    return_role: str,
) -> bool:
    nav_candidate = suggestions[nav_role].recommended
    return_candidate = suggestions[return_role].recommended
    if nav_candidate is None or return_candidate is None:
        return False
    nav = _numeric_series(frame, nav_candidate.column_name)
    observed_return = _numeric_series(frame, return_candidate.column_name)
    derived_return = nav.pct_change(fill_method=None)
    agreement, count = _agreement_ratio(derived_return, observed_return)
    if count < 3:
        return True
    if agreement >= 0.9:
        reason = "与候选净值推导收益高度一致（仅作候选一致性核对）。"
        _replace_recommended(
            suggestions,
            return_role,
            _add_candidate_message(return_candidate, reason=reason, score_delta=5),
        )
        _replace_recommended(
            suggestions,
            nav_role,
            _add_candidate_message(
                nav_candidate,
                reason="与候选收益率高度一致（仅作候选一致性核对）。",
                score_delta=5,
            ),
        )
    elif agreement < 0.5:
        warning = "该收益列与候选净值推导收益存在明显差异，请人工核对口径和单位。"
        _replace_recommended(
            suggestions,
            return_role,
            _add_candidate_message(return_candidate, warning=warning),
        )
        _replace_recommended(
            suggestions,
            nav_role,
            _add_candidate_message(nav_candidate, warning=warning),
        )
    return True


def _check_nav_drawdown(
    frame: pd.DataFrame,
    suggestions: dict[str, FieldSuggestion],
) -> bool:
    nav_candidate = suggestions["strategy_nav"].recommended
    drawdown_candidate = suggestions["drawdown"].recommended
    if nav_candidate is None or drawdown_candidate is None:
        return False
    nav = _numeric_series(frame, nav_candidate.column_name)
    observed_drawdown = _numeric_series(frame, drawdown_candidate.column_name)
    derived_drawdown = nav / nav.cummax() - 1
    agreement, count = _agreement_ratio(derived_drawdown, observed_drawdown)
    if count < 3:
        return True
    if agreement >= 0.9:
        _replace_recommended(
            suggestions,
            "drawdown",
            _add_candidate_message(
                drawdown_candidate,
                reason="与候选净值推导的逐日回撤高度一致（仅作候选一致性核对）。",
                score_delta=5,
            ),
        )
    elif agreement < 0.5:
        _replace_recommended(
            suggestions,
            "drawdown",
            _add_candidate_message(
                drawdown_candidate,
                warning="候选回撤与候选净值推导结果一致性较低，请人工核对定义。",
            ),
        )
    return True


def _apply_cross_field_checks(
    frame: pd.DataFrame,
    suggestions: dict[str, FieldSuggestion],
) -> int:
    checks = 0
    if _check_nav_return(frame, suggestions, "strategy_nav", "strategy_return"):
        checks += 1
    if checks < MAX_CROSS_FIELD_CHECKS and _check_nav_drawdown(frame, suggestions):
        checks += 1
    if checks < MAX_CROSS_FIELD_CHECKS and _check_nav_return(
        frame,
        suggestions,
        "benchmark_nav",
        "benchmark_return",
    ):
        checks += 1
    return checks


def _add_cross_role_conflicts(
    suggestions: dict[str, FieldSuggestion],
) -> list[str]:
    columns_to_roles: dict[str, list[str]] = {}
    for role in ROLE_ORDER:
        candidate = suggestions[role].recommended
        if candidate is not None:
            columns_to_roles.setdefault(candidate.column_name, []).append(role)

    warnings: list[str] = []
    for column_name, roles in columns_to_roles.items():
        if len(roles) < 2:
            continue
        warning = (
            f"字段“{column_name}”同时成为多个角色的首选候选："
            f"{', '.join(roles)}。系统不会自动解决该冲突。"
        )
        warnings.append(warning)
        for role in roles:
            candidate = suggestions[role].recommended
            if candidate is not None:
                _replace_recommended(
                    suggestions,
                    role,
                    _add_candidate_message(candidate, warning=warning),
                )
    return warnings


def detect_field_candidates(dataframe: pd.DataFrame) -> DetectionResult:
    """Suggest likely business fields without changing or mapping the dataframe."""

    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("dataframe 必须是 pandas.DataFrame")

    contexts: list[_ColumnContext] = []
    profiles: dict[str, ColumnProfile] = {}
    for position, original_name in enumerate(dataframe.columns):
        column_name = str(original_name)
        series = dataframe.iloc[:, position]
        profile = _build_profile(column_name, series)
        contexts.append(_ColumnContext(profile=profile, series=series))
        profiles[column_name] = profile

    suggestions: dict[str, FieldSuggestion] = {}
    global_warnings: list[str] = []
    for role in ROLE_ORDER:
        candidates = [_score_candidate(role, context) for context in contexts]
        suggestion, close_warning = _build_suggestion(role, candidates)
        suggestions[role] = suggestion
        if close_warning:
            global_warnings.append(close_warning)

    cross_field_checks = _apply_cross_field_checks(dataframe, suggestions)
    global_warnings.extend(_add_cross_role_conflicts(suggestions))

    return DetectionResult(
        suggestions=suggestions,
        column_profiles=profiles,
        global_warnings=tuple(dict.fromkeys(global_warnings)),
        cross_field_checks=cross_field_checks,
    )
