"""Base classes and schemas for extractors."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ExtractError(Exception):
    """Raised when an extractor encounters an unrecoverable extraction error."""

    pass


class NeedsUser(Exception):
    """Raised when extraction requires human intervention (e.g. asking for screenshots)."""

    def __init__(self, reason: str, ask: str):
        super().__init__(f"{reason}: {ask}")
        self.reason = reason
        self.ask = ask


class ContentDocument(BaseModel):
    title: str
    author: str = ""
    publisher: str = ""
    published_at: str | None = None
    canonical_url: str = ""
    text_md: str
    transcript: str | None = None
    ocr_text: str | None = None
    media: list[dict[str, Any]] = Field(default_factory=list)
    word_count: int = 0
    media_seconds: int = 0
    original_minutes: float = 0.0
    language: str = "en"
    extraction_method: str = ""
    warnings: list[str] = Field(default_factory=list)


class BaseExtractor(ABC):
    @abstractmethod
    def can_handle(self, url: str | None, hints: dict[str, Any] | None = None) -> bool:
        """Returns True if this extractor can handle the given URL/source."""
        pass

    @abstractmethod
    async def extract(
        self, url: str | None, raw_payload: str | None = None, hints: dict[str, Any] | None = None
    ) -> ContentDocument:
        """Extracts content into a standardized ContentDocument."""
        pass
