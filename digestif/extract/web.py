"""Generic web extractor using trafilatura, readability-lxml, and r.jina.ai."""

from typing import Any
from urllib.parse import urlparse

import markdownify
import readability
import trafilatura
from bs4 import BeautifulSoup

from digestif.extract.base import BaseExtractor, ContentDocument, ExtractError
from digestif.observability import logger
from digestif.security.ssrf import safe_fetch

PAYWALL_INDICATORS = [
    "subscribe to continue reading",
    "become a subscriber",
    "already a subscriber? log in",
    "you have reached your limit of free articles",
    "create a free account to read",
    "members only",
    "this story is for subscribers",
]


class WebExtractor(BaseExtractor):
    def can_handle(self, url: str | None, hints: dict[str, Any] | None = None) -> bool:
        return bool(url and url.startswith(("http://", "https://")))

    async def extract(
        self, url: str | None, raw_payload: str | None = None, hints: dict[str, Any] | None = None
    ) -> ContentDocument:
        if not url:
            raise ExtractError("No URL provided to WebExtractor")

        logger.info("Extracting generic web page", url=url)
        warnings: list[str] = []
        html_content = ""

        # Fetch page with SSRF protection
        try:
            resp = await safe_fetch(url, timeout=15.0, max_bytes=5 * 1024 * 1024)
            html_content = resp.text
        except Exception as e:
            logger.warning("Direct web fetch failed, trying r.jina.ai", url=url, error=str(e))
            return await self._fallback_jina(url)

        # 1. Tier 1: Trafilatura
        extracted_text = trafilatura.extract(
            html_content,
            output_format="markdown",
            include_links=True,
            include_images=False,
            url=url,
        )
        metadata = trafilatura.extract_metadata(html_content, default_url=url)

        title = metadata.title if metadata and metadata.title else ""
        author = metadata.author if metadata and metadata.author else ""
        publisher = metadata.sitename if metadata and metadata.sitename else urlparse(url).netloc
        published_at = metadata.date if metadata and metadata.date else None
        method = "web.trafilatura"

        # 2. Tier 2: Readability-lxml fallback if content is too short
        words = len(extracted_text.split()) if extracted_text else 0
        if words < 120:
            try:
                doc = readability.Document(html_content)
                summary_html = doc.summary()
                readability_text = markdownify.markdownify(
                    summary_html, heading_style="ATX"
                ).strip()
                if len(readability_text.split()) > words:
                    extracted_text = readability_text
                    if not title:
                        title = doc.title()
                    method = "web.readability"
            except Exception as e:
                logger.warning("Readability fallback failed", error=str(e))

        # Check paywall heuristics
        text_lower = (extracted_text or "").lower()
        if any(ind in text_lower for ind in PAYWALL_INDICATORS):
            warnings.append("paywalled_excerpt")

        # 3. Tier 3: r.jina.ai fallback if still < 60 words
        if not extracted_text or len(extracted_text.split()) < 60:
            try:
                jina_doc = await self._fallback_jina(url)
                if jina_doc.word_count >= 60:
                    return jina_doc
            except Exception as e:
                logger.warning("r.jina.ai fallback failed", error=str(e))

        if not extracted_text or len(extracted_text.split()) < 30:
            raise ExtractError(
                f"Could not extract sufficient text from {url} (extracted {words} words)"
            )

        final_words = len(extracted_text.split())
        original_minutes = round(final_words / 230.0, 1)

        if not title:
            # Fallback to BeautifulSoup title tag
            soup = BeautifulSoup(html_content, "html.parser")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            else:
                title = url

        return ContentDocument(
            title=title,
            author=author,
            publisher=publisher,
            published_at=published_at,
            canonical_url=url,
            text_md=extracted_text,
            word_count=final_words,
            original_minutes=original_minutes,
            extraction_method=method,
            warnings=warnings,
        )

    async def _fallback_jina(self, url: str) -> ContentDocument:
        jina_url = f"https://r.jina.ai/{url}"
        resp = await safe_fetch(jina_url, timeout=20.0, max_bytes=5 * 1024 * 1024)
        text = resp.text
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = url
        if lines and lines[0].startswith("Title:"):
            title = lines[0].replace("Title:", "").strip()

        warnings: list[str] = []
        if any(ind in text.lower() for ind in PAYWALL_INDICATORS):
            warnings.append("paywalled_excerpt")

        words = len(text.split())
        return ContentDocument(
            title=title,
            canonical_url=url,
            text_md=text,
            word_count=words,
            original_minutes=round(words / 230.0, 1),
            extraction_method="web.jina",
            warnings=warnings,
        )


web_extractor = WebExtractor()
