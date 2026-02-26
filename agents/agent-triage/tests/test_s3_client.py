"""Unit tests for agent_triage.s3_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call
from datetime import date

import pytest
from botocore.exceptions import ClientError

from agent_triage.s3_client import S3Client, _short_description


# ---------------------------------------------------------------------------
# _short_description helper
# ---------------------------------------------------------------------------

class TestShortDescription:
    def test_basic(self):
        assert _short_description("image displayer project") == "image-displayer-project"

    def test_truncates_to_max_words(self):
        result = _short_description("one two three four five six", max_words=3)
        assert result == "one-two-three"

    def test_strips_punctuation(self):
        assert _short_description("Hello, World!") == "hello-world"

    def test_empty_falls_back(self):
        assert _short_description("") == "epic"


# ---------------------------------------------------------------------------
# S3Client
# ---------------------------------------------------------------------------

def _make_settings(endpoint="http://minio:9000"):
    s = MagicMock()
    s.S3_ENDPOINT_URL = endpoint
    s.S3_ACCESS_KEY = "minioadmin"
    s.S3_SECRET_KEY = "minioadmin"
    s.S3_REGION = "us-east-1"
    s.S3_BUCKET_TEMPLATE = "jarvis-{project_slug}"
    s.S3_LOG_PREFIX = "logs"
    return s


class TestS3ClientBucketName:
    def test_bucket_name_from_template(self):
        settings = _make_settings()
        with patch("agent_triage.s3_client.boto3"):
            client = S3Client(settings)
        assert client.bucket_name("image-displayer") == "jarvis-image-displayer"


class TestEnsureBucket:
    def test_does_not_create_if_exists(self):
        settings = _make_settings()
        with patch("agent_triage.s3_client.boto3") as mock_boto3:
            mock_boto_client = MagicMock()
            mock_boto3.client.return_value = mock_boto_client
            mock_boto_client.head_bucket.return_value = {}

            client = S3Client(settings)
            name = client.ensure_bucket("my-project")

        mock_boto_client.create_bucket.assert_not_called()
        assert name == "jarvis-my-project"

    def test_creates_bucket_on_404(self):
        settings = _make_settings()
        error = ClientError({"Error": {"Code": "404", "Message": "Not found"}}, "HeadBucket")

        with patch("agent_triage.s3_client.boto3") as mock_boto3:
            mock_boto_client = MagicMock()
            mock_boto3.client.return_value = mock_boto_client
            mock_boto_client.head_bucket.side_effect = error

            client = S3Client(settings)
            client.ensure_bucket("new-project")

        mock_boto_client.create_bucket.assert_called_once_with(Bucket="jarvis-new-project")


class TestWriteReadEpic:
    def test_write_epic_puts_object(self):
        settings = _make_settings()
        with patch("agent_triage.s3_client.boto3") as mock_boto3:
            mock_boto_client = MagicMock()
            mock_boto3.client.return_value = mock_boto_client
            mock_boto_client.head_bucket.return_value = {}

            client = S3Client(settings)
            key = client.write_epic("my-project", "# Epic\nContent", "my project")

        assert key.startswith("epics/")
        assert key.endswith(".md")
        mock_boto_client.put_object.assert_called_once()

    def test_get_object_returns_none_on_missing(self):
        settings = _make_settings()
        error = ClientError({"Error": {"Code": "NoSuchKey", "Message": ""}}, "GetObject")

        with patch("agent_triage.s3_client.boto3") as mock_boto3:
            mock_boto_client = MagicMock()
            mock_boto3.client.return_value = mock_boto_client
            mock_boto_client.get_object.side_effect = error

            client = S3Client(settings)
            result = client.get_object("jarvis-my-project", "epics/something.md")

        assert result is None
