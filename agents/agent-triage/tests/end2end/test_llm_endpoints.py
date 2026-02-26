"""End-to-end tests for the external LLM service calls.

These tests make **real HTTP / process calls** to the configured LLM backends.
They require a valid `.env` file at the root of the agent-triage project with
the relevant credentials filled in.

Run only the e2e suite:

    pytest tests/end2end/ -v -s

Or via the registered mark:

    pytest -m e2e -v -s

Each test is individually skipped (not failed) when its backend is not
configured, so the suite stays green in environments without full credentials.

Prompt used for all tests
--------------------------
A simple, deterministic subject: **"Give a short summary about the Enigma machine."**
This is factual, short, easy to reason about, and avoids any content policy issues.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from agent_triage.config import Settings

# ---------------------------------------------------------------------------
# Shared prompt
# ---------------------------------------------------------------------------

SYSTEM_MSG = (
    "You are a concise technical assistant. "
    "Answer in plain English, maximum 3 short paragraphs."
)
USER_PROMPT = "Give a short summary about the Enigma machine."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_valid_response(response: str, backend_name: str) -> None:
    """Common assertions applied to every LLM response."""
    assert isinstance(response, str), f"[{backend_name}] Response must be a string."
    assert len(response.strip()) > 50, (
        f"[{backend_name}] Response is suspiciously short ({len(response)} chars). "
        "Got: " + repr(response[:200])
    )
    # The word "Enigma" should appear — basic sanity that the model answered on-topic.
    assert "enigma" in response.lower() or "cipher" in response.lower() or "encrypt" in response.lower(), (
        f"[{backend_name}] Response does not mention Enigma, cipher, or encryption.\n"
        "Got: " + repr(response[:500])
    )


# ---------------------------------------------------------------------------
# ChatGPT backend
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestChatGPTEndpoint:
    """E2E tests for the ChatGPT / OpenAI-compatible API backend."""

    @pytest.fixture(autouse=True)
    def _skip_if_unconfigured(self, settings: "Settings") -> None:
        if not settings.CHATGPT_API_URL or not settings.CHATGPT_API_KEY:
            pytest.skip("ChatGPT backend not configured (missing CHATGPT_API_URL or CHATGPT_API_KEY).")

    def test_simple_call_returns_response(self, settings: "Settings") -> None:
        """Call the ChatGPT endpoint and verify a coherent response is returned."""
        from agent_triage.llm_client import ChatGPTBackend

        backend = ChatGPTBackend(settings)
        print(f"\n[ChatGPT] endpoint : {settings.CHATGPT_API_URL}")
        print(f"[ChatGPT] model    : {settings.CHATGPT_MODEL}")

        start = time.perf_counter()
        response = backend.generate(SYSTEM_MSG, USER_PROMPT)
        elapsed = time.perf_counter() - start

        print(f"[ChatGPT] duration : {elapsed:.2f}s")
        print(f"[ChatGPT] length   : {len(response)} chars")
        print(f"[ChatGPT] response :\n{'-' * 60}\n{response}\n{'-' * 60}")

        _assert_valid_response(response, "ChatGPT")

    def test_response_time_is_acceptable(self, settings: "Settings") -> None:
        """Response must arrive within CHATGPT_TIMEOUT seconds."""
        from agent_triage.llm_client import ChatGPTBackend

        backend = ChatGPTBackend(settings)
        start = time.perf_counter()
        backend.generate(SYSTEM_MSG, USER_PROMPT)
        elapsed = time.perf_counter() - start

        assert elapsed < settings.CHATGPT_TIMEOUT, (
            f"[ChatGPT] Call took {elapsed:.2f}s which exceeds the configured "
            f"timeout of {settings.CHATGPT_TIMEOUT}s."
        )

    def test_circuit_breaker_starts_closed(self, settings: "Settings") -> None:
        """The circuit breaker must start in CLOSED state on a fresh backend instance."""
        from agent_triage.llm_client import ChatGPTBackend

        backend = ChatGPTBackend(settings)
        assert backend._cb.current_state == "closed", (
            f"Expected circuit to start CLOSED, got: {backend._cb.current_state}"
        )
        # Trigger one successful call — circuit must remain closed.
        backend.generate(SYSTEM_MSG, USER_PROMPT)
        assert backend._cb.current_state == "closed"


# ---------------------------------------------------------------------------
# Copilot backend
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestCopilotEndpoint:
    """E2E tests for the GitHub Copilot SDK backend."""

    @pytest.fixture(autouse=True)
    def _skip_if_unconfigured(self, settings: "Settings") -> None:
        import shutil
        import subprocess

        if not settings.GITHUB_TOKEN:
            pytest.skip("Copilot backend not configured (missing GITHUB_TOKEN).")

        # Resolve the full path (SDK uses os.path.exists, not PATH lookup).
        cli_path = shutil.which(settings.COPILOT_CLI_PATH)
        if not cli_path:
            pytest.skip(
                f"Copilot CLI binary '{settings.COPILOT_CLI_PATH}' not found on PATH. "
                "Install it with: gh extension install github/gh-copilot"
            )

        # Detect the VS Code Copilot Chat stub (a shell script placed on PATH by
        # the VS Code extension). It exits immediately with code 0 and prints
        # "Cannot find GitHub Copilot CLI" — it is NOT the real CLI agent.
        # We detect it either by its well-known path pattern or by its content.
        vscode_stub_markers = (
            "globalStorage/github.copilot-chat",
            "copilotCli",
        )
        if any(marker in cli_path for marker in vscode_stub_markers):
            pytest.skip(
                f"Copilot CLI at '{cli_path}' is the VS Code Copilot Chat stub, "
                "not the real GitHub Copilot CLI agent. "
                "Install the real CLI with: gh extension install github/gh-copilot"
            )

        # Final sanity check: probe with a quick timeout via --version.
        try:
            probe = subprocess.run(
                [cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            combined = (probe.stdout + probe.stderr).lower()
            if "cannot find" in combined or "not found" in combined:
                pytest.skip(
                    f"Copilot CLI at '{cli_path}' reported it cannot find the "
                    "GitHub Copilot CLI agent."
                )
        except subprocess.TimeoutExpired:
            pass  # Real CLI server blocks on stdin — that's fine.
        except OSError as exc:
            pytest.skip(f"Could not execute Copilot CLI at '{cli_path}': {exc}")

    def test_simple_call_returns_response(self, settings: "Settings") -> None:
        """Call the Copilot SDK and verify a coherent response is returned."""
        from agent_triage.llm_client import CopilotBackend

        backend = CopilotBackend(settings)
        print(f"\n[Copilot] model  : {settings.COPILOT_MODEL}")
        print(f"[Copilot] cli    : {settings.COPILOT_CLI_PATH}")

        start = time.perf_counter()
        response = backend.generate(SYSTEM_MSG, USER_PROMPT)
        elapsed = time.perf_counter() - start

        print(f"[Copilot] duration : {elapsed:.2f}s")
        print(f"[Copilot] length   : {len(response)} chars")
        print(f"[Copilot] response :\n{'-' * 60}\n{response}\n{'-' * 60}")

        _assert_valid_response(response, "Copilot")

    def test_circuit_breaker_starts_closed(self, settings: "Settings") -> None:
        """The circuit breaker must start in CLOSED state on a fresh backend instance."""
        from agent_triage.llm_client import CopilotBackend

        backend = CopilotBackend(settings)
        assert backend._cb.current_state == "closed", (
            f"Expected circuit to start CLOSED, got: {backend._cb.current_state}"
        )
        backend.generate(SYSTEM_MSG, USER_PROMPT)
        assert backend._cb.current_state == "closed"


# ---------------------------------------------------------------------------
# LLMClient facade (primary → fallback flow)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestLLMClientFacade:
    """E2E tests for the LLMClient primary→fallback chain."""

    def test_facade_returns_response(self, settings: "Settings") -> None:
        """LLMClient.generate() must succeed using whichever backend is available."""
        from agent_triage.llm_client import LLMClient

        if not settings.CHATGPT_API_URL and not settings.GITHUB_TOKEN:
            pytest.skip("No LLM backend configured.")

        client = LLMClient(settings)

        start = time.perf_counter()
        response = client.generate(SYSTEM_MSG, USER_PROMPT)
        elapsed = time.perf_counter() - start

        print(f"\n[LLMClient] duration : {elapsed:.2f}s")
        print(f"[LLMClient] length   : {len(response)} chars")
        print(f"[LLMClient] response :\n{'-' * 60}\n{response}\n{'-' * 60}")

        _assert_valid_response(response, "LLMClient")
