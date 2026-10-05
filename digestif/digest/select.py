"""Candidate item selection and prioritization for nightly digest."""

from typing import Any

from digestif.db.repo import db
from digestif.observability import logger
from digestif.settings import settings


def select_candidates_for_digest() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (candidates_for_digest, letting_go_items).

    Items exceeding carryover_max_days are placed in letting_go.
    """
    all_ready = db.list_candidate_items()
    max_carryover = settings.app_config.get("digest", {}).get("carryover_max_days", 7)

    candidates = []
    letting_go = []

    for item in all_ready:
        carryover = item.get("carryover_count", 0)
        if carryover >= max_carryover:
            letting_go.append(item)
            # Archive item
            db.update_item_status(item["id"], "archived")
            logger.info("Archiving item due to carryover limit ('letting go')", item_id=item["id"])
        else:
            candidates.append(item)

    logger.info(
        "Selected items for digest build",
        candidate_count=len(candidates),
        letting_go_count=len(letting_go),
    )
    return (candidates, letting_go)
