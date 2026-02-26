"""End-to-end tests for SMTP (outgoing) and IMAP (incoming) email connectivity.

These tests make **real** network calls to the configured mail server.
They require a valid ``.env`` file with IMAP and SMTP credentials.

Run:

    pytest tests/end2end/test_email_endpoints.py -v -s

Strategy
--------
1. ``TestSMTPEndpoint`` – connects via SMTP and sends a probe email from
   the configured agent mailbox **to itself**, using a unique UUID
   embedded in the subject so the companion IMAP test can find it.

2. ``TestIMAPEndpoint`` – connects via IMAP and polls the inbox for up to
   30 s waiting for the probe email sent in step 1.

If SMTP is blocked (e.g. ISP port-filtering on 587), the test reports the
exact error and is marked as ``ERROR`` — not silently skipped — so the
problem is clearly visible.

SSH tunnel reminder (when ports are blocked locally)
-----------------------------------------------------
Server details are stored in ``.env.test`` (MAIL_HOST, VPS_HOST, SSH_USER).

    ssh -L 5587:{MAIL_HOST}:587 \\
        -L 9993:{MAIL_HOST}:993 \\
        {SSH_USER}@{VPS_HOST} -N -f

Then override in .env:
    SMTP_PORT=5587
    IMAP_PORT=9993
    IMAP_HOST=localhost
    SMTP_HOST=localhost        ← or leave empty (falls back to IMAP_HOST)
"""

from __future__ import annotations

import imaplib
import smtplib
import ssl
import time
import uuid
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from agent_triage.config import Settings

# ---------------------------------------------------------------------------
# Session-scoped probe subject shared between SMTP and IMAP tests
# ---------------------------------------------------------------------------

# Unique token generated once per test session — both test classes read it.
_PROBE_UUID: str = str(uuid.uuid4())
_PROBE_SUBJECT: str = f"[JARVIS][e2e-test] probe-{_PROBE_UUID}"

# How long the IMAP test waits for the message to appear (seconds).
_RECEIVE_TIMEOUT: int = 45
_POLL_INTERVAL: float = 3.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _smtp_connect(settings: "Settings") -> smtplib.SMTP | smtplib.SMTP_SSL:
    """Open and authenticate an SMTP connection based on *settings*."""
    host = settings.smtp_host
    port = settings.SMTP_PORT

    if settings.SMTP_USE_SSL:
        # Implicit TLS — port 465
        ctx = ssl.create_default_context()
        conn: smtplib.SMTP | smtplib.SMTP_SSL = smtplib.SMTP_SSL(
            host, port, context=ctx, timeout=15
        )
    else:
        # STARTTLS — port 587
        conn = smtplib.SMTP(host, port, timeout=15)
        conn.ehlo()
        conn.starttls(context=ssl.create_default_context())
        conn.ehlo()

    conn.login(settings.smtp_username, settings.smtp_password)
    return conn


def _imap_connect(settings: "Settings") -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
    """Open and authenticate an IMAP connection based on *settings*."""
    if settings.IMAP_USE_SSL:
        ctx = ssl.create_default_context()
        conn: imaplib.IMAP4 | imaplib.IMAP4_SSL = imaplib.IMAP4_SSL(
            settings.IMAP_HOST, settings.IMAP_PORT, ssl_context=ctx
        )
    else:
        conn = imaplib.IMAP4(settings.IMAP_HOST, settings.IMAP_PORT)

    conn.login(settings.IMAP_USERNAME, settings.IMAP_PASSWORD)
    conn.select(settings.IMAP_MAILBOX)
    return conn


# ---------------------------------------------------------------------------
# SMTP — outgoing mail
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestSMTPEndpoint:
    """E2E tests for the outgoing SMTP connection."""

    def test_send_email(self, settings: "Settings", test_hints: dict) -> None:
        """Send a probe email from the agent mailbox to itself via SMTP.

        Fails (not skips) if the connection is refused so port-blocking issues
        are immediately visible.
        """
        sender = settings.smtp_username
        recipient = settings.IMAP_USERNAME  # send to self

        msg = MIMEText(
            f"This is an automated probe from the agent-triage e2e test suite.\n"
            f"UUID: {_PROBE_UUID}\n"
            f"If you see this email, SMTP delivery is working correctly.",
            "plain",
            "utf-8",
        )
        msg["Subject"] = _PROBE_SUBJECT
        msg["From"] = sender
        msg["To"] = recipient

        print(f"\n[SMTP] host      : {settings.smtp_host}:{settings.SMTP_PORT}")
        print(f"[SMTP] use_ssl   : {settings.SMTP_USE_SSL}")
        print(f"[SMTP] sender    : {sender}")
        print(f"[SMTP] recipient : {recipient}")
        print(f"[SMTP] subject   : {_PROBE_SUBJECT}")

        start = time.perf_counter()
        try:
            with _smtp_connect(settings) as conn:
                conn.sendmail(sender, [recipient], msg.as_bytes())
        except (ConnectionRefusedError, TimeoutError, OSError) as exc:
            mail_host = test_hints["MAIL_HOST"]
            vps_host = test_hints["VPS_HOST"]
            ssh_user = test_hints["SSH_USER"]
            pytest.fail(
                f"[SMTP] Connection to {settings.smtp_host}:{settings.SMTP_PORT} failed: {exc}\n"
                "\nIf your ISP blocks port 587, set up an SSH tunnel and override "
                "SMTP_PORT (and optionally SMTP_HOST=localhost) in .env:\n"
                f"  ssh -L 5587:{mail_host}:587 {ssh_user}@{vps_host} -N -f\n"
                "  SMTP_PORT=5587\n"
                "  SMTP_HOST=localhost"
            )
        except smtplib.SMTPAuthenticationError as exc:
            pytest.fail(f"[SMTP] Authentication failed: {exc}")
        except smtplib.SMTPException as exc:
            pytest.fail(f"[SMTP] SMTP error: {exc}")

        elapsed = time.perf_counter() - start
        print(f"[SMTP] sent in {elapsed:.2f}s — OK")

    def test_starttls_upgrade(self, settings: "Settings", test_hints: dict) -> None:
        """Verify the STARTTLS handshake succeeds (plain SMTP mode only).

        Skipped when SMTP_USE_SSL=true (implicit TLS) since STARTTLS does not
        apply to SMTP_SSL connections.
        """
        if settings.SMTP_USE_SSL:
            pytest.skip("SMTP_USE_SSL=true — STARTTLS test not applicable.")

        host = settings.smtp_host
        port = settings.SMTP_PORT

        print(f"\n[SMTP/STARTTLS] connecting to {host}:{port} …")
        try:
            conn = smtplib.SMTP(host, port, timeout=15)
            conn.ehlo()
            code, _ = conn.starttls(context=ssl.create_default_context())
            conn.quit()
        except (ConnectionRefusedError, TimeoutError, OSError) as exc:
            mail_host = test_hints["MAIL_HOST"]
            vps_host = test_hints["VPS_HOST"]
            ssh_user = test_hints["SSH_USER"]
            pytest.fail(
                f"[SMTP/STARTTLS] Cannot reach {host}:{port}: {exc}\n"
                f"Set up an SSH tunnel — see test_send_email docstring.\n"
                f"  ssh -L 5587:{mail_host}:587 {ssh_user}@{vps_host} -N -f"
            )
        except smtplib.SMTPException as exc:
            pytest.fail(f"[SMTP/STARTTLS] STARTTLS negotiation failed: {exc}")

        assert code == 220, f"Expected STARTTLS response code 220, got {code}"
        print(f"[SMTP/STARTTLS] upgrade OK (code {code})")


# ---------------------------------------------------------------------------
# IMAP — incoming mail
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestIMAPEndpoint:
    """E2E tests for the incoming IMAP connection."""

    def test_imap_login(self, settings: "Settings", test_hints: dict) -> None:
        """Connect and authenticate to the IMAP server — basic connectivity check."""
        print(f"\n[IMAP] host     : {settings.IMAP_HOST}:{settings.IMAP_PORT}")
        print(f"[IMAP] use_ssl  : {settings.IMAP_USE_SSL}")
        print(f"[IMAP] username : {settings.IMAP_USERNAME}")

        try:
            conn = _imap_connect(settings)
        except (ConnectionRefusedError, TimeoutError, OSError) as exc:
            mail_host = test_hints["MAIL_HOST"]
            vps_host = test_hints["VPS_HOST"]
            ssh_user = test_hints["SSH_USER"]
            pytest.fail(
                f"[IMAP] Cannot connect to {settings.IMAP_HOST}:{settings.IMAP_PORT}: {exc}\n"
                "If your ISP blocks port 993, set up an SSH tunnel:\n"
                f"  ssh -L 9993:{mail_host}:993 {ssh_user}@{vps_host} -N -f\n"
                "  IMAP_PORT=9993\n"
                "  IMAP_HOST=localhost"
            )
        except imaplib.IMAP4.error as exc:
            pytest.fail(f"[IMAP] Authentication failed: {exc}")

        status, data = conn.status(settings.IMAP_MAILBOX, "(MESSAGES UNSEEN)")
        conn.logout()

        print(f"[IMAP] mailbox status: {data[0].decode()}")
        assert status == "OK", f"Expected OK from IMAP STATUS, got {status}"

    def test_receive_probe_email(self, settings: "Settings") -> None:
        """Poll the mailbox for the probe email sent by test_send_email.

        Waits up to ``_RECEIVE_TIMEOUT`` seconds polling every
        ``_POLL_INTERVAL`` seconds.  Fails if the message does not arrive in
        time, which would indicate an SMTP delivery problem.
        """
        print(f"\n[IMAP] waiting for probe email (up to {_RECEIVE_TIMEOUT}s) …")
        print(f"[IMAP] looking for subject: {_PROBE_SUBJECT}")

        deadline = time.monotonic() + _RECEIVE_TIMEOUT
        found = False
        attempt = 0

        while time.monotonic() < deadline:
            attempt += 1
            try:
                conn = _imap_connect(settings)
            except Exception as exc:
                pytest.fail(f"[IMAP] Cannot connect: {exc}")

            try:
                # Search ALL messages (read + unread) for the probe subject
                status, data = conn.search(
                    None, f'SUBJECT "{_PROBE_UUID}"'
                )
                uid_list = data[0].split() if data[0] else []
            finally:
                try:
                    conn.close()
                    conn.logout()
                except Exception:
                    pass

            if uid_list:
                found = True
                print(f"[IMAP] probe email found after attempt {attempt} ✓")
                break

            remaining = deadline - time.monotonic()
            print(
                f"[IMAP] attempt {attempt}: not found yet "
                f"({max(0, remaining):.0f}s remaining) …"
            )
            time.sleep(_POLL_INTERVAL)

        assert found, (
            f"[IMAP] Probe email with UUID '{_PROBE_UUID}' did not arrive in "
            f"{_RECEIVE_TIMEOUT}s.\n"
            "This may indicate:\n"
            "  • SMTP send failed (check test_send_email result)\n"
            "  • Mail server delivery delay\n"
            "  • Spam filtering\n"
            "  • IMAP search index lag"
        )
