"""Telegram delivery module sending formatted teaser and HTML document."""

from pathlib import Path

import httpx

from digestif.observability import logger
from digestif.settings import settings

TEASER_MAX_CHARS = 3500


async def send_telegram_digest(
    digest_id: int,
    teaser_text: str,
    html_path: str,
) -> bool:
    """Delivers Telegram teaser with inline keyboard and attaches full HTML file as document."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_ALLOWED_USER_ID

    if not token or not chat_id:
        logger.warning("Telegram bot credentials not configured; skipping Telegram delivery")
        return False

    if len(teaser_text) > TEASER_MAX_CHARS:
        logger.warning(
            "Telegram teaser exceeded length cap; truncating",
            original_length=len(teaser_text),
        )
        teaser_text = (
            teaser_text[: TEASER_MAX_CHARS - 60].rstrip() + "\n\n… (open full digest below)"
        )

    base_url = f"https://api.telegram.org/bot{token}"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📖 Full digest", "callback_data": f"full:{digest_id}"},
                {"text": "✅ Done", "callback_data": f"done:{digest_id}"},
            ]
        ]
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Send Teaser Message
        try:
            resp = await client.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": teaser_text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard,
                },
            )
            resp.raise_for_status()
            logger.info("Sent Telegram digest teaser", digest_id=digest_id)
        except Exception as e:
            logger.error("Failed to send Telegram digest teaser", error=str(e), digest_id=digest_id)
            return False

        # 2. Send Full HTML File Document
        try:
            path = Path(html_path)
            if path.exists():
                with open(path, "rb") as f:
                    doc_resp = await client.post(
                        f"{base_url}/sendDocument",
                        data={
                            "chat_id": chat_id,
                            "caption": "Full interactive digest (open in browser)",
                        },
                        files={"document": (path.name, f, "text/html")},
                    )
                    doc_resp.raise_for_status()
                    logger.info("Sent Telegram digest HTML document", digest_id=digest_id)
        except Exception as e:
            logger.error("Failed to send Telegram HTML document", error=str(e), digest_id=digest_id)

    return True
