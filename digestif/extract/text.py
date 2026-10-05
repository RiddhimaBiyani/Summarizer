"""Extractor for pasted raw text and user notes."""

from typing import Any

from digestif.extract.base import BaseExtractor, ContentDocument, ExtractError


class TextExtractor(BaseExtractor):
    def can_handle(self, url: str | None, hints: dict[str, Any] | None = None) -> bool:
        if hints and hints.get("is_text"):
            return True
        return not bool(url)

    async def extract(
        self, url: str | None, raw_payload: str | None = None, hints: dict[str, Any] | None = None
    ) -> ContentDocument:
        text = (raw_payload or "").strip()
        if not text:
            raise ExtractError("No text provided to TextExtractor")

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0][:80] if lines else "Pasted Text"
        words = len(text.split())

        return ContentDocument(
            title=title,
            canonical_url="",
            text_md=text,
            word_count=words,
            original_minutes=round(words / 230.0, 1),
            extraction_method="text.direct",
            warnings=[],
        )


text_extractor = TextExtractor()
