"""Substack extractor using official public API endpoint with web fallback."""

import re
from typing import Any
from urllib.parse import urlparse

import markdownify

from digestif.extract.base import BaseExtractor, ContentDocument
from digestif.extract.web import web_extractor
from digestif.observability import logger
from digestif.security.ssrf import safe_fetch


class SubstackExtractor(BaseExtractor):
    def can_handle(self, url: str | None, hints: dict[str, Any] | None = None) -> bool:
        if not url:
            return False
        netloc = urlparse(url.lower()).netloc
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc.endswith(".substack.com") or netloc == "substack.com"

    async def extract(
        self, url: str | None, raw_payload: str | None = None, hints: dict[str, Any] | None = None
    ) -> ContentDocument:
        if not url:
            return await web_extractor.extract(url)

        parsed = urlparse(url)
        netloc = parsed.netloc
        slug_match = re.search(r"/p/([a-zA-Z0-9_-]+)", parsed.path)
        if not slug_match:
            return await web_extractor.extract(url)

        slug = slug_match.group(1)
        api_url = f"https://{netloc}/api/v1/posts/{slug}"
        logger.info("Attempting Substack API extraction", api_url=api_url)

        try:
            resp = await safe_fetch(api_url, timeout=12.0)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title") or ""
                subtitle = data.get("subtitle") or ""
                body_html = data.get("body_html") or ""
                post_date = data.get("post_date")
                audience = data.get("audience", "everyone")

                warnings: list[str] = []

                # truncated_body_text is populated on essentially every post (used for
                # RSS/social-card previews), including fully free ones -- it is not a
                # reliable paywall signal. `audience` is Substack's actual gate flag.
                if audience != "everyone":
                    warnings.append("paywalled_excerpt")

                # Convert HTML body to Markdown
                body_md = markdownify.markdownify(body_html, heading_style="ATX").strip()
                if subtitle and subtitle not in body_md:
                    full_text = f"**{subtitle}**\n\n{body_md}"
                else:
                    full_text = body_md

                actual_words = len(full_text.split())
                if actual_words >= 60:
                    return ContentDocument(
                        title=title or slug,
                        author=data.get("publishedBps", [{}])[0].get("name", "")
                        if data.get("publishedBps")
                        else "",
                        publisher=netloc,
                        published_at=post_date,
                        canonical_url=url,
                        text_md=full_text,
                        word_count=actual_words,
                        original_minutes=round(actual_words / 230.0, 1),
                        extraction_method="substack.api",
                        warnings=warnings,
                    )
        except Exception as e:
            logger.warning(
                "Substack API extraction failed, falling back to web", url=url, error=str(e)
            )

        # Fallback to generic web extractor
        doc = await web_extractor.extract(url)
        doc.extraction_method = "substack.web_fallback"
        return doc


substack_extractor = SubstackExtractor()
