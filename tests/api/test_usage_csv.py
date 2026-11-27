import csv
import io

from modelglot.api.usage_csv import usage_csv


def _payload():
    return {
        "coverage_start": "2026-11-01T00:00:00.000Z",
        "coverage_end": "2026-11-18T12:00:00.000Z",
        "generated_at": "2026-11-18T12:00:00.000Z",
        "retention_days": 30,
        "rows": [
            {
                "day": "2026-11-18",
                "provider_id": "=unsafe",
                "gateway_model": "provider/model",
                "provider_model": "@model",
                "request_count": 1,
                "successful_count": 1,
                "failed_count": 0,
                "cancelled_count": 0,
                "physical_attempt_count": 1,
                "failed_attempt_count": 0,
                "input_tokens": None,
                "cache_read_tokens": 0,
                "cache_creation_tokens": None,
                "input_total_tokens": 10,
                "output_tokens": 5,
                "reasoning_tokens": None,
                "total_tokens": 15,
                "estimated_input_tokens": 12,
                "reported_counts": {
                    "input_tokens": 0,
                    "cache_read_tokens": 1,
                    "cache_creation_tokens": 0,
                    "input_total_tokens": 1,
                    "output_tokens": 1,
                    "reasoning_tokens": 0,
                    "total_tokens": 1,
                    "estimated_input_tokens": 1,
                },
                "duration_ms": {
                    "average": 12.5,
                    "maximum": 12.5,
                    "reported_count": 1,
                },
                "token_basis": "provider_reported",
                "estimated_basis": "estimated",
            }
        ],
    }


def test_usage_csv_has_stable_columns_values_coverage_and_formula_escaping():
    content = usage_csv(_payload())
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    assert len(rows) == 1
    row = rows[0]
    assert row["provider_id"] == "'=unsafe"
    assert row["provider_model"] == "'@model"
    assert row["input_tokens"] == ""
    assert row["cache_read_tokens"] == "0"
    assert row["output_tokens"] == "5"
    assert row["estimated_basis"] == "estimated"
    assert row["coverage_start"] == "2026-11-01T00:00:00.000Z"
    assert row["retention_days"] == "30"
    assert list(rows[0])[:4] == [
        "day",
        "provider_id",
        "gateway_model",
        "provider_model",
    ]


def test_usage_csv_empty_and_unicode():
    payload = _payload()
    assert (
        len(list(csv.reader(io.StringIO(usage_csv({**payload, "rows": []}).decode()))))
        == 1
    )
    payload["rows"][0]["gateway_model"] = "provider/model-☃"
    assert "model-☃" in usage_csv(payload).decode("utf-8")
