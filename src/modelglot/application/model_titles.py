"""Pure model-title resolution for the application model catalog."""

import re
from collections.abc import Mapping, Sequence

from modelglot.config.model_catalog_mapping import (
    MODEL_CATALOG_PROVIDER_MAPPING,
)
from modelglot.config.model_title_overrides import MODEL_TITLE_OVERRIDES

CatalogTitleMap = Mapping[tuple[str, str], tuple[str, str]]

_TOKEN_PATTERN = re.compile(r"[-_/]+")
_NUMERIC_UNIT_PATTERN = re.compile(r"\d+(?:\.\d+)?[A-Za-z]?")
_ALPHA_NUMERIC_UNIT_PATTERN = re.compile(r"[A-Za-z]\d+(?:\.\d+)?[A-Za-z]?")
_KNOWN_VENDOR_PREFIXES = frozenset(
    {
        "anthropic",
        "azure",
        "claude",
        "cohere",
        "deepseek",
        "google",
        "kimi",
        "llama",
        "meta",
        "microsoft",
        "minimax",
        "mistral",
        "moonshot",
        "nvidia",
        "openai",
        "qwen",
        "xai",
        "zai",
    }
)
_WORD_TITLES = {
    "ai": "AI",
    "chat": "Chat",
    "code": "Code",
    "deepseek": "DeepSeek",
    "gpt": "GPT",
    "llama": "Llama",
    "minimax": "MiniMax",
    "qwen": "Qwen",
    "ultra": "Ultra",
}
_ACRONYMS = frozenset({"ai", "api", "gpu", "llm", "moe", "vl", "vlm"})


def lookup_model_catalog_entry(
    provider_id: str,
    model_id: str,
    catalog: CatalogTitleMap | None = None,
) -> tuple[str, str | None] | None:
    """Return normalized cached title and purpose text without I/O."""
    catalog_provider = MODEL_CATALOG_PROVIDER_MAPPING.get(provider_id)
    if catalog_provider is None or catalog is None:
        return None
    entry = catalog.get((catalog_provider, model_id))
    if entry is None or not entry[0].strip():
        return None
    description = entry[1].strip() if isinstance(entry[1], str) else ""
    return entry[0].strip(), description or None


def resolve_model_title(
    provider_id: str,
    model_id: str,
    provider_model_ref: str,
    catalog: CatalogTitleMap | None = None,
) -> str:
    """Resolve one presentation title without I/O or mutable global state."""
    override = MODEL_TITLE_OVERRIDES.get((provider_id, model_id))
    if override is not None:
        return override.title
    entry = lookup_model_catalog_entry(provider_id, model_id, catalog)
    if entry is not None:
        return entry[0]
    return heuristic_model_title(model_id) or provider_model_ref


def heuristic_model_title(model_id: str) -> str:
    """Derive a deterministic readable title from a provider-relative model id."""
    segments = [segment for segment in model_id.split("/") if segment]
    if len(segments) > 1 and segments[0].casefold() in _KNOWN_VENDOR_PREFIXES:
        segments = segments[1:]
    tokens = [
        token
        for segment in segments
        for token in _TOKEN_PATTERN.split(segment)
        if token
    ]
    if not tokens:
        return ""
    return " ".join(_title_token(token) for token in tokens)


def disambiguate_duplicate_titles(
    titles: Sequence[tuple[str, str, str]],
) -> dict[tuple[str, str], str]:
    """Disambiguate equal titles belonging to one provider."""
    result: dict[tuple[str, str], str] = {}
    groups: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for provider_id, model_id, title in titles:
        groups.setdefault((provider_id, title.casefold()), []).append(
            (provider_id, model_id, title)
        )
    for model_ids in groups.values():
        if len(model_ids) < 2:
            continue
        model_ids.sort(key=lambda item: item[1])
        title = model_ids[0][2]
        suffixes = _unique_model_suffixes([item[1] for item in model_ids[1:]])
        for (provider_id, model_id, _), suffix in zip(
            model_ids[1:], suffixes, strict=True
        ):
            result[(provider_id, model_id)] = f"{title} ({suffix})"
    return result


def _title_token(token: str) -> str:
    if token.casefold() in _ACRONYMS:
        return token.upper()
    if token in _WORD_TITLES:
        return _WORD_TITLES[token]
    if _NUMERIC_UNIT_PATTERN.fullmatch(token):
        suffix = token[-1] if token[-1].isalpha() else ""
        number = token[:-1] if suffix else token
        return f"{number}{suffix.upper()}"
    if _ALPHA_NUMERIC_UNIT_PATTERN.fullmatch(token):
        suffix = token[-1] if token[-1].isalpha() else ""
        body = token[:-1] if suffix else token
        return f"{body[:1].upper()}{body[1:]}{suffix.upper()}"
    if token[:1].islower():
        return token[:1].upper() + token[1:]
    if any(character.isupper() for character in token[1:]):
        return token
    return token


def _unique_model_suffixes(model_ids: list[str]) -> list[str]:
    suffixes: list[str] = []
    for model_id in model_ids:
        parts = model_id.split("/")
        chosen = parts[-1]
        for count in range(2, len(parts) + 1):
            candidate = "/".join(parts[-count:])
            if all(candidate != suffix for suffix in suffixes):
                chosen = candidate
                break
        suffixes.append(chosen)
    return suffixes
