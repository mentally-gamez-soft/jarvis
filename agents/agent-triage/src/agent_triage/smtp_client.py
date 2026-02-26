"""SMTP client for sending reply emails with requirements attachment.

Handles outgoing email via SMTP with STARTTLS or implicit TLS,
with fallback to IMAP credentials if SMTP-specific ones are not set.
"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

from .logger import get_logger

if TYPE_CHECKING:
    from .config import Settings

log = get_logger(__name__)


class SMTPClient:
    """Sends outgoing emails via SMTP with optional attachment."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send_reply(
        self,
        recipient: str,
        subject: str,
        body: str,
        attachment_filename: str,
        attachment_content: bytes,
    ) -> None:
        """Send an email reply with an attached file.

        Args:
            recipient: Email address to send to.
            subject: Email subject line.
            body: Plain-text email body.
            attachment_filename: Name of the attachment (e.g., "requirements.md").
            attachment_content: Binary content of the attachment file.

        Raises:
            SMTPException: If the SMTP operation fails.
        """
        cfg = self._settings

        # Build the message
        msg = MIMEMultipart()
        msg["From"] = cfg.smtp_username
        msg["To"] = recipient
        msg["Subject"] = subject

        # Add body
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Add attachment
        attachment = MIMEApplication(attachment_content, Name=attachment_filename)
        attachment["Content-Disposition"] = f'attachment; filename="{attachment_filename}"'
        msg.attach(attachment)

        # Send via SMTP
        host = cfg.smtp_host
        port = cfg.SMTP_PORT
        username = cfg.smtp_username
        password = cfg.smtp_password

        log.info(
            "smtp.connecting",
            host=host,
            port=port,
            use_ssl=cfg.SMTP_USE_SSL,
            recipient=recipient,
        )

        try:
            if cfg.SMTP_USE_SSL:
                # Implicit TLS on port 465
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, context=ctx) as server:
                    server.login(username, password)
                    server.send_message(msg)
            else:
                # STARTTLS on port 587
                ctx = ssl.create_default_context()
                with smtplib.SMTP(host, port) as server:
                    server.starttls(context=ctx)
                    server.login(username, password)
                    server.send_message(msg)

            log.info(
                "smtp.email_sent",
                recipient=recipient,
                subject=subject,
                attachment=attachment_filename,
            )
        except smtplib.SMTPException as exc:
            log.error(
                "smtp.send_failed",
                recipient=recipient,
                subject=subject,
                error=str(exc),
            )
            raise
