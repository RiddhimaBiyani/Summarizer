"""Deduplication logic (URL hash check and content hash comparison)."""

import hashlib
import re
from typing import Any

from digestif.db.repo import db
from digestif.observability import logger


def compute_content_hash(text: str) -> str:
    """Computes SHA-256 hash of normalized text (lowercased, collapsed whitespace, first 20k chars)."""
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text.lower().strip())[:20000]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def check_and_handle_url_dedup(
    url_hash: str, new_user_note: str | None = None
) -> dict[str, Any] | None:
    """Checks if an item with the same url_hash exists within the last 30 days.

    If found:
      - Appends new_user_note if provided.
      - Sets pinned=1 ('saved twice = important').
      - Returns existing item dict.
    Otherwise returns None.
    """
    existing = db.find_item_by_url_hash(url_hash, days=30)
    if not existing:
        return None

    item_id = existing["id"]
    notes = [existing["user_note"]] if existing.get("user_note") else []
    if new_user_note and new_user_note not in notes:
        notes.append(new_user_note)

    combined_note = " | ".join(notes) if notes else None
    db.update_item_metadata(item_id, user_note=combined_note, pinned=1)
    logger.info("Deduplicated item by url_hash; pinned and updated notes", item_id=item_id)
    return db.get_item(item_id)
