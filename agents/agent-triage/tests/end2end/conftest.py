"""Pytest configuration for end-to-end tests.

Loads the project .env file and exposes a session-scoped ``settings`` fixture.
Loads the project .env.test file and exposes a session-scoped ``test_hints``
fixture containing server / SSH hint values used in error messages.
The entire e2e suite is skipped when the .env file is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# .env / .env.test are two directory levels above this file:
#   tests/end2end/conftest.py  →  ../../  →  agents/agent-triage/
_ENV_FILE = Path(__file__).parents[2] / ".env"
_TEST_ENV_FILE = Path(__file__).parents[2] / ".env.test"


@pytest.fixture(scope="session")
def settings():
    """Return a Settings instance loaded from the project .env file.

    Skips the entire session if the file is absent or required fields are missing.
    """
    if not _ENV_FILE.exists():
        pytest.skip(f".env file not found at {_ENV_FILE} — skipping all e2e tests.")

    try:
        # Pass the explicit env file path to override the default relative lookup.
        from agent_triage.config import Settings
        return Settings(_env_file=str(_ENV_FILE))
    except Exception as exc:
        pytest.skip(f"Could not load settings from {_ENV_FILE}: {exc}")


@pytest.fixture(scope="session")
def test_hints() -> dict[str, Any]:
    """Return hint values (server name, SSH user, etc.) loaded from .env.test.

    These are used only in pytest.fail / error messages to avoid hardcoding
    infrastructure details in the test source code.
    Falls back to generic placeholder strings when .env.test is absent.
    """
    defaults: dict[str, Any] = {
        "MAIL_HOST": "<mail-host>",
        "SSH_USER": "<ssh-user>",
        "VPS_HOST": "<vps-host>",
        "S3_ENDPOINT_URL": "<s3-endpoint-url>",
    }
    if not _TEST_ENV_FILE.exists():
        return defaults
    try:
        from dotenv import dotenv_values
        loaded = dotenv_values(str(_TEST_ENV_FILE))
        defaults.update({k: v for k, v in loaded.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    return defaults
