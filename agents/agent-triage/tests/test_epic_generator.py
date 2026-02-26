"""Unit tests for agent_triage.epic_generator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_triage.epic_generator import (
    EpicGenerator,
    _build_creation_prompt,
    _build_update_prompt,
    _build_system_message,
    _load_email_format_rules,
)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

class TestBuildSystemMessage:
    def test_no_extension_rules_returns_base_and_format_rules(self):
        with patch("agent_triage.epic_generator._load_base_rules", return_value="BASE"), \
             patch("agent_triage.epic_generator._load_email_format_rules", return_value="FORMAT"):
            msg = _build_system_message()
        assert "BASE" in msg
        assert "FORMAT" in msg

    def test_no_extension_rules_omits_format_section_when_empty(self):
        with patch("agent_triage.epic_generator._load_base_rules", return_value="BASE"), \
             patch("agent_triage.epic_generator._load_email_format_rules", return_value=""):
            msg = _build_system_message()
        assert msg == "BASE"

    def test_with_extension_rules_appended(self):
        with patch("agent_triage.epic_generator._load_base_rules", return_value="BASE"), \
             patch("agent_triage.epic_generator._load_email_format_rules", return_value=""):
            msg = _build_system_message("EXTENSION")
        assert "BASE" in msg
        assert "EXTENSION" in msg
        assert "Project-Specific Extension Rules" in msg

    def test_email_format_section_header_present(self):
        with patch("agent_triage.epic_generator._load_base_rules", return_value="BASE"), \
             patch("agent_triage.epic_generator._load_email_format_rules", return_value="FORMAT"):
            msg = _build_system_message()
        assert "Email Format Rules" in msg


class TestBuildCreationPrompt:
    def test_contains_project_name_and_body_fallback(self):
        prompt = _build_creation_prompt("Image Displayer", "Show images in a grid.")
        assert "Image Displayer" in prompt
        assert "Show images in a grid." in prompt

    def test_contains_epic_instructions(self):
        prompt = _build_creation_prompt("Proj", "Req.")
        assert "Goals and success criteria" in prompt

    def test_structured_title_and_idea(self):
        prompt = _build_creation_prompt(
            "Phoenix", "raw body",
            title="Project Phoenix",
            idea="A fitness tracking app.",
        )
        assert "Project Phoenix" in prompt
        assert "A fitness tracking app." in prompt
        assert "Project Title" in prompt
        assert "Idea / Concept" in prompt

    def test_envs_section_included(self):
        prompt = _build_creation_prompt(
            "Phoenix", "raw",
            idea="Some idea.",
            envs="DATABASE_URL: db connection",
        )
        assert "DATABASE_URL" in prompt
        assert "Environment Variables" in prompt

    def test_directives_section_included(self):
        prompt = _build_creation_prompt(
            "Phoenix", "raw",
            idea="Some idea.",
            directives="- Use Django MVT pattern",
        )
        assert "Django" in prompt
        assert "Technical Directives" in prompt

    def test_optional_sections_absent_when_not_provided(self):
        prompt = _build_creation_prompt("Proj", "raw body")
        assert "Environment Variables" not in prompt
        assert "Technical Directives" not in prompt


class TestBuildUpdatePrompt:
    def test_contains_all_parts(self):
        prompt = _build_update_prompt("Proj", "# Existing", "New feature request.")
        assert "# Existing" in prompt
        assert "New feature request." in prompt
        assert "merge" in prompt.lower()

    def test_structured_fields_in_update_prompt(self):
        prompt = _build_update_prompt(
            "Proj", "# Existing", "raw body",
            title="New Title",
            idea="Updated concept.",
            envs="SECRET_KEY: app secret",
            directives="- Use FastAPI",
        )
        assert "New Title" in prompt
        assert "Updated concept." in prompt
        assert "SECRET_KEY" in prompt
        assert "FastAPI" in prompt


# ---------------------------------------------------------------------------
# EpicGenerator.generate — LLMClient is mocked
# ---------------------------------------------------------------------------

def _make_settings():
    s = MagicMock()
    s.GITHUB_TOKEN = "gh_token"
    s.COPILOT_MODEL = "gpt-4o"
    s.COPILOT_CLI_PATH = "copilot"
    s.CHATGPT_API_KEY = "key"
    s.CHATGPT_API_URL = "http://api.example.com/chat"
    s.CHATGPT_MODEL = "gpt-4o-mini"
    s.CHATGPT_TIMEOUT = 30.0
    s.CB_FAIL_MAX = 3
    s.CB_RESET_TIMEOUT = 60
    s.CB_RETRY_ATTEMPTS = 2
    s.CB_RETRY_WAIT_MIN = 0.1
    s.CB_RETRY_WAIT_MAX = 1.0
    return s


class TestEpicGeneratorGenerate:
    def test_generate_delegates_to_llm_client(self):
        settings = _make_settings()
        with patch("agent_triage.epic_generator.LLMClient") as MockLLM, \
             patch("agent_triage.epic_generator._load_base_rules", return_value="BASE"), \
             patch("agent_triage.epic_generator._load_email_format_rules", return_value=""):
            mock_llm_instance = MockLLM.return_value
            mock_llm_instance.generate.return_value = "# Epic\nGenerated content"

            generator = EpicGenerator(settings)
            result = generator.generate(
                project_name="Image Displayer",
                requirements_body="Show images in a grid.",
            )

        mock_llm_instance.generate.assert_called_once()
        assert result == "# Epic\nGenerated content"

    def test_generate_delegates_to_llm_client_with_structured_fields(self):
        settings = _make_settings()
        with patch("agent_triage.epic_generator.LLMClient") as MockLLM, \
             patch("agent_triage.epic_generator._load_base_rules", return_value="BASE"), \
             patch("agent_triage.epic_generator._load_email_format_rules", return_value=""):
            mock_llm_instance = MockLLM.return_value
            mock_llm_instance.generate.return_value = "# Epic"

            generator = EpicGenerator(settings)
            result = generator.generate(
                project_name="Phoenix",
                requirements_body="raw body",
                title="Project Phoenix",
                idea="A fitness app.",
                envs="DATABASE_URL: conn",
                directives="- Use Django",
            )

        mock_llm_instance.generate.assert_called_once()
        call_args = mock_llm_instance.generate.call_args
        user_prompt = call_args[0][1]  # second positional arg
        assert "Project Phoenix" in user_prompt
        assert "fitness app" in user_prompt
        assert "DATABASE_URL" in user_prompt
        assert "Django" in user_prompt

    def test_generate_uses_update_prompt_when_existing_epic(self):
        settings = _make_settings()
        captured: list[str] = []

        with patch("agent_triage.epic_generator.LLMClient") as MockLLM, \
             patch("agent_triage.epic_generator._load_base_rules", return_value="BASE"), \
             patch("agent_triage.epic_generator._load_email_format_rules", return_value=""):
            def capture(system_msg, user_prompt):
                captured.append(user_prompt)
                return "# Updated Epic"

            MockLLM.return_value.generate.side_effect = capture

            generator = EpicGenerator(settings)
            result = generator.generate(
                project_name="proj",
                requirements_body="New feature.",
                existing_epic="# Old Epic",
            )

        assert "# Old Epic" in captured[0]
        assert "New feature." in captured[0]
        assert result == "# Updated Epic"

    def test_extension_rules_included_in_system_message(self):
        settings = _make_settings()
        captured_system: list[str] = []

        with patch("agent_triage.epic_generator.LLMClient") as MockLLM, \
             patch("agent_triage.epic_generator._load_base_rules", return_value="BASE"), \
             patch("agent_triage.epic_generator._load_email_format_rules", return_value=""):
            def capture(system_msg, user_prompt):
                captured_system.append(system_msg)
                return "# Epic"

            MockLLM.return_value.generate.side_effect = capture

            generator = EpicGenerator(settings)
            generator.generate(
                project_name="proj",
                requirements_body="Req.",
                extension_rules="# Custom rule",
            )

        assert "# Custom rule" in captured_system[0]

