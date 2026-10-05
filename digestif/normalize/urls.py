"""URL canonicalization, entity extraction, tracking param stripping, and hashing."""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from digestif.security.ssrf import safe_fetch

# Regex for extracting URLs from raw text
URL_REGEX = re.compile(
    r"https?://(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?::\d+)?(?:/[^\s<>'\"`]*)*",
    re.IGNORECASE,
)

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "igsh",
    "igshid",
    "si",
    "ref",
    "ref_src",
    "mc_cid",
    "mc_eid",
    "r",
    "triedredirect",
    "publication_id",
    "post_id",
}

SHORTENER_DOMAINS = {
    "t.co",
    "bit.ly",
    "lnkd.in",
    "buff.ly",
    "tinyurl.com",
    "link.mail.beehiiv.com",
    "click.convertkit-mail.com",
    "cur.at",
    "ift.tt",
    "ow.ly",
}


def extract_urls(text: str) -> list[str]:
    """Extracts all HTTP/HTTPS URLs from raw text in order of appearance."""
    if not text:
        return []
    matches = URL_REGEX.findall(text)
    # Clean trailing punctuation often caught by regex
    cleaned = []
    for m in matches:
        while m and m[-1] in (")", "]", "}", ".", ",", ";", "!", "?", '"', "'"):
            # Only keep a trailing ")" while it's actually balancing an unmatched "(":
            # a plain substring check (old behavior) also matched internal parens
            # like "Foo_(bar)" and wrongly kept a genuinely extraneous outer ")".
            if m[-1] == ")" and m.count(")") <= m.count("("):
                break
            m = m[:-1]
        if m:
            cleaned.append(m)
    return cleaned


def compute_url_hash(canonical_url: str) -> str:
    """Computes SHA-256 hash of the canonical URL string."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    """Canonicalizes a URL deterministically without network calls."""
    if not url:
        return ""

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return url

    # Lowercase netloc and strip www.
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if ":" in netloc:
        host, port = netloc.split(":", 1)
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            netloc = host

    path = parsed.path
    if not path:
        path = "/"

    # 1. Platform: X / Twitter
    if netloc in (
        "x.com",
        "twitter.com",
        "mobile.twitter.com",
        "fxtwitter.com",
        "vxtwitter.com",
        "fixupx.com",
    ):
        m = re.search(r"/(?:[^/]+)/status/(\d+)", path)
        if m:
            return f"https://x.com/i/status/{m.group(1)}"

    # 2. Platform: Instagram
    if netloc in ("instagram.com", "instagr.am"):
        m = re.search(r"/(?:p|reel|reels|tv)/([a-zA-Z0-9_-]+)", path)
        if m:
            return f"https://instagram.com/p/{m.group(1)}/"

    # 3. Platform: YouTube
    if netloc in ("youtube.com", "m.youtube.com"):
        # Shorts
        m = re.search(r"/shorts/([a-zA-Z0-9_-]+)", path)
        if m:
            return f"https://youtube.com/watch?v={m.group(1)}"
        # Watch URL with ?v=
        q = dict(parse_qsl(parsed.query))
        if "v" in q:
            video_id = q["v"]
            # Keep list param if present
            if "list" in q:
                return f"https://youtube.com/watch?v={video_id}&list={q['list']}"
            return f"https://youtube.com/watch?v={video_id}"
    elif netloc == "youtu.be":
        video_id = path.lstrip("/").split("/")[0]
        if video_id:
            return f"https://youtube.com/watch?v={video_id}"

    # 4. Platform: Substack
    # open.substack.com/pub/{pub}/p/{slug} -> https://{pub}.substack.com/p/{slug}
    if netloc == "open.substack.com":
        m = re.search(r"^/pub/([a-zA-Z0-9_-]+)/p/([a-zA-Z0-9_-]+)", path)
        if m:
            return f"https://{m.group(1)}.substack.com/p/{m.group(2)}"

    # Strip tracking parameters from query
    query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
    filtered_pairs = []
    for k, v in query_pairs:
        k_lower = k.lower()
        if k_lower in TRACKING_PARAMS:
            continue
        # Special case: X 's' and 't' tracking params
        if netloc in ("x.com", "twitter.com") and k_lower in ("s", "t"):
            continue
        filtered_pairs.append((k, v))

    # Normalize path trailing slashes (except root)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    sorted_query = urlencode(sorted(filtered_pairs))
    # Drop fragments
    return urlunparse((scheme, netloc, path, "", sorted_query, ""))


async def resolve_and_canonicalize(url: str) -> str:
    """Resolves shortener redirects through SSRF guard, then returns canonical URL."""
    canonical = canonicalize_url(url)
    parsed = urlparse(canonical)
    if parsed.netloc in SHORTENER_DOMAINS or "substack.com/redirect" in canonical:
        try:
            resp = await safe_fetch(url, max_redirects=5, timeout=10.0)
            return canonicalize_url(str(resp.url))
        except Exception:
            return canonical
    return canonical
