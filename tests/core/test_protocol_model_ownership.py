"""Protocol models live with the protocol logic that consumes them."""

import subprocess
import sys

from modelglot.core.anthropic import (
    MessagesRequest as PublicMessagesRequest,
)
from modelglot.core.anthropic import (
    MessagesResponse,
    TokenCountResponse,
)
from modelglot.core.anthropic.models import MessagesRequest
from modelglot.core.openai_responses import (
    OpenAIResponsesRequest as PublicOpenAIResponsesRequest,
)
from modelglot.core.openai_responses.models import OpenAIResponsesRequest


def test_anthropic_request_model_is_core_owned_and_permissive() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "provider-model",
            "messages": [{"role": "user", "content": "hello"}],
            "provider_extension": {"enabled": True},
        }
    )

    assert MessagesRequest.__module__ == "modelglot.core.anthropic.models"
    assert PublicMessagesRequest is MessagesRequest
    assert request.model_extra == {"provider_extension": {"enabled": True}}


def test_responses_request_model_is_core_owned_and_permissive() -> None:
    request = OpenAIResponsesRequest.model_validate(
        {
            "model": "provider-model",
            "input": "hello",
            "provider_extension": {"enabled": True},
        }
    )

    assert OpenAIResponsesRequest.__module__ == "modelglot.core.openai_responses.models"
    assert PublicOpenAIResponsesRequest is OpenAIResponsesRequest
    assert request.model_extra == {"provider_extension": {"enabled": True}}


def test_anthropic_response_models_are_protocol_owned() -> None:
    assert MessagesResponse.__module__ == "modelglot.core.anthropic.models"
    assert TokenCountResponse.__module__ == "modelglot.core.anthropic.models"


def test_protocol_facades_are_import_order_independent() -> None:
    import_orders = (
        (
            "modelglot.core.anthropic",
            "modelglot.core.openai_responses",
        ),
        (
            "modelglot.core.openai_responses",
            "modelglot.core.anthropic",
        ),
    )

    for modules in import_orders:
        script = "; ".join(f"import {module}" for module in modules)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
