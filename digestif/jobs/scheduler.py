"""APScheduler setup for Digestif in Asia/Kolkata timezone."""

import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from digestif.db.repo import db
from digestif.observability import logger
from digestif.settings import settings


class SchedulerService:
    def __init__(self) -> None:
        tz_str = settings.app_config.get("timezone", "Asia/Kolkata")
        self.timezone = pytz.timezone(tz_str)
        self.scheduler = AsyncIOScheduler(
            timezone=self.timezone,
            job_defaults={
                "coalesce": True,
                "misfire_grace_time": 6 * 3600,  # 6 hours
            },
        )

    def setup_jobs(self) -> None:
        """Sets up scheduled cron and interval triggers."""
        # 1. Digest generation trigger: digest.time - 30 minutes
        digest_time_str = settings.app_config.get("digest", {}).get("time", "21:30")
        try:
            hour, minute = map(int, digest_time_str.split(":"))
        except Exception:
            hour, minute = 21, 30

        # Subtract 30 minutes
        dt = datetime.datetime(2026, 1, 1, hour, minute) - datetime.timedelta(minutes=30)
        build_hour, build_minute = dt.hour, dt.minute

        self.scheduler.add_job(
            self._trigger_daily_digest,
            trigger=CronTrigger(hour=build_hour, minute=build_minute, timezone=self.timezone),
            id="daily_digest_build",
            name="Daily Digest Build Trigger",
            replace_existing=True,
        )
        logger.info(
            "Scheduled daily digest build",
            build_time=f"{build_hour:02d}:{build_minute:02d}",
            delivery_time=digest_time_str,
            timezone=str(self.timezone),
        )

        # 2. IMAP polling: every 5 minutes
        self.scheduler.add_job(
            self._trigger_imap_poll,
            trigger=IntervalTrigger(minutes=5),
            id="imap_poll",
            name="IMAP Inbox Poll Trigger",
            replace_existing=True,
        )

        # 3. Catch-up check on wake: every 15 minutes
        self.scheduler.add_job(
            self._trigger_catchup_check,
            trigger=IntervalTrigger(minutes=15),
            id="catchup_check",
            name="Wake Catch-Up Check",
            replace_existing=True,
        )

    async def start(self) -> None:
        self.setup_jobs()
        self.scheduler.start()
        logger.info("Scheduler started successfully")

    async def stop(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    async def _trigger_daily_digest(self) -> None:
        logger.info("Triggering scheduled nightly digest job")
        db.enqueue_job(kind="build_digest", payload={"reason": "scheduled"})

    async def _trigger_imap_poll(self) -> None:
        db.enqueue_job(kind="imap_poll", payload={})

    async def _trigger_catchup_check(self) -> None:
        from digestif.reliability.catchup import check_and_run_catchup

        await check_and_run_catchup()


scheduler_service = SchedulerService()
