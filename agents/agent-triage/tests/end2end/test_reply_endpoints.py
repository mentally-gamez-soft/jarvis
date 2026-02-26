"""End-to-end tests for the reply-with-attachment functionality.

These tests verify that the agent can successfully generate requirements
and send them back to the sender via email.

Run:

    pytest tests/end2end/test_reply_endpoints.py -v -s
"""

from __future__ import annotations

import smtplib
import time
import uuid
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from agent_triage.config import Settings


def get_settings() -> Settings:
    """Load settings from .env."""
    from agent_triage.config import get_settings as gs

    return gs()


@pytest.mark.skip(
    reason="Requires real mail server configured in .env; run manually for integration testing"
)
class TestReplyWithAttachment:
    """Test SMTP reply functionality with requirements attachment."""

    @pytest.fixture
    def probe_subject(self) -> str:
        """Generate a unique subject for this test run."""
        return f"[JARVIS]-[reply test {uuid.uuid4().hex[:8]}]"

    def test_reply_includes_attachment(self):
        """Test that a reply email includes the requirements attachment.

        This test:
        1. Creates an SMTPClient
        2. Sends a reply with an attachment
        3. Verifies the message was sent successfully (no exceptions)
        """
        settings = get_settings()
        from agent_triage.smtp_client import SMTPClient

        client = SMTPClient(settings)

        # Send test reply
        test_content = "# Generated Requirements\n\n## Feature 1\nDescription here."

        try:
            client.send_reply(
                recipient=settings.smtp_username,  # Send to self for testing
                subject="Test Reply with Attachment",
                body="Test reply body",
                attachment_filename="requirements.md",
                attachment_content=test_content.encode("utf-8"),
            )
        except smtplib.SMTPException as e:
            pytest.fail(f"Failed to send reply: {e}")

    def test_reply_uses_fallback_smtp_credentials(self):
        """Test that SMTP falls back to IMAP credentials when not specified.

        This requires that SMTP_* environment variables are empty,
        and we verify the fallback is used.
        """
        settings = get_settings()
        from agent_triage.smtp_client import SMTPClient

        # Verify fallback is being used
        assert settings.smtp_host == (settings.SMTP_HOST or settings.IMAP_HOST)
        assert settings.smtp_username == (
            settings.SMTP_USERNAME or settings.IMAP_USERNAME
        )
        assert settings.smtp_password == (
            settings.SMTP_PASSWORD or settings.IMAP_PASSWORD
        )

        client = SMTPClient(settings)

        # This should work with fallback credentials
        try:
            client.send_reply(
                recipient=settings.smtp_username,
                subject="Fallback Test",
                body="Body",
                attachment_filename="test.txt",
                attachment_content=b"test content",
            )
        except smtplib.SMTPException as e:
            pytest.fail(f"Failed to send with fallback credentials: {e}")

    def test_reply_with_markdown_content(self):
        """Test sending a reply with actual Markdown requirements content."""
        settings = get_settings()
        from agent_triage.smtp_client import SMTPClient

        client = SMTPClient(settings)

        markdown_content = """\
# Project Phoenix - Generated Requirements

## Overview
This is a generated epic document with requirements.

## Functional Requirements
### User Authentication
- Support OAuth2 integration
- Rate limiting on login attempts

### Data Management
- RESTful API for CRUD operations
- Support for pagination
- Filtering and sorting

## Non-Functional Requirements
- Response time < 200ms for 95th percentile
- Availability > 99.9%
- Support for 1000 concurrent users
"""

        try:
            client.send_reply(
                recipient=settings.smtp_username,
                subject="Re: [JARVIS]-[Project Phoenix]",
                body=(
                    "Hello,\n\n"
                    "We've processed your requirements for 'Project Phoenix' "
                    "and generated a project specification document. "
                    "Please see the attached file for details.\n\n"
                    "Best regards,\n"
                    "JARVIS Agent"
                ),
                attachment_filename="requirements.md",
                attachment_content=markdown_content.encode("utf-8"),
            )
        except smtplib.SMTPException as e:
            pytest.fail(f"Failed to send Markdown requirements: {e}")
