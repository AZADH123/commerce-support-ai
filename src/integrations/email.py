"""Email delivery adapters.

- ``InMemoryEmailAdapter`` — default for tests/local runs; records deliveries.
- ``SmtpEmailAdapter`` — plain SMTP, used with Mailpit locally
  (``EMAIL_TRANSPORT=smtp``, ``SMTP_HOST=localhost``, ``SMTP_PORT=1025``).

Delivery guarantee: the notification worker is at-least-once. SMTP itself has no
idempotency, so a crash after the provider accepts but before the local SENT
commit can resend; duplicate sends are otherwise prevented by the durable
status CAS (PENDING -> SENDING -> SENT).
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

logger = logging.getLogger("support_agent.email")


class EmailDeliveryError(Exception):
    pass


class RetryableEmailError(EmailDeliveryError):
    pass


class EmailAdapter(Protocol):
    def send(self, *, to_email: str, subject: str, body: str) -> str: ...


class InMemoryEmailAdapter:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, *, to_email: str, subject: str, body: str) -> str:
        message_id = f"mem-{len(self.sent) + 1}"
        self.sent.append(
            {"to_email": to_email, "subject": subject, "body": body, "message_id": message_id}
        )
        return message_id


class SmtpEmailAdapter:
    def __init__(self, host: str, port: int, sender: str = "no-reply@commerce-support.local"):
        self.host = host
        self.port = port
        self.sender = sender

    def send(self, *, to_email: str, subject: str, body: str) -> str:
        import smtplib
        from email.message import EmailMessage

        if not to_email:
            raise RetryableEmailError("Customer has no email address on file.")

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            # Never log the message body; only the failure class.
            logger.warning("smtp_delivery_failed (%s)", type(exc).__name__)
            raise RetryableEmailError("Could not deliver email via SMTP.") from exc

        return message["Message-ID"] or f"smtp-{self.host}-{self.port}"


def get_email_adapter() -> EmailAdapter:
    transport = (os.environ.get("EMAIL_TRANSPORT") or "memory").strip().lower()
    if transport == "smtp":
        return SmtpEmailAdapter(
            host=os.environ.get("SMTP_HOST", "localhost"),
            port=int(os.environ.get("SMTP_PORT", "1025")),
            sender=os.environ.get("SMTP_SENDER", "no-reply@commerce-support.local"),
        )
    return InMemoryEmailAdapter()
