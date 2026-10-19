"""Optional: email the finished PDF. Skipped quietly if SMTP is not configured."""
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)


def email_configured(recipients: list[str] | None = None) -> bool:
    return bool(settings.smtp_host and settings.smtp_from and (recipients or settings.report_email_to))


def send_report(pdf_path: Path, subject: str, body: str, recipients: list[str] | None = None) -> bool:
    to_addresses = recipients or settings.report_email_to
    if not email_configured(to_addresses):
        log.info("Email not configured; skipping delivery.")
        return False
    msg = EmailMessage()  # EmailMessage blocks header-injection
    msg["Subject"] = subject[:150]
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(to_addresses)
    msg.set_content(body)
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename="report.pdf")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                if not settings.smtp_password:
                    log.error("Email failed: SMTP password is missing")
                    return False
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        log.error("Email failed: %s", type(exc).__name__)
        return False


def valid_email_address(address: str) -> bool:
    return len(address) <= 254 and bool(
        re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address)
    )
