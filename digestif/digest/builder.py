"""Digest builder coordinating item selection, budgeting, synthesis, rendering, and delivery."""

import datetime
from typing import Any

from digestif.db.repo import db
from digestif.deliver.email_out import send_email_digest
from digestif.deliver.telegram_out import send_telegram_digest
from digestif.digest.budget import allocate_digest_budget
from digestif.digest.editor import run_editor_pass
from digestif.digest.render import renderer
from digestif.digest.select import select_candidates_for_digest
from digestif.digest.writers import write_all_sections
from digestif.observability import logger
from digestif.settings import settings


async def build_and_deliver_digest(
    digest_date: str | None = None,
    budget_minutes: int | None = None,
    kind: str = "daily",
    force: bool = False,
) -> dict[str, Any] | None:
    """Builds and delivers the nightly digest."""
    if not digest_date:
        digest_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # Check for existing delivered digest for today (Idempotency)
    existing = db.get_digest_by_date(digest_date)
    if existing and existing.get("status") == "delivered" and not force:
        logger.info("Digest for date already delivered; skipping build", digest_date=digest_date)
        return existing

    if budget_minutes is None:
        configured_budget = settings.app_config.get("digest", {}).get("default_budget_minutes", 20)
        try:
            budget_minutes = int(configured_budget)
        except (TypeError, ValueError):
            # "auto" is accepted by /budget but has no dedicated allocation logic yet;
            # fall back to the default rather than crashing the whole nightly build.
            logger.warning(
                "Non-numeric default_budget_minutes in config.yaml; using 20",
                value=configured_budget,
            )
            budget_minutes = 20

    # 1. Select Candidates
    candidates, letting_go = select_candidates_for_digest()
    if not candidates:
        logger.info("No candidate items ready for digest build", digest_date=digest_date)
        return None

    logger.info("Beginning digest build", digest_date=digest_date, candidates=len(candidates))

    # 2. Allocate Time Budget
    wpm = int(settings.app_config.get("digest", {}).get("reading_wpm", 230))
    budget_items, budget_stats = allocate_digest_budget(
        candidates, budget_minutes=budget_minutes, wpm=wpm
    )

    items_by_id = {c["id"]: c for c in candidates}
    active_budget_items = [b for b in budget_items if b.tier != "carryover"]

    # 3. Create or Update DB Digest record
    if existing:
        digest_id = existing["id"]
        db.update_digest(digest_id, status="building", budget_minutes=budget_minutes)
    else:
        digest_id = db.insert_digest(
            digest_date=digest_date,
            budget_minutes=budget_minutes,
            kind=kind,
            status="building",
        )

    # 4. Generate Sections in Parallel
    full_sections_md, quick_hits_md = await write_all_sections(
        active_budget_items, items_by_id, concurrency=2
    )

    # 5. Run Chief Editor Pass
    editor_result = await run_editor_pass([items_by_id[b.id] for b in active_budget_items])

    # 6. Render Deliverables
    section_titles = []
    total_original = 0.0
    for b in active_budget_items:
        it = items_by_id[b.id]
        orig_m = float(it.get("original_minutes") or 2.0)
        total_original += orig_m
        if b.tier in ("deep", "standard"):
            section_titles.append(
                {
                    "title": it.get("title", f"Item #{b.id}"),
                    "minutes": round(b.target_words / float(wpm), 1),
                }
            )

    rendered = renderer.render_digest(
        digest_date=digest_date,
        editor_result=editor_result,
        full_sections_md=full_sections_md,
        quick_hits_md=quick_hits_md,
        section_titles=section_titles,
        saved_count=len(active_budget_items),
        total_original_minutes=total_original,
        letting_go=letting_go,
        wpm=wpm,
    )

    # 7. Update Digested State in DB
    for b in active_budget_items:
        db.update_item_metadata(b.id, digested_in=digest_id)

    # Handle carryover count for un-digested overflow items
    carryover_items = [b for b in budget_items if b.tier == "carryover"]
    for cb in carryover_items:
        current_carryover = items_by_id[cb.id].get("carryover_count", 0)
        db.update_item_metadata(cb.id, carryover_count=current_carryover + 1)

    # 8. Delivery
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Check quiet hours before sending Telegram teaser
    from digestif.reliability.catchup import is_in_quiet_hours

    in_quiet = is_in_quiet_hours()
    # `force` also means "bypass the already-delivered check" for the unattended
    # catch-up path, so it must not itself override quiet hours; only an explicit
    # user-initiated build (CLI/Telegram /digest, kind="daily") should ping through.
    if not in_quiet or kind != "catchup":
        await send_telegram_digest(
            digest_id=digest_id,
            teaser_text=rendered["telegram_teaser"],
            html_path=rendered["html_path"],
        )
    else:
        logger.info("Inside quiet hours: holding Telegram teaser until quiet hours end")

    # Email always delivers immediately
    await send_email_digest(
        digest_date=digest_date,
        headline=editor_result.headline,
        est_minutes=rendered["est_minutes"],
        html_content=rendered["email_html_content"],
    )

    db.update_digest(
        digest_id,
        status="delivered",
        html_path=rendered["html_path"],
        email_html_path=rendered["email_html_path"],
        word_count=rendered["word_count"],
        est_minutes=rendered["est_minutes"],
        delivered_at=now_iso,
    )

    logger.info(
        "Digest build and delivery sequence completed", digest_id=digest_id, digest_date=digest_date
    )
    return db.get_digest_by_date(digest_date)
