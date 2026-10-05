"""Email delivery module sending premailer-inlined HTML via Gmail SMTP (SSL 465)."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from digestif.observability import logger
from digestif.settings import settings


async def send_email_digest(
    digest_date: str,
    headline: str,
    est_minutes: float,
    html_content: str,
    plain_text_content: str = "",
) -> bool:
    """Delivers digest email via Gmail SMTP using aiosmtplib with SSL."""
    username = settings.DIGEST_GMAIL_ADDRESS
    password = settings.DIGEST_GMAIL_APP_PASSWORD
    recipient = settings.DELIVERY_EMAIL_TO

    if not username or not password or not recipient:
        logger.warning(
            "Gmail SMTP credentials or recipient not configured; skipping email delivery"
        )
        return False

    subject = f"Digestif · {digest_date} · {est_minutes} min · {headline}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Digestif <{username}>"
    msg["To"] = recipient

    # Fallback plain text part
    if not plain_text_content:
        plain_text_content = f"Digestif Briefing for {digest_date}\n\n{headline}\nEstimated read time: {est_minutes} min\nPlease view in an HTML-capable email client."

    part1 = MIMEText(plain_text_content, "plain", "utf-8")
    part2 = MIMEText(html_content, "html", "utf-8")

    msg.attach(part1)
    msg.attach(part2)

    try:
        logger.info("Sending email via Gmail SMTP", to=recipient, subject=subject)
        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=465,
            use_tls=True,
            username=username,
            password=password,
            timeout=30.0,
        )
        logger.info("Email digest delivered successfully", to=recipient)
        return True
    except Exception as e:
        logger.error("Failed to send email digest via SMTP", error=str(e), to=recipient)
        return False
