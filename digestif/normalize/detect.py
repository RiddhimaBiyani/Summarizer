"""Source type detection based on URL, domain, or content hints."""

from urllib.parse import urlparse


def detect_source_type(url: str | None, content_type_hint: str | None = None) -> str:
    """Detects source_type: web | substack | newsletter | x | instagram | youtube | pdf | image | text | voice_note."""
    if not url:
        if content_type_hint:
            if "pdf" in content_type_hint.lower():
                return "pdf"
            if "image" in content_type_hint.lower():
                return "image"
            if "audio" in content_type_hint.lower() or "voice" in content_type_hint.lower():
                return "voice_note"
        return "text"

    parsed = urlparse(url.lower())
    netloc = parsed.netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # X / Twitter
    if netloc in ("x.com", "twitter.com", "mobile.twitter.com", "fxtwitter.com", "vxtwitter.com"):
        return "x"

    # Instagram
    if netloc in ("instagram.com", "instagr.am"):
        return "instagram"

    # YouTube
    if netloc in ("youtube.com", "m.youtube.com", "youtu.be"):
        return "youtube"

    # Substack
    if netloc.endswith(".substack.com") or netloc == "substack.com":
        return "substack"

    # LinkedIn
    if netloc.endswith("linkedin.com"):
        return "linkedin"

    # PDF direct link
    if parsed.path.lower().endswith(".pdf"):
        return "pdf"

    return "web"
