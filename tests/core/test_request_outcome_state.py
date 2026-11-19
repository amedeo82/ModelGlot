from free_claude_code.core.request_outcomes import (
    RequestOutcome,
    current_request_outcome,
    finalize_request_outcome,
    record_estimated_input_tokens,
    record_request_failure,
    record_request_gateway_model,
    record_request_observation,
    record_request_route,
)


def test_route_gateway_estimate_and_first_failure_are_request_local():
    outcome = RequestOutcome()
    token = current_request_outcome.set(outcome)
    try:
        record_request_route("provider-a", "model-a")
        record_request_gateway_model("gateway/model")
        record_estimated_input_tokens(120)
        record_request_failure("first")
        record_request_failure("second")
        record_request_route("provider-b", "model-b")
    finally:
        current_request_outcome.reset(token)

    assert outcome.provider_id == "provider-b"
    assert outcome.model == "model-b"
    assert outcome.gateway_model == "gateway/model"
    assert outcome.estimated_input_tokens == 120
    assert outcome.failure_reason == "first"


def test_observations_are_deduplicated_bounded_and_finalized():
    outcome = RequestOutcome()
    token = current_request_outcome.set(outcome)
    try:
        first = object()
        assert record_request_observation("execution", 1, first)
        assert not record_request_observation("execution", 1, object())
        assert record_request_observation("execution", 2, object())
        snapshot = finalize_request_outcome(outcome)
        assert not record_request_observation("execution", 3, object())
    finally:
        current_request_outcome.reset(token)

    assert snapshot == (first, outcome.observations[1])
    assert outcome.finalized


def test_observation_limit_and_invalid_estimate_do_not_invent_values():
    outcome = RequestOutcome()
    token = current_request_outcome.set(outcome)
    try:
        assert record_request_observation("execution", 1, object(), limit=1)
        assert not record_request_observation("execution", 2, object(), limit=1)
        for invalid in (True, -1, 1.5, "10"):
            record_estimated_input_tokens(invalid)
    finally:
        current_request_outcome.reset(token)
    assert outcome.estimated_input_tokens is None
    assert len(outcome.observations) == 1
