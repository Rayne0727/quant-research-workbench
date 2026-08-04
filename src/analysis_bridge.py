"""Bridge validated B.4A previews into the existing strict analysis protocols.

This module owns request identity and protocol gates only.  It deliberately
does not import performance, reporting, charting, export, or Streamlit code.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Final, Mapping, Sequence

import pandas as pd

from src.adapters import (
    DailyReturnDiagnostics,
    WeeklyNavValidationError,
    adapt_weekly_nav_data,
)
from src.data_loader import DataValidationError, validate_returns_data
from src.field_mapping import PRIMARY_BASIS_NAV, PRIMARY_BASIS_RETURN
from src.standardization import (
    StandardizationResult,
    is_standardization_result_current,
)


ANALYSIS_BRIDGE_VERSION: Final = "b4b-analysis-bridge-v1"
STRICT_RETURN_PROTOCOL_VERSION: Final = "standard-daily-return-v1"
STRICT_NAV_PROTOCOL_VERSION: Final = "weekly-nav-protocol-v1"
NAV_ADAPTER_VERSION: Final = "weekly-nav-adapter-v1"
RETURN_PROTOCOL_NAME: Final = "标准日收益协议"
NAV_PROTOCOL_NAME: Final = "净值适配协议"


class AnalysisBridgeValidationError(ValueError):
    """表示尚未满足 B.4B 严格验证入口条件。"""


@dataclass(frozen=True)
class GenericAnalysisRequest:
    """绑定来源、映射、标准化结果和现有协议的分析请求。"""

    source_key: str
    mapping_key: str
    standardization_key: str
    primary_basis: str
    protocol_name: str
    protocol_version: str
    adapter_version: str
    bridge_version: str
    analysis_input_columns: tuple[str, ...]
    analysis_request_key: str


@dataclass(frozen=True)
class StrictProtocolResult:
    """现有严格协议的验证结果，不包含任何绩效计算。"""

    analysis_request_key: str
    source_key: str
    mapping_key: str
    standardization_key: str
    primary_basis: str
    protocol_name: str
    protocol_version: str
    adapter_version: str
    bridge_version: str
    analysis_input_columns: tuple[str, ...]
    is_valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    validated_frame: pd.DataFrame | None
    adapter_diagnostics: DailyReturnDiagnostics | None
    row_count: int
    valid_observation_count: int
    date_start: pd.Timestamp | None
    date_end: pd.Timestamp | None
    has_benchmark: bool


def _sha256_payload(payload: Mapping[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _default_input_columns(primary_basis: str) -> tuple[str, ...]:
    if primary_basis == PRIMARY_BASIS_RETURN:
        return ("date", "strategy_return")
    if primary_basis == PRIMARY_BASIS_NAV:
        return ("date", "nav_strat")
    return ()


def build_analysis_request_key(
    standardization_key: str,
    primary_basis: str,
    protocol_version: str,
    *,
    adapter_version: str = NAV_ADAPTER_VERSION,
    bridge_version: str = ANALYSIS_BRIDGE_VERSION,
    input_columns: Sequence[str] | None = None,
) -> str:
    """为标准化结果和现有协议配置生成稳定 SHA-256 标识。"""

    ordered_columns = tuple(
        input_columns
        if input_columns is not None
        else _default_input_columns(primary_basis)
    )
    return _sha256_payload(
        {
            "standardization_key": str(standardization_key),
            "primary_basis": str(primary_basis),
            "protocol_version": str(protocol_version),
            "adapter_version": str(adapter_version),
            "bridge_version": str(bridge_version),
            "analysis_input_columns": list(ordered_columns),
        }
    )


def _protocol_details(primary_basis: str) -> tuple[str, str]:
    if primary_basis == PRIMARY_BASIS_RETURN:
        return RETURN_PROTOCOL_NAME, STRICT_RETURN_PROTOCOL_VERSION
    if primary_basis == PRIMARY_BASIS_NAV:
        return NAV_PROTOCOL_NAME, STRICT_NAV_PROTOCOL_VERSION
    raise AnalysisBridgeValidationError("当前主口径不受 B.4B 严格协议支持。")


def build_generic_analysis_request(
    standardization_result: StandardizationResult,
    *,
    protocol_version: str | None = None,
    adapter_version: str = NAV_ADAPTER_VERSION,
    bridge_version: str = ANALYSIS_BRIDGE_VERSION,
) -> GenericAnalysisRequest:
    """根据当前 B.4A 结果创建只含标识和协议信息的请求。"""

    if not isinstance(standardization_result, StandardizationResult):
        raise AnalysisBridgeValidationError("标准化预览不存在，请先生成预览。")
    if not standardization_result.is_preview_valid:
        raise AnalysisBridgeValidationError(
            "标准化预检未通过，当前不能执行严格协议验证。"
        )
    if not is_standardization_result_current(
        standardization_result,
        standardization_result.confirmed_mapping,
    ):
        raise AnalysisBridgeValidationError(
            "标准化结果已失效，请重新生成标准化预览。"
        )

    protocol_name, default_protocol_version = _protocol_details(
        standardization_result.primary_basis
    )
    resolved_protocol_version = protocol_version or default_protocol_version
    input_columns = tuple(str(column) for column in standardization_result.analysis_frame.columns)
    request_key = build_analysis_request_key(
        standardization_result.standardization_key,
        standardization_result.primary_basis,
        resolved_protocol_version,
        adapter_version=adapter_version,
        bridge_version=bridge_version,
        input_columns=input_columns,
    )
    return GenericAnalysisRequest(
        source_key=standardization_result.source_key,
        mapping_key=standardization_result.mapping_key,
        standardization_key=standardization_result.standardization_key,
        primary_basis=standardization_result.primary_basis,
        protocol_name=protocol_name,
        protocol_version=resolved_protocol_version,
        adapter_version=adapter_version,
        bridge_version=bridge_version,
        analysis_input_columns=input_columns,
        analysis_request_key=request_key,
    )


def _adapter_warnings(
    diagnostics: DailyReturnDiagnostics | None,
) -> tuple[str, ...]:
    if diagnostics is None or diagnostics.mismatch_count == 0:
        return ()
    return (
        "daily_ret 与净值推导收益存在不一致；当前分析继续以 nav_strat 为主。",
    )


def _date_bounds(
    data: pd.DataFrame | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if data is None or data.empty or "date" not in data.columns:
        return None, None
    return pd.Timestamp(data["date"].iloc[0]), pd.Timestamp(data["date"].iloc[-1])


def _invalid_result(
    request: GenericAnalysisRequest,
    source_row_count: int,
    message: str,
) -> StrictProtocolResult:
    return StrictProtocolResult(
        analysis_request_key=request.analysis_request_key,
        source_key=request.source_key,
        mapping_key=request.mapping_key,
        standardization_key=request.standardization_key,
        primary_basis=request.primary_basis,
        protocol_name=request.protocol_name,
        protocol_version=request.protocol_version,
        adapter_version=request.adapter_version,
        bridge_version=request.bridge_version,
        analysis_input_columns=request.analysis_input_columns,
        is_valid=False,
        errors=(message,),
        warnings=(),
        validated_frame=None,
        adapter_diagnostics=None,
        row_count=source_row_count,
        valid_observation_count=0,
        date_start=None,
        date_end=None,
        has_benchmark=False,
    )


def validate_standardized_result(
    standardization_result: StandardizationResult,
    *,
    protocol_version: str | None = None,
    adapter_version: str = NAV_ADAPTER_VERSION,
    bridge_version: str = ANALYSIS_BRIDGE_VERSION,
) -> StrictProtocolResult:
    """把 B.4A 候选表交给现有严格协议，仅返回验证结果。"""

    request = build_generic_analysis_request(
        standardization_result,
        protocol_version=protocol_version,
        adapter_version=adapter_version,
        bridge_version=bridge_version,
    )
    source_frame = standardization_result.analysis_frame
    source_copy = source_frame.copy(deep=True)
    try:
        if request.primary_basis == PRIMARY_BASIS_RETURN:
            validated_frame = validate_returns_data(source_copy)
            diagnostics = None
            valid_observations = len(validated_frame)
        else:
            adapter_result = adapt_weekly_nav_data(source_copy)
            validated_frame = adapter_result.data
            diagnostics = adapter_result.diagnostics
            valid_observations = int(validated_frame["strategy_return"].notna().sum())
    except (DataValidationError, WeeklyNavValidationError) as exc:
        return _invalid_result(request, len(source_frame), str(exc))

    date_start, date_end = _date_bounds(validated_frame)
    return StrictProtocolResult(
        analysis_request_key=request.analysis_request_key,
        source_key=request.source_key,
        mapping_key=request.mapping_key,
        standardization_key=request.standardization_key,
        primary_basis=request.primary_basis,
        protocol_name=request.protocol_name,
        protocol_version=request.protocol_version,
        adapter_version=request.adapter_version,
        bridge_version=request.bridge_version,
        analysis_input_columns=request.analysis_input_columns,
        is_valid=True,
        errors=(),
        warnings=_adapter_warnings(diagnostics),
        validated_frame=validated_frame,
        adapter_diagnostics=diagnostics,
        row_count=len(source_frame),
        valid_observation_count=valid_observations,
        date_start=date_start,
        date_end=date_end,
        has_benchmark="benchmark_return" in validated_frame.columns,
    )


def is_strict_protocol_result_current(
    strict_result: StrictProtocolResult,
    standardization_result: StandardizationResult,
) -> bool:
    """检查严格验证结果是否仍绑定当前标准化结果和协议版本。"""

    if not isinstance(strict_result, StrictProtocolResult):
        return False
    try:
        request = build_generic_analysis_request(standardization_result)
    except AnalysisBridgeValidationError:
        return False
    return bool(
        strict_result.analysis_request_key == request.analysis_request_key
        and strict_result.source_key == request.source_key
        and strict_result.mapping_key == request.mapping_key
        and strict_result.standardization_key == request.standardization_key
        and strict_result.primary_basis == request.primary_basis
    )


def build_generic_analysis_input(
    strict_protocol_result: StrictProtocolResult,
) -> pd.DataFrame:
    """为用户最终确认后的现有分析流程返回独立 DataFrame 副本。"""

    if not isinstance(strict_protocol_result, StrictProtocolResult):
        raise AnalysisBridgeValidationError("严格协议验证结果不存在。")
    if not strict_protocol_result.is_valid or strict_protocol_result.validated_frame is None:
        raise AnalysisBridgeValidationError(
            "现有严格协议验证未通过，当前不能进入绩效分析。"
        )
    return strict_protocol_result.validated_frame.copy(deep=True)
