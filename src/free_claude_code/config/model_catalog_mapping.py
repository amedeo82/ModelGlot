"""Explicit mapping between FCC providers and models.dev providers."""

from types import MappingProxyType

MODEL_CATALOG_PROVIDER_MAPPING = MappingProxyType(
    {
        "nvidia_nim": "nvidia",
        "minimax": "minimax",
        "open_router": "openrouter",
        "together": "togetherai",
        "gemini": "google",
        "novita": "novita-ai",
        "fireworks": "fireworks-ai",
        "github_copilot": "github-copilot",
        "azure_openai": "azure",
        "alibaba_cloud": "alibaba",
        "opencode_zen": "opencode",
        "opencode_go": "opencode",
        "deepseek": "deepseek",
        "groq": "groq",
        "cerebras": "cerebras",
        "siliconflow": "siliconflow",
        "nebius": "nebius",
        "chutes": "chutes",
        "cohere": "cohere",
        "xai": "xai",
        "zai": "zai",
        "huggingface": "huggingface",
        "lmstudio": "lmstudio",
        "mistral": "mistral",
        "openai": "openai",
        "anthropic": "anthropic",
        "vercel": "vercel",
        "sambanova": "sambanova",
        "scaleway": "scaleway",
        "poolside": "poolside",
        "wandb": "wandb",
        "kilo": "kilo",
        "deepinfra": "deepinfra",
        "zenmux": "zenmux",
    }
)
