"""Bounded, validated models.dev logos cached outside Admin request paths."""

import asyncio
import os
import re
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path

import httpx

from free_claude_code.config.model_catalog_metadata import ModelCatalogMetadata

_LOGO_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_EXTERNAL_CSS_URL = re.compile(r"url\(\s*['\"]?\s*([^)'\"\s]+)", re.IGNORECASE)
_MAX_LOGO_BYTES = 64 * 1024
_FETCH_TIMEOUT_SECONDS = 5.0
_KINDS = frozenset({"providers", "labs"})
_BLOCKED_ELEMENTS = frozenset({"script", "foreignobject", "iframe", "object", "embed"})


class ModelCatalogLogoError(ValueError):
    """Raised when a downloaded logo violates the SVG asset contract."""


class ModelCatalogLogoStore:
    """Cache validated same-origin logos and expose their local availability."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._available: set[tuple[str, str]] = set()
        for kind in _KINDS:
            directory = root / kind
            if not directory.is_dir():
                continue
            for path in directory.glob("*.svg"):
                logo_id = path.stem
                if _valid_logo_id(logo_id) and path.is_file():
                    self._available.add((kind, logo_id))

    def url_for(self, kind: str, logo_id: str | None) -> str | None:
        if logo_id is None or (kind, logo_id) not in self._available:
            return None
        return f"/admin/catalog-logos/{kind}/{logo_id}.svg"

    def path_for(self, kind: str, logo_id: str) -> Path | None:
        if (
            kind not in _KINDS
            or not _valid_logo_id(logo_id)
            or (kind, logo_id) not in self._available
        ):
            return None
        return self.root / kind / f"{logo_id}.svg"

    async def refresh(
        self, metadata: Mapping[tuple[str, str], ModelCatalogMetadata]
    ) -> None:
        """Refresh required logos without failing catalog metadata publication."""
        assets = {
            ("labs", lab_id)
            for item in metadata.values()
            if (lab_id := item.lab_id) is not None
        }
        assets = {
            (kind, logo_id) for kind, logo_id in assets if _valid_logo_id(logo_id)
        }
        if not assets:
            return
        semaphore = asyncio.Semaphore(4)
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            await asyncio.gather(
                *(
                    self._refresh_one(client, semaphore, kind, logo_id)
                    for kind, logo_id in sorted(assets)
                )
            )

    async def _refresh_one(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        kind: str,
        logo_id: str,
    ) -> None:
        path = (
            f"/logos/{logo_id}.svg"
            if kind == "providers"
            else f"/logos/labs/{logo_id}.svg"
        )
        try:
            async with (
                semaphore,
                client.stream("GET", f"https://models.dev{path}") as response,
            ):
                response.raise_for_status()
                content_type: str = response.headers.get("content-type", "")
                if content_type.partition(";")[0].strip().lower() != "image/svg+xml":
                    raise ModelCatalogLogoError("logo response is not SVG")
                content_length: str | None = response.headers.get("content-length")
                if (
                    content_length
                    and content_length.isdigit()
                    and int(content_length) > _MAX_LOGO_BYTES
                ):
                    raise ModelCatalogLogoError("logo exceeds size limit")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_LOGO_BYTES:
                        raise ModelCatalogLogoError("logo exceeds size limit")
            validate_catalog_svg(bytes(content))
            self._publish(kind, logo_id, bytes(content))
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    def _publish(self, kind: str, logo_id: str, content: bytes) -> None:
        directory = self.root / kind
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{logo_id}.svg"
        temporary = directory / f".{logo_id}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_bytes(content)
            os.replace(temporary, destination)
            self._available.add((kind, logo_id))
        finally:
            temporary.unlink(missing_ok=True)


def validate_catalog_svg(content: bytes) -> None:
    """Reject active or externally linked SVG before same-origin publication."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ModelCatalogLogoError("logo is not UTF-8 SVG") from exc
    if "<!doctype" in text.lower() or "<!entity" in text.lower():
        raise ModelCatalogLogoError("SVG document types and entities are not allowed")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ModelCatalogLogoError("logo is not well-formed SVG") from exc
    if _local_name(root.tag) != "svg":
        raise ModelCatalogLogoError("logo root is not SVG")
    for element in root.iter():
        element_name = _local_name(element.tag)
        if element_name in _BLOCKED_ELEMENTS:
            raise ModelCatalogLogoError("SVG active elements are not allowed")
        if element_name == "style":
            _validate_css(element.text or "")
        for name, value in element.attrib.items():
            local_name = _local_name(name).lower()
            normalized = re.sub(r"[\s\x00-\x20]+", "", value).lower()
            if local_name.startswith("on"):
                raise ModelCatalogLogoError("SVG event handlers are not allowed")
            if "javascript:" in normalized or "vbscript:" in normalized:
                raise ModelCatalogLogoError("SVG active URLs are not allowed")
            if (
                local_name in {"href", "src"}
                and value.strip()
                and not value.strip().startswith("#")
            ):
                raise ModelCatalogLogoError("SVG external references are not allowed")
            if local_name == "style":
                _validate_css(value)
            for match in _EXTERNAL_CSS_URL.finditer(value):
                url: str = match.group(1)
                if not url.startswith("#"):
                    raise ModelCatalogLogoError("SVG external CSS URLs are not allowed")


def _validate_css(value: str) -> None:
    normalized = re.sub(r"[\s\x00-\x20]+", "", value).lower()
    if "@import" in normalized:
        raise ModelCatalogLogoError("SVG CSS imports are not allowed")
    for match in _EXTERNAL_CSS_URL.finditer(value):
        url: str = match.group(1)
        if not url.startswith("#"):
            raise ModelCatalogLogoError("SVG external CSS URLs are not allowed")


def _local_name(name: str) -> str:
    return name.rpartition("}")[2].lower()


def _valid_logo_id(logo_id: str) -> bool:
    return isinstance(logo_id, str) and _LOGO_ID.fullmatch(logo_id) is not None
