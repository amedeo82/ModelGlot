"""Admin configuration manifest."""

from collections.abc import Iterable

from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.config.reasoning import (
    FALLBACK_REASONING_PREFERENCES,
    ROOT_REASONING_PREFERENCES,
    ROUTE_REASONING_PREFERENCES,
    ReasoningPreference,
)

from .provider_manifest import provider_field_specs
from .specs import ConfigFieldSpec, ConfigOptionSpec, ConfigSectionSpec


def _reasoning_options(
    preferences: tuple[ReasoningPreference, ...],
) -> tuple[ConfigOptionSpec, ...]:
    labels = {
        ReasoningPreference.INHERIT: "Inherit",
        ReasoningPreference.OFF: "Off",
        ReasoningPreference.CLIENT: "From client",
        ReasoningPreference.LOW: "Low",
        ReasoningPreference.MEDIUM: "Medium",
        ReasoningPreference.HIGH: "High",
        ReasoningPreference.XHIGH: "X-High",
        ReasoningPreference.MAX: "Max",
    }
    return tuple(
        ConfigOptionSpec(preference.value, labels[preference])
        for preference in preferences
    )


SECTIONS: tuple[ConfigSectionSpec, ...] = (
    ConfigSectionSpec(
        "providers",
        "Providers",
        "Provider keys, local endpoints, and proxy settings.",
    ),
    ConfigSectionSpec(
        "models",
        "Model Routing",
        "Choose a model and effort together. Tier overrides can inherit the defaults.",
    ),
    ConfigSectionSpec(
        "runtime",
        "Runtime",
        "Server API token, rate limits, timeouts, and process settings.",
    ),
    ConfigSectionSpec(
        "messaging",
        "Messaging",
        "Platform selection and shared messaging limits.",
    ),
    ConfigSectionSpec(
        "telegram",
        "Telegram",
        "Telegram bot and access settings.",
    ),
    ConfigSectionSpec(
        "discord",
        "Discord",
        "Discord bot and channel access settings.",
    ),
    ConfigSectionSpec(
        "workspace",
        "CLI Workspace",
        "Directory used by messaging-triggered Claude Code sessions.",
    ),
    ConfigSectionSpec(
        "voice",
        "Voice",
        "Voice note transcription settings.",
    ),
    ConfigSectionSpec(
        "web_tools",
        "Web Tools",
        "Local Anthropic web_search and web_fetch behavior.",
    ),
    ConfigSectionSpec(
        "diagnostics",
        "Diagnostics",
        "Logging and debugging flags.",
        advanced=True,
    ),
    ConfigSectionSpec(
        "smoke",
        "Smoke Tests",
        "Optional live smoke-test model overrides.",
        advanced=True,
    ),
)


_NON_PROVIDER_FIELDS: tuple[ConfigFieldSpec, ...] = (
    ConfigFieldSpec(
        "MODEL",
        "Default Model",
        "models",
        "model",
        settings_attr="model",
        description="Provider/model used when no tier-specific override applies.",
    ),
    ConfigFieldSpec(
        "MODEL_FABLE",
        "Fable Override",
        "models",
        "optional_model",
        settings_attr="model_fable",
        description="Select None to use the Default Model for Fable requests.",
    ),
    ConfigFieldSpec(
        "MODEL_OPUS",
        "Opus Override",
        "models",
        "optional_model",
        settings_attr="model_opus",
        description="Select None to use the Default Model for Opus requests.",
    ),
    ConfigFieldSpec(
        "MODEL_SONNET",
        "Sonnet Override",
        "models",
        "optional_model",
        settings_attr="model_sonnet",
        description="Select None to use the Default Model for Sonnet requests.",
    ),
    ConfigFieldSpec(
        "MODEL_HAIKU",
        "Haiku Override",
        "models",
        "optional_model",
        settings_attr="model_haiku",
        description="Select None to use the Default Model for Haiku requests.",
    ),
    ConfigFieldSpec(
        "MODEL_FALLBACKS",
        "Fallback Models",
        "models",
        "model_list",
        settings_attr="model_fallbacks",
        options=_reasoning_options(FALLBACK_REASONING_PREFERENCES),
        description=(
            "Tried in order when the selected provider/model fails before output "
            "starts. Applies to every client. One request may reach multiple "
            "providers and consume usage at each. Native Anthropic Messages requests "
            "use only other Anthropic models as fallbacks."
        ),
    ),
    ConfigFieldSpec(
        "REASONING_POLICY",
        "Default Effort",
        "models",
        "select",
        settings_attr="reasoning_policy",
        options=_reasoning_options(ROOT_REASONING_PREFERENCES),
        description=(
            "Used by inherited routes and direct provider/model requests. From client "
            "preserves CLI effort. Native Anthropic primary requests use client "
            "thinking controls."
        ),
    ),
    ConfigFieldSpec(
        "REASONING_FABLE",
        "Fable Effort",
        "models",
        "select",
        settings_attr="reasoning_fable",
        options=_reasoning_options(ROUTE_REASONING_PREFERENCES),
        description=(
            "Reasoning effort for Fable requests. Inherit uses the Default Effort."
        ),
    ),
    ConfigFieldSpec(
        "REASONING_OPUS",
        "Opus Effort",
        "models",
        "select",
        settings_attr="reasoning_opus",
        options=_reasoning_options(ROUTE_REASONING_PREFERENCES),
        description=(
            "Reasoning effort for Opus requests. Inherit uses the Default Effort."
        ),
    ),
    ConfigFieldSpec(
        "REASONING_SONNET",
        "Sonnet Effort",
        "models",
        "select",
        settings_attr="reasoning_sonnet",
        options=_reasoning_options(ROUTE_REASONING_PREFERENCES),
        description=(
            "Reasoning effort for Sonnet requests. Inherit uses the Default Effort."
        ),
    ),
    ConfigFieldSpec(
        "REASONING_HAIKU",
        "Haiku Effort",
        "models",
        "select",
        settings_attr="reasoning_haiku",
        options=_reasoning_options(ROUTE_REASONING_PREFERENCES),
        description=(
            "Reasoning effort for Haiku requests. Inherit uses the Default Effort."
        ),
    ),
    ConfigFieldSpec(
        "PROXY_AUTH_ENABLED",
        "Require API Authentication",
        "runtime",
        "boolean",
        settings_attr="proxy_auth_enabled",
        restart_required=True,
        description=(
            "Require the retained API/CLI token on FCC API routes. "
            "Changing it restarts FCC."
        ),
    ),
    ConfigFieldSpec(
        "ANTHROPIC_AUTH_TOKEN",
        "API/CLI Auth Token",
        "runtime",
        "secret",
        settings_attr="proxy_auth_token",
        secret=True,
        restart_required=True,
        description=(
            "Retained non-empty token passed to every harness. Authentication can be "
            "disabled without clearing it. Changing it restarts FCC."
        ),
    ),
    ConfigFieldSpec(
        "PROVIDER_RATE_LIMIT",
        "Provider Rate Limit",
        "runtime",
        "number",
        settings_attr="provider_rate_limit",
        description=(
            "Maximum provider requests admitted per rate window (sliding "
            "window, shared across credentials). Must be greater than 0."
        ),
    ),
    ConfigFieldSpec(
        "PROVIDER_RATE_WINDOW",
        "Provider Rate Window",
        "runtime",
        "number",
        settings_attr="provider_rate_window",
        description=(
            "Length of the sliding rate-limit window in seconds. Must be "
            "greater than 0."
        ),
    ),
    ConfigFieldSpec(
        "PROVIDER_MAX_CONCURRENCY",
        "Provider Max Concurrency",
        "runtime",
        "number",
        settings_attr="provider_max_concurrency",
        description=(
            "Maximum simultaneous in-flight requests per provider. Must be "
            "greater than 0."
        ),
    ),
    ConfigFieldSpec(
        "PROVIDER_MAX_ATTEMPTS",
        "Provider Max Attempts",
        "runtime",
        "number",
        settings_attr="provider_max_attempts",
        description=(
            "Total tries per model for one request, including the first. Retries, "
            "mid-stream continuations, and model discovery all count against it."
        ),
    ),
    ConfigFieldSpec(
        "HTTP_READ_TIMEOUT",
        "HTTP Read Timeout",
        "runtime",
        "number",
        settings_attr="http_read_timeout",
        description=(
            "Seconds to wait between response packets, including streaming. "
            "Applies without restarting FCC."
        ),
    ),
    ConfigFieldSpec(
        "HTTP_WRITE_TIMEOUT",
        "HTTP Write Timeout",
        "runtime",
        "number",
        settings_attr="http_write_timeout",
        description=(
            "Seconds to allow for sending the request body. Applies without "
            "restarting FCC."
        ),
    ),
    ConfigFieldSpec(
        "HTTP_CONNECT_TIMEOUT",
        "HTTP Connect Timeout",
        "runtime",
        "number",
        settings_attr="http_connect_timeout",
        description=(
            "Seconds to allow for establishing the TCP/TLS connection. "
            "Applies without restarting FCC."
        ),
    ),
    ConfigFieldSpec(
        "HOST",
        "Server Host",
        "runtime",
        settings_attr="host",
        restart_required=True,
        description=(
            "Network address the FCC server binds to. Changing it restarts FCC."
        ),
    ),
    ConfigFieldSpec(
        "PORT",
        "Server Port",
        "runtime",
        "number",
        settings_attr="port",
        restart_required=True,
        description="TCP port the FCC server listens on. Changing it restarts FCC.",
    ),
    ConfigFieldSpec(
        "FCC_OPEN_BROWSER",
        "Open Admin on Startup",
        "runtime",
        "boolean",
        settings_attr="open_admin_browser",
        description="Open the Admin UI after the next fcc-server launch becomes healthy.",
    ),
    ConfigFieldSpec(
        "MESSAGING_PLATFORM",
        "Messaging Platform",
        "messaging",
        "select",
        settings_attr="messaging_platform",
        options=("telegram", "discord", "none"),
        session_sensitive=True,
        description=(
            "Selects the messaging platform started by FCC. Choose Telegram or "
            "Discord, or None to disable messaging startup."
        ),
    ),
    ConfigFieldSpec(
        "MESSAGING_RATE_LIMIT",
        "Messaging Rate Limit",
        "messaging",
        "number",
        settings_attr="messaging_rate_limit",
        session_sensitive=True,
        description=(
            "Maximum outbound messaging tasks dispatched per rate window "
            "(sliding window). Must be greater than 0."
        ),
    ),
    ConfigFieldSpec(
        "MESSAGING_RATE_WINDOW",
        "Messaging Rate Window",
        "messaging",
        "number",
        settings_attr="messaging_rate_window",
        session_sensitive=True,
        description=(
            "Length of the messaging rate-limit window in seconds. Must be "
            "greater than 0."
        ),
    ),
    ConfigFieldSpec(
        "TELEGRAM_BOT_TOKEN",
        "Telegram Bot Token",
        "telegram",
        "secret",
        settings_attr="telegram_bot_token",
        secret=True,
        session_sensitive=True,
        description=(
            "Bot token issued by BotFather and used to connect FCC to Telegram."
        ),
    ),
    ConfigFieldSpec(
        "ALLOWED_TELEGRAM_USER_ID",
        "Allowed Telegram User ID",
        "telegram",
        settings_attr="allowed_telegram_user_id",
        session_sensitive=True,
        description=(
            "Restricts Telegram messages to one numeric user ID. Leave blank "
            "to accept messages from any user."
        ),
    ),
    ConfigFieldSpec(
        "TELEGRAM_PROXY_URL",
        "Telegram Proxy URL",
        "telegram",
        "secret",
        settings_attr="telegram_proxy_url",
        secret=True,
        session_sensitive=True,
        description=(
            "Optional Telegram-only proxy, e.g. socks5://127.0.0.1:1080. "
            "Leave blank to connect directly."
        ),
    ),
    ConfigFieldSpec(
        "DISCORD_BOT_TOKEN",
        "Discord Bot Token",
        "discord",
        "secret",
        settings_attr="discord_bot_token",
        secret=True,
        session_sensitive=True,
        description=(
            "Bot token issued by the Discord Developer Portal and used to "
            "connect FCC to Discord."
        ),
    ),
    ConfigFieldSpec(
        "ALLOWED_DISCORD_CHANNELS",
        "Allowed Discord Channels",
        "discord",
        settings_attr="allowed_discord_channels",
        session_sensitive=True,
        description=(
            "Comma-separated Discord channel IDs that may use FCC. Leave blank "
            "to accept messages from no channels."
        ),
    ),
    ConfigFieldSpec(
        "ALLOWED_DIR",
        "Allowed Directory",
        "workspace",
        settings_attr="allowed_dir",
        session_sensitive=True,
        description=(
            "Workspace directory used by messaging-triggered Claude Code "
            "sessions. Leave blank to use the server's current directory."
        ),
    ),
    ConfigFieldSpec(
        "MAX_MESSAGE_LOG_ENTRIES_PER_CHAT",
        "Max Tracked Messages Per Chat",
        "messaging",
        "number",
        settings_attr="max_message_log_entries_per_chat",
        advanced=True,
        session_sensitive=True,
        description=(
            "Maximum number of tracked message entries retained per chat. "
            "Leave blank to keep all existing entries."
        ),
    ),
    ConfigFieldSpec(
        "VOICE_NOTE_ENABLED",
        "Voice Notes",
        "voice",
        "boolean",
        settings_attr="voice_note_enabled",
        session_sensitive=True,
        description=(
            "Transcribe incoming voice notes into text before sending them to "
            "Claude Code."
        ),
    ),
    ConfigFieldSpec(
        "WHISPER_DEVICE",
        "Whisper Device",
        "voice",
        "select",
        settings_attr="whisper_device",
        options=("cpu", "cuda", "nvidia_nim"),
        session_sensitive=True,
        description=(
            "Transcription backend: local Whisper on CPU or CUDA, or the "
            "NVIDIA NIM Whisper API."
        ),
    ),
    ConfigFieldSpec(
        "WHISPER_MODEL",
        "Whisper Model",
        "voice",
        settings_attr="whisper_model",
        session_sensitive=True,
        description=(
            "Whisper model name for local transcription or the model ID used "
            "by NVIDIA NIM."
        ),
    ),
    ConfigFieldSpec(
        "ENABLE_WEB_SERVER_TOOLS",
        "Web Server Tools",
        "web_tools",
        "boolean",
        settings_attr="enable_web_server_tools",
        description=(
            "Let Claude Code use WebSearch through FCC and allow forced local web "
            "tools. Disable to prevent local web access."
        ),
    ),
    ConfigFieldSpec(
        "WEB_FETCH_ALLOWED_SCHEMES",
        "Allowed Web Fetch Schemes",
        "web_tools",
        settings_attr="web_fetch_allowed_schemes",
        description=(
            "Comma-separated URL schemes that web_fetch may use, for example "
            "http,https."
        ),
    ),
    ConfigFieldSpec(
        "WEB_FETCH_ALLOW_PRIVATE_NETWORKS",
        "Allow Private Networks",
        "web_tools",
        "boolean",
        settings_attr="web_fetch_allow_private_networks",
        description=(
            "Allow web_fetch to reach loopback, private, and link-local "
            "addresses. Leave disabled to prevent access to internal services."
        ),
    ),
    ConfigFieldSpec(
        "LOG_LEVEL",
        "Log Level",
        "diagnostics",
        "select",
        settings_attr="log_level",
        options=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "DEBUG_PLATFORM_EDITS",
        "Debug Platform Edits",
        "diagnostics",
        "boolean",
        settings_attr="debug_platform_edits",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "DEBUG_SUBAGENT_STACK",
        "Debug Subagent Stack",
        "diagnostics",
        "boolean",
        settings_attr="debug_subagent_stack",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_RAW_API_PAYLOADS",
        "Log Raw API Payloads",
        "diagnostics",
        "boolean",
        settings_attr="log_raw_api_payloads",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_RAW_SSE_EVENTS",
        "Log Raw SSE Events",
        "diagnostics",
        "boolean",
        settings_attr="log_raw_sse_events",
        advanced=True,
    ),
    ConfigFieldSpec(
        "LOG_API_ERROR_TRACEBACKS",
        "Log API Error Tracebacks",
        "diagnostics",
        "boolean",
        settings_attr="log_api_error_tracebacks",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_RAW_MESSAGING_CONTENT",
        "Log Raw Messaging Content",
        "diagnostics",
        "boolean",
        settings_attr="log_raw_messaging_content",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_RAW_CLI_DIAGNOSTICS",
        "Log Raw CLI Diagnostics",
        "diagnostics",
        "boolean",
        settings_attr="log_raw_cli_diagnostics",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_MESSAGING_ERROR_DETAILS",
        "Log Messaging Error Details",
        "diagnostics",
        "boolean",
        settings_attr="log_messaging_error_details",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_MODEL_MISTRAL_REASONING",
        "Smoke Mistral Reasoning Model",
        "smoke",
        advanced=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_NIM_MODELS",
        "Smoke NIM Models",
        "smoke",
        advanced=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_NIM_EXTRA_MODELS",
        "Smoke NIM Extra Models",
        "smoke",
        advanced=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_OPENROUTER_FREE_MODELS",
        "Smoke OpenRouter Free Models",
        "smoke",
        advanced=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_OPENROUTER_FREE_EXTRA_MODELS",
        "Smoke OpenRouter Free Extra Models",
        "smoke",
        advanced=True,
    ),
)


def _catalog_smoke_fields() -> tuple[ConfigFieldSpec, ...]:
    return tuple(
        ConfigFieldSpec(
            key=f"FCC_SMOKE_MODEL_{provider_id.upper()}",
            label=f"Smoke {descriptor.display_name} Model",
            section_id="smoke",
            advanced=True,
        )
        for provider_id, descriptor in PROVIDER_CATALOG.items()
    )


FIELDS: tuple[ConfigFieldSpec, ...] = (
    *provider_field_specs(),
    *_NON_PROVIDER_FIELDS,
    *_catalog_smoke_fields(),
)
FIELD_BY_KEY = {field.key: field for field in FIELDS}


def env_keys() -> frozenset[str]:
    """Return env keys owned by the admin manifest."""

    return frozenset(field.key for field in FIELDS)


def fields_with_attrs() -> Iterable[ConfigFieldSpec]:
    """Yield fields that validate through Settings."""

    return (field for field in FIELDS if field.settings_attr is not None)
