"""Job tasks and handlers registered for Digestif worker pool."""

from typing import Any, Callable, Coroutine

from digestif.db.repo import db
from digestif.observability import logger

TaskHandler = Callable[[int | None, dict[str, Any]], Coroutine[Any, Any, None]]

_REGISTRY: dict[str, TaskHandler] = {}


def register_task(kind: str) -> Callable[[TaskHandler], TaskHandler]:
    """Decorator to register an async function as a job task handler."""

    def decorator(func: TaskHandler) -> TaskHandler:
        _REGISTRY[kind] = func
        return func

    return decorator


async def execute_task(kind: str, item_id: int | None, payload: dict[str, Any]) -> None:
    """Dispatches a task to its registered handler."""
    if kind not in _REGISTRY:
        raise ValueError(f"No task handler registered for job kind '{kind}'")
    handler = _REGISTRY[kind]
    logger.info("Executing job task", kind=kind, item_id=item_id)
    await handler(item_id, payload)


# --- Core Registered Task Handlers ---


@register_task("extract")
async def handle_extract_task(item_id: int | None, payload: dict[str, Any]) -> None:
    if item_id is None:
        return
    item = db.get_item(item_id)
    if not item:
        return

    from digestif.extract.router import extract_item_content

    url = item.get("canonical_url") or item.get("url")
    hints = {"source_type": item.get("source_type")}
    db.update_item_status(item_id, "extracting")

    try:
        doc = await extract_item_content(url=url, hints=hints)
        db.save_item_content(
            item_id=item_id,
            text_md=doc.text_md,
            extraction_method=doc.extraction_method,
            extraction_meta="; ".join(doc.warnings) if doc.warnings else None,
        )
        db.update_item_metadata(
            item_id=item_id,
            title=doc.title or item.get("title"),
            author=doc.author or item.get("author"),
            publisher=doc.publisher or item.get("publisher"),
            published_at=doc.published_at or item.get("published_at"),
            word_count=doc.word_count,
            original_minutes=doc.original_minutes,
            language=doc.language,
            status="extracted",
        )
        # Enqueue downstream analysis
        db.enqueue_job(kind="analyze", item_id=item_id)
        logger.info("Content extracted successfully, enqueued for analysis", item_id=item_id)

    except Exception as e:
        logger.error("Extraction task failed", item_id=item_id, error=str(e))
        db.update_item_status(item_id, "failed", failure_reason=str(e))
        raise


@register_task("analyze")
async def handle_analyze_task(item_id: int | None, payload: dict[str, Any]) -> None:
    if item_id is None:
        return
    from digestif.analyze.item import analyze_item

    await analyze_item(item_id)


@register_task("build_digest")
async def handle_build_digest_task(item_id: int | None, payload: dict[str, Any]) -> None:
    from digestif.digest.builder import build_and_deliver_digest

    budget_minutes = payload.get("budget_minutes")
    await build_and_deliver_digest(budget_minutes=budget_minutes, force=payload.get("force", False))


@register_task("imap_poll")
async def handle_imap_poll_task(item_id: int | None, payload: dict[str, Any]) -> None:
    from digestif.capture.imap import imap_poller

    await imap_poller.poll_once()
