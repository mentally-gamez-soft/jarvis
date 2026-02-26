"""End-to-end tests for the MinIO / S3 backend.

These tests make **real** calls to the configured MinIO server.
They require a valid ``.env`` file with S3 credentials (``S3_ENDPOINT_URL``,
``S3_ACCESS_KEY``, ``S3_SECRET_KEY``).

Run:

    pytest tests/end2end/test_s3_endpoints.py -v -s

Test structure
--------------
All tests share a single session-scoped ``s3_client`` fixture that constructs
an :class:`~agent_triage.s3_client.S3Client`.  A unique project slug
(``e2e-test-<uuid4>``) is generated per session so tests are completely
isolated from production data and can be cleaned up unconditionally.

Cleanup
-------
A session-scoped autouse fixture deletes every object and the test bucket at
the end of the session, regardless of test outcome.

Tests covered
-------------
1. ``test_connection``         – list_buckets succeeds (basic connectivity).
2. ``test_create_project_bucket`` – project bucket is created (idempotent).
3. ``test_create_logs_bucket`` – write_log creates an object under ``logs/``.
4. ``test_upload_requirements`` – dummy ``requirements.md`` can be stored and
                                  retrieved under ``epics/``.
5. ``test_client_disconnect``  – boto3 client can be explicitly closed without
                                  raising an exception.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

import pytest
from botocore.exceptions import ClientError, EndpointResolutionError

if TYPE_CHECKING:
    from agent_triage.config import Settings
    from agent_triage.s3_client import S3Client

# ---------------------------------------------------------------------------
# Session-scoped unique project slug (avoids collisions with production data)
# ---------------------------------------------------------------------------

_TEST_SLUG: str = f"e2e-test-{uuid.uuid4().hex[:8]}"
_DUMMY_REQUIREMENTS = """\
# Dummy requirements (e2e test)

## Overview
This file was created automatically by the agent-triage end-to-end test suite.
It is safe to delete.

## Requirements
- REQ-001: The system shall do nothing harmful.
- REQ-002: The system shall clean up after itself.
"""


# ---------------------------------------------------------------------------
# Session-scoped S3Client fixture + auto-cleanup
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def s3_client(settings: "Settings", test_hints: dict) -> "S3Client":
    """Construct an S3Client against the real MinIO server.

    Skips the entire class when endpoint / credentials are absent.
    """
    if not settings.S3_ENDPOINT_URL or not settings.S3_ACCESS_KEY:
        pytest.skip(
            "S3 backend not configured (missing S3_ENDPOINT_URL or S3_ACCESS_KEY)."
        )
    from agent_triage.s3_client import S3Client
    return S3Client(settings)


@pytest.fixture(scope="session", autouse=False)
def _cleanup_test_bucket(s3_client: "S3Client") -> None:
    """Session-scoped teardown: delete all objects and the test bucket."""
    yield  # tests run here

    bucket = s3_client.bucket_name(_TEST_SLUG)
    raw_client = s3_client._client

    try:
        # Delete all objects first (MinIO requires an empty bucket before deletion).
        # Use individual delete_object calls — some MinIO versions reject
        # delete_objects (bulk) due to missing Content-MD5 header.
        paginator = raw_client.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                raw_client.delete_object(Bucket=bucket, Key=obj["Key"])
                deleted += 1
        raw_client.delete_bucket(Bucket=bucket)
        print(f"\n[S3/cleanup] bucket '{bucket}' deleted ({deleted} objects removed) ✓")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code not in ("404", "NoSuchBucket"):
            print(f"\n[S3/cleanup] WARNING: could not delete '{bucket}': {exc}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestS3Connection:
    """Basic connectivity: can we reach the MinIO server at all?"""

    def test_connection(self, s3_client: "S3Client", test_hints: dict) -> None:
        """Call list_buckets — succeeds if credentials and endpoint are valid."""
        endpoint = test_hints.get("S3_ENDPOINT_URL", "<s3-endpoint-url>")
        print(f"\n[S3] endpoint : {endpoint}")

        try:
            response = s3_client._client.list_buckets()
        except (EndpointResolutionError, OSError) as exc:
            pytest.fail(
                f"[S3] Cannot reach MinIO at {endpoint}: {exc}\n"
                "Check S3_ENDPOINT_URL in .env and that the MinIO server is running."
            )
        except ClientError as exc:
            pytest.fail(f"[S3] AWS/MinIO API error: {exc}")

        existing = [b["Name"] for b in response.get("Buckets", [])]
        print(f"[S3] existing buckets ({len(existing)}): {existing}")
        assert isinstance(existing, list), "Expected a list of buckets."
        print("[S3] connection OK ✓")


@pytest.mark.e2e
class TestS3ProjectBucket:
    """Project bucket lifecycle: create and verify existence."""

    @pytest.fixture(autouse=True)
    def _use_cleanup(self, _cleanup_test_bucket: None) -> None:
        """Pull in the cleanup fixture so the bucket is removed after the session."""

    def test_create_project_bucket(self, s3_client: "S3Client") -> None:
        """ensure_bucket creates the project bucket if it does not exist."""
        bucket = s3_client.bucket_name(_TEST_SLUG)
        print(f"\n[S3] creating project bucket: '{bucket}'")

        returned = s3_client.ensure_bucket(_TEST_SLUG)

        assert returned == bucket, (
            f"ensure_bucket returned '{returned}', expected '{bucket}'"
        )

        # Verify by calling head_bucket — raises ClientError on failure.
        try:
            s3_client._client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            pytest.fail(f"[S3] bucket '{bucket}' not found after creation: {exc}")

        print(f"[S3] bucket '{bucket}' exists ✓")

    def test_create_project_bucket_is_idempotent(self, s3_client: "S3Client") -> None:
        """Calling ensure_bucket twice must not raise an error."""
        bucket = s3_client.ensure_bucket(_TEST_SLUG)
        bucket2 = s3_client.ensure_bucket(_TEST_SLUG)
        assert bucket == bucket2
        print(f"\n[S3] idempotent bucket creation OK ✓ ({bucket})")


@pytest.mark.e2e
class TestS3LogsBucket:
    """Log objects: write_log stores content under logs/ prefix."""

    @pytest.fixture(autouse=True)
    def _use_cleanup(self, _cleanup_test_bucket: None) -> None:
        """Pull in the cleanup fixture."""

    def test_write_log_creates_object(self, s3_client: "S3Client") -> None:
        """write_log must store a log entry and return a key under logs/."""
        log_content = (
            f"[e2e test log]\n"
            f"project : {_TEST_SLUG}\n"
            f"date    : {date.today().isoformat()}\n"
            f"status  : ok\n"
        )

        key = s3_client.write_log(_TEST_SLUG, log_content)
        bucket = s3_client.bucket_name(_TEST_SLUG)
        prefix = s3_client._settings.S3_LOG_PREFIX

        print(f"\n[S3] log written → {bucket}/{key}")

        assert key.startswith(f"{prefix}/"), (
            f"Expected log key to start with '{prefix}/', got '{key}'"
        )
        assert key.endswith(".log"), f"Expected .log extension, got '{key}'"

        # Verify the object is retrievable and content matches.
        stored = s3_client.get_object(bucket, key)
        assert stored is not None, f"Object '{key}' not found in bucket '{bucket}'"
        assert stored.decode("utf-8") == log_content
        print(f"[S3] log object verified ✓ ({len(stored)} bytes)")


@pytest.mark.e2e
class TestS3Requirements:
    """Requirements file upload: store and retrieve a dummy requirements.md."""

    @pytest.fixture(autouse=True)
    def _use_cleanup(self, _cleanup_test_bucket: None) -> None:
        """Pull in the cleanup fixture."""

    def test_upload_requirements(self, s3_client: "S3Client") -> None:
        """Upload a dummy requirements.md as an epic and retrieve it verbatim."""
        bucket = s3_client.bucket_name(_TEST_SLUG)
        key = s3_client.write_epic(
            project_slug=_TEST_SLUG,
            epic_markdown=_DUMMY_REQUIREMENTS,
            short_description="dummy requirements e2e test",
        )

        print(f"\n[S3] requirements written → {bucket}/{key}")
        assert key.startswith("epics/"), (
            f"Expected key under 'epics/', got '{key}'"
        )
        assert key.endswith(".md"), f"Expected .md extension, got '{key}'"

        # Retrieve and verify content.
        stored = s3_client.get_object(bucket, key)
        assert stored is not None, f"Object '{key}' not found after upload"
        assert stored.decode("utf-8") == _DUMMY_REQUIREMENTS
        print(f"[S3] requirements file verified ✓ ({len(stored)} bytes)")

    def test_read_latest_epic_returns_requirements(self, s3_client: "S3Client") -> None:
        """read_latest_epic should return the content uploaded in the previous test."""
        content = s3_client.read_latest_epic(_TEST_SLUG)
        assert content is not None, (
            f"read_latest_epic returned None for slug '{_TEST_SLUG}' — "
            "was the upload test skipped?"
        )
        assert "dummy requirements" in content.lower(), (
            "Expected uploaded content not found in read_latest_epic result."
        )
        print(f"\n[S3] read_latest_epic ✓ ({len(content)} chars)")


@pytest.mark.e2e
class TestS3Disconnect:
    """Graceful close of the boto3 client."""

    def test_client_disconnect(self, s3_client: "S3Client") -> None:
        """boto3 client.close() must not raise an exception."""
        from agent_triage.s3_client import S3Client

        # Use a fresh client instance so we don't break the session-scoped one.
        fresh = S3Client(s3_client._settings)

        try:
            fresh._client.close()
        except Exception as exc:
            pytest.fail(f"[S3] client.close() raised an unexpected exception: {exc}")

        print("\n[S3] client.close() OK ✓")
