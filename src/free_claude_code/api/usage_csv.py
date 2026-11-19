"""Deterministic, bounded CSV projection of the visible Admin usage rows."""

import csv
import io
from collections.abc import Mapping

_TOKEN_FIELDS = (
    "input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "input_total_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)
_COLUMNS = (
    "day",
    "provider_id",
    "gateway_model",
    "provider_model",
    "request_count",
    "successful_count",
    "failed_count",
    "cancelled_count",
    "physical_attempt_count",
    "failed_attempt_count",
    *_TOKEN_FIELDS,
    "estimated_input_tokens",
    *(f"{field}_reported_count" for field in _TOKEN_FIELDS),
    "estimated_input_tokens_reported_count",
    "duration_average_ms",
    "duration_maximum_ms",
    "duration_reported_count",
    "token_basis",
    "estimated_basis",
    "coverage_start",
    "coverage_end",
    "generated_at",
    "retention_days",
)


def _safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    # Neutralize formulas even after leading whitespace/control characters.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text[:1] in {
        "\t",
        "\r",
        "\n",
    }:
        return f"'{text}"
    return text


def usage_csv(payload: Mapping[str, object]) -> bytes:
    """Serialize at most the same 5,000 rows exposed by the JSON response."""

    rows = payload.get("rows", [])
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError("invalid bounded usage rows")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(_COLUMNS)
    for row in rows[:5000]:
        if not isinstance(row, dict):
            raise ValueError("invalid usage row")
        duration = row.get("duration_ms") or {}
        reported = row.get("reported_counts") or {}
        values: dict[str, object] = {
            key: row.get(key)
            for key in (
                "day",
                "provider_id",
                "gateway_model",
                "provider_model",
                "request_count",
                "successful_count",
                "failed_count",
                "cancelled_count",
                "physical_attempt_count",
                "failed_attempt_count",
                *_TOKEN_FIELDS,
                "estimated_input_tokens",
                "token_basis",
                "estimated_basis",
            )
        }
        values.update(
            {
                "duration_average_ms": duration.get("average"),
                "duration_maximum_ms": duration.get("maximum"),
                "duration_reported_count": duration.get("reported_count"),
                "coverage_start": payload.get("coverage_start"),
                "coverage_end": payload.get("coverage_end"),
                "generated_at": payload.get("generated_at"),
                "retention_days": payload.get("retention_days"),
            }
        )
        for field in (*_TOKEN_FIELDS, "estimated_input_tokens"):
            values[f"{field}_reported_count"] = reported.get(field)
        writer.writerow([_safe_cell(values.get(column)) for column in _COLUMNS])
    return output.getvalue().encode("utf-8")
