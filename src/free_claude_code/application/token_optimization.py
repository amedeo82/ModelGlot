"""Typed, JSON-safe reports for external token optimization tools.

This module deliberately has no process, filesystem, or HTTP dependencies.  The
runtime collector owns command execution; these models expose only the small,
sanitized subset of each tool's report that Admin is allowed to display.
"""

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import NoReturn, cast

from free_claude_code.core.json_types import JsonObject, JsonValue


class OptimizationState(StrEnum):
    AVAILABLE = "available"
    NOT_INSTALLED = "not_installed"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    ERROR = "error"


class OptimizationReportError(ValueError):
    """The external report does not satisfy the public, sanitized schema."""


def _invalid(reason: str) -> NoReturn:
    raise OptimizationReportError(reason)


def _mapping(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, dict):
        _invalid(f"{field_name} must be an object")
    return cast(JsonObject, value)


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _invalid(f"{field_name} must be a non-negative integer or null")
    return value


def _optional_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        _invalid(f"{field_name} must be a non-negative finite number or null")
    return float(value)


def _optional_version(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _invalid("version must be a string or null")
    normalized = value.strip()
    if not normalized:
        return None
    # Version commands differ in decoration ("rtk 0.44.2" vs "0.44.2").
    # Return only a bounded token and never arbitrary command output.
    token = normalized.split()[0].removeprefix("v")
    if len(token) > 64 or any(character not in "0123456789.+-" for character in token):
        return None
    return token


def parse_tool_version(output: str | bytes) -> str | None:
    """Extract a bounded version token, or return unknown for unusual output."""

    try:
        text = (
            output.decode("utf-8", errors="strict")
            if isinstance(output, bytes)
            else output
        )
    except UnicodeDecodeError:
        return None
    if not isinstance(text, str):
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        for part in (parts[-1], parts[0]):
            candidate = part.removeprefix("v")
            if candidate and candidate[0].isdigit():
                return _optional_version(candidate)
    return None


def _decode_json(payload: str | bytes | dict[str, JsonValue]) -> JsonObject:
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, (str, bytes)):
        _invalid("report must be JSON text or an object")
    try:
        value: JsonValue = json.loads(
            payload,
            parse_constant=lambda constant: _invalid(
                f"non-finite JSON number: {constant}"
            ),
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OptimizationReportError("report is not valid UTF-8 JSON") from exc
    return _mapping(value, "report")


@dataclass(frozen=True, slots=True)
class RTKDailyReport:
    day: date
    commands: int | None
    tokens_before: int | None
    tokens_after: int | None
    tokens_saved: int | None
    savings_percent: float | None

    def as_dict(self) -> JsonObject:
        return {
            "date": self.day.isoformat(),
            "commands": self.commands,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "savings_percent": self.savings_percent,
            "basis": "tool_reported",
        }


@dataclass(frozen=True, slots=True)
class RTKOptimizationReport:
    state: OptimizationState
    version: str | None = None
    total_commands: int | None = None
    tokens_before: int | None = None
    tokens_after: int | None = None
    tokens_saved: int | None = None
    savings_percent: float | None = None
    message: str | None = None
    daily: tuple[RTKDailyReport, ...] | None = None

    @property
    def source(self) -> str:
        return "rtk gain --format json"

    def as_dict(self) -> JsonObject:
        result: JsonObject = {
            "state": self.state.value,
            "version": self.version,
            "source": self.source,
            "basis": "tool_reported",
            "total_commands": self.total_commands,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "savings_percent": self.savings_percent,
            "message": self.message,
        }
        if self.daily is not None:
            result["daily"] = [row.as_dict() for row in self.daily]
        return result


@dataclass(frozen=True, slots=True)
class HeadroomOptimizationReport:
    state: OptimizationState
    version: str | None = None
    tokens_saved: int | None = None
    tokens_before: int | None = None
    calls: int | None = None
    savings_percent: float | None = None
    model_attribution: str | None = "unknown"
    message: str | None = None

    @property
    def source(self) -> str:
        return "headroom savings --json"

    def as_dict(self) -> JsonObject:
        return {
            "state": self.state.value,
            "version": self.version,
            "source": self.source,
            "basis": "tool_reported",
            "tokens_saved": self.tokens_saved,
            "tokens_before": self.tokens_before,
            "calls": self.calls,
            "savings_percent": self.savings_percent,
            "model_attribution": self.model_attribution,
            "message": self.message,
        }


def unavailable_rtk(
    state: OptimizationState, message: str, *, version: str | None = None
) -> RTKOptimizationReport:
    if state is OptimizationState.AVAILABLE:
        raise ValueError("available reports must be parsed from tool output")
    return RTKOptimizationReport(state=state, version=version, message=message)


def unavailable_headroom(
    state: OptimizationState, message: str, *, version: str | None = None
) -> HeadroomOptimizationReport:
    if state is OptimizationState.AVAILABLE:
        raise ValueError("available reports must be parsed from tool output")
    return HeadroomOptimizationReport(
        state=state, version=version, message=message, model_attribution=None
    )


def _parse_rtk_daily(value: object) -> tuple[RTKDailyReport, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        _invalid("daily must be an array")
    rows: list[RTKDailyReport] = []
    seen: set[date] = set()
    for index, item in enumerate(value):
        row = _mapping(item, f"daily[{index}]")
        raw_day = row.get("date")
        if not isinstance(raw_day, str):
            _invalid(f"daily[{index}].date must be an ISO date")
        try:
            day = date.fromisoformat(raw_day)
        except ValueError as exc:
            raise OptimizationReportError("daily date must be an ISO date") from exc
        if day in seen:
            _invalid("daily dates must be unique")
        seen.add(day)
        rows.append(
            RTKDailyReport(
                day=day,
                commands=_optional_int(row.get("commands"), "daily.commands"),
                tokens_before=_optional_int(
                    row.get("input_tokens"), "daily.input_tokens"
                ),
                tokens_after=_optional_int(
                    row.get("output_tokens"), "daily.output_tokens"
                ),
                tokens_saved=_optional_int(
                    row.get("saved_tokens"), "daily.saved_tokens"
                ),
                savings_percent=_optional_float(
                    row.get("savings_pct"), "daily.savings_pct"
                ),
            )
        )
    return tuple(sorted(rows, key=lambda row: row.day)[-31:])


def parse_rtk_report(
    payload: str | bytes | dict[str, JsonValue], *, version: str | None = None
) -> RTKOptimizationReport:
    report = _decode_json(payload)
    summary = _mapping(report.get("summary"), "summary")
    return RTKOptimizationReport(
        state=OptimizationState.AVAILABLE,
        version=version,
        total_commands=_optional_int(summary.get("total_commands"), "total_commands"),
        tokens_before=_optional_int(summary.get("total_input"), "total_input"),
        tokens_after=_optional_int(summary.get("total_output"), "total_output"),
        tokens_saved=_optional_int(summary.get("total_saved"), "total_saved"),
        savings_percent=_optional_float(
            summary.get("avg_savings_pct"), "avg_savings_pct"
        ),
        daily=_parse_rtk_daily(report.get("daily")),
    )


def parse_headroom_report(
    payload: str | bytes | dict[str, JsonValue], *, version: str | None = None
) -> HeadroomOptimizationReport:
    report = _decode_json(payload)
    lifetime = _mapping(report.get("lifetime"), "lifetime")
    model = report.get("top_model", "unknown")
    if model is not None and not isinstance(model, str):
        _invalid("top_model must be a string or null")
    # Deliberately do not copy path, windows, by_client, prices, or ledger data.
    return HeadroomOptimizationReport(
        state=OptimizationState.AVAILABLE,
        version=version,
        tokens_saved=_optional_int(lifetime.get("tokens_saved"), "tokens_saved"),
        tokens_before=_optional_int(lifetime.get("tokens_before"), "tokens_before"),
        calls=_optional_int(lifetime.get("calls"), "calls"),
        savings_percent=_optional_float(
            lifetime.get("savings_percent"), "savings_percent"
        ),
        model_attribution=model or "unknown",
    )


def utc_timestamp(value: datetime) -> str:
    """Serialize an aware/naive clock value as a canonical UTC RFC3339 value."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def token_optimization_payload(
    *,
    rtk: RTKOptimizationReport,
    headroom: HeadroomOptimizationReport,
    generated_at: datetime,
) -> JsonObject:
    notices = [
        "RTK and Headroom use separate, potentially overlapping ledgers; their savings are not additive.",
        "Tool-reported savings are not provider-reported usage or a billing statement.",
    ]
    return {
        "schema_version": 1,
        "generated_at": utc_timestamp(generated_at),
        "optimizations": {"rtk": rtk.as_dict(), "headroom": headroom.as_dict()},
        "notices": notices,
    }
