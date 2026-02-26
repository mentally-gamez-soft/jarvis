"""Main entrypoint for agent-triage.

This script is invoked by cron every POLL_INTERVAL_MINUTES minutes inside
the Docker container. It:

1. Connects to the configured IMAP mailbox.
2. Fetches all unread ``[JARVIS]-[…]`` emails.
3. Groups emails by project slug.
4. For each project group:
   a. Ensures the per-project MinIO bucket exists.
   b. Downloads any existing epic from S3.
   c. Resolves extension rules (email attachment → S3 storage → existing S3 copy).
   d. Iterates through each email for the project, calling the Copilot SDK to
      accumulate requirement merges **in memory**.
   e. Writes the final merged epic to S3 **once** — triggering exactly one
      MinIO bucket notification to agent-scrum-master regardless of how many
      emails arrived for the same project.
   f. Marks all emails for that project as seen.
5. Flushes accumulated logs to S3.

Grouping by project before writing is critical: it guarantees that
``agent-scrum-master`` receives **one webhook per project per cron run**,
preventing duplicate Trello card creation and race conditions that would arise
from multiple rapid writes to the same S3 key.

Usage::

    python -m agent_triage.main
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from .config import get_settings
from .email_client import AgentEmail, EmailClient
from .epic_generator import EpicGenerator
from .logger import S3LogHandler, configure_logging, get_logger
from .s3_client import S3Client
from .smtp_client import SMTPClient

log = get_logger(__name__)


def _resolve_extension_rules(
    mail: AgentEmail,
    s3: S3Client,
    pending_extension_rules: Optional[str],
) -> Optional[str]:
    """Return the best available extension rules for this email.

    Priority:
    1. Rules attached to the current email (freshest).
    2. Rules accumulated from earlier emails in the same project group this run.
    3. Rules previously stored in S3 from a past run.
    """
    if mail.extension_rules:
        log.info(
            "agent.extension_rules_from_email",
            project=mail.project_slug,
            length=len(mail.extension_rules),
        )
        return mail.extension_rules

    if pending_extension_rules:
        return pending_extension_rules

    stored = s3.read_extension_rules(mail.project_slug)
    if stored:
        log.info(
            "agent.extension_rules_from_s3",
            project=mail.project_slug,
            length=len(stored),
        )
    return stored


def _process_project_emails(
    project_slug: str,
    mails: list[AgentEmail],
    s3: S3Client,
    generator: EpicGenerator,
    email_client: EmailClient,
    smtp_client: SMTPClient,
) -> int:
    """Process all emails for a single project and return the count of successes.

    All requirement merges are accumulated in memory.  S3 is written — and the
    MinIO bucket notification fired — **exactly once** at the end, regardless of
    how many emails arrived for this project in the current cron run.
    """
    log.info(
        "agent.project_run_started",
        project=project_slug,
        email_count=len(mails),
    )

    # 1. Ensure bucket (registers webhook notification if new).
    bucket = s3.ensure_bucket(project_slug)

    # 2. Seed the epic with whatever is already in S3.
    accumulated_epic: Optional[str] = s3.read_latest_epic(project_slug)
    if accumulated_epic:
        log.info(
            "agent.existing_epic_found",
            project=project_slug,
            length=len(accumulated_epic),
        )
    else:
        log.info("agent.no_existing_epic", project=project_slug)

    # Track the latest extension rules seen across this project's emails.
    accumulated_extension_rules: Optional[str] = None
    processed_uids: list[str] = []
    project_name: str = mails[0].project_name  # all emails share the same project name

    for mail in mails:
        log.info(
            "agent.processing_email",
            uid=mail.uid,
            project=project_slug,
            subject=mail.subject,
            email_index=mails.index(mail) + 1,
            total_emails=len(mails),
        )
        try:
            # Resolve extension rules for this email.
            extension_rules = _resolve_extension_rules(
                mail, s3, accumulated_extension_rules
            )
            if mail.extension_rules:
                # Keep the freshest attachment for the final S3 write.
                accumulated_extension_rules = mail.extension_rules

            # Merge this email's requirements into the accumulated epic.
            accumulated_epic = generator.generate(
                project_name=mail.project_name,
                requirements_body=mail.body,
                existing_epic=accumulated_epic,
                extension_rules=extension_rules,
                title=mail.title,
                idea=mail.idea,
                envs=mail.envs,
                directives=mail.directives,
            )
            processed_uids.append(mail.uid)

            # Send reply to the sender with the generated epic attached
            if mail.sender and accumulated_epic:
                try:
                    reply_body = (
                        f"Hello,\n\n"
                        f"We've processed your requirements for '{mail.project_name}' "
                        f"and generated a project specification document. "
                        f"Please see the attached file for details.\n\n"
                        f"Best regards,\n"
                        f"JARVIS Agent"
                    )
                    smtp_client.send_reply(
                        recipient=mail.sender,
                        subject=f"Re: {mail.subject}",
                        body=reply_body,
                        attachment_filename="requirements.md",
                        attachment_content=accumulated_epic.encode("utf-8"),
                    )
                    log.info(
                        "agent.reply_sent",
                        uid=mail.uid,
                        recipient=mail.sender,
                        project=project_slug,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "agent.reply_failed",
                        uid=mail.uid,
                        recipient=mail.sender,
                        project=project_slug,
                        error=str(exc),
                    )
                    # Continue processing; reply failure doesn't block further work

        except Exception as exc:  # noqa: BLE001
            log.error(
                "agent.email_generation_failed",
                uid=mail.uid,
                project=project_slug,
                error=str(exc),
                exc_info=True,
            )
            # Skip this email; do not add its uid to processed_uids so it
            # remains unseen and will be retried on the next cron run.

    if not processed_uids:
        log.warning("agent.project_no_emails_succeeded", project=project_slug)
        return 0

    # 3. Persist extension rules to S3 if updated this run.
    if accumulated_extension_rules:
        s3.write_extension_rules(project_slug, accumulated_extension_rules)

    # 4. Single S3 write → single MinIO notification → single agent-scrum-master trigger.
    if accumulated_epic:
        key = s3.write_epic(
            project_slug=project_slug,
            epic_markdown=accumulated_epic,
            short_description=project_name,
        )
        log.info(
            "agent.epic_uploaded",
            project=project_slug,
            s3_key=key,
            bucket=bucket,
            emails_merged=len(processed_uids),
        )

    # 5. Mark all successfully processed emails as seen only after the S3 write.
    for uid in processed_uids:
        email_client.mark_as_seen(uid)

    return len(processed_uids)


def run() -> None:
    """Main execution function — called by cron."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    started_at = datetime.now(tz=timezone.utc)
    log.info("agent.run_started", timestamp=started_at.isoformat())

    s3 = S3Client(settings)
    smtp_client = SMTPClient(settings)
    _LOG_PROJECT_SLUG = "agent-triage-logs"

    stdlib_logger = logging.getLogger()
    s3_handler = S3LogHandler(
        s3_client=s3,
        bucket=s3.bucket_name(_LOG_PROJECT_SLUG),
        prefix=settings.S3_LOG_PREFIX,
    )
    s3_handler.setFormatter(logging.Formatter("%(message)s"))
    stdlib_logger.addHandler(s3_handler)

    generator = EpicGenerator(settings)
    processed = 0
    errors = 0

    try:
        with EmailClient(settings) as email_client:
            emails = email_client.fetch_unread_jarvis_emails()
            log.info("agent.emails_fetched", count=len(emails))

            if not emails:
                log.info("agent.nothing_to_do")
                return

            # Group by project slug so each project gets exactly one S3 write.
            emails_by_project: dict[str, list[AgentEmail]] = defaultdict(list)
            for mail in emails:
                emails_by_project[mail.project_slug].append(mail)

            log.info(
                "agent.projects_in_run",
                project_count=len(emails_by_project),
                projects=list(emails_by_project.keys()),
            )

            for project_slug, project_mails in emails_by_project.items():
                try:
                    count = _process_project_emails(
                        project_slug, project_mails, s3, generator, email_client, smtp_client
                    )
                    processed += count
                    errors += len(project_mails) - count
                except Exception as exc:  # noqa: BLE001
                    errors += len(project_mails)
                    log.error(
                        "agent.project_failed",
                        project=project_slug,
                        error=str(exc),
                        exc_info=True,
                    )

    except Exception as exc:  # noqa: BLE001
        log.error("agent.fatal_error", error=str(exc), exc_info=True)
        errors += 1

    finally:
        finished_at = datetime.now(tz=timezone.utc)
        duration_s = (finished_at - started_at).total_seconds()
        log.info(
            "agent.run_finished",
            processed=processed,
            errors=errors,
            duration_seconds=round(duration_s, 2),
        )
        run_ts = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
        try:
            s3.ensure_bucket(_LOG_PROJECT_SLUG)
            s3_handler.flush_to_s3(run_ts)
        except Exception as exc:  # noqa: BLE001
            log.error("agent.s3_log_flush_failed", error=str(exc))


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        # Last-resort stderr output so the cron daemon captures it.
        print(f"[agent-triage] UNHANDLED ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
