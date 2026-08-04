"""确认字段映射后的确定性标准化预览与数据质量预检。

本模块只创建新的内存 DataFrame，并生成可审计的问题清单。它不会修改
来源数据、推导收益率、调整单位、排序、去重、填充或调用绩效分析流程。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from numbers import Integral, Real
import re
from typing import Final, Mapping, Sequence

import pandas as pd

from src.field_detection import ROLE_ORDER
from src.field_mapping import (
    PRIMARY_BASIS_NAV,
    PRIMARY_BASIS_OPTIONS,
    PRIMARY_BASIS_RETURN,
    ConfirmedMapping,
)


STANDARDIZATION_POLICY_VERSION: Final = "b4a-standardization-v1"
MAPPING_KEY_POLICY_VERSION: Final = "b3-confirmed-mapping-v1"
BLOCKING: Final = "blocking"
WARNING: Final = "warning"

_DATE_DASH_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_SLASH_PATTERN = re.compile(r"^\d{4}/\d{2}/\d{2}$")
_DATE_COMPACT_PATTERN = re.compile(r"^\d{8}$")
_AMBIGUOUS_DATE_PATTERN = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}(?:$|[ T])")
_ISO_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?$"
)
_PLAIN_NUMBER_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)

_RETURN_ANALYSIS_ROLES: Final = (
    ("date", "date"),
    ("strategy_return", "strategy_return"),
)
_NAV_ANALYSIS_ROLES: Final = (
    ("date", "date"),
    ("strategy_nav", "nav_strat"),
)


@dataclass(frozen=True)
class StandardizationIssue:
    """单项阻断问题或风险提示。"""

    level: str
    code: str
    role: str | None
    column_name: str | None
    row_count: int
    message: str


@dataclass(frozen=True)
class StandardizationResult:
    """与来源、确认映射和策略版本绑定的只读预检结果。"""

    source_key: str
    mapping_key: str
    standardization_key: str
    policy_version: str
    confirmed_mapping: ConfirmedMapping
    primary_basis: str
    structure_type: str
    analysis_frame: pd.DataFrame
    diagnostic_frame: pd.DataFrame
    issues: tuple[StandardizationIssue, ...]
    is_preview_valid: bool
    source_row_count: int
    row_count: int
    column_count: int


@dataclass(frozen=True)
class _NumericParseResult:
    series: pd.Series
    missing_count: int
    invalid_count: int
    non_finite_count: int


@dataclass(frozen=True)
class _DateParseResult:
    series: pd.Series
    missing_count: int
    invalid_count: int
    time_count: int
    timezone_count: int


def _sha256_payload(payload: Mapping[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def build_mapping_key(confirmed_mapping: ConfirmedMapping) -> str:
    """按固定角色顺序为 B.3 确认映射生成稳定 SHA-256 标识。"""

    if not isinstance(confirmed_mapping, ConfirmedMapping):
        raise TypeError("confirmed_mapping 必须是 ConfirmedMapping")
    payload = {
        "mapping_policy_version": MAPPING_KEY_POLICY_VERSION,
        "source_key": confirmed_mapping.source_key,
        "primary_basis": confirmed_mapping.primary_basis,
        "roles": [
            {
                "role": role,
                "column": confirmed_mapping.role_to_column.get(role),
            }
            for role in ROLE_ORDER
        ],
    }
    return _sha256_payload(payload)


def build_standardization_key(
    source_key: str,
    mapping_key: str,
    policy_version: str,
    *,
    primary_basis: str = "",
    output_columns: Sequence[str] = (),
) -> str:
    """为来源、映射、策略和有序输出结构生成稳定 SHA-256 标识。"""

    payload = {
        "source_key": str(source_key),
        "mapping_key": str(mapping_key),
        "policy_version": str(policy_version),
        "primary_basis": str(primary_basis),
        "output_columns": list(output_columns),
    }
    return _sha256_payload(payload)


def analysis_output_columns(
    confirmed_mapping: ConfirmedMapping,
) -> tuple[str, ...]:
    """返回当前主口径下固定顺序的分析候选字段。"""

    if confirmed_mapping.primary_basis == PRIMARY_BASIS_RETURN:
        columns = [target for _, target in _RETURN_ANALYSIS_ROLES]
        if confirmed_mapping.role_to_column.get("benchmark_return"):
            columns.append("benchmark_return")
        return tuple(columns)
    if confirmed_mapping.primary_basis == PRIMARY_BASIS_NAV:
        columns = [target for _, target in _NAV_ANALYSIS_ROLES]
        if confirmed_mapping.role_to_column.get("daily_ret"):
            columns.append("daily_ret")
        return tuple(columns)
    return ("date",)


def _analysis_role_pairs(
    confirmed_mapping: ConfirmedMapping,
) -> tuple[tuple[str, str], ...]:
    if confirmed_mapping.primary_basis == PRIMARY_BASIS_RETURN:
        pairs = list(_RETURN_ANALYSIS_ROLES)
        if confirmed_mapping.role_to_column.get("benchmark_return"):
            pairs.append(("benchmark_return", "benchmark_return"))
        return tuple(pairs)
    if confirmed_mapping.primary_basis == PRIMARY_BASIS_NAV:
        pairs = list(_NAV_ANALYSIS_ROLES)
        if confirmed_mapping.role_to_column.get("daily_ret"):
            pairs.append(("daily_ret", "daily_ret"))
        return tuple(pairs)
    return (("date", "date"),)


def _diagnostic_roles(
    confirmed_mapping: ConfirmedMapping,
    analysis_pairs: Sequence[tuple[str, str]],
) -> tuple[str, ...]:
    analysis_roles = {role for role, _ in analysis_pairs}
    return tuple(
        role
        for role in ROLE_ORDER
        if role != "date"
        and role not in analysis_roles
        and confirmed_mapping.role_to_column.get(role) is not None
    )


def _source_series(
    dataframe: pd.DataFrame,
    column_name: str,
) -> pd.Series | None:
    positions = [
        position
        for position, current_name in enumerate(dataframe.columns)
        if str(current_name) == column_name
    ]
    if len(positions) != 1:
        return None
    return dataframe.iloc[:, positions[0]].copy(deep=True)


def _is_explicit_missing(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _parse_numeric_series(series: pd.Series, target_name: str) -> _NumericParseResult:
    values: list[object] = []
    missing_count = 0
    invalid_count = 0
    non_finite_count = 0

    for value in series.tolist():
        if _is_explicit_missing(value):
            values.append(pd.NA)
            missing_count += 1
            continue
        if isinstance(value, bool):
            values.append(pd.NA)
            invalid_count += 1
            continue
        if isinstance(value, Decimal):
            if not value.is_finite():
                values.append(pd.NA)
                non_finite_count += 1
            else:
                values.append(value)
            continue
        if isinstance(value, Integral):
            values.append(value)
            continue
        if isinstance(value, Real):
            numeric_value = float(value)
            if math.isnan(numeric_value):
                values.append(pd.NA)
                missing_count += 1
                non_finite_count += 1
            elif not math.isfinite(numeric_value):
                values.append(pd.NA)
                non_finite_count += 1
            else:
                values.append(value)
            continue
        if isinstance(value, str):
            text = value.strip()
            if not _PLAIN_NUMBER_PATTERN.fullmatch(text):
                values.append(pd.NA)
                invalid_count += 1
                continue
            try:
                parsed = Decimal(text)
            except InvalidOperation:
                values.append(pd.NA)
                invalid_count += 1
                continue
            if not parsed.is_finite():
                values.append(pd.NA)
                non_finite_count += 1
            else:
                values.append(parsed)
            continue
        values.append(pd.NA)
        invalid_count += 1

    return _NumericParseResult(
        series=pd.Series(
            values,
            index=series.index.copy(deep=True),
            name=target_name,
            dtype="object",
        ),
        missing_count=missing_count,
        invalid_count=invalid_count,
        non_finite_count=non_finite_count,
    )


def _normalize_timestamp(value: object) -> tuple[pd.Timestamp, bool, bool]:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("日期为空")
    has_timezone = bool(
        timestamp.tzinfo is not None and timestamp.utcoffset() is not None
    )
    has_time = bool(
        timestamp.hour
        or timestamp.minute
        or timestamp.second
        or timestamp.microsecond
        or timestamp.nanosecond
    )
    if has_timezone:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp, has_time, has_timezone


def _parse_date_value(value: object) -> tuple[pd.Timestamp, bool, bool]:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return _normalize_timestamp(value)
    if not isinstance(value, str):
        raise ValueError("日期类型不受支持")

    text = value.strip()
    if _AMBIGUOUS_DATE_PATTERN.fullmatch(text):
        raise ValueError("日期格式含糊")
    if _DATE_DASH_PATTERN.fullmatch(text):
        parsed = datetime.strptime(text, "%Y-%m-%d")
    elif _DATE_SLASH_PATTERN.fullmatch(text):
        parsed = datetime.strptime(text, "%Y/%m/%d")
    elif _DATE_COMPACT_PATTERN.fullmatch(text):
        parsed = datetime.strptime(text, "%Y%m%d")
    elif _ISO_DATETIME_PATTERN.fullmatch(text):
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        raise ValueError("日期格式不在确定性白名单中")
    return _normalize_timestamp(parsed)


def _parse_date_series(series: pd.Series) -> _DateParseResult:
    parsed_values: list[pd.Timestamp | pd.NaTType] = []
    missing_count = 0
    invalid_count = 0
    time_count = 0
    timezone_count = 0

    for value in series.tolist():
        if _is_explicit_missing(value) or (
            not isinstance(value, str) and bool(pd.isna(value))
        ):
            parsed_values.append(pd.NaT)
            missing_count += 1
            continue
        try:
            parsed, has_time, has_timezone = _parse_date_value(value)
        except (OverflowError, TypeError, ValueError):
            parsed_values.append(pd.NaT)
            invalid_count += 1
            continue
        parsed_values.append(parsed)
        time_count += int(has_time)
        timezone_count += int(has_timezone)

    parsed_series = pd.Series(
        pd.to_datetime(parsed_values, errors="coerce"),
        index=series.index.copy(deep=True),
        name="date",
        dtype="datetime64[ns]",
    )
    conversion_failures = int(parsed_series.isna().sum()) - missing_count - invalid_count
    if conversion_failures > 0:
        invalid_count += conversion_failures
    return _DateParseResult(
        series=parsed_series,
        missing_count=missing_count,
        invalid_count=invalid_count,
        time_count=time_count,
        timezone_count=timezone_count,
    )


def _add_issue(
    issues: list[StandardizationIssue],
    *,
    level: str,
    code: str,
    role: str | None,
    column_name: str | None,
    row_count: int,
    message: str,
) -> None:
    if row_count <= 0:
        return
    issues.append(
        StandardizationIssue(
            level=level,
            code=code,
            role=role,
            column_name=column_name,
            row_count=int(row_count),
            message=message,
        )
    )


def _finite_numeric(series: pd.Series) -> pd.Series:
    converted = pd.to_numeric(series, errors="coerce")
    return converted[converted.map(lambda value: pd.notna(value) and math.isfinite(float(value)))]


def _add_numeric_conversion_issues(
    issues: list[StandardizationIssue],
    parsed: _NumericParseResult,
    *,
    role: str,
    column_name: str,
    blocking: bool,
) -> None:
    level = BLOCKING if blocking else WARNING
    prefix = "分析候选字段" if blocking else "诊断字段"
    _add_issue(
        issues,
        level=level,
        code="numeric_missing",
        role=role,
        column_name=column_name,
        row_count=parsed.missing_count,
        message=f"{prefix}“{column_name}”存在缺失值，系统不会自动填充。",
    )
    _add_issue(
        issues,
        level=level,
        code="numeric_unparseable",
        role=role,
        column_name=column_name,
        row_count=parsed.invalid_count,
        message=(
            f"{prefix}“{column_name}”存在不可按普通数值规则转换的值，"
            "系统不会猜测百分号、千分位、货币或中文单位。"
        ),
    )
    _add_issue(
        issues,
        level=level,
        code="numeric_non_finite",
        role=role,
        column_name=column_name,
        row_count=parsed.non_finite_count,
        message=f"{prefix}“{column_name}”存在 NaN 或正负无穷。",
    )


def _add_return_checks(
    issues: list[StandardizationIssue],
    series: pd.Series,
    *,
    role: str,
    column_name: str,
    blocking_floor: bool,
) -> None:
    finite = _finite_numeric(series)
    if finite.empty:
        return
    floor_count = int((finite <= -1).sum())
    _add_issue(
        issues,
        level=BLOCKING if blocking_floor else WARNING,
        code="return_at_or_below_minus_one",
        role=role,
        column_name=column_name,
        row_count=floor_count,
        message=(
            f"收益字段“{column_name}”存在小于或等于 -1 的值；"
            "系统不会截断或修正。"
        ),
    )

    count = len(finite)
    large_count = int((finite.abs() > 1).sum())
    extreme_count = int(((finite > 0.2) | (finite < -0.2)).sum())
    if large_count / count >= 0.2:
        _add_issue(
            issues,
            level=WARNING,
            code="return_large_absolute_values",
            role=role,
            column_name=column_name,
            row_count=large_count,
            message=f"收益字段“{column_name}”较多值绝对值大于 1，请核对定义和单位。",
        )
        _add_issue(
            issues,
            level=WARNING,
            code="return_possible_percentage_unit",
            role=role,
            column_name=column_name,
            row_count=large_count,
            message=(
                f"收益字段“{column_name}”的数值尺度可能使用百分数单位；"
                "系统不会自动除以 100。"
            ),
        )
    if extreme_count / count >= 0.2:
        _add_issue(
            issues,
            level=WARNING,
            code="return_many_extreme_values",
            role=role,
            column_name=column_name,
            row_count=extreme_count,
            message=f"收益字段“{column_name}”较多值超出 [-0.2, 0.2]，请核对数据定义。",
        )
    if bool((finite > 0).all()):
        _add_issue(
            issues,
            level=WARNING,
            code="return_all_positive",
            role=role,
            column_name=column_name,
            row_count=count,
            message=f"收益字段“{column_name}”全部为正，请核对数据定义。",
        )
    if bool((finite == 0).all()):
        _add_issue(
            issues,
            level=WARNING,
            code="return_all_zero",
            role=role,
            column_name=column_name,
            row_count=count,
            message=f"收益字段“{column_name}”全部为零，请核对数据定义。",
        )
    unique_count = int(finite.nunique(dropna=True))
    if count >= 3 and unique_count <= 2:
        _add_issue(
            issues,
            level=WARNING,
            code="return_low_uniqueness",
            role=role,
            column_name=column_name,
            row_count=count,
            message=f"收益字段“{column_name}”唯一值过少，请核对序列是否完整。",
        )

    absolute = finite.abs()
    median_absolute = float(absolute.median())
    if count >= 10 and median_absolute > 0:
        outlier_count = int((absolute > max(0.2, median_absolute * 10)).sum())
        if 0 < outlier_count / count <= 0.1:
            _add_issue(
                issues,
                level=WARNING,
                code="return_sparse_outliers",
                role=role,
                column_name=column_name,
                row_count=outlier_count,
                message=f"收益字段“{column_name}”出现少量异常极值，请核对原始定义和单位。",
            )


def _add_nav_checks(
    issues: list[StandardizationIssue],
    series: pd.Series,
    *,
    role: str,
    column_name: str,
    primary: bool,
) -> None:
    finite = _finite_numeric(series)
    if finite.empty:
        return
    non_positive_count = int((finite <= 0).sum())
    _add_issue(
        issues,
        level=BLOCKING if primary else WARNING,
        code="nav_non_positive",
        role=role,
        column_name=column_name,
        row_count=non_positive_count,
        message=f"净值字段“{column_name}”存在小于或等于 0 的值，系统不会修正。",
    )
    if primary and len(finite) < 2:
        _add_issue(
            issues,
            level=BLOCKING,
            code="nav_insufficient_observations",
            role=role,
            column_name=column_name,
            row_count=len(finite),
            message="净值主口径至少需要 2 个有效观察值。",
        )
    if len(finite) >= 2 and int(finite.nunique(dropna=True)) == 1:
        _add_issue(
            issues,
            level=WARNING,
            code="nav_constant",
            role=role,
            column_name=column_name,
            row_count=len(finite),
            message=f"净值字段“{column_name}”全部数值相同。",
        )
    if len(finite) >= 3 and int(finite.nunique(dropna=True)) <= 2:
        _add_issue(
            issues,
            level=WARNING,
            code="nav_low_uniqueness",
            role=role,
            column_name=column_name,
            row_count=len(finite),
            message=f"净值字段“{column_name}”唯一值过少，请核对序列。",
        )
    first_value = float(finite.iloc[0])
    if abs(first_value - 1) > 0.25:
        _add_issue(
            issues,
            level=WARNING,
            code="nav_initial_value_far_from_one",
            role=role,
            column_name=column_name,
            row_count=1,
            message=(
                f"净值字段“{column_name}”初始值明显不接近 1；"
                "这不是阻断问题，系统不会归一化。"
            ),
        )
    if len(finite) >= 2:
        temporary = finite.astype(float)
        jumps = temporary.pct_change(fill_method=None).abs()
        jump_count = int((jumps > 0.5).sum())
        _add_issue(
            issues,
            level=WARNING,
            code="nav_extreme_jump",
            role=role,
            column_name=column_name,
            row_count=jump_count,
            message=f"净值字段“{column_name}”存在超过 50% 的相邻跳变，请核对数据定义。",
        )
        scale = max(abs(first_value), 1e-12)
        if float(temporary.max() - temporary.min()) / scale < 1e-4:
            _add_issue(
                issues,
                level=WARNING,
                code="nav_too_little_variation",
                role=role,
                column_name=column_name,
                row_count=len(finite),
                message=f"净值字段“{column_name}”序列变化过小，请核对数据精度。",
            )
    if float(finite.abs().median()) > 10:
        _add_issue(
            issues,
            level=WARNING,
            code="nav_large_scale",
            role=role,
            column_name=column_name,
            row_count=len(finite),
            message=(
                f"净值字段“{column_name}”的尺度更像账户资产或价格指数；"
                "系统不会自动归一化。"
            ),
        )


def _add_date_checks(
    issues: list[StandardizationIssue],
    parsed: _DateParseResult,
    *,
    column_name: str,
) -> None:
    _add_issue(
        issues,
        level=BLOCKING,
        code="date_missing",
        role="date",
        column_name=column_name,
        row_count=parsed.missing_count,
        message=f"日期字段“{column_name}”存在缺失值，系统不会自动填充。",
    )
    _add_issue(
        issues,
        level=BLOCKING,
        code="date_unparseable",
        role="date",
        column_name=column_name,
        row_count=parsed.invalid_count,
        message=(
            f"日期字段“{column_name}”存在无法按确定性白名单解析的非空值；"
            "系统不会根据地区环境猜测。"
        ),
    )
    valid = parsed.series.dropna()
    duplicate_count = int(valid.duplicated(keep=False).sum())
    _add_issue(
        issues,
        level=BLOCKING,
        code="date_duplicate",
        role="date",
        column_name=column_name,
        row_count=duplicate_count,
        message="日期字段存在重复时间戳，系统不会去重或聚合。",
    )
    natural_days = valid.dt.normalize()
    natural_duplicate_mask = natural_days.duplicated(keep=False)
    natural_duplicate_count = 0
    if parsed.time_count and bool(natural_duplicate_mask.any()):
        duplicate_groups = valid[natural_duplicate_mask].groupby(
            natural_days[natural_duplicate_mask]
        )
        natural_duplicate_count = sum(
            len(group) for _, group in duplicate_groups if group.nunique() > 1
        )
    _add_issue(
        issues,
        level=BLOCKING,
        code="date_same_natural_day_duplicate",
        role="date",
        column_name=column_name,
        row_count=natural_duplicate_count,
        message=(
            "含时间的日期在统一时区规则后落入同一自然日；"
            "系统不会自动聚合这些记录。"
        ),
    )
    non_increasing_count = 0
    if len(valid) >= 2:
        non_increasing_count = int((valid.diff().iloc[1:] <= pd.Timedelta(0)).sum())
    _add_issue(
        issues,
        level=BLOCKING,
        code="date_not_strictly_increasing",
        role="date",
        column_name=column_name,
        row_count=non_increasing_count,
        message="日期不是严格递增顺序，系统不会自动排序修复。",
    )
    _add_issue(
        issues,
        level=WARNING,
        code="date_contains_time",
        role="date",
        column_name=column_name,
        row_count=parsed.time_count,
        message="日期包含明确时间部分，标准化预览将保留该时间。",
    )
    _add_issue(
        issues,
        level=WARNING,
        code="date_contains_timezone",
        role="date",
        column_name=column_name,
        row_count=parsed.timezone_count,
        message=(
            "日期包含时区信息；有时区值统一转换为 UTC 后移除时区标记，"
            "无时区值保持原墙上时间，此规则不会按本地环境猜测。"
        ),
    )
    if len(valid) < 20:
        _add_issue(
            issues,
            level=WARNING,
            code="few_observations",
            role="date",
            column_name=column_name,
            row_count=len(valid),
            message="有效日期观察数量较少，请确认是否满足下一阶段协议。",
        )
    if len(valid) >= 3:
        positive_differences = valid.diff().dropna()
        positive_differences = positive_differences[
            positive_differences > pd.Timedelta(0)
        ]
        if positive_differences.nunique() > 1:
            _add_issue(
                issues,
                level=WARNING,
                code="date_irregular_intervals",
                role="date",
                column_name=column_name,
                row_count=len(positive_differences),
                message="日期间隔不规则；系统不会推断频率或重采样。",
            )
        if not positive_differences.empty:
            median_gap = positive_differences.median()
            long_gap_threshold = max(median_gap * 3, pd.Timedelta(days=7))
            long_gap_count = int((positive_differences > long_gap_threshold).sum())
            _add_issue(
                issues,
                level=WARNING,
                code="date_long_gap",
                role="date",
                column_name=column_name,
                row_count=long_gap_count,
                message="日期序列存在较长时间缺口；系统不会补充缺失日期。",
            )


def _numeric_agreement(
    left: pd.Series,
    right: pd.Series,
) -> tuple[float, int]:
    paired = pd.DataFrame(
        {
            "left": pd.to_numeric(left, errors="coerce"),
            "right": pd.to_numeric(right, errors="coerce"),
        }
    ).dropna()
    if paired.empty:
        return 1.0, 0
    finite_mask = paired.apply(
        lambda row: math.isfinite(float(row["left"]))
        and math.isfinite(float(row["right"])),
        axis=1,
    )
    paired = paired[finite_mask]
    if paired.empty:
        return 1.0, 0
    tolerance = 1e-6 + 1e-4 * paired.abs().max(axis=1)
    matches = (paired["left"] - paired["right"]).abs() <= tolerance
    return float(matches.mean()), len(paired)


def _add_cross_field_diagnostics(
    issues: list[StandardizationIssue],
    converted_by_role: Mapping[str, pd.Series],
    confirmed_mapping: ConfirmedMapping,
) -> None:
    strategy_nav = converted_by_role.get("strategy_nav")
    strategy_return = converted_by_role.get("strategy_return")
    if strategy_nav is not None and strategy_return is not None:
        temporary_nav = pd.to_numeric(strategy_nav, errors="coerce")
        derived_return = temporary_nav.pct_change(fill_method=None)
        agreement, count = _numeric_agreement(derived_return, strategy_return)
        if count >= 3 and agreement < 0.5:
            _add_issue(
                issues,
                level=WARNING,
                code="strategy_nav_return_mismatch",
                role=confirmed_mapping.primary_basis,
                column_name=confirmed_mapping.role_to_column.get(
                    confirmed_mapping.primary_basis
                ),
                row_count=count,
                message=(
                    "策略收益率与策略净值只读推导结果明显不一致；"
                    "主口径保持用户选择，系统不会判定哪一个更正确。"
                ),
            )

    drawdown = converted_by_role.get("drawdown")
    if strategy_nav is not None and drawdown is not None:
        temporary_nav = pd.to_numeric(strategy_nav, errors="coerce")
        derived_drawdown = temporary_nav / temporary_nav.cummax() - 1
        agreement, count = _numeric_agreement(derived_drawdown, drawdown)
        if count >= 3 and agreement < 0.5:
            _add_issue(
                issues,
                level=WARNING,
                code="drawdown_nav_mismatch",
                role="drawdown",
                column_name=confirmed_mapping.role_to_column.get("drawdown"),
                row_count=count,
                message=(
                    "回撤字段与策略净值只读推导结果明显不一致；"
                    "用户回撤不会覆盖未来系统计算。"
                ),
            )

    daily_ret = converted_by_role.get("daily_ret")
    if strategy_nav is not None and daily_ret is not None:
        temporary_nav = pd.to_numeric(strategy_nav, errors="coerce")
        derived_return = temporary_nav.pct_change(fill_method=None)
        agreement, count = _numeric_agreement(derived_return, daily_ret)
        if count >= 3 and agreement < 0.5:
            _add_issue(
                issues,
                level=WARNING,
                code="daily_ret_nav_mismatch",
                role="daily_ret",
                column_name=confirmed_mapping.role_to_column.get("daily_ret"),
                row_count=count,
                message=(
                    "daily_ret 与策略净值只读推导结果明显不一致；"
                    "系统不会覆盖任一字段，也不会推断差异原因。"
                ),
            )


def _add_diagnostic_role_checks(
    issues: list[StandardizationIssue],
    role: str,
    column_name: str,
    series: pd.Series,
) -> None:
    finite = _finite_numeric(series)
    if role in {"strategy_return", "benchmark_return", "daily_ret"}:
        _add_return_checks(
            issues,
            series,
            role=role,
            column_name=column_name,
            blocking_floor=False,
        )
    if role in {"strategy_nav", "benchmark_nav"}:
        _add_nav_checks(
            issues,
            series,
            role=role,
            column_name=column_name,
            primary=False,
        )
    if role == "drawdown" and not finite.empty:
        positive_count = int((finite > 0).sum())
        below_minus_one_count = int((finite < -1).sum())
        _add_issue(
            issues,
            level=WARNING,
            code="drawdown_positive",
            role=role,
            column_name=column_name,
            row_count=positive_count,
            message="回撤诊断字段存在正值；系统不会自动改为负值。",
        )
        _add_issue(
            issues,
            level=WARNING,
            code="drawdown_below_minus_one",
            role=role,
            column_name=column_name,
            row_count=below_minus_one_count,
            message="回撤诊断字段存在小于 -1 的值；系统不会截断或除以 100。",
        )
        if float((finite <= 0).mean()) < 0.5:
            _add_issue(
                issues,
                level=WARNING,
                code="drawdown_mostly_positive",
                role=role,
                column_name=column_name,
                row_count=len(finite),
                message="回撤字段大部分时间不在小于或等于 0 的范围。",
            )
        if len(finite) >= 5 and int(finite.nunique(dropna=True)) <= 2:
            _add_issue(
                issues,
                level=WARNING,
                code="drawdown_may_be_summary",
                role=role,
                column_name=column_name,
                row_count=len(finite),
                message="回撤字段更像汇总值而非逐期回撤序列，请人工核对。",
            )


def _add_mapping_warnings(
    issues: list[StandardizationIssue],
    confirmed_mapping: ConfirmedMapping,
) -> None:
    for warning in confirmed_mapping.warnings:
        if "与 B.2 首选建议" not in warning:
            continue
        role = next((item for item in ROLE_ORDER if warning.startswith(item)), None)
        _add_issue(
            issues,
            level=WARNING,
            code="mapping_differs_from_b2",
            role=role,
            column_name=(
                confirmed_mapping.role_to_column.get(role) if role else None
            ),
            row_count=1,
            message=warning,
        )
    if (
        confirmed_mapping.role_to_column.get("strategy_return")
        and confirmed_mapping.role_to_column.get("strategy_nav")
    ):
        _add_issue(
            issues,
            level=WARNING,
            code="multiple_strategy_basis_mapped",
            role=confirmed_mapping.primary_basis,
            column_name=confirmed_mapping.role_to_column.get(
                confirmed_mapping.primary_basis
            ),
            row_count=1,
            message=(
                "同时映射了策略收益率和策略净值；"
                "只有用户确认的主口径进入相应候选结构，另一字段仅用于诊断。"
            ),
        )


def standardize_confirmed_mapping(
    dataframe: pd.DataFrame,
    confirmed_mapping: ConfirmedMapping,
) -> StandardizationResult:
    """创建独立标准化预览，并执行结构和数据质量预检。"""

    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("dataframe 必须是 pandas.DataFrame")
    if not isinstance(confirmed_mapping, ConfirmedMapping):
        raise TypeError("confirmed_mapping 必须是 ConfirmedMapping")

    issues: list[StandardizationIssue] = []
    if confirmed_mapping.primary_basis not in PRIMARY_BASIS_OPTIONS:
        _add_issue(
            issues,
            level=BLOCKING,
            code="invalid_primary_basis",
            role=None,
            column_name=None,
            row_count=1,
            message="确认映射中的策略分析主口径无效。",
        )

    analysis_pairs = _analysis_role_pairs(confirmed_mapping)
    diagnostic_roles = _diagnostic_roles(confirmed_mapping, analysis_pairs)
    analysis_data: dict[str, pd.Series] = {}
    diagnostic_data: dict[str, pd.Series] = {}
    converted_by_role: dict[str, pd.Series] = {}
    source_index = dataframe.index.copy(deep=True)

    for role, target_name in analysis_pairs:
        column_name = confirmed_mapping.role_to_column.get(role)
        if not column_name:
            empty = (
                pd.Series(pd.NaT, index=source_index, name=target_name)
                if role == "date"
                else pd.Series(pd.NA, index=source_index, name=target_name, dtype="object")
            )
            analysis_data[target_name] = empty
            _add_issue(
                issues,
                level=BLOCKING,
                code="required_mapping_missing",
                role=role,
                column_name=None,
                row_count=len(dataframe) or 1,
                message=f"主口径必需角色 {role} 没有确认字段映射。",
            )
            continue
        source = _source_series(dataframe, column_name)
        if source is None:
            empty = (
                pd.Series(pd.NaT, index=source_index, name=target_name)
                if role == "date"
                else pd.Series(pd.NA, index=source_index, name=target_name, dtype="object")
            )
            analysis_data[target_name] = empty
            _add_issue(
                issues,
                level=BLOCKING,
                code="source_column_missing",
                role=role,
                column_name=column_name,
                row_count=len(dataframe) or 1,
                message=f"确认字段“{column_name}”在当前 DataFrame 中不存在或不唯一。",
            )
            continue
        if role == "date":
            parsed_date = _parse_date_series(source)
            analysis_data[target_name] = parsed_date.series
            _add_date_checks(issues, parsed_date, column_name=column_name)
            continue

        parsed_numeric = _parse_numeric_series(source, target_name)
        analysis_data[target_name] = parsed_numeric.series
        converted_by_role[role] = parsed_numeric.series
        _add_numeric_conversion_issues(
            issues,
            parsed_numeric,
            role=role,
            column_name=column_name,
            blocking=True,
        )
        if role in {"strategy_return", "benchmark_return"}:
            _add_return_checks(
                issues,
                parsed_numeric.series,
                role=role,
                column_name=column_name,
                blocking_floor=True,
            )
        elif role == "strategy_nav":
            _add_nav_checks(
                issues,
                parsed_numeric.series,
                role=role,
                column_name=column_name,
                primary=True,
            )
        elif role == "daily_ret":
            _add_return_checks(
                issues,
                parsed_numeric.series,
                role=role,
                column_name=column_name,
                blocking_floor=False,
            )

    for role in diagnostic_roles:
        column_name = confirmed_mapping.role_to_column.get(role)
        assert column_name is not None
        source = _source_series(dataframe, column_name)
        if source is None:
            diagnostic_data[role] = pd.Series(
                pd.NA,
                index=source_index,
                name=role,
                dtype="object",
            )
            _add_issue(
                issues,
                level=WARNING,
                code="diagnostic_source_column_missing",
                role=role,
                column_name=column_name,
                row_count=len(dataframe) or 1,
                message=f"诊断字段“{column_name}”在当前 DataFrame 中不存在或不唯一。",
            )
            continue
        parsed_numeric = _parse_numeric_series(source, role)
        diagnostic_data[role] = parsed_numeric.series
        converted_by_role[role] = parsed_numeric.series
        _add_numeric_conversion_issues(
            issues,
            parsed_numeric,
            role=role,
            column_name=column_name,
            blocking=False,
        )
        _add_diagnostic_role_checks(
            issues,
            role,
            column_name,
            parsed_numeric.series,
        )

    analysis_frame = pd.DataFrame(analysis_data, index=source_index.copy(deep=True))
    diagnostic_frame = pd.DataFrame(
        diagnostic_data,
        index=source_index.copy(deep=True),
    )
    if len(analysis_frame) != len(dataframe):
        _add_issue(
            issues,
            level=BLOCKING,
            code="row_count_changed",
            role=None,
            column_name=None,
            row_count=abs(len(analysis_frame) - len(dataframe)) or 1,
            message="标准化后行数与原始数据不一致。",
        )
    if not analysis_frame.index.equals(dataframe.index):
        _add_issue(
            issues,
            level=BLOCKING,
            code="index_or_order_changed",
            role=None,
            column_name=None,
            row_count=len(dataframe) or 1,
            message="标准化后索引或行顺序发生变化。",
        )

    _add_cross_field_diagnostics(issues, converted_by_role, confirmed_mapping)
    _add_mapping_warnings(issues, confirmed_mapping)
    mapping_key = build_mapping_key(confirmed_mapping)
    output_columns = tuple(analysis_frame.columns)
    standardization_key = build_standardization_key(
        confirmed_mapping.source_key,
        mapping_key,
        STANDARDIZATION_POLICY_VERSION,
        primary_basis=confirmed_mapping.primary_basis,
        output_columns=output_columns,
    )
    structure_type = (
        "收益率分析候选表"
        if confirmed_mapping.primary_basis == PRIMARY_BASIS_RETURN
        else "净值适配候选表"
    )
    return StandardizationResult(
        source_key=confirmed_mapping.source_key,
        mapping_key=mapping_key,
        standardization_key=standardization_key,
        policy_version=STANDARDIZATION_POLICY_VERSION,
        confirmed_mapping=confirmed_mapping,
        primary_basis=confirmed_mapping.primary_basis,
        structure_type=structure_type,
        analysis_frame=analysis_frame,
        diagnostic_frame=diagnostic_frame,
        issues=tuple(issues),
        is_preview_valid=not any(issue.level == BLOCKING for issue in issues),
        source_row_count=len(dataframe),
        row_count=len(analysis_frame),
        column_count=len(analysis_frame.columns),
    )


def is_standardization_result_current(
    result: StandardizationResult | None,
    confirmed_mapping: ConfirmedMapping,
) -> bool:
    """判断会话预览是否仍与当前来源、映射和策略版本完全一致。"""

    if not isinstance(result, StandardizationResult):
        return False
    mapping_key = build_mapping_key(confirmed_mapping)
    expected_key = build_standardization_key(
        confirmed_mapping.source_key,
        mapping_key,
        STANDARDIZATION_POLICY_VERSION,
        primary_basis=confirmed_mapping.primary_basis,
        output_columns=analysis_output_columns(confirmed_mapping),
    )
    return bool(
        result.source_key == confirmed_mapping.source_key
        and result.mapping_key == mapping_key
        and result.standardization_key == expected_key
        and result.policy_version == STANDARDIZATION_POLICY_VERSION
    )
