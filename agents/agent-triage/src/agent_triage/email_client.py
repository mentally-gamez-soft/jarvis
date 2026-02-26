"""IMAP email client for agent-triage.

Polls the configured mailbox for unread messages whose subject matches the
``[JARVIS]-[<PROJECT_TITLE>]`` prefix, parses them, and returns structured
:class:`AgentEmail` objects.

Subject format expected::

    [JARVIS]-[<PROJECT_TITLE>]

Example::

    [JARVIS]-[Project Phoenix]

Body format (tags are parsed out of the plain-text body)::

    [title]
    <concise project title>
    [idea]
    <detailed description of the concept, features and functionalities>
    [envs]          ← optional
    <environment variables with descriptions>
    [directives]    ← optional
    <technical instructions: dependencies, frameworks, coding standards, etc.>
"""

from __future__ import annotations

import email
import imaplib
import re
import ssl
from dataclasses import dataclass, field
from email.message import Message
from typing import Optional

from .config import Settings
from .logger import get_logger

log = get_logger(__name__)

# Matches  [JARVIS]-[Project Title]  at the start of a subject.
# Group 1 → raw project name / title (may contain spaces / mixed case).
_SUBJECT_RE = re.compile(
    r"^\[JARVIS\]-\[([^\]]+)\]",
    re.IGNORECASE,
)

# Matches the four structured body tags defined in email-format.md.
_BODY_TAG_RE = re.compile(r"\[(title|idea|envs|directives)\]", re.IGNORECASE)


@dataclass
class AgentEmail:
    """Represents a parsed JARVIS email ready for epic generation."""

    uid: str
    """IMAP UID of the message (used to mark as seen after processing)."""

    project_name: str
    """Raw project name extracted from the subject, e.g. ``Project Phoenix``."""

    project_slug: str
    """URL/bucket-safe slug, e.g. ``project-phoenix``."""

    subject: str
    """Full email subject line."""

    body: str
    """Complete plain-text body of the email."""

    # ------------------------------------------------------------------
    # Structured body fields (parsed from [tag] sections in the body).
    # ------------------------------------------------------------------

    title: Optional[str] = None
    """Concise project title from the ``[title]`` body tag."""

    idea: Optional[str] = None
    """Detailed idea / concept description from the ``[idea]`` body tag."""

    envs: Optional[str] = None
    """Environment variables block from the optional ``[envs]`` body tag."""

    directives: Optional[str] = None
    """Technical instructions from the optional ``[directives]`` body tag."""

    extension_rules: Optional[str] = None
    """Contents of ``project-extension-rules.md`` attachment, if present."""

    raw_attachments: list[tuple[str, bytes]] = field(default_factory=list)
    """All other attachments as (filename, bytes) pairs."""


def _parse_body_tags(body: str) -> dict[str, str]:
    """Extract structured tag sections from the email body.

    Splits the body on ``[title]``, ``[idea]``, ``[envs]``, and
    ``[directives]`` markers.  Each tag's content runs until the next tag
    or the end of the body.  Unknown text before the first tag is ignored.

    Returns:
        A dict with any subset of the keys
        ``{"title", "idea", "envs", "directives"}``.
    """
    parts = _BODY_TAG_RE.split(body)
    result: dict[str, str] = {}
    # parts[0] is text before the first tag (ignored).
    # Subsequent entries alternate: tag_name, tag_content, tag_name, …
    i = 1
    while i + 1 <= len(parts) - 1:
        tag = parts[i].lower()
        content = parts[i + 1].strip()
        if content:
            result[tag] = content
        i += 2
    return result


def _slugify(name: str) -> str:
    """Convert a human-readable project name to a lowercase hyphenated slug."""
    slug = name.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug


def _decode_header_value(raw: str) -> str:
    """Decode a (potentially encoded) email header value to a plain string."""
    parts = email.header.decode_header(raw)
    decoded_parts: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)


def _extract_body(msg: Message) -> str:
    """Return the plain-text body of an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                if isinstance(payload, bytes):
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        if isinstance(payload, bytes):
            return payload.decode(charset, errors="replace")
    return ""


def _extract_attachments(
    msg: Message,
) -> tuple[Optional[str], list[tuple[str, bytes]]]:
    """Return (extension_rules_content, other_attachments) from the message."""
    extension_rules: Optional[str] = None
    others: list[tuple[str, bytes]] = []

    if not msg.is_multipart():
        return extension_rules, others

    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        if filename.lower() == "project-extension-rules.md":
            extension_rules = payload.decode("utf-8", errors="replace")
        else:
            others.append((filename, payload))

    return extension_rules, others


def _parse_message(uid: str, raw_data: bytes) -> Optional[AgentEmail]:
    """Parse raw RFC 822 bytes into an :class:`AgentEmail`, or *None* if skipped."""
    msg = email.message_from_bytes(raw_data)
    subject_raw = msg.get("Subject", "")
    subject = _decode_header_value(subject_raw)

    match = _SUBJECT_RE.match(subject)
    if not match:
        log.debug("email.skipped.no_jarvis_prefix", subject=subject, uid=uid)
        return None

    project_name = match.group(1).strip()
    project_slug = _slugify(project_name)
    body = _extract_body(msg)
    extension_rules, raw_attachments = _extract_attachments(msg)

    # Parse structured body tags defined by email-format.md.
    tags = _parse_body_tags(body)

    return AgentEmail(
        uid=uid,
        project_name=project_name,
        project_slug=project_slug,
        subject=subject,
        body=body,
        title=tags.get("title"),
        idea=tags.get("idea"),
        envs=tags.get("envs"),
        directives=tags.get("directives"),
        extension_rules=extension_rules,
        raw_attachments=raw_attachments,
    )


class EmailClient:
    """Thin wrapper around :mod:`imaplib` for polling the JARVIS mailbox."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: Optional[imaplib.IMAP4 | imaplib.IMAP4_SSL] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the IMAP connection and select the configured mailbox."""
        cfg = self._settings
        log.info("imap.connecting", host=cfg.IMAP_HOST, port=cfg.IMAP_PORT)
        if cfg.IMAP_USE_SSL:
            ctx = ssl.create_default_context()
            self._connection = imaplib.IMAP4_SSL(
                cfg.IMAP_HOST, cfg.IMAP_PORT, ssl_context=ctx
            )
        else:
            self._connection = imaplib.IMAP4(cfg.IMAP_HOST, cfg.IMAP_PORT)

        self._connection.login(cfg.IMAP_USERNAME, cfg.IMAP_PASSWORD)
        self._connection.select(cfg.IMAP_MAILBOX)
        log.info("imap.connected", mailbox=cfg.IMAP_MAILBOX)

    def disconnect(self) -> None:
        """Close the IMAP connection gracefully."""
        if self._connection:
            try:
                self._connection.close()
                self._connection.logout()
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._connection = None
                log.info("imap.disconnected")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_unread_jarvis_emails(self) -> list[AgentEmail]:
        """Fetch and return all unread JARVIS emails as :class:`AgentEmail` objects.

        Each successfully processed message is **not** automatically marked as
        seen here — callers should call :meth:`mark_as_seen` after the email
        has been fully processed (epic written to S3).
        """
        if self._connection is None:
            raise RuntimeError("Not connected. Call connect() first.")

        prefix = self._settings.EMAIL_SUBJECT_PREFIX
        # Search for UNSEEN messages whose subject contains the JARVIS prefix.
        # RFC 3501 SEARCH SUBJECT is case-insensitive on most servers.
        _, data = self._connection.search(None, f'(UNSEEN SUBJECT "{prefix}")')
        uid_list: list[bytes] = data[0].split() if data[0] else []

        log.info("imap.search_results", unseen_jarvis_count=len(uid_list))
        results: list[AgentEmail] = []

        for uid_bytes in uid_list:
            uid = uid_bytes.decode()
            _, fetch_data = self._connection.fetch(uid_bytes, "(RFC822)")
            if not fetch_data or fetch_data[0] is None:
                log.warning("imap.fetch_empty", uid=uid)
                continue
            raw: bytes = fetch_data[0][1]  # type: ignore[index]
            parsed = _parse_message(uid, raw)
            if parsed:
                log.info(
                    "imap.email_parsed",
                    uid=uid,
                    project=parsed.project_slug,
                    subject=parsed.subject,
                    has_extension_rules=parsed.extension_rules is not None,
                )
                results.append(parsed)

        return results

    def mark_as_seen(self, uid: str) -> None:
        """Mark the message identified by *uid* as ``\\Seen``."""
        if self._connection is None:
            raise RuntimeError("Not connected. Call connect() first.")
        self._connection.store(uid.encode(), "+FLAGS", "\\Seen")
        log.debug("imap.marked_seen", uid=uid)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "EmailClient":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()
