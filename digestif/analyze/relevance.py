"""Personal relevance scoring and priority calculation."""

from pathlib import Path

from digestif.llm.router import router
from digestif.llm.schemas import RelevanceResult
from digestif.observability import logger
from digestif.settings import settings

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "relevance.md"


def compute_item_priority(
    relevance: float,
    substance: float,
    novelty: float = 1.0,
    user_note: str | None = None,
    pinned: int = 0,
    time_sensitivity: str = "evergreen",
    carryover_count: int = 0,
    source_affinity: float = 0.5,
) -> float:
    """Computes deterministic priority score according to Section 13.2 formula."""
    user_signal = 1.0 if pinned else (0.6 if user_note else 0.0)
    timeliness = 0.5 if time_sensitivity == "evergreen" else 0.8
    carryover_boost = 0.05 * carryover_count

    priority = (
        0.30 * (relevance / 10.0)
        + 0.25 * (substance / 10.0)
        + 0.15 * novelty
        + 0.15 * user_signal
        + 0.10 * timeliness
        + 0.05 * source_affinity
        + carryover_boost
    )
    return round(priority, 3)


async def score_item_relevance(
    item_id: int,
    title: str,
    one_liner: str,
    core_thesis: str,
    topics: list[str],
    user_note: str = "",
) -> RelevanceResult:
    """Scores relevance against user's profile on the privacy lane (never sent to training tiers)."""
    profile_text = settings.user_profile

    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")
    user_prompt = (
        prompt_template.split("USER:", 1)[1]
        .strip()
        .format(
            user_profile=profile_text,
            title=title,
            one_liner=one_liner,
            core_thesis=core_thesis,
            topics=", ".join(topics),
            user_note=user_note,
        )
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a personal relevance analyst. Given a user's professional background and interests, "
                "score how relevant a saved item is to them on a scale of 0 to 10. "
                "Output JSON matching the RelevanceResult schema."
            ),
        },
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = await router.run(
            task="relevance",
            messages=messages,
            schema=RelevanceResult,
            content_class="personal",  # STRICT PRIVACY BARRIER
            item_id=item_id,
        )
        return result
    except Exception as e:
        logger.warning(
            "Relevance scoring failed, returning default score 5", error=str(e), item_id=item_id
        )
        return RelevanceResult(
            relevance=5,
            why_it_matters_to_you="Relevant to general knowledge and strategy.",
            connects_to_profile=["general"],
        )
