"""Extractor dispatcher choosing the appropriate extractor for each item."""

from typing import Any

from digestif.extract.base import BaseExtractor, ContentDocument, ExtractError
from digestif.extract.newsletter import newsletter_extractor
from digestif.extract.substack import substack_extractor
from digestif.extract.text import text_extractor
from digestif.extract.web import web_extractor

ALL_EXTRACTORS: list[BaseExtractor] = [
    newsletter_extractor,
    substack_extractor,
    web_extractor,
    text_extractor,
]


async def extract_item_content(
    url: str | None,
    raw_payload: str | None = None,
    hints: dict[str, Any] | None = None,
) -> ContentDocument:
    """Dispatches content extraction to the first capable extractor."""
    hints = hints or {}
    for extractor in ALL_EXTRACTORS:
        if extractor.can_handle(url, hints):
            return await extractor.extract(url, raw_payload, hints)

    raise ExtractError(f"No suitable extractor found for url='{url}'")
