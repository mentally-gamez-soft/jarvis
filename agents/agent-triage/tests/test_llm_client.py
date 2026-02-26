"""Unit tests for agent_triage.llm_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pybreaker
import pytest

from agent_triage.llm_client import ChatGPTBackend, CopilotBackend, LLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(
    chatgpt_url: str = "http://api.example.com/chat",
    chatgpt_key: str = "key123",
    github_token: str = "gh_token",
    fail_max: int = 3,
    reset_timeout: int = 60,
    retry_attempts: int = 2,
    retry_wait_min: float = 0.01,
    retry_wait_max: float = 0.05,
) -> MagicMock:
    s = MagicMock()
    s.CHATGPT_API_URL = chatgpt_url
    s.CHATGPT_API_KEY = chatgpt_key
    s.CHATGPT_MODEL = "gpt-4o-mini"
    s.CHATGPT_TIMEOUT = 5.0
    s.GITHUB_TOKEN = github_token
    s.COPILOT_MODEL = "gpt-4o"
    s.COPILOT_CLI_PATH = "copilot"
    s.CB_FAIL_MAX = fail_max
    s.CB_RESET_TIMEOUT = reset_timeout
    s.CB_RETRY_ATTEMPTS = retry_attempts
    s.CB_RETRY_WAIT_MIN = retry_wait_min
    s.CB_RETRY_WAIT_MAX = retry_wait_max
    return s


# ---------------------------------------------------------------------------
# ChatGPTBackend
# ---------------------------------------------------------------------------

class TestChatGPTBackend:
    def test_is_configured_true_when_url_and_key_set(self):
        backend = ChatGPTBackend(_make_settings())
        assert backend.is_configured is True

    def test_is_configured_false_when_url_missing(self):
        backend = ChatGPTBackend(_make_settings(chatgpt_url=""))
        assert backend.is_configured is False

    def test_is_configured_false_when_key_missing(self):
        backend = ChatGPTBackend(_make_settings(chatgpt_key=""))
        assert backend.is_configured is False

    def test_raises_when_not_configured(self):
        backend = ChatGPTBackend(_make_settings(chatgpt_url=""))
        with pytest.raises(RuntimeError, match="not configured"):
            backend.generate("sys", "user")

    def test_successful_http_call_returns_content(self):
        settings = _make_settings()
        backend = ChatGPTBackend(settings)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "# Epic"}}],
            "model": "gpt-4o-mini",
        }

        with patch("agent_triage.llm_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_response
            result = backend.generate("system msg", "user prompt")

        assert result == "# Epic"

    def test_5xx_raises_ioerror_triggering_retry(self):
        settings = _make_settings(retry_attempts=2)
        backend = ChatGPTBackend(settings)

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        with patch("agent_triage.llm_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_response
            with pytest.raises(IOError, match="server error 503"):
                backend.generate("sys", "user")

    def test_4xx_raises_valueerror_without_retry(self):
        settings = _make_settings()
        backend = ChatGPTBackend(settings)

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        call_count = 0

        def fake_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_response

        with patch("agent_triage.llm_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = fake_post
            with pytest.raises(ValueError, match="client error 401"):
                backend.generate("sys", "user")

        # 4xx must NOT be retried — only one call should have happened.
        assert call_count == 1

    def test_circuit_opens_after_fail_max_exhausted_retries(self):
        settings = _make_settings(fail_max=2, retry_attempts=1)
        backend = ChatGPTBackend(settings)

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "error"

        with patch("agent_triage.llm_client.httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_response

            # First call: retries exhausted → circuit records 1 failure (still closed)
            with pytest.raises(IOError):
                backend.generate("sys", "user")

            # Second call: retries exhausted → circuit records 2nd failure → trips open.
            # New pybreaker behaviour: the call that opens the circuit raises
            # CircuitBreakerError directly rather than re-raising the underlying IOError.
            with pytest.raises(pybreaker.CircuitBreakerError):
                backend.generate("sys", "user")

            # Third call: circuit is OPEN → CircuitBreakerError, no HTTP call made
            with pytest.raises(pybreaker.CircuitBreakerError):
                backend.generate("sys", "user")


# ---------------------------------------------------------------------------
# LLMClient facade
# ---------------------------------------------------------------------------

class TestLLMClient:
    def test_uses_chatgpt_when_available(self):
        settings = _make_settings()
        client = LLMClient(settings)

        with patch.object(client._chatgpt, "generate", return_value="# From ChatGPT") as mock_cg, \
             patch.object(client._copilot, "generate") as mock_cp:
            result = client.generate("sys", "user")

        mock_cg.assert_called_once()
        mock_cp.assert_not_called()
        assert result == "# From ChatGPT"

    def test_falls_back_to_copilot_when_chatgpt_raises(self):
        settings = _make_settings()
        client = LLMClient(settings)

        with patch.object(client._chatgpt, "generate", side_effect=IOError("timeout")), \
             patch.object(client._copilot, "generate", return_value="# From Copilot"):
            result = client.generate("sys", "user")

        assert result == "# From Copilot"

    def test_falls_back_to_copilot_when_chatgpt_circuit_open(self):
        settings = _make_settings()
        client = LLMClient(settings)

        with patch.object(
            client._chatgpt, "generate",
            side_effect=pybreaker.CircuitBreakerError("open"),
        ), patch.object(client._copilot, "generate", return_value="# From Copilot"):
            result = client.generate("sys", "user")

        assert result == "# From Copilot"

    def test_skips_chatgpt_when_not_configured(self):
        settings = _make_settings(chatgpt_url="")
        client = LLMClient(settings)

        with patch.object(client._copilot, "generate", return_value="# From Copilot") as mock_cp:
            result = client.generate("sys", "user")

        mock_cp.assert_called_once()
        assert result == "# From Copilot"

    def test_raises_when_both_backends_fail(self):
        settings = _make_settings()
        client = LLMClient(settings)

        with patch.object(client._chatgpt, "generate", side_effect=IOError("chatgpt down")), \
             patch.object(client._copilot, "generate", side_effect=RuntimeError("copilot down")):
            with pytest.raises(RuntimeError, match="Both LLM backends failed"):
                client.generate("sys", "user")

    def test_raises_when_both_backends_unconfigured(self):
        settings = _make_settings(chatgpt_url="", github_token="")
        client = LLMClient(settings)

        with pytest.raises(RuntimeError, match="unconfigured"):
            client.generate("sys", "user")
