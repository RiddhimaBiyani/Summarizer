"""Gmail IMAP capture poller with sender allowlist and forwarded email unwrapping."""

import email
import hashlib
import re
from email import policy
from email.utils import parseaddr

import httpx
from aioimaplib import aioimaplib

from digestif.db.repo import db
from digestif.extract.newsletter import newsletter_extractor
from digestif.observability import logger
from digestif.settings import settings

FETCH_HEADER_RE = re.compile(rb"^\d+\s+FETCH\s+\(")


class IMAPPoller:
    def __init__(self) -> None:
        self.host = "imap.gmail.com"
        self.port = 993
        self.username = settings.DIGEST_GMAIL_ADDRESS
        self.password = settings.DIGEST_GMAIL_APP_PASSWORD

    async def poll_once(self) -> int:
        """Polls inbox once for unseen emails, returning count of processed messages."""
        if not self.username or not self.password:
            logger.debug("Gmail IMAP credentials not configured; skipping IMAP poll")
            return 0

        processed_count = 0
        imap_client = aioimaplib.IMAP4_SSL(host=self.host, port=self.port, timeout=30)
        try:
            await imap_client.wait_hello_from_server()
            login_resp = await imap_client.login(self.username, self.password)
            if login_resp.result != "OK":
                logger.error("Gmail IMAP login failed", result=login_resp.result)
                return 0

            await imap_client.select("INBOX")
            logger.info(
                "Polling Gmail IMAP for UNSEEN messages", host=self.host, user=self.username
            )

            search_resp = await imap_client.search("UNSEEN")
            if search_resp.result != "OK" or not search_resp.lines or not search_resp.lines[0]:
                await imap_client.logout()
                return 0

            msg_ids = search_resp.lines[0].split()
            logger.info("Found unseen emails in INBOX", count=len(msg_ids))

            for msg_id in msg_ids:
                msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                fetch_resp = await imap_client.fetch(msg_id_str, "(RFC822)")
                if fetch_resp.result != "OK":
                    continue
                raw_email_bytes = self._extract_literal(fetch_resp.lines)
                if not raw_email_bytes:
                    continue
                if await self._process_raw_email(raw_email_bytes):
                    processed_count += 1
                    await imap_client.store(msg_id_str, "+FLAGS", "\\Seen")

            await imap_client.logout()
        except Exception as e:
            logger.error("Error during IMAP poll execution", error=str(e))

        return processed_count

    @staticmethod
    def _extract_literal(lines: list) -> bytes | None:
        """Picks the raw message literal out of a FETCH response's line list.

        aioimaplib returns FETCH data as a mix of header/closing marker lines
        (e.g. b'1 FETCH (RFC822 {12345}', b')') and the literal payload as its
        own element; the payload is reliably the largest byte chunk returned.
        """
        candidates = [
            line
            for line in lines
            if isinstance(line, (bytes, bytearray))
            and line != b")"
            and not FETCH_HEADER_RE.match(line)
        ]
        if not candidates:
            return None
        return bytes(max(candidates, key=len))

    async def _process_raw_email(self, raw_bytes: bytes) -> bool:
        msg = email.message_from_bytes(raw_bytes, policy=policy.default)
        message_id = msg.get("Message-ID", "")
        if not message_id:
            # hash() is randomized per-process (PYTHONHASHSEED); a stable digest is
            # required so a restart between insert_capture() and the IMAP Seen-flag
            # update doesn't re-ingest the same email as a "new" one.
            message_id = f"gen-{hashlib.sha256(raw_bytes).hexdigest()}"

        # 1. Save raw .eml to DATA_DIR/mail/
        mail_dir = settings.mail_dir
        safe_msg_id = re.sub(r"[^\w.-]", "_", message_id)
        eml_file = mail_dir / f"{safe_msg_id}.eml"
        eml_file.write_bytes(raw_bytes)

        # 2. Idempotent insert into captures table
        capture_id = db.insert_capture(
            channel="email",
            external_id=message_id,
            raw_json=str(eml_file),
        )
        if not capture_id:
            logger.debug("Duplicate email capture ignored", message_id=message_id)
            return True

        from_header = str(msg.get("From", ""))
        # parseaddr() strips the display name (e.g. "Stratechery <digest@stratechery.com>"
        # -> "digest@stratechery.com"); senders.yaml/newsletter_senders store bare
        # addresses, so matching the raw header here caused every configured sender
        # to be rejected as "unapproved" in real-world mail.
        from_addr = parseaddr(from_header)[1].lower()
        subject = str(msg.get("Subject", ""))
        raw_str = raw_bytes.decode("utf-8", errors="replace")

        # 3. Check for Gmail Forwarding Confirmation
        if "forwarding confirmation" in subject.lower() or "verify forwarding" in subject.lower():
            logger.info("Detected Gmail forwarding confirmation email; relaying to Telegram")
            await self._relay_confirmation_to_telegram(subject, raw_str)
            return True

        # 4. Check Allowlist: Sender Registry or Allowed Forwarders
        allowed_forwarders = settings.allowed_forwarder_emails
        is_allowed_forwarder = any(f_addr in from_addr for f_addr in allowed_forwarders)
        sender_entry = db.get_sender(from_addr)

        if not is_allowed_forwarder and not (sender_entry and sender_entry.get("auto_ingest")):
            logger.warning(
                "Email from unapproved sender; skipping auto-ingest", from_addr=from_addr
            )
            return False

        # 5. Unwrap Manual Forwards if present
        unwrapped_text, original_sender = self._unwrap_forward(raw_str)

        # 6. Insert into items table
        item_id = db.insert_item(
            capture_id=capture_id,
            source_type="newsletter",
            title=subject,
            author=original_sender or from_addr,
            status="received",
        )

        # 7. Extract content and enqueue analysis
        try:
            doc = await newsletter_extractor.extract(
                url=None, raw_payload=unwrapped_text or raw_str, hints={"is_email": True}
            )

            db.save_item_content(
                item_id=item_id,
                text_md=doc.text_md,
                extraction_method=doc.extraction_method,
            )
            db.update_item_metadata(
                item_id=item_id,
                title=doc.title or subject,
                word_count=doc.word_count,
                original_minutes=doc.original_minutes,
                status="extracted",
            )
            db.enqueue_job(kind="analyze", item_id=item_id)
            logger.info("Ingested and extracted newsletter item", item_id=item_id, title=subject)
        except Exception as e:
            logger.error("Failed to extract newsletter content", item_id=item_id, error=str(e))
            db.update_item_status(item_id, "failed", failure_reason=str(e))

        return True

    def _unwrap_forward(self, text: str) -> tuple[str | None, str | None]:
        """Detects and strips manual forward header blocks, recovering original sender."""
        forward_patterns = [
            r"---------- Forwarded message ---------\s*From:\s*(.+?)\n.*?Subject:\s*(.+?)\n",
            r"Begin forwarded message:\s*From:\s*(.+?)\n.*?Subject:\s*(.+?)\n",
        ]
        for pat in forward_patterns:
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            if m:
                original_from = m.group(1).strip()
                # Strip the header block
                unwrapped = text[m.end() :].strip()
                return (unwrapped, original_from)
        return (None, None)

    async def _relay_confirmation_to_telegram(self, subject: str, body: str) -> None:
        """Sends Gmail forwarding confirmation code or link directly to the user's Telegram."""
        token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_ALLOWED_USER_ID
        if not token or not chat_id:
            return

        # Extract confirmation code or verification URL
        code_match = re.search(r"confirmation code is:?\s*(\d{7,10})", body, re.IGNORECASE)
        url_match = re.search(r"https://mail-settings\.google\.com/[^\s<>'\"`]+", body)

        msg_lines = [
            "📬 <b>Gmail Forwarding Verification Received</b>",
            f"Subject: {subject}",
        ]
        if code_match:
            msg_lines.append(f"\nConfirmation Code: <code>{code_match.group(1)}</code>")
        if url_match:
            msg_lines.append(
                f"\nVerification Link: <a href='{url_match.group(0)}'>Confirm Forwarding</a>"
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": "\n".join(msg_lines),
                        "parse_mode": "HTML",
                    },
                )
        except Exception as e:
            logger.error("Failed to relay confirmation email to Telegram", error=str(e))


imap_poller = IMAPPoller()
