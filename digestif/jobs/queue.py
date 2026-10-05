"""Job worker pool executing background jobs from SQLite jobs table."""

import asyncio
import json
import traceback

from digestif.db.repo import db
from digestif.jobs.tasks import execute_task
from digestif.observability import logger

RETRY_DELAYS_SECONDS = [60, 300, 1800, 7200, 86400]  # 1m, 5m, 30m, 2h, 24h
MAX_ATTEMPTS = 5


class JobWorkerPool:
    def __init__(self, concurrency: int = 2):
        self.concurrency = concurrency
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Starts worker pool tasks."""
        self._stop_event.clear()
        requeued = db.reset_stale_running_jobs()
        if requeued:
            logger.warning(
                "Requeued jobs left stuck in 'running' by a previous process exit",
                count=requeued,
            )
        logger.info("Starting job worker pool", concurrency=self.concurrency)
        for i in range(self.concurrency):
            t = asyncio.create_task(self._worker_loop(i), name=f"job-worker-{i}")
            self._tasks.append(t)

    async def stop(self) -> None:
        """Gracefully stops all workers."""
        logger.info("Stopping job worker pool")
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _worker_loop(self, worker_id: int) -> None:
        while not self._stop_event.is_set():
            try:
                job = db.fetch_next_job()
                if not job:
                    await asyncio.sleep(1.0)
                    continue

                job_id = job["id"]
                kind = job["kind"]
                item_id = job["item_id"]
                attempts = job["attempts"]
                try:
                    payload = json.loads(job["payload"]) if job["payload"] else {}
                except Exception:
                    payload = {}

                logger.info(
                    "Worker picked up job",
                    worker_id=worker_id,
                    job_id=job_id,
                    kind=kind,
                    item_id=item_id,
                    attempt=attempts + 1,
                )

                try:
                    await execute_task(kind, item_id, payload)
                    db.complete_job(job_id)
                    logger.info("Job completed successfully", job_id=job_id, kind=kind)
                except Exception as exc:
                    err_msg = f"{exc}\n{traceback.format_exc()}"
                    next_attempt = attempts + 1
                    logger.error(
                        "Job execution failed",
                        job_id=job_id,
                        kind=kind,
                        error=str(exc),
                        attempt=next_attempt,
                    )
                    if next_attempt < MAX_ATTEMPTS:
                        delay = RETRY_DELAYS_SECONDS[min(attempts, len(RETRY_DELAYS_SECONDS) - 1)]
                        db.fail_job(job_id, error=err_msg, retry_delay=delay)
                    else:
                        db.fail_job(job_id, error=err_msg, retry_delay=None)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Worker error in loop", worker_id=worker_id, error=str(e))
                await asyncio.sleep(2.0)


worker_pool = JobWorkerPool()
