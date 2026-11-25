from unittest.mock import Mock

from free_claude_code.providers.continuation import SourceRecoveryState


def test_source_usage_merges_anthropic_snapshots_and_strips_unknown_fields():
    source = SourceRecoveryState(Mock())
    source.observe(
        "messages",
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 4,
                    "cache_creation_input_tokens": 2,
                    "prompt": "private",
                }
            },
        },
    )
    source.observe(
        "messages",
        {"type": "message_delta", "usage": {"output_tokens": 7}},
    )

    assert source.usage_snapshot() == (
        "messages",
        {
            "input_tokens": 10,
            "cache_read_input_tokens": 4,
            "cache_creation_input_tokens": 2,
            "output_tokens": 7,
        },
    )


def test_source_usage_retains_chat_cache_reasoning_and_gemini_metadata():
    chat = SourceRecoveryState(Mock())
    chat.observe(
        "chat",
        {
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 8,
                "prompt_tokens_details": {
                    "cached_tokens": 5,
                    "unknown_private_detail": "hidden",
                },
                "completion_tokens_details": {"reasoning_tokens": 3},
                "raw_provider_extension": "hidden",
            }
        },
    )
    assert chat.usage_snapshot() == (
        "chat",
        {
            "prompt_tokens": 20,
            "completion_tokens": 8,
            "prompt_tokens_details": {"cached_tokens": 5},
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    )

    gemini = SourceRecoveryState(Mock())
    gemini.observe(
        "gemini",
        {
            "usageMetadata": {
                "promptTokenCount": 20,
                "cachedContentTokenCount": 5,
                "candidatesTokenCount": 8,
                "thoughtsTokenCount": 3,
                "totalTokenCount": 28,
            }
        },
    )
    snapshot = gemini.usage_snapshot()
    assert snapshot is not None
    usage = snapshot[1]
    assert usage["totalTokenCount"] == 28
    assert "promptTokenCount" in usage
