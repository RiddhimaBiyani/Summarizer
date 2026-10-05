"""Newsletter extractor parsing .eml or raw email strings into clean Markdown."""

import email
import re
from email import policy
from typing import Any

import markdownify
from bs4 import BeautifulSoup

from digestif.extract.base import BaseExtractor, ContentDocument, ExtractError
from digestif.observability import logger

SPONSOR_REGEX = re.compile(
    r"\b(sponsor[a-z]*|presented by|advertis[a-z]*|in partnership with|paid partnership)\b",
    re.IGNORECASE,
)
FOOTER_INDICATORS = ["unsubscribe", "manage your preferences", "update profile", "view in browser"]


class NewsletterExtractor(BaseExtractor):
    def can_handle(self, url: str | None, hints: dict[str, Any] | None = None) -> bool:
        if hints and hints.get("is_email"):
            return True
        return False

    async def extract(
        self, url: str | None, raw_payload: str | None = None, hints: dict[str, Any] | None = None
    ) -> ContentDocument:
        if not raw_payload:
            raise ExtractError("No raw email payload provided to NewsletterExtractor")

        logger.info("Extracting newsletter email")
        # Parse email message
        msg = email.message_from_string(raw_payload, policy=policy.default)
        subject = str(msg.get("Subject", "Untitled Newsletter"))
        from_header = str(msg.get("From", ""))
        date_header = str(msg.get("Date", ""))

        html_body = ""
        text_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/html" and not html_body:
                    html_body = part.get_content()
                elif ctype == "text/plain" and not text_body:
                    text_body = part.get_content()
        else:
            ctype = msg.get_content_type()
            if ctype == "text/html":
                html_body = msg.get_content()
            else:
                text_body = msg.get_content()

        warnings: list[str] = []
        if html_body:
            extracted_text = self._clean_html_to_markdown(html_body, warnings)
        else:
            extracted_text = text_body

        words = len(extracted_text.split())
        if words < 20:
            raise ExtractError(f"Newsletter body too short ({words} words)")

        return ContentDocument(
            title=subject,
            author=from_header,
            publisher=from_header,
            published_at=date_header,
            canonical_url=url or "",
            text_md=extracted_text,
            word_count=words,
            original_minutes=round(words / 230.0, 1),
            extraction_method="newsletter.email",
            warnings=warnings,
        )

    def _clean_html_to_markdown(self, html_str: str, warnings: list[str]) -> str:
        soup = BeautifulSoup(html_str, "html.parser")

        # Strip scripts, styles, noscript, hidden preheaders
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # Remove 1x1 tracking pixels
        for img in soup.find_all("img"):
            width = img.get("width")
            height = img.get("height")
            if (width in ("1", 1, "0", 0) and height in ("1", 1, "0", 0)) or "tracker" in str(
                img.get("src", "")
            ):
                img.decompose()

        # Detect and remove footer/unsubscribe blocks
        for element in soup.find_all(["div", "p", "table", "footer", "section"]):
            text = element.get_text().lower()
            if any(ind in text for ind in FOOTER_INDICATORS) and len(text) < 500:
                element.decompose()

        # Detect sponsor blocks
        for element in soup.find_all(["div", "section", "p"]):
            text = element.get_text()
            if SPONSOR_REGEX.search(text) and len(text) < 400:
                warnings.append("sponsored_section_removed")
                element.decompose()

        cleaned_html = str(soup)
        md = markdownify.markdownify(cleaned_html, heading_style="ATX", strip=["img"]).strip()
        # Collapse multiple newlines
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md


newsletter_extractor = NewsletterExtractor()
