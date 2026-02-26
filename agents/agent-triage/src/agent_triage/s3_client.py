"""MinIO / S3 client for agent-triage.

Handles:
- Creating per-project buckets if they don't exist.
- Reading and writing epic documents.
- Storing ``project-extension-rules.md`` attachments.
- Writing log objects.

All paths follow these conventions:

  epics/<project-name>/epic_<short_description>_<YYYY-MM-DD>.md
  epics/<project-name>/project-extension-rules.md   (optional, if provided in email)
  logs/<YYYY-MM-DD>/<ISO-timestamp>.log
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Optional

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from .config import Settings
from .logger import get_logger

log = get_logger(__name__)


def _short_description(text: str, max_words: int = 4) -> str:
    """Build a short slug from the first *max_words* words of *text*."""
    words = re.sub(r"[^\w\s]", "", text.lower()).split()[:max_words]
    return "-".join(words) if words else "epic"


class S3Client:
    """Thin wrapper around :mod:`boto3` configured for MinIO."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: BaseClient = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
        )

    # ------------------------------------------------------------------
    # Bucket helpers
    # ------------------------------------------------------------------

    def bucket_name(self, project_slug: str) -> str:
        """Return the bucket name for *project_slug*."""
        return self._settings.S3_BUCKET_TEMPLATE.format(project_slug=project_slug)

    def ensure_bucket(self, project_slug: str) -> str:
        """Create the project bucket if it doesn't exist; return bucket name.

        When a new bucket is created and ``S3_NOTIFICATION_WEBHOOK_URL`` is
        configured, a MinIO bucket notification is automatically registered so
        that ``agent-scrum-master`` is triggered whenever an epic object lands
        under ``epics/``.
        """
        name = self.bucket_name(project_slug)
        try:
            self._client.head_bucket(Bucket=name)
            log.debug("s3.bucket_exists", bucket=name)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchBucket"):
                self._client.create_bucket(Bucket=name)
                log.info("s3.bucket_created", bucket=name)
                self._register_notification(name)
            else:
                raise
        return name

    def _register_notification(self, bucket: str) -> None:
        """Register a MinIO webhook notification on *bucket* for ``epics/`` puts.

        Only executed when ``S3_NOTIFICATION_WEBHOOK_URL`` is non-empty.
        This makes the handoff to ``agent-scrum-master`` fully automatic:
        no manual ``mc event add`` command is needed per project.
        """
        webhook_url = self._settings.S3_NOTIFICATION_WEBHOOK_URL
        if not webhook_url:
            log.debug(
                "s3.notification_skipped",
                bucket=bucket,
                reason="S3_NOTIFICATION_WEBHOOK_URL not set",
            )
            return

        notification_config = {
            "QueueConfigurations": [
                {
                    "Id": f"{bucket}-epics-put",
                    "QueueArn": self._settings.S3_NOTIFICATION_QUEUE_ARN,
                    "Events": ["s3:ObjectCreated:Put"],
                    "Filter": {
                        "Key": {
                            "FilterRules": [
                                {"Name": "prefix", "Value": "epics/"},
                            ]
                        }
                    },
                }
            ]
        }

        try:
            self._client.put_bucket_notification_configuration(
                Bucket=bucket,
                NotificationConfiguration=notification_config,
            )
            log.info(
                "s3.notification_registered",
                bucket=bucket,
                prefix="epics/",
                webhook_url=webhook_url,
                queue_arn=self._settings.S3_NOTIFICATION_QUEUE_ARN,
            )
        except ClientError as exc:
            # Non-fatal: log the error but don't abort the run.
            log.error(
                "s3.notification_registration_failed",
                bucket=bucket,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Generic put / get
    # ------------------------------------------------------------------

    def put_object(self, bucket: str, key: str, body: bytes) -> None:
        """Upload *body* bytes to *bucket*/*key*."""
        self._client.put_object(Bucket=bucket, Key=key, Body=body)
        log.debug("s3.put_object", bucket=bucket, key=key, size=len(body))

    def get_object(self, bucket: str, key: str) -> Optional[bytes]:
        """Download *bucket*/*key*; returns ``None`` if the object doesn't exist."""
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            data: bytes = response["Body"].read()
            log.debug("s3.get_object", bucket=bucket, key=key, size=len(data))
            return data
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                return None
            raise

    # ------------------------------------------------------------------
    # Epic helpers
    # ------------------------------------------------------------------

    def epic_key(self, short_description: str) -> str:
        """Build the S3 key for an epic object.

        Pattern: ``epics/<short-description>_<YYYY-MM-DD>.md``
        """
        today = date.today().isoformat()
        slug = _short_description(short_description)
        return f"epics/{slug}_{today}.md"

    def read_latest_epic(self, project_slug: str) -> Optional[str]:
        """Return the content of the most recently written epic, or ``None``."""
        bucket = self.bucket_name(project_slug)
        try:
            response = self._client.list_objects_v2(
                Bucket=bucket, Prefix="epics/", Delimiter="/"
            )
        except ClientError:
            return None

        objects = response.get("Contents", [])
        if not objects:
            return None

        # Pick the lexicographically last key (date-suffix ensures recency).
        latest = max(obj["Key"] for obj in objects)
        data = self.get_object(bucket, latest)
        return data.decode("utf-8") if data else None

    def write_epic(
        self,
        project_slug: str,
        epic_markdown: str,
        short_description: str,
    ) -> str:
        """Write (or overwrite) the epic for *project_slug* and return the S3 key."""
        bucket = self.ensure_bucket(project_slug)
        key = self.epic_key(short_description)
        self.put_object(bucket, key, epic_markdown.encode("utf-8"))
        log.info("s3.epic_written", bucket=bucket, key=key)
        return key

    def write_extension_rules(
        self, project_slug: str, content: str
    ) -> str:
        """Store ``project-extension-rules.md`` for *project_slug*; return key."""
        bucket = self.ensure_bucket(project_slug)
        key = "epics/project-extension-rules.md"
        self.put_object(bucket, key, content.encode("utf-8"))
        log.info("s3.extension_rules_written", bucket=bucket, key=key)
        return key

    def read_extension_rules(self, project_slug: str) -> Optional[str]:
        """Return previously stored extension rules, or ``None``."""
        bucket = self.bucket_name(project_slug)
        data = self.get_object(bucket, "epics/project-extension-rules.md")
        return data.decode("utf-8") if data else None

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def write_log(self, project_slug: str, content: str) -> str:
        """Append a log snapshot to the project bucket under ``logs/``."""
        bucket = self.ensure_bucket(project_slug)
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        day = date.today().isoformat()
        key = f"{self._settings.S3_LOG_PREFIX}/{day}/{ts}.log"
        self.put_object(bucket, key, content.encode("utf-8"))
        log.debug("s3.log_written", bucket=bucket, key=key)
        return key
