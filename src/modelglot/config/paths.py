"""Shared filesystem paths for ModelGlot configuration."""

from pathlib import Path

MODELGLOT_CONFIG_DIRNAME = ".modelglot"
MODELGLOT_ENV_FILENAME = ".env"
MESSAGING_STATE_DIRNAME = "agent_workspace"
MODELGLOT_LOGS_DIRNAME = "logs"
SERVER_LOG_FILENAME = "server.log"
SERVER_STARTUP_LOG_FILENAME = "startup.log"
CODEX_MODEL_CATALOG_FILENAME = "codex-model-catalog.json"
MODEL_CATALOG_CACHE_FILENAME = "models-dev-catalog.json"
AUTH_DIRNAME = "auth"
OPENAI_AUTH_FILENAME = "openai.json"
OPENAI_AUTH_LOCK_FILENAME = "openai.lock"
CONFIG_LOCK_FILENAME = "config.lock"
SERVER_STARTUP_LOCK_FILENAME = "server.startup.lock"
SERVER_OWNER_LOCK_FILENAME = "server.owner.lock"
MODELGLOT_TEMP_DIRNAME = "tmp"
LAUNCHER_TEMP_DIRNAME = "launchers"
CODE_STATE_DIRNAME = "code"
MODELGLOT_DATABASE_FILENAME = "modelglot.db"
CODE_DATABASE_FILENAME = "code.db"
CODE_LOCK_FILENAME = "code.lock"


def config_dir_path() -> Path:
    """Return the default user config directory."""

    return Path.home() / MODELGLOT_CONFIG_DIRNAME


def managed_env_path() -> Path:
    """Return the default user-managed env file path."""

    return config_dir_path() / MODELGLOT_ENV_FILENAME


def config_lock_path() -> Path:
    """Return the cross-process managed-config migration lock path."""

    return config_dir_path() / CONFIG_LOCK_FILENAME


def server_startup_lock_path() -> Path:
    """Return the lock launchers hold while starting one shared modelglot-server."""

    return config_dir_path() / SERVER_STARTUP_LOCK_FILENAME


def server_owner_lock_path() -> Path:
    """Return the lock held by one server through all configuration restarts."""

    return config_dir_path() / SERVER_OWNER_LOCK_FILENAME


def launcher_temp_dir_path() -> Path:
    """Return the base directory for private native launcher configuration."""

    return config_dir_path() / MODELGLOT_TEMP_DIRNAME / LAUNCHER_TEMP_DIRNAME


def modelglot_database_path() -> Path:
    """Return the shared ModelGlot database path."""
    return config_dir_path() / MODELGLOT_DATABASE_FILENAME


def legacy_code_database_path() -> Path:
    """Return the former Code database path for startup relocation."""
    return config_dir_path() / CODE_STATE_DIRNAME / CODE_DATABASE_FILENAME


def code_lock_path() -> Path:
    """Return the exclusive Code sessions process-lock path."""
    return config_dir_path() / CODE_STATE_DIRNAME / CODE_LOCK_FILENAME


def messaging_state_dir_path() -> Path:
    """Return the managed messaging state directory."""

    return config_dir_path() / MESSAGING_STATE_DIRNAME


def server_log_path() -> Path:
    """Return the canonical server log path."""

    return config_dir_path() / MODELGLOT_LOGS_DIRNAME / SERVER_LOG_FILENAME


def server_startup_log_path() -> Path:
    """Return the latest automatic owner's output before runtime logging starts."""

    return config_dir_path() / MODELGLOT_LOGS_DIRNAME / SERVER_STARTUP_LOG_FILENAME


def codex_model_catalog_path() -> Path:
    """Return the generated Codex model catalog path."""

    return config_dir_path() / CODEX_MODEL_CATALOG_FILENAME


def model_catalog_cache_path() -> Path:
    """Return the reduced external model-title cache path."""

    return config_dir_path() / MODEL_CATALOG_CACHE_FILENAME


def model_catalog_logo_dir_path() -> Path:
    """Return the validated models.dev SVG cache directory."""

    return config_dir_path() / "models-dev-logos"


def claude_desktop_disconnect_path() -> Path:
    return config_dir_path() / "claude-desktop-disconnect.json"


def openai_auth_path() -> Path:
    """Return ModelGlot's private ChatGPT credential file path."""

    return config_dir_path() / AUTH_DIRNAME / OPENAI_AUTH_FILENAME


def openai_auth_lock_path() -> Path:
    """Return the cross-process lock path for ChatGPT credentials."""

    return config_dir_path() / AUTH_DIRNAME / OPENAI_AUTH_LOCK_FILENAME


def github_copilot_auth_path() -> Path:
    """Return ModelGlot connection state; native Copilot retains credentials."""
    return config_dir_path() / AUTH_DIRNAME / "github_copilot.json"
