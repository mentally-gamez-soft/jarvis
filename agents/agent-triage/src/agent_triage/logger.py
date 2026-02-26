"""Dual-destination logger for agent-triage.

Logs are written to:
1. Container stdout  — visible via `docker logs` in real time.
2. MinIO S3          — stored under ``<bucket>/logs/<YYYY-MM-DD>/<ISO-timestamp>.log``
                       for long-term analysis.

Usage::

    from agent_triage.logger import get_logger
    log = get_logger(__name__)
    log.info("email.received", subject="[JARVIS][my-project] …", uid=42)
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from agent_triage.s3_client import S3Client


def configure_logging(log_level: str = "INFO") -> None:
    """Set up structlog to emit JSON to stdout.

    Call once at application startup (before creating any logger).
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for *name*."""
    return structlog.get_logger(name)


class S3LogHandler(logging.Handler):
    """A stdlib logging handler that writes formatted log records to MinIO S3.

    Log records are accumulated in memory and flushed to S3 either explicitly
    (via :meth:`flush_to_s3`) or when the handler is closed.  The S3 key
    follows the pattern ``logs/<YYYY-MM-DD>/<ISO-timestamp>_<name>.log``.
    """

    def __init__(self, s3_client: "S3Client", bucket: str, prefix: str = "logs") -> None:
        super().__init__()
        self._s3 = s3_client
        self._bucket = bucket
        self._prefix = prefix
        self._buffer: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            self._buffer.append(self.format(record))
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def flush_to_s3(self, key_suffix: str) -> None:
        """Write accumulated records to S3 and clear the buffer.

        Args:
            key_suffix: appended to the S3 key, e.g. an ISO timestamp string.
        """
        if not self._buffer:
            return
        from datetime import date

        day = date.today().isoformat()
        key = f"{self._prefix}/{day}/{key_suffix}.log"
        content = "\n".join(self._buffer)
        self._s3.put_object(bucket=self._bucket, key=key, body=content.encode())
        self._buffer.clear()
