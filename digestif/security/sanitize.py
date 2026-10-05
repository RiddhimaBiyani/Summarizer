"""Sanitization and prompt injection protection."""

import re

UNTRUSTED_CONTENT_TEMPLATE = """<untrusted_content>
{content}
</untrusted_content>"""

UNTRUSTED_SOURCE_TEMPLATE = """<untrusted_source id={source_id}>
Title: {title}
Publisher: {publisher}
URL: {url}
{content}
</untrusted_source>"""


def wrap_untrusted_content(content: str) -> str:
    """Wraps raw fetched content in untrusted_content tags, escaping nested tags."""
    # Defang any attempted closing tags inside untrusted text
    safe_content = re.sub(
        r"</\s*untrusted_content\s*>", "&lt;/untrusted_content&gt;", content, flags=re.IGNORECASE
    )
    return UNTRUSTED_CONTENT_TEMPLATE.format(content=safe_content.strip())


def wrap_untrusted_source(
    source_id: int, title: str, publisher: str, url: str, content: str
) -> str:
    """Wraps raw fetched enrichment source in untrusted_source tags."""
    safe_content = re.sub(
        r"</\s*untrusted_source\s*>", "&lt;/untrusted_source&gt;", content, flags=re.IGNORECASE
    )
    return UNTRUSTED_SOURCE_TEMPLATE.format(
        source_id=source_id,
        title=title,
        publisher=publisher,
        url=url,
        content=safe_content.strip(),
    )


def sanitize_text(text: str) -> str:
    """Basic text cleanup, normalizing unicode and removing dangerous control characters."""
    if not text:
        return ""
    # Remove null bytes and non-printable control chars except tabs/newlines
    cleaned = "".join(ch for ch in text if ch in ("\n", "\r", "\t") or ch >= " ")
    return cleaned.strip()
