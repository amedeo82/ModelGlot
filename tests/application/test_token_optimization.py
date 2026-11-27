import json
import math
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from modelglot.application.token_optimization import (
    OptimizationReportError,
    OptimizationState,
    parse_headroom_report,
    parse_rtk_report,
    parse_tool_version,
    token_optimization_payload,
    unavailable_headroom,
    unavailable_rtk,
    utc_timestamp,
)
from modelglot.core.json_types import (
    JsonObject,
    JsonValue,
    json_array,
    json_object,
    load_json_value,
)

FIXTURES = Path(__file__).parent / "fixtures" / "token_optimization"
FORBIDDEN_FIXTURE_KEYS = {"path", "command", "prompt", "authorization", "api_key"}


def _walk_keys(value: JsonValue) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_every_json_fixture_is_sanitized_and_valid():
    fixtures = sorted(FIXTURES.glob("*.json"))
    assert fixtures
    for fixture in fixtures:
        value = load_json_value(fixture.read_text(encoding="utf-8"))
        assert FORBIDDEN_FIXTURE_KEYS.isdisjoint(_walk_keys(value)), fixture.name


@pytest.mark.parametrize(
    ("fixture", "commands", "before", "after", "saved", "percent"),
    [
        ("rtk_populated.json", 29, 19009, 10289, 8720, 45.87300752275238),
        ("rtk_zero.json", 0, 0, 0, 0, 0.0),
        ("rtk_extra_fields.json", 2, 200, 120, 80, 40.0),
    ],
)
def test_rtk_observed_reports(
    fixture: str,
    commands: int,
    before: int,
    after: int,
    saved: int,
    percent: float,
) -> None:
    report = parse_rtk_report(
        (FIXTURES / fixture).read_text(encoding="utf-8"), version="0.44.2"
    )
    assert report.state is OptimizationState.AVAILABLE
    assert report.total_commands == commands
    assert report.tokens_before == before
    assert report.tokens_after == after
    assert report.tokens_saved == saved
    assert report.savings_percent == percent
    assert report.as_dict()["basis"] == "tool_reported"


def test_rtk_missing_values_remain_unknown():
    report = parse_rtk_report((FIXTURES / "rtk_missing_fields.json").read_bytes())
    assert report.tokens_saved is None
    assert report.savings_percent is None
    assert report.total_commands == 3


@pytest.mark.parametrize(
    "summary",
    [
        {"total_commands": True},
        {"total_commands": -1},
        {"total_commands": 1.5},
        {"total_commands": "1"},
        {"total_input": math.inf},
        {"total_output": math.nan},
        {"avg_savings_pct": -0.1},
    ],
)
def test_rtk_rejects_invalid_counts(summary: JsonObject) -> None:
    with pytest.raises(OptimizationReportError):
        parse_rtk_report({"summary": summary})


def test_headroom_populated_zero_and_private_fields_are_sanitized():
    populated = json_object(
        load_json_value((FIXTURES / "headroom_populated.json").read_text())
    )
    populated.update(
        {
            "path": "C:/private/ledger.jsonl",
            "prompt": "private",
            "authorization": "secret",
        }
    )
    report = parse_headroom_report(populated, version="0.40.0")
    assert report.tokens_saved == 4200
    assert report.tokens_before == 12000
    assert report.calls == 18
    assert report.model_attribution == "provider/example-model"
    serialized = json.dumps(report.as_dict())
    assert "private" not in serialized
    assert "secret" not in serialized
    assert "cost" not in serialized
    assert "path" not in serialized

    zero = parse_headroom_report((FIXTURES / "headroom_zero.json").read_bytes())
    assert zero.state is OptimizationState.AVAILABLE
    assert zero.tokens_saved == 0
    assert zero.calls == 0
    assert zero.model_attribution == "unknown"


def test_headroom_missing_fields_and_extra_fields_are_tolerated():
    missing = parse_headroom_report(
        (FIXTURES / "headroom_missing_fields.json").read_text()
    )
    assert missing.calls is None
    assert missing.savings_percent is None
    extra = parse_headroom_report((FIXTURES / "headroom_extra_fields.json").read_text())
    assert extra.tokens_saved == 15
    assert "future_metric" not in extra.as_dict()


@pytest.mark.parametrize("tool", ["rtk", "headroom"])
def test_malformed_json_and_schema_raise_controlled_errors(tool: str) -> None:
    with pytest.raises(OptimizationReportError):
        parser = parse_rtk_report if tool == "rtk" else parse_headroom_report
        parser((FIXTURES / f"{tool}_malformed_json.txt").read_bytes())
    with pytest.raises(OptimizationReportError):
        parser = parse_rtk_report if tool == "rtk" else parse_headroom_report
        parser((FIXTURES / f"{tool}_malformed_schema.json").read_bytes())


@pytest.mark.parametrize("payload", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_constants_are_rejected(payload: str) -> None:
    with pytest.raises(OptimizationReportError):
        parse_rtk_report(payload)


def test_daily_trend_is_sorted_validated_and_explicitly_tool_reported() -> None:
    payload = json_object(
        load_json_value((FIXTURES / "rtk_daily_populated.json").read_text())
    )
    json_array(payload["daily"]).reverse()
    report = parse_rtk_report(payload)
    assert report.daily is not None
    assert [row.day.isoformat() for row in report.daily] == [
        "2026-11-12",
        "2026-11-13",
    ]
    daily = json_array(report.as_dict()["daily"])
    assert json_object(daily[0])["basis"] == "tool_reported"

    with pytest.raises(OptimizationReportError):
        parse_rtk_report({"summary": {}, "daily": [{"date": "not-a-date"}]})
    with pytest.raises(OptimizationReportError):
        parse_rtk_report(
            {
                "summary": {},
                "daily": [{"date": "2026-11-12"}, {"date": "2026-11-12"}],
            }
        )


def test_daily_trend_is_empty_or_bounded_to_latest_31_days():
    empty = parse_rtk_report((FIXTURES / "rtk_daily_zero.json").read_bytes())
    assert empty.daily == ()
    payload: JsonObject = {
        "summary": {},
        "daily": [
            {"date": f"2026-10-{day:02d}", "saved_tokens": day} for day in range(1, 32)
        ]
        + [{"date": "2026-11-01", "saved_tokens": 32}],
    }
    report = parse_rtk_report(payload)
    daily = report.daily
    assert daily is not None
    assert len(daily) == 31
    assert daily[0].day.isoformat() == "2026-10-02"
    assert daily[-1].day.isoformat() == "2026-11-01"


def test_unavailable_serialization_has_stable_shape_and_safe_message():
    report = unavailable_rtk(OptimizationState.NOT_INSTALLED, "RTK is not installed.")
    assert report.as_dict() == {
        "state": "not_installed",
        "version": None,
        "source": "rtk gain --format json",
        "basis": "tool_reported",
        "total_commands": None,
        "tokens_before": None,
        "tokens_after": None,
        "tokens_saved": None,
        "savings_percent": None,
        "message": "RTK is not installed.",
    }
    headroom = unavailable_headroom(OptimizationState.TIMEOUT, "Headroom timed out.")
    assert headroom.as_dict()["state"] == "timeout"
    assert headroom.as_dict()["model_attribution"] is None


def test_version_and_timestamp_helpers_bound_external_text():
    assert parse_tool_version("rtk 0.44.2\n") == "0.44.2"
    assert parse_tool_version("v0.40.0") == "0.40.0"
    assert parse_tool_version("unrecognized arbitrary local details") is None
    assert parse_tool_version(b"\xff") is None
    assert utc_timestamp(datetime(2026, 11, 17, 13, 0, tzinfo=UTC)) == (
        "2026-11-17T13:00:00.000Z"
    )


def test_top_level_payload_is_versioned_and_does_not_add_savings():
    payload = token_optimization_payload(
        rtk=parse_rtk_report((FIXTURES / "rtk_populated.json").read_text()),
        headroom=parse_headroom_report((FIXTURES / "headroom_zero.json").read_text()),
        generated_at=datetime(2026, 11, 17, 12, 0, tzinfo=UTC),
    )
    assert payload["schema_version"] == 1
    assert payload["generated_at"] == "2026-11-17T12:00:00.000Z"
    assert set(json_object(payload["optimizations"])) == {"rtk", "headroom"}
    assert "total_tokens_saved" not in payload
    notices = json_array(payload["notices"])
    assert isinstance(notices[0], str)
    assert "not additive" in notices[0]
