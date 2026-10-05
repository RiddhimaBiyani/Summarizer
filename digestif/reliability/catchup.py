"""Catch-up logic on wake and quiet hours evaluation."""

import datetime

import pytz

from digestif.db.repo import db
from digestif.observability import logger
from digestif.settings import settings


def get_current_local_time() -> datetime.datetime:
    """Returns the current datetime in the configured timezone."""
    tz_str = settings.app_config.get("timezone", "Asia/Kolkata")
    tz = pytz.timezone(tz_str)
    return datetime.datetime.now(tz)


def is_in_quiet_hours(dt: datetime.datetime | None = None) -> bool:
    """Evaluates whether the given (or current) local time is in quiet hours."""
    if dt is None:
        dt = get_current_local_time()

    quiet_cfg = settings.app_config.get("quiet_hours", ["23:30", "07:30"])
    if not quiet_cfg or len(quiet_cfg) < 2:
        return False

    try:
        start_h, start_m = map(int, quiet_cfg[0].split(":"))
        end_h, end_m = map(int, quiet_cfg[1].split(":"))

        current_time = dt.time()
        start_time = datetime.time(start_h, start_m)
        end_time = datetime.time(end_h, end_m)

        # Cross-midnight range (e.g. 23:30 to 07:30)
        if start_time > end_time:
            return current_time >= start_time or current_time < end_time
        else:
            return start_time <= current_time < end_time
    except Exception as e:
        logger.warning("Error evaluating quiet hours; defaulting to False", error=str(e))
        return False


async def check_and_run_catchup() -> None:
    """Checks if today's digest was missed while offline/sleeping and builds if candidates exist."""
    local_now = get_current_local_time()
    today_str = local_now.strftime("%Y-%m-%d")

    digest_time_str = settings.app_config.get("digest", {}).get("time", "21:30")
    try:
        target_h, target_m = map(int, digest_time_str.split(":"))
        target_time = datetime.time(target_h, target_m)
    except Exception:
        target_time = datetime.time(21, 30)

    # Only catch up if we are past today's scheduled digest time
    if local_now.time() < target_time:
        return

    # Check if digest was already built/delivered today
    existing = db.get_digest_by_date(today_str)
    if existing and existing.get("status") in ("delivered", "ready", "building"):
        return

    # Check if there are candidate items
    candidates = db.list_candidate_items()
    if not candidates:
        return

    logger.info(
        "Catch-up detected: machine woke up past scheduled digest time with pending items; building now",
        today=today_str,
        candidates=len(candidates),
    )
    from digestif.digest.builder import build_and_deliver_digest

    await build_and_deliver_digest(digest_date=today_str, kind="catchup", force=True)
