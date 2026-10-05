"""QA Process 3: End-to-End Pipeline Simulation & Idempotency Validator."""

from pathlib import Path

import pytest

from digestif.analyze.item import analyze_item
from digestif.digest.builder import build_and_deliver_digest
from digestif.llm.router import router
from digestif.llm.schemas import EditorPassResult, ItemAnalysis, KeyPoint, RelevanceResult


@pytest.fixture
def mock_llm_for_e2e(monkeypatch):
    """Sets up deterministic mock responses for the LLM router to simulate offline end-to-end execution."""

    async def mock_router_run(task, messages, schema=None, content_class="public", **kwargs):
        if task == "analyze":
            return ItemAnalysis(
                title="State Machine Agents",
                author="Research Team",
                content_kind="essay",
                one_liner="Why deterministic loops outperform unconstrained autonomous agent loops.",
                what_it_is="An architectural study analyzing failure modes in LLM agent trajectories.",
                core_thesis="Deterministic state machine transitions bound latency and prevent infinite loops.",
                key_points=[
                    KeyPoint(
                        point="Unconstrained agent loops degrade exponentially.",
                        detail="As trajectory length increases, compounding errors degrade task completion.",
                        evidence="Data from 500 benchmark tests.",
                        evidence_type="data",
                    ),
                    KeyPoint(
                        point="Finite state machines guarantee bounded execution.",
                        detail="State machine transitions ensure every branch has a deterministic timeout.",
                        evidence="Formal verification in robotics and distributed systems.",
                        evidence_type="reasoning",
                    ),
                ],
                what_you_can_learn=["Always define explicit state boundaries for LLM tasks."],
                actions=["Implement bounded retries with jitter."],
                substance=8,
                verdict="read_original",
                verdict_reason="Dense technical proofs worth studying in full.",
                topics=["ai", "systems", "architecture"],
            )
        elif task == "relevance":
            return RelevanceResult(
                relevance=9,
                why_it_matters_to_you="Directly aligns with software architecture and AI product strategy.",
                connects_to_profile=["AI product strategy"],
            )
        elif task == "editor":
            return EditorPassResult(
                headline="Deterministic Architecture for AI Agents",
                top_three=[
                    "Unconstrained agent loops fail exponentially on long tasks.",
                    "Finite state machines provide guaranteed bounded execution.",
                    "Explicit state boundaries prevent token runaway.",
                ],
                themes=[],
                reading_order=[1, 2],
                reflection_prompt="Where can you replace an open agent loop with a deterministic transition?",
            )
        elif task == "section_write":
            return (
                "### 1. State Machine Agents\n\n"
                "**In one line:** Why deterministic loops outperform autonomous agent loops.\n\n"
                "**What it is:** An architectural study analyzing failure modes in LLM agent trajectories.\n\n"
                "**Key takeaways:**\n"
                "1. Unconstrained loops degrade exponentially.\n"
                "2. Finite state machines guarantee bounded execution.\n\n"
                "**Why it matters to you:** Directly aligns with AI product strategy.\n\n"
                "**Read the original?** Read Original [Source](https://example.com/agents)"
            )
        return "Generic mock text"

    router.set_mock_handler(mock_router_run)
    yield
    router.set_mock_handler(None)


@pytest.mark.asyncio
async def test_e2e_pipeline_and_idempotency(tmp_path, monkeypatch, mock_llm_for_e2e):
    # Setup temporary database and data directories
    test_db = tmp_path / "e2e_digestif.db"
    monkeypatch.setattr("digestif.settings.settings.DATA_DIR", tmp_path)
    from digestif.db.repo import db

    db.set_db_path(test_db)

    # 1. Capture 2 items into database
    c1 = db.insert_capture(
        "telegram", "101", '{"text": "https://example.com/agents check this out"}'
    )
    item_id_1 = db.insert_item(
        capture_id=c1,
        source_type="web",
        url="https://example.com/agents",
        canonical_url="https://example.com/agents",
        url_hash="hash_agents",
        user_note="check this out",
        status="extracted",
    )
    db.save_item_content(
        item_id=item_id_1,
        text_md="Deterministic state machines guarantee bounded execution for autonomous agents.",
        extraction_method="web.trafilatura",
    )

    c2 = db.insert_capture("email", "msg-202", '{"subject": "Newsletter"}')
    item_id_2 = db.insert_item(
        capture_id=c2,
        source_type="newsletter",
        title="Weekly Systems Brief",
        status="extracted",
    )
    db.save_item_content(
        item_id=item_id_2,
        text_md="Distributed systems and event-driven pipelines are resilient under load.",
        extraction_method="newsletter.email",
    )

    # 2. Run analysis on both items
    analysis1 = await analyze_item(item_id_1)
    analysis2 = await analyze_item(item_id_2)

    assert analysis1.substance >= 5
    assert analysis2.substance >= 5

    # Verify status changed to ready
    it1 = db.get_item(item_id_1)
    it2 = db.get_item(item_id_2)
    assert it1["status"] == "ready"
    assert it2["status"] == "ready"

    # 3. Build Digest for today
    today_date = "2026-09-27"
    digest = await build_and_deliver_digest(digest_date=today_date, budget_minutes=15)
    assert digest is not None
    assert digest["status"] == "delivered"
    assert digest["word_count"] > 50
    assert digest["est_minutes"] > 0.0

    # Verify generated deliverables on disk
    html_path = Path(digest["html_path"])
    email_html_path = Path(digest["email_html_path"])
    assert html_path.exists()
    assert email_html_path.exists()

    html_content = html_path.read_text(encoding="utf-8")
    assert "DIGESTIF" in html_content
    assert "Deterministic Architecture for AI Agents" in html_content

    # 4. Assert Idempotency on Re-run
    # Re-running build_and_deliver_digest should NOT create another digest or fail
    second_run = await build_and_deliver_digest(
        digest_date=today_date, budget_minutes=15, force=False
    )
    assert second_run is not None
    assert second_run["id"] == digest["id"]
    assert second_run["delivered_at"] == digest["delivered_at"]
