"""LLM client with circuit breaker and retry for agent-triage.

Architecture
------------
Two independent backends are available:

1. **ChatGPT** (primary) — calls any OpenAI-compatible ``/chat/completions``
   endpoint via ``httpx``.  Configured via ``CHATGPT_API_URL`` / ``CHATGPT_API_KEY``.

2. **GitHub Copilot SDK** (fallback) — spawns the Copilot CLI and communicates
   via JSON-RPC.  Configured via ``GITHUB_TOKEN`` / ``COPILOT_MODEL``.

Each backend is protected by two layers:

* **tenacity retry** — retries the raw call on transient errors (network
  timeouts, 5xx responses) with exponential back-off.  4xx errors and
  ``CircuitBreakerError`` are *not* retried.

* **pybreaker circuit breaker** — wraps the tenacity-retried call.  After
  ``CB_FAIL_MAX`` consecutive exhausted-retry sequences, the circuit opens
  and subsequent calls are rejected immediately without touching the network.
  After ``CB_RESET_TIMEOUT`` seconds the circuit moves to HALF-OPEN and allows
  one probe call through.

Fallback flow
-------------
::

    LLMClient.generate()
        ├─ ChatGPT backend  (tenacity → pybreaker)
        │      success → return response
        │      CircuitBreakerError / all retries exhausted → log warning
        └─ Copilot fallback (tenacity → pybreaker)
               success → return response
               CircuitBreakerError / all retries exhausted → raise RuntimeError
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx
import pybreaker
from tenacity import (
    RetryError,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings
from .logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared circuit-breaker listener (logs state transitions)
# ---------------------------------------------------------------------------

class _CBListener(pybreaker.CircuitBreakerListener):
    def __init__(self, name: str) -> None:
        self._name = name

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: pybreaker.CircuitBreakerState,
        new_state: pybreaker.CircuitBreakerState,
    ) -> None:
        log.warning(
            "circuit_breaker.state_change",
            backend=self._name,
            old=str(old_state.name),
            new=str(new_state.name),
        )

    def failure(self, cb: pybreaker.CircuitBreaker, exc: Exception) -> None:
        log.warning(
            "circuit_breaker.failure",
            backend=self._name,
            fail_count=cb.fail_counter,
            fail_max=cb.fail_max,
            error=str(exc),
        )

    def success(self, cb: pybreaker.CircuitBreaker) -> None:
        log.debug("circuit_breaker.success", backend=self._name)


# ---------------------------------------------------------------------------
# ChatGPT backend
# ---------------------------------------------------------------------------

class ChatGPTBackend:
    """Calls an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cb = pybreaker.CircuitBreaker(
            fail_max=settings.CB_FAIL_MAX,
            reset_timeout=settings.CB_RESET_TIMEOUT,
            listeners=[_CBListener("chatgpt")],
            name="chatgpt",
        )

    @property
    def is_configured(self) -> bool:
        """Return True if API URL and key are set."""
        return bool(self._settings.CHATGPT_API_URL and self._settings.CHATGPT_API_KEY)

    def generate(self, system_message: str, user_prompt: str) -> str:
        """Call the ChatGPT endpoint; raises on failure."""
        if not self.is_configured:
            raise RuntimeError("ChatGPT backend is not configured (missing URL or key).")

        # Inner function with tenacity retry applied.
        @retry(
            stop=stop_after_attempt(self._settings.CB_RETRY_ATTEMPTS),
            wait=wait_exponential(
                min=self._settings.CB_RETRY_WAIT_MIN,
                max=self._settings.CB_RETRY_WAIT_MAX,
            ),
            # Do not retry on auth errors (4xx) or open circuit.
            retry=retry_if_not_exception_type(
                (pybreaker.CircuitBreakerError, ValueError)
            ),
            reraise=True,
        )
        def _call_with_retry() -> str:
            return self._http_call(system_message, user_prompt)

        # Circuit breaker wraps the tenacity-retried sequence.
        return self._cb.call(_call_with_retry)  # type: ignore[return-value]

    def _http_call(self, system_message: str, user_prompt: str) -> str:
        """Single synchronous HTTP POST to the chat completions endpoint."""
        cfg = self._settings
        headers = {
            "Content-Type": "application/json",
            "api-key": cfg.CHATGPT_API_KEY,
            # Also send as Bearer for non-Azure endpoints.
            "Authorization": f"Bearer {cfg.CHATGPT_API_KEY}",
        }
        payload = {
            "model": cfg.CHATGPT_MODEL,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt},
            ],
        }

        log.debug("chatgpt.request", url=cfg.CHATGPT_API_URL)
        with httpx.Client(timeout=cfg.CHATGPT_TIMEOUT) as client:
            response = client.post(cfg.CHATGPT_API_URL, headers=headers, json=payload)

        if response.status_code >= 500:
            # 5xx → transient, tenacity will retry.
            raise IOError(
                f"ChatGPT server error {response.status_code}: {response.text[:200]}"
            )
        if response.status_code >= 400:
            # 4xx → non-transient (wrong key, quota, etc.); do NOT retry.
            raise ValueError(
                f"ChatGPT client error {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        content: str = data["choices"][0]["message"]["content"]
        log.info(
            "chatgpt.response_received",
            response_length=len(content),
            model=data.get("model", cfg.CHATGPT_MODEL),
        )
        return content


# ---------------------------------------------------------------------------
# Copilot fallback backend
# ---------------------------------------------------------------------------

class CopilotBackend:
    """Calls the GitHub Copilot SDK via the CLI process."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cb = pybreaker.CircuitBreaker(
            fail_max=settings.CB_FAIL_MAX,
            reset_timeout=settings.CB_RESET_TIMEOUT,
            listeners=[_CBListener("copilot")],
            name="copilot",
        )

    @property
    def is_configured(self) -> bool:
        """Return True if a GitHub token is set."""
        return bool(self._settings.GITHUB_TOKEN)

    def generate(self, system_message: str, user_prompt: str) -> str:
        """Call Copilot SDK; raises on failure."""
        if not self.is_configured:
            raise RuntimeError("Copilot backend is not configured (missing GITHUB_TOKEN).")

        @retry(
            stop=stop_after_attempt(self._settings.CB_RETRY_ATTEMPTS),
            wait=wait_exponential(
                min=self._settings.CB_RETRY_WAIT_MIN,
                max=self._settings.CB_RETRY_WAIT_MAX,
            ),
            retry=retry_if_not_exception_type(pybreaker.CircuitBreakerError),
            reraise=True,
        )
        def _call_with_retry() -> str:
            return asyncio.run(
                _run_copilot_session(self._settings, system_message, user_prompt)
            )

        return self._cb.call(_call_with_retry)  # type: ignore[return-value]


async def _run_copilot_session(
    settings: Settings,
    system_message_content: str,
    user_prompt: str,
) -> str:
    """Open a Copilot SDK session, send the prompt, and return the response."""
    import shutil

    from copilot import CopilotClient  # type: ignore[import]

    # The Copilot SDK uses os.path.exists() which requires an absolute path.
    # Resolve the binary through PATH first; fall back to the raw value so that
    # already-absolute paths (e.g. /usr/local/bin/copilot) still work.
    cli_path = shutil.which(settings.COPILOT_CLI_PATH) or settings.COPILOT_CLI_PATH

    client = CopilotClient(
        {
            "cli_path": cli_path,
            "github_token": settings.GITHUB_TOKEN,
            "log_level": "warning",
        }
    )
    await client.start()

    session = await client.create_session(
        {
            "model": settings.COPILOT_MODEL,
            "system_message": {"content": system_message_content},
            "streaming": False,
        }
    )

    response_event = await session.send_and_wait({"prompt": user_prompt}, timeout=120.0)

    await session.destroy()
    await client.stop()

    response_text: str = ""
    if response_event is not None:
        response_text = getattr(response_event.data, "content", "") or ""

    if not response_text:
        raise RuntimeError("Copilot SDK returned an empty response.")

    log.info("copilot.response_received", response_length=len(response_text))
    return response_text


# ---------------------------------------------------------------------------
# LLMClient facade
# ---------------------------------------------------------------------------

class LLMClient:
    """Facade that tries ChatGPT first and falls back to Copilot SDK.

    Both backends are independently protected by a circuit breaker and
    tenacity retries.  The circuit breakers are instance-level, so they
    preserve state across multiple ``.generate()`` calls within the same
    cron run — preventing repeated hammering of a dead endpoint for each
    email in a batch.
    """

    def __init__(self, settings: Settings) -> None:
        self._chatgpt = ChatGPTBackend(settings)
        self._copilot = CopilotBackend(settings)

    def generate(self, system_message: str, user_prompt: str) -> str:
        """Generate a response, trying ChatGPT first then Copilot as fallback.

        Raises:
            RuntimeError: if both backends fail or are unconfigured.
        """
        # --- Primary: ChatGPT ---
        if self._chatgpt.is_configured:
            try:
                result = self._chatgpt.generate(system_message, user_prompt)
                log.info("llm.backend_used", backend="chatgpt")
                return result
            except pybreaker.CircuitBreakerError:
                log.warning(
                    "llm.chatgpt_circuit_open",
                    reason="circuit open — falling back to Copilot",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "llm.chatgpt_failed",
                    error=str(exc),
                    reason="falling back to Copilot",
                )
        else:
            log.info("llm.chatgpt_skipped", reason="not configured")

        # --- Fallback: Copilot SDK ---
        if self._copilot.is_configured:
            try:
                result = self._copilot.generate(system_message, user_prompt)
                log.info("llm.backend_used", backend="copilot")
                return result
            except pybreaker.CircuitBreakerError as exc:
                raise RuntimeError(
                    "Both LLM backends are unavailable: "
                    "ChatGPT failed or unconfigured, Copilot circuit is open."
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Both LLM backends failed. Copilot error: {exc}"
                ) from exc
        else:
            raise RuntimeError(
                "Both LLM backends are unconfigured. "
                "Set CHATGPT_API_URL+CHATGPT_API_KEY or GITHUB_TOKEN."
            )
