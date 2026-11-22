from pathlib import Path
from typing import Any

import pytest

from free_claude_code.config.model_catalog_metadata import ModelCatalogMetadata
from free_claude_code.providers.model_catalog_logos import (
    ModelCatalogLogoError,
    ModelCatalogLogoStore,
    validate_catalog_svg,
)


@pytest.mark.parametrize(
    "content",
    (
        b'<html xmlns="http://www.w3.org/1999/xhtml"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b'<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="https://evil.example"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://evil.example)</style></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><path style="fill:url(https://evil.example)"/></svg>',
        b"<svg",
    ),
)
def test_svg_validation_rejects_active_external_and_malformed_content(
    content: bytes,
) -> None:
    with pytest.raises(ModelCatalogLogoError):
        validate_catalog_svg(content)


def test_svg_validation_allows_local_paint_and_fragments() -> None:
    validate_catalog_svg(
        b'<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"/></defs>'
        b'<path fill="url(#g)"/></svg>'
    )


@pytest.mark.asyncio
async def test_logo_refresh_publishes_valid_assets_and_preserves_stale_on_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    valid = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1z"/></svg>'
    responses = {"nvidia": valid, "minimax": valid}

    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content
            self.headers = {"content-type": "image/svg+xml"}

        async def __aenter__(self) -> Response:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield self.content

    class Client:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        def stream(self, _method: str, url: str) -> Response:
            self.urls.append(url)
            logo_id = url.rsplit("/", 1)[-1].removesuffix(".svg")
            return Response(responses[logo_id])

    clients: list[Client] = []

    def client_factory(**_kwargs: Any) -> Client:
        client = Client()
        clients.append(client)
        return client

    monkeypatch.setattr(
        "free_claude_code.providers.model_catalog_logos.httpx.AsyncClient",
        client_factory,
    )
    store = ModelCatalogLogoStore(tmp_path / "logos")
    metadata = {
        ("nvidia", "minimaxai/minimax-m3.1-flash"): ModelCatalogMetadata(
            canonical_model_id="minimax/MiniMax-M3.1-Flash"
        )
    }

    await store.refresh(metadata)

    assert store.url_for("providers", "nvidia") is None
    assert store.url_for("labs", "minimax") == ("/admin/catalog-logos/labs/minimax.svg")
    lab_path = store.path_for("labs", "minimax")
    assert lab_path is not None
    assert lab_path.read_bytes() == valid
    assert set(clients[0].urls) == {"https://models.dev/logos/labs/minimax.svg"}

    responses["minimax"] = (
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    )
    await store.refresh(metadata)

    assert lab_path.read_bytes() == valid
    assert store.url_for("labs", "minimax") is not None


@pytest.mark.asyncio
async def test_logo_refresh_rejects_wrong_content_type_and_oversize_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Response:
        def __init__(self) -> None:
            self.headers = {"content-type": "image/svg+xml"}

        async def __aenter__(self) -> Response:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b'<svg xmlns="http://www.w3.org/2000/svg">'
            yield b"x" * (64 * 1024)

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        def stream(self, _method: str, _url: str) -> Response:
            return Response()

    monkeypatch.setattr(
        "free_claude_code.providers.model_catalog_logos.httpx.AsyncClient",
        lambda **_kwargs: Client(),
    )
    store = ModelCatalogLogoStore(tmp_path / "logos")

    await store.refresh(
        {("nvidia", "model"): ModelCatalogMetadata(canonical_model_id="minimax/model")}
    )

    assert store.url_for("labs", "minimax") is None
    assert not (tmp_path / "logos" / "labs" / "minimax.svg").exists()
