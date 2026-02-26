"""Unit tests for agent_triage.email_client."""

from __future__ import annotations

import email as email_lib
import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from unittest.mock import MagicMock, patch

import pytest

from agent_triage.email_client import (
    AgentEmail,
    EmailClient,
    _parse_body_tags,
    _parse_message,
    _slugify,
    _extract_sender,
)


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic(self):
        assert _slugify("Image Displayer") == "image-displayer"

    def test_extra_spaces(self):
        assert _slugify("  My  Project  ") == "my-project"

    def test_special_chars_stripped(self):
        assert _slugify("Foo & Bar!") == "foo-bar"

    def test_already_slug(self):
        assert _slugify("my-project") == "my-project"


# ---------------------------------------------------------------------------
# _parse_message
# ---------------------------------------------------------------------------

def _make_raw_email(subject: str, body: str) -> bytes:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = "user@example.com"
    msg["To"] = "test-agent@example.com"
    return msg.as_bytes()


def _make_multipart_email(
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]] | None = None,
) -> bytes:
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = "user@example.com"
    msg["To"] = "test-agent@example.com"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for filename, content in (attachments or []):
        part = MIMEBase("application", "octet-stream")
        part.set_payload(content)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
    return msg.as_bytes()


class TestParseMessage:
    def test_valid_jarvis_subject(self):
        raw = _make_raw_email("[JARVIS]-[image-displayer] Add feature X", "Requirements here.")
        result = _parse_message("1", raw)
        assert result is not None
        assert result.project_name == "image-displayer"
        assert result.project_slug == "image-displayer"
        assert result.body == "Requirements here."
        assert result.extension_rules is None

    def test_project_name_with_spaces(self):
        raw = _make_raw_email("[JARVIS]-[Image Displayer] Add feature", "Body.")
        result = _parse_message("2", raw)
        assert result is not None
        assert result.project_name == "Image Displayer"
        assert result.project_slug == "image-displayer"

    def test_non_jarvis_email_returns_none(self):
        raw = _make_raw_email("Hello from support", "Some text.")
        result = _parse_message("3", raw)
        assert result is None

    def test_old_format_without_dash_returns_none(self):
        """[JARVIS][proj] without dash must no longer be accepted."""
        raw = _make_raw_email("[JARVIS][image-displayer] Old format", "Body.")
        result = _parse_message("99", raw)
        assert result is None

    def test_extension_rules_attachment_parsed(self):
        rules_content = b"# Custom rules\n- Rule 1"
        raw = _make_multipart_email(
            "[JARVIS]-[my-project] Requirements",
            "Body text.",
            attachments=[("project-extension-rules.md", rules_content)],
        )
        result = _parse_message("4", raw)
        assert result is not None
        assert result.extension_rules == "# Custom rules\n- Rule 1"

    def test_other_attachment_stored_separately(self):
        raw = _make_multipart_email(
            "[JARVIS]-[my-project] Req",
            "Body.",
            attachments=[("diagram.png", b"\x89PNG data")],
        )
        result = _parse_message("5", raw)
        assert result is not None
        assert result.extension_rules is None
        assert len(result.raw_attachments) == 1
        assert result.raw_attachments[0][0] == "diagram.png"

    def test_uid_preserved(self):
        raw = _make_raw_email("[JARVIS]-[proj] Test", "Body.")
        result = _parse_message("42", raw)
        assert result is not None
        assert result.uid == "42"

    def test_structured_body_tags_parsed(self):
        body = textwrap.dedent("""\
            [title]
            Project Phoenix
            [idea]
            A fitness tracking web application.
            [envs]
            DATABASE_URL: connection string
            [directives]
            - Use Django MVT pattern
        """)
        raw = _make_raw_email("[JARVIS]-[Project Phoenix]", body)
        result = _parse_message("10", raw)
        assert result is not None
        assert result.title == "Project Phoenix"
        assert "fitness tracking" in (result.idea or "")
        assert "DATABASE_URL" in (result.envs or "")
        assert "Django" in (result.directives or "")

    def test_optional_tags_absent_when_missing(self):
        body = textwrap.dedent("""\
            [title]
            Simple Project
            [idea]
            A straightforward idea.
        """)
        raw = _make_raw_email("[JARVIS]-[Simple Project]", body)
        result = _parse_message("11", raw)
        assert result is not None
        assert result.title == "Simple Project"
        assert result.idea == "A straightforward idea."
        assert result.envs is None
        assert result.directives is None


# ---------------------------------------------------------------------------
# _parse_body_tags
# ---------------------------------------------------------------------------

class TestParseBodyTags:
    def test_all_four_tags(self):
        body = textwrap.dedent("""\
            [title]
            Project Phoenix
            [idea]
            A fitness app.
            [envs]
            DATABASE_URL: db connection
            [directives]
            - Use Django
        """)
        tags = _parse_body_tags(body)
        assert tags["title"] == "Project Phoenix"
        assert tags["idea"] == "A fitness app."
        assert "DATABASE_URL" in tags["envs"]
        assert "Django" in tags["directives"]

    def test_only_mandatory_tags(self):
        body = "[title]\nMy App\n[idea]\nCore concept here."
        tags = _parse_body_tags(body)
        assert tags["title"] == "My App"
        assert tags["idea"] == "Core concept here."
        assert "envs" not in tags
        assert "directives" not in tags

    def test_empty_body_returns_empty_dict(self):
        assert _parse_body_tags("") == {}

    def test_no_tags_returns_empty_dict(self):
        assert _parse_body_tags("Just some plain text.") == {}

    def test_tag_names_are_case_insensitive(self):
        body = "[TITLE]\nMy Project\n[IDEA]\nDescription."
        tags = _parse_body_tags(body)
        assert tags["title"] == "My Project"
        assert tags["idea"] == "Description."


# ---------------------------------------------------------------------------
# EmailClient (integration-level with mocked imaplib)
# ---------------------------------------------------------------------------

class TestEmailClient:
    def _make_settings(self):
        settings = MagicMock()
        settings.IMAP_HOST = "mail.example.com"
        settings.IMAP_PORT = 993
        settings.IMAP_USE_SSL = True
        settings.IMAP_USERNAME = "test-agent@example.com"
        settings.IMAP_PASSWORD = "secret"
        settings.IMAP_MAILBOX = "INBOX"
        settings.EMAIL_SUBJECT_PREFIX = "[JARVIS]-"
        return settings

    def test_fetch_returns_parsed_emails(self):
        settings = self._make_settings()
        raw = _make_raw_email("[JARVIS]-[test-proj] Feature A", "Requirements for A.")

        with patch("agent_triage.email_client.imaplib") as mock_imaplib:
            mock_conn = MagicMock()
            mock_imaplib.IMAP4_SSL.return_value = mock_conn
            mock_conn.search.return_value = (None, [b"1"])
            mock_conn.fetch.return_value = (None, [(None, raw)])

            client = EmailClient(settings)
            client._connection = mock_conn

            results = client.fetch_unread_jarvis_emails()

        assert len(results) == 1
        assert results[0].project_slug == "test-proj"

    def test_mark_as_seen_calls_store(self):
        settings = self._make_settings()
        mock_conn = MagicMock()

        client = EmailClient(settings)
        client._connection = mock_conn
        client.mark_as_seen("7")

        mock_conn.store.assert_called_once_with(b"7", "+FLAGS", "\\Seen")


# ---------------------------------------------------------------------------
# _extract_sender
# ---------------------------------------------------------------------------

class TestExtractSender:
    def test_simple_email_address(self):
        """Test extracting sender from simple email address."""
        msg = email_lib.message_from_string("From: user@example.com\n\nBody")
        assert _extract_sender(msg) == "user@example.com"

    def test_email_with_display_name(self):
        """Test extracting sender with display name."""
        msg = email_lib.message_from_string(
            'From: "John Doe" <john@example.com>\n\nBody'
        )
        assert _extract_sender(msg) == "john@example.com"

    def test_missing_from_header(self):
        """Test that None is returned when From header is missing."""
        msg = email_lib.message_from_string("To: someone@example.com\n\nBody")
        assert _extract_sender(msg) is None

    def test_empty_from_header(self):
        """Test that None is returned for empty From header."""
        msg = email_lib.message_from_string("From: \n\nBody")
        assert _extract_sender(msg) is None


# ---------------------------------------------------------------------------
# _parse_message with sender
# ---------------------------------------------------------------------------

class TestParseMessageSender:
    def test_parse_message_extracts_sender(self):
        """Test that _parse_message correctly extracts the sender."""
        subject = "[JARVIS]-[test-proj] Feature"
        body = "[title]\nTest\n[idea]\nDescription"
        from_addr = "developer@example.com"

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_addr
        raw = msg.as_bytes()

        parsed = _parse_message("1", raw)

        assert parsed is not None
        assert parsed.sender == from_addr
        assert parsed.project_slug == "test-proj"

    def test_parse_message_without_sender(self):
        """Test that _parse_message handles missing sender gracefully."""
        subject = "[JARVIS]-[test-proj] Feature"
        body = "[title]\nTest\n[idea]\nDescription"

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        # No From header
        raw = msg.as_bytes()

        parsed = _parse_message("1", raw)

        assert parsed is not None
        assert parsed.sender is None
