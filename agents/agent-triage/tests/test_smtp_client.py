"""Unit tests for agent_triage.smtp_client."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from unittest.mock import MagicMock, Mock, patch, call

import pytest

from agent_triage.smtp_client import SMTPClient


class MockSettings:
    """Mock Settings object for testing."""

    def __init__(
        self,
        smtp_host: str = "smtp.example.com",
        smtp_port: int = 587,
        smtp_use_ssl: bool = False,
        smtp_username: str = "user@example.com",
        smtp_password: str = "password",
        SMTP_HOST: str = "",
        SMTP_PORT: int = 587,
        SMTP_USE_SSL: bool = False,
        SMTP_USERNAME: str = "",
        SMTP_PASSWORD: str = "",
        IMAP_HOST: str = "imap.example.com",
        IMAP_USERNAME: str = "imap_user@example.com",
        IMAP_PASSWORD: str = "imap_password",
    ):
        self.SMTP_HOST = SMTP_HOST
        self.SMTP_PORT = SMTP_PORT
        self.SMTP_USE_SSL = SMTP_USE_SSL
        self.SMTP_USERNAME = SMTP_USERNAME
        self.SMTP_PASSWORD = SMTP_PASSWORD
        self.IMAP_HOST = IMAP_HOST
        self.IMAP_USERNAME = IMAP_USERNAME
        self.IMAP_PASSWORD = IMAP_PASSWORD

    @property
    def smtp_host(self) -> str:
        return self.SMTP_HOST or self.IMAP_HOST

    @property
    def smtp_username(self) -> str:
        return self.SMTP_USERNAME or self.IMAP_USERNAME

    @property
    def smtp_password(self) -> str:
        return self.SMTP_PASSWORD or self.IMAP_PASSWORD


class TestSMTPClient:
    """Tests for SMTPClient."""

    def test_send_reply_starttls(self):
        """Test sending email with STARTTLS (port 587)."""
        settings = MockSettings(
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=587,
            SMTP_USE_SSL=False,
            SMTP_USERNAME="sender@example.com",
            SMTP_PASSWORD="password",
        )

        client = SMTPClient(settings)

        with patch("agent_triage.smtp_client.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server

            client.send_reply(
                recipient="recipient@example.com",
                subject="Test Subject",
                body="Test body",
                attachment_filename="test.txt",
                attachment_content=b"content",
            )

            # Verify SMTP connection
            mock_smtp.assert_called_once_with("smtp.example.com", 587)
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with(
                "sender@example.com", "password"
            )
            mock_server.send_message.assert_called_once()

    def test_send_reply_implicit_tls(self):
        """Test sending email with implicit TLS (port 465)."""
        settings = MockSettings(
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=465,
            SMTP_USE_SSL=True,
            SMTP_USERNAME="sender@example.com",
            SMTP_PASSWORD="password",
        )

        client = SMTPClient(settings)

        with patch("agent_triage.smtp_client.smtplib.SMTP_SSL") as mock_smtp_ssl:
            mock_server = MagicMock()
            mock_smtp_ssl.return_value.__enter__.return_value = mock_server

            client.send_reply(
                recipient="recipient@example.com",
                subject="Test Subject",
                body="Test body",
                attachment_filename="test.txt",
                attachment_content=b"content",
            )

            # Verify SMTP_SSL connection (no starttls needed)
            mock_smtp_ssl.assert_called_once_with(
                "smtp.example.com", 465, context=mock_smtp_ssl.call_args[1]["context"]
            )
            mock_server.login.assert_called_once_with(
                "sender@example.com", "password"
            )
            mock_server.send_message.assert_called_once()

    def test_send_reply_fallback_to_imap_credentials(self):
        """Test that SMTP falls back to IMAP credentials when not specified."""
        settings = MockSettings(
            SMTP_HOST="",  # Empty, should fall back
            SMTP_USERNAME="",  # Empty, should fall back
            SMTP_PASSWORD="",  # Empty, should fall back
            IMAP_HOST="imap.example.com",
            IMAP_USERNAME="imap_user@example.com",
            IMAP_PASSWORD="imap_pass",
        )

        client = SMTPClient(settings)

        with patch("agent_triage.smtp_client.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server

            client.send_reply(
                recipient="recipient@example.com",
                subject="Test Subject",
                body="Test body",
                attachment_filename="test.txt",
                attachment_content=b"content",
            )

            # Should use IMAP credentials
            mock_smtp.assert_called_once_with("imap.example.com", 587)
            mock_server.login.assert_called_once_with(
                "imap_user@example.com", "imap_pass"
            )

    def test_send_reply_includes_attachment(self):
        """Test that attachment is properly included in the email."""
        settings = MockSettings()
        client = SMTPClient(settings)

        with patch("agent_triage.smtp_client.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server

            client.send_reply(
                recipient="user@example.com",
                subject="Requirements",
                body="Here is your requirements",
                attachment_filename="requirements.md",
                attachment_content=b"# Requirements\n\nSome content",
            )

            # Get the message that was sent
            sent_message = mock_server.send_message.call_args[0][0]

            # Verify it's a multipart message
            assert sent_message.is_multipart()

            # Verify headers
            assert sent_message["Subject"] == "Requirements"
            assert sent_message["To"] == "user@example.com"

            # Verify attachment is present (multipart message has 2 parts)
            parts = sent_message.get_payload()
            assert len(parts) == 2
            assert parts[1].get_filename() == "requirements.md"

    def test_send_reply_smtp_exception_logged(self):
        """Test that SMTP exceptions are properly logged and re-raised."""
        settings = MockSettings()
        client = SMTPClient(settings)

        with patch("agent_triage.smtp_client.smtplib.SMTP") as mock_smtp:
            mock_smtp.side_effect = smtplib.SMTPException("Connection failed")

            with pytest.raises(smtplib.SMTPException):
                client.send_reply(
                    recipient="user@example.com",
                    subject="Test",
                    body="Test",
                    attachment_filename="test.txt",
                    attachment_content=b"content",
                )
