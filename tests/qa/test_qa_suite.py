"""QA Process 1: Unit, Fixture, URL Canonicalization, and Budget Invariants Test Suite."""

import pytest

from digestif.db.repo import Repository
from digestif.digest.budget import allocate_digest_budget
from digestif.extract.newsletter import newsletter_extractor
from digestif.extract.text import text_extractor
from digestif.normalize.urls import (
    canonicalize_url,
    compute_url_hash,
    extract_urls,
)

# 40+ URL Canonicalization and Sanitization Cases
URL_TEST_CASES = [
    # 1-7: X / Twitter
    (
        "https://twitter.com/sama/status/1800000000000000000",
        "https://x.com/i/status/1800000000000000000",
    ),
    (
        "https://x.com/karpathy/status/1700000000000000000?s=20",
        "https://x.com/i/status/1700000000000000000",
    ),
    ("https://mobile.twitter.com/user/status/123456789", "https://x.com/i/status/123456789"),
    ("https://fxtwitter.com/jack/status/20?t=abc", "https://x.com/i/status/20"),
    ("https://vxtwitter.com/elonmusk/status/987654321", "https://x.com/i/status/987654321"),
    ("https://fixupx.com/paulg/status/555555555", "https://x.com/i/status/555555555"),
    ("https://x.com/i/status/1122334455?utm_source=twitter", "https://x.com/i/status/1122334455"),
    # 8-14: Substack
    (
        "https://open.substack.com/pub/stratechery/p/ai-and-the-future?utm_source=email",
        "https://stratechery.substack.com/p/ai-and-the-future",
    ),
    (
        "https://open.substack.com/pub/danwang/p/2026-letter?r=xyz&utm_campaign=post",
        "https://danwang.substack.com/p/2026-letter",
    ),
    (
        "https://thegeneralist.substack.com/p/stripe-breakdown/",
        "https://thegeneralist.substack.com/p/stripe-breakdown",
    ),
    (
        "https://notboring.substack.com/p/nanobots?triedRedirect=true",
        "https://notboring.substack.com/p/nanobots",
    ),
    (
        "https://sinocism.substack.com/p/march-briefing?utm_medium=web",
        "https://sinocism.substack.com/p/march-briefing",
    ),
    (
        "https://diff.substack.com/p/rates-and-tech?publication_id=123",
        "https://diff.substack.com/p/rates-and-tech",
    ),
    (
        "https://open.substack.com/pub/lenny/p/managing-up?r=abc",
        "https://lenny.substack.com/p/managing-up",
    ),
    # 15-21: YouTube
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/watch?v=dQw4w9WgXcQ"),
    (
        "https://youtube.com/watch?v=dQw4w9WgXcQ&feature=share&si=abc",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
    ),
    ("https://youtu.be/dQw4w9WgXcQ?si=def", "https://youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/abcdefghijk", "https://youtube.com/watch?v=abcdefghijk"),
    (
        "https://youtube.com/shorts/12345678901?utm_source=yt",
        "https://youtube.com/watch?v=12345678901",
    ),
    (
        "https://www.youtube.com/watch?v=abc&list=PL12345&index=2",
        "https://youtube.com/watch?v=abc&list=PL12345",
    ),
    # 22-28: Instagram
    ("https://www.instagram.com/p/C-123456789/", "https://instagram.com/p/C-123456789/"),
    ("https://instagram.com/reel/C-987654321/?igsh=xyz", "https://instagram.com/p/C-987654321/"),
    (
        "https://www.instagram.com/reels/C-abcdefghi/?utm_source=ig_web_copy_link",
        "https://instagram.com/p/C-abcdefghi/",
    ),
    ("https://instagr.am/p/C-xyz123456/", "https://instagram.com/p/C-xyz123456/"),
    ("https://www.instagram.com/tv/C-tv9876543/", "https://instagram.com/p/C-tv9876543/"),
    ("https://instagram.com/p/C-test123?utm_campaign=share", "https://instagram.com/p/C-test123/"),
    (
        "https://www.instagram.com/reel/C-anotherOne/?igshid=abc123def",
        "https://instagram.com/p/C-anotherOne/",
    ),
    # 29-42: Generic Web & Tracking Parameters
    (
        "https://paulgraham.com/greatwork.html?utm_source=twitter",
        "https://paulgraham.com/greatwork.html",
    ),
    (
        "https://www.bloomberg.com/news/articles/2026-09-27/markets?fbclid=IwAR123",
        "https://bloomberg.com/news/articles/2026-09-27/markets",
    ),
    (
        "https://techcrunch.com/2026/09/27/startups/?gclid=Cj0KCQ",
        "https://techcrunch.com/2026/09/27/startups",
    ),
    (
        "https://www.theverge.com/ai/article?utm_medium=social&utm_campaign=news",
        "https://theverge.com/ai/article",
    ),
    ("https://example.com/post/?utm_content=button&utm_term=link", "https://example.com/post"),
    (
        "https://news.ycombinator.com/item?id=12345678",
        "https://news.ycombinator.com/item?id=12345678",
    ),
    ("https://github.com/astral-sh/uv?ref=badge", "https://github.com/astral-sh/uv"),
    ("https://example.org/blog/article#comments", "https://example.org/blog/article"),
    (
        "https://www.reuters.com/business/article-id/?mc_cid=12345&mc_eid=abcde",
        "https://reuters.com/business/article-id",
    ),
    (
        "https://arstechnica.com/gadgets/2026/09/review/?ref_src=twsrc",
        "https://arstechnica.com/gadgets/2026/09/review",
    ),
    (
        "https://medium.com/@author/story-slug?source=email",
        "https://medium.com/@author/story-slug?source=email",
    ),
    ("https://mint.com/article?triedredirect=true&r=home", "https://mint.com/article"),
    ("https://example.com:443/secure", "https://example.com/secure"),
    ("http://example.com:80/standard", "http://example.com/standard"),
]


@pytest.mark.parametrize("raw_url,expected_canonical", URL_TEST_CASES)
def test_url_canonicalization_table(raw_url: str, expected_canonical: str):
    actual = canonicalize_url(raw_url)
    assert actual == expected_canonical, (
        f"Failed for {raw_url}: got {actual}, expected {expected_canonical}"
    )


def test_url_extraction_from_mixed_text():
    sample = (
        "Check this out: https://paulgraham.com/greatwork.html. Also read (https://x.com/sama/status/123) "
        "and https://youtu.be/dQw4w9WgXcQ!"
    )
    urls = extract_urls(sample)
    assert len(urls) == 3
    assert "https://paulgraham.com/greatwork.html" in urls
    assert "https://x.com/sama/status/123" in urls
    assert "https://youtu.be/dQw4w9WgXcQ" in urls


def test_budget_allocation_invariants():
    # Simulate 10 items of varying priorities and lengths
    items = []
    for i in range(1, 11):
        items.append(
            {
                "id": i,
                "title": f"Article {i}",
                "priority": 0.3 + (i * 0.06),  # 0.36 to 0.90
                "original_minutes": 2.0 + (i * 1.5),  # 3.5 to 17 min
                "word_count": int((2.0 + (i * 1.5)) * 230),
            }
        )

    budget_minutes = 20
    wpm = 230
    total_budget_words = budget_minutes * wpm  # 4600

    budget_items, stats = allocate_digest_budget(items, budget_minutes=budget_minutes, wpm=wpm)

    # Invariant 1: Total allocated target words + reserves should stay within budget
    assert stats["total_target_words"] <= total_budget_words

    # Invariant 2: No item target words exceeds half of its original word count (with 150 floor)
    items_by_id = {it["id"]: it for it in items}
    for b in budget_items:
        if b.tier in ("deep", "standard"):
            orig_wc = items_by_id[b.id]["word_count"]
            assert b.target_words <= max(150, int(0.5 * orig_wc))
            # Invariant 3: Clamping bounds
            if b.tier == "deep":
                assert b.target_words >= 150  # clamped with floor
            elif b.tier == "standard":
                assert b.target_words >= 150
            assert b.target_words <= 1100

    # Invariant 4: Quick hits capped at 35 words
    for b in budget_items:
        if b.tier == "quick_hit":
            assert b.target_words == 35


@pytest.mark.asyncio
async def test_text_extractor():
    raw_text = (
        "Zero-Cost Content Architecture\n\n"
        "Building systems that run entirely on free tiers requires robust routing and caching. "
        "Each provider must be treated as transient."
    )
    doc = await text_extractor.extract(url=None, raw_payload=raw_text)
    assert doc.title == "Zero-Cost Content Architecture"
    assert doc.word_count > 10
    assert doc.original_minutes >= 0.1
    assert doc.extraction_method == "text.direct"


@pytest.mark.asyncio
async def test_newsletter_extractor_clean_html():
    raw_email = (
        "From: editor@newsletter.com\n"
        "Subject: Weekly Brief\n"
        "Content-Type: text/html; charset=utf-8\n\n"
        "<html><body>"
        "<p>Welcome to this edition of our research series on autonomous software engineering.</p>"
        "<div class='sponsor'>Sponsored by SuperCorp: Buy our tools!</div>"
        "<p>Here is the main thesis: AI agent architectures will converge on state-machine loops. "
        "Unconstrained prompt chaining creates compounding errors, whereas deterministic state transitions "
        "ensure predictable execution, zero recurring operational overhead, and robust observability across all pipelines.</p>"
        "<img src='https://tracker.com/pixel.gif' width='1' height='1'>"
        "<footer>To unsubscribe, click here.</footer>"
        "</body></html>"
    )

    doc = await newsletter_extractor.extract(
        url=None, raw_payload=raw_email, hints={"is_email": True}
    )
    assert "Weekly Brief" in doc.title
    assert "SuperCorp" not in doc.text_md
    assert "pixel.gif" not in doc.text_md
    assert "unsubscribe" not in doc.text_md.lower()
    assert "AI agent architectures" in doc.text_md
    assert "sponsored_section_removed" in doc.warnings


def test_repository_idempotency_and_dedup(tmp_path):
    repo = Repository(db_path=tmp_path / "test.db")

    # Idempotent captures
    c1 = repo.insert_capture("telegram", "1001", '{"test": 1}')
    assert c1 is not None
    c2 = repo.insert_capture("telegram", "1001", '{"test": 2}')
    assert c2 is None  # duplicate ignored

    # Dedup level 1
    u_hash = compute_url_hash("https://example.com/unique")
    item_id = repo.insert_item(
        capture_id=c1,
        source_type="web",
        url="https://example.com/unique",
        canonical_url="https://example.com/unique",
        url_hash=u_hash,
        title="Unique Article",
        user_note="First note",
    )
    assert item_id > 0

    # Search by url_hash
    found = repo.find_item_by_url_hash(u_hash)
    assert found is not None
    assert found["id"] == item_id
    assert found["title"] == "Unique Article"
