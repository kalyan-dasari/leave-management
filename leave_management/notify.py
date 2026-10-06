import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

from .db import execute, query, utcnow

logger = logging.getLogger(__name__)


def _send_email(to: str, subject: str, body: str) -> bool:
    """Send an email. Returns True on success, False when mail is unavailable.

    In development (no MAIL_USERNAME / MAIL_PASSWORD) this falls back to
    logging the message so the workflow keeps working without SMTP.
    """
    cfg = current_app.config
    username = cfg.get("MAIL_USERNAME")
    password = cfg.get("MAIL_PASSWORD")
    if not username or not password:
        logger.info("MAIL not configured - skipped email to %s: %s", to, subject)
        return False
    if cfg.get("TESTING"):
        logger.info("TESTING mode - suppressed email to %s: %s", to, subject)
        return True

    msg = EmailMessage()
    msg["From"] = cfg.get("MAIL_DEFAULT_SENDER") or username
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg.get("MAIL_SERVER", "smtp.gmail.com"), int(cfg.get("MAIL_PORT", 587)), timeout=10) as smtp:
            if cfg.get("MAIL_USE_TLS", True):
                smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 - mail must never break the workflow
        logger.warning("Email delivery failed for %s: %s", to, exc)
        return False


def notify(recipient_id, message, request_id=None, subject=None, email_body=None):
    """Create an in-app notification and attempt an email copy."""
    recipient = query("SELECT id, email, name FROM users WHERE id = ?", (recipient_id,), one=True)
    if recipient is None:
        return None

    notif_id = execute(
        "INSERT INTO notifications (recipient_id, request_id, message, channel, is_read, sent_at) VALUES (?, ?, ?, 'in_app', 0, ?)",
        (recipient_id, request_id, message, utcnow()),
    ).lastrowid

    if recipient["email"]:
        delivered = _send_email(
            recipient["email"],
            subject or "Leave Management Notification",
            email_body or message,
        )
        execute(
            "INSERT INTO notifications (recipient_id, request_id, message, channel, is_read, sent_at) VALUES (?, ?, ?, 'email', 1, ?)",
            (recipient_id, request_id, f"{message} [{'sent' if delivered else 'not sent'}]", utcnow()),
        )
    return notif_id


def notify_many(recipient_ids, message, request_id=None, subject=None, email_body=None):
    for rid in recipient_ids:
        notify(rid, message, request_id=request_id, subject=subject, email_body=email_body)


def unread_count(user_id) -> int:
    row = query(
        "SELECT COUNT(*) AS n FROM notifications WHERE recipient_id = ? AND is_read = 0 AND channel = 'in_app'",
        (user_id,),
        one=True,
    )
    return row["n"] if row else 0
