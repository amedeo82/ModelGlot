"""Curated descriptive titles for flagship provider models."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ModelTitleOverride:
    """One repository-owned model title and optional description."""

    title: str
    description: str | None = None


MODEL_TITLE_OVERRIDES = MappingProxyType(
    {
        ("nvidia_nim", "nvidia/nemotron-3-ultra-550b-a55b"): ModelTitleOverride(
            "Nemotron 3 Ultra 550B A55B"
        ),
        ("minimax", "MiniMax-M3.1-Flash"): ModelTitleOverride("MiniMax-M3.1-Flash"),
    }
)
