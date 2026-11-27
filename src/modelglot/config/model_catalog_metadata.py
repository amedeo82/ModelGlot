"""Shared provider-scoped catalog presentation metadata."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelCatalogMetadata:
    """Validated provider-scoped models.dev facts for presentation only."""

    canonical_model_id: str | None = None
    reasoning: bool | None = None
    tool_call: bool | None = None
    structured_output: bool | None = None
    input_modalities: tuple[str, ...] | None = None
    output_modalities: tuple[str, ...] | None = None
    context_limit: int | None = None
    input_limit: int | None = None
    output_limit: int | None = None
    status: str | None = None
    release_date: str | None = None
    last_updated: str | None = None
    knowledge: str | None = None
    open_weights: bool | None = None
    fetched_at: float | None = None

    @property
    def lab_id(self) -> str | None:
        canonical = self.canonical_model_id
        return canonical.partition("/")[0] if canonical else None

    @property
    def lab_label(self) -> str | None:
        lab = self.lab_id
        if lab is None:
            return None
        return {
            "google": "Google",
            "minimax": "MiniMax",
            "nvidia": "NVIDIA",
            "openai": "OpenAI",
        }.get(lab, lab.replace("-", " ").replace("_", " ").title())
