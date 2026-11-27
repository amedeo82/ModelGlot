"""Request-scoped diagnostic fields shared by routing and HTTP delivery."""

from contextvars import ContextVar
from dataclasses import dataclass, field

from .failures import find_execution_failure


@dataclass
class RequestOutcome:
    """Mutable fields shared with the request's response and cleanup tasks."""

    provider_id: str | None = None
    model: str | None = None
    gateway_model: str | None = None
    failure_reason: str | None = None
    estimated_input_tokens: int | None = None
    observations: list[object] = field(default_factory=list, repr=False)
    observation_keys: set[tuple[str, int]] = field(default_factory=set, repr=False)
    finalized: bool = False


current_request_outcome: ContextVar[RequestOutcome | None] = ContextVar(
    "request_outcome", default=None
)


def record_request_route(provider_id: str, model: str) -> None:
    outcome = current_request_outcome.get()
    if outcome is not None:
        outcome.provider_id = provider_id
        outcome.model = model


def record_request_gateway_model(model: str) -> None:
    outcome = current_request_outcome.get()
    if outcome is not None:
        outcome.gateway_model = model


def record_estimated_input_tokens(tokens: int) -> None:
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        return
    outcome = current_request_outcome.get()
    if outcome is not None:
        outcome.estimated_input_tokens = tokens


def record_request_observation(
    execution_id: str, attempt: int, observation: object, *, limit: int = 64
) -> bool:
    """Deduplicate bounded opaque observations without importing application."""

    outcome = current_request_outcome.get()
    key = (execution_id, attempt)
    if (
        outcome is None
        or outcome.finalized
        or key in outcome.observation_keys
        or len(outcome.observations) >= limit
    ):
        return False
    outcome.observation_keys.add(key)
    outcome.observations.append(observation)
    return True


def finalize_request_outcome(outcome: RequestOutcome) -> tuple[object, ...]:
    outcome.finalized = True
    return tuple(outcome.observations)


def record_request_failure(reason: str) -> None:
    outcome = current_request_outcome.get()
    if outcome is not None and outcome.failure_reason is None:
        outcome.failure_reason = reason


def record_request_exception(error: BaseException) -> None:
    failure = find_execution_failure(error)
    record_request_failure(failure.kind.value if failure else type(error).__name__)
