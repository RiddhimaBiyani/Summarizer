"""Telegram bot capture poller and command/callback router."""

import asyncio
import datetime
import json
from typing import Any

import httpx

from digestif.db.repo import db
from digestif.normalize.dedup import check_and_handle_url_dedup
from digestif.normalize.detect import detect_source_type
from digestif.normalize.urls import compute_url_hash, extract_urls, resolve_and_canonicalize
from digestif.observability import logger
from digestif.settings import settings


class TelegramBotPoller:
    def __init__(self) -> None:
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.allowed_user_id = settings.TELEGRAM_ALLOWED_USER_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.last_update_id = 0
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if not self.token or not self.allowed_user_id:
            logger.warning("Telegram bot credentials not configured; Telegram poller disabled")
            return

        self._stop_event.clear()
        logger.info("Starting Telegram bot long-polling", allowed_user_id=self.allowed_user_id)

        async with httpx.AsyncClient(timeout=60.0) as client:
            while not self._stop_event.is_set():
                try:
                    params: dict[str, Any] = {"timeout": 50}
                    if self.last_update_id > 0:
                        params["offset"] = self.last_update_id + 1

                    resp = await client.get(f"{self.base_url}/getUpdates", params=params)
                    if resp.status_code != 200:
                        logger.warning("getUpdates returned non-200", status=resp.status_code)
                        await asyncio.sleep(3.0)
                        continue

                    data = resp.json()
                    updates = data.get("result", [])
                    for update in updates:
                        self.last_update_id = max(self.last_update_id, update["update_id"])
                        await self._process_update(client, update)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Error in Telegram poller loop", error=str(e))
                    await asyncio.sleep(2.0)

    async def stop(self) -> None:
        logger.info("Stopping Telegram poller")
        self._stop_event.set()

    async def _process_update(self, client: httpx.AsyncClient, update: dict[str, Any]) -> None:
        update_id = update["update_id"]

        # Check for callback query (inline button clicks)
        if "callback_query" in update:
            await self._handle_callback_query(client, update["callback_query"])
            return

        message = update.get("message")
        if not message:
            return

        from_user = message.get("from", {})
        user_id = from_user.get("id")

        # 1. Enforce strict single-user allowlist
        if user_id != self.allowed_user_id:
            logger.warning("Unauthorized user attempted to message bot", user_id=user_id)
            return

        chat_id = message["chat"]["id"]
        message_id = message["message_id"]

        # 2. Idempotent insert into captures table
        raw_json = json.dumps(update)
        capture_id = db.insert_capture(
            channel="telegram", external_id=str(update_id), raw_json=raw_json
        )
        if not capture_id:
            logger.debug("Duplicate Telegram update ignored", update_id=update_id)
            return

        # 3. Non-blocking reaction: 👀 (eyes) on receipt
        await self._set_reaction(client, chat_id, message_id, "👀")

        # Voice/audio/document/photo capture (transcription, OCR) isn't built yet
        # (Phase 5) -- tell the user instead of silently dropping the message.
        if not (message.get("text") or message.get("caption")) and any(
            k in message for k in ("voice", "audio", "document", "photo", "video", "video_note")
        ):
            await self._send_reply(
                client,
                chat_id,
                "📎 Voice notes, photos, and files aren't supported yet -- share a link or type/paste text instead.",
            )
            return

        # Extract text or caption
        text = message.get("text") or message.get("caption") or ""
        urls = extract_urls(text)

        # 4. Route commands if starts with /
        if text.startswith("/"):
            from digestif.interaction.commands import handle_telegram_command

            reply_text = await handle_telegram_command(text)
            await self._send_reply(client, chat_id, reply_text)
            return

        # 5. Handle URLs
        if urls:
            for url in urls:
                # Resolves shortener redirects (t.co, bit.ly, ...) through the SSRF
                # guard before canonicalizing, so the same article shared via a
                # shortened link and its real URL dedup to the same hash.
                canonical = await resolve_and_canonicalize(url)
                u_hash = compute_url_hash(canonical)

                # Dedup check
                clean_note = text.replace(url, "").strip() or None
                existing = check_and_handle_url_dedup(u_hash, new_user_note=clean_note)
                if existing:
                    await self._set_reaction(client, chat_id, message_id, "👍")
                    continue

                source_type = detect_source_type(canonical)
                item_id = db.insert_item(
                    capture_id=capture_id,
                    source_type=source_type,
                    url=url,
                    canonical_url=canonical,
                    url_hash=u_hash,
                    user_note=clean_note,
                    status="received",
                )
                logger.info(
                    "Captured new URL item from Telegram", item_id=item_id, canonical=canonical
                )
                # Enqueue extraction job
                db.enqueue_job(kind="extract", item_id=item_id, payload={"url": canonical})

            await self._set_reaction(client, chat_id, message_id, "👍")
            return

        # 6. Handle Long text (> 280 chars) as text document
        if len(text) > 280:
            item_id = db.insert_item(
                capture_id=capture_id,
                source_type="text",
                status="received",
            )
            # Save content immediately and enqueue analysis
            from digestif.extract.text import text_extractor

            doc = await text_extractor.extract(url=None, raw_payload=text)
            db.save_item_content(
                item_id=item_id,
                text_md=doc.text_md,
                extraction_method=doc.extraction_method,
            )
            db.update_item_metadata(
                item_id=item_id,
                title=doc.title,
                word_count=doc.word_count,
                original_minutes=doc.original_minutes,
                status="extracted",
            )
            db.enqueue_job(kind="analyze", item_id=item_id)
            await self._set_reaction(client, chat_id, message_id, "👍")
            return

        # 7. Short text: Save as reflection / general thought note
        if text:
            await self._send_reply(client, chat_id, f'Saved thought: "{text[:50]}..."')

    async def _handle_callback_query(
        self, client: httpx.AsyncClient, query: dict[str, Any]
    ) -> None:
        data = query.get("data", "")
        query_id = query.get("id")
        from_id = query.get("from", {}).get("id")
        chat_id = query.get("message", {}).get("chat", {}).get("id")

        if from_id != self.allowed_user_id:
            return

        # Acknowledge callback query
        await client.post(
            f"{self.base_url}/answerCallbackQuery", json={"callback_query_id": query_id}
        )

        if data.startswith("done:"):
            digest_id = int(data.split(":")[1])
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            db.update_digest(digest_id, done_at=now_iso)
            if chat_id:
                await client.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": chat_id, "text": "✅ Marked digest as completed! Great job!"},
                )
        elif data.startswith("full:"):
            digest_id = int(data.split(":")[1])
            today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
            html_file = settings.digests_dir / f"digest-{today}.html"
            if html_file.exists() and chat_id:
                with open(html_file, "rb") as f:
                    await client.post(
                        f"{self.base_url}/sendDocument",
                        data={"chat_id": chat_id, "caption": "Full interactive digest"},
                        files={"document": (html_file.name, f, "text/html")},
                    )

    async def _set_reaction(
        self, client: httpx.AsyncClient, chat_id: int, message_id: int, emoji: str
    ) -> None:
        try:
            await client.post(
                f"{self.base_url}/setMessageReaction",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reaction": [{"type": "emoji", "emoji": emoji}],
                },
            )
        except Exception as e:
            logger.debug("Failed to set reaction on Telegram message", error=str(e))

    async def _send_reply(self, client: httpx.AsyncClient, chat_id: int, text: str) -> None:
        try:
            await client.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
        except Exception as e:
            logger.error("Failed to send Telegram message", error=str(e))


telegram_poller = TelegramBotPoller()
