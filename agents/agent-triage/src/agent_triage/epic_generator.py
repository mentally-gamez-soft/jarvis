"""Epic generator for agent-triage.

Translates raw email requirements into — or updates — a structured Markdown
epic, using the :class:`~agent_triage.llm_client.LLMClient` facade which
tries ChatGPT first and falls back to the GitHub Copilot SDK.

The system message is derived from the rules defined in
``rules/challenge-requirements.md`` and ``rules/email-format.md`` (both
located inside the ``agent-triage`` directory), plus any project-specific
extension rules provided via email attachment or previously stored in S3.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Optional

from .config import Settings
from .llm_client import LLMClient
from .logger import get_logger

log = get_logger(__name__)

# Path to the base challenge-requirements rules file (relative to agent-triage root).
_RULES_PATH = Path(__file__).parents[2] / "rules" / "challenge-requirements.md"

# Path to the email-format rules file (relative to agent-triage root).
_EMAIL_FORMAT_RULES_PATH = Path(__file__).parents[2] / "rules" / "email-format.md"


def _load_base_rules() -> str:
    """Load the base triage rules from the rules file, or return a fallback."""
    if _RULES_PATH.exists():
        return _RULES_PATH.read_text(encoding="utf-8")
    log.warning("rules.file_not_found", path=str(_RULES_PATH))
    return (
        "You are a senior product owner. Translate the provided requirements "
        "into a well-structured Markdown epic document."
    )


def _load_email_format_rules() -> str:
    """Load the email-format rules file, or return an empty string."""
    if _EMAIL_FORMAT_RULES_PATH.exists():
        return _EMAIL_FORMAT_RULES_PATH.read_text(encoding="utf-8")
    log.warning("rules.email_format_file_not_found", path=str(_EMAIL_FORMAT_RULES_PATH))
    return ""


def _build_system_message(extension_rules: Optional[str] = None) -> str:
    """Compose the system message for the Copilot session.

    Combines the base challenge-requirements rules with the email-format rules,
    then appends any project-specific extension rules when provided.

    Args:
        extension_rules: Optional project-specific rules that override / extend
                         the base rules.

    Returns:
        A single string used as the system prompt.
    """
    base = _load_base_rules()
    email_format = _load_email_format_rules()

    parts = [base]
    if email_format:
        parts.append(
            "## Email Format Rules\n\n"
            "The following rules define the structured email format that was "
            "used to send the requirements. Use them to correctly interpret "
            "each section of the incoming email:\n\n"
            f"{email_format}"
        )
    if extension_rules:
        parts.append(
            "## Project-Specific Extension Rules\n\n"
            "The following project-specific rules take precedence over the "
            "general rules above:\n\n"
            f"{extension_rules}"
        )
    return "\n\n".join(parts)


def _build_creation_prompt(
    project_name: str,
    body: str,
    title: Optional[str] = None,
    idea: Optional[str] = None,
    envs: Optional[str] = None,
    directives: Optional[str] = None,
) -> str:
    """Build the user prompt for *creating* a new epic.

    When structured body fields (title, idea, envs, directives) are provided
    they are presented as labelled sections.  The raw body is always appended
    as a fallback reference so that no information is lost.
    """
    sections: list[str] = []

    if title:
        sections.append(f"### Project Title\n\n{title}")

    if idea:
        sections.append(f"### Idea / Concept\n\n{idea}")
    else:
        sections.append(f"### Requirements\n\n{body}")

    if envs:
        sections.append(
            "### Environment Variables\n\n"
            "Translate these into a `.env`-equivalent section in the epic "
            "(the agent-scrum-master will later generate the actual `.env` file):\n\n"
            f"{envs}"
        )

    if directives:
        sections.append(
            "### Technical Directives\n\n"
            "These instructions must be reflected in the epic's technical sections "
            "(dependencies, frameworks, architectural patterns, coding standards, "
            "tools, etc.):\n\n"
            f"{directives}"
        )

    structured_block = "\n\n".join(sections)

    return textwrap.dedent(f"""
        # Requirements email for project: {project_name}

        {structured_block}

        ---

        Please analyse the requirements above and produce a comprehensive,
        well-structured Markdown epic document for the development team.

        The epic must include at minimum:
        - Project title and executive summary
        - Goals and success criteria
        - Key features / functional requirements
        - Non-functional requirements (performance, security, scalability)
        - Environment variables section (if [envs] was provided)
        - Technical stack and directives section (if [directives] was provided)
        - Out-of-scope items
        - Open questions / assumptions
        - A Mermaid architecture or flow diagram if appropriate

        Use proper Markdown headings (##, ###), bullet lists, and tables
        where they improve readability.
    """).strip()


def _build_update_prompt(
    project_name: str,
    existing_epic: str,
    new_requirements: str,
    title: Optional[str] = None,
    idea: Optional[str] = None,
    envs: Optional[str] = None,
    directives: Optional[str] = None,
) -> str:
    """Build the user prompt for *updating* an existing epic."""
    # Build the new-requirements block using structured fields when available.
    new_sections: list[str] = []
    if title:
        new_sections.append(f"### Project Title\n\n{title}")
    if idea:
        new_sections.append(f"### Idea / Concept Update\n\n{idea}")
    else:
        new_sections.append(f"### New Requirements\n\n{new_requirements}")
    if envs:
        new_sections.append(f"### Environment Variables\n\n{envs}")
    if directives:
        new_sections.append(f"### Technical Directives\n\n{directives}")

    new_block = "\n\n".join(new_sections) if new_sections else new_requirements

    return textwrap.dedent(f"""
        # Update request for project: {project_name}

        ## Existing epic

        {existing_epic}

        ---

        ## New requirements / changes received via email

        {new_block}

        ---

        Please merge the new requirements into the existing epic.
        - Preserve all existing content that is not superseded.
        - Add new sections or extend existing ones as needed.
        - Update the "Last Updated" date at the top.
        - If requirements conflict with existing content, prefer the new ones
          and add a note explaining what changed.
        - Return the *complete* updated epic as a Markdown document.
    """).strip()


class EpicGenerator:
    """Orchestrates epic creation and updates via the LLM client.

    Uses :class:`~agent_triage.llm_client.LLMClient` which calls ChatGPT
    first and falls back to the GitHub Copilot SDK automatically.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = LLMClient(settings)

    def generate(
        self,
        project_name: str,
        requirements_body: str,
        existing_epic: Optional[str] = None,
        extension_rules: Optional[str] = None,
        title: Optional[str] = None,
        idea: Optional[str] = None,
        envs: Optional[str] = None,
        directives: Optional[str] = None,
    ) -> str:
        """Generate or update an epic; returns the complete Markdown string.

        Args:
            project_name:       Human-readable project name.
            requirements_body:  Raw requirements text (full email body).
            existing_epic:      The current epic content from S3, if any.
            extension_rules:    Project-specific rule overrides, if any.
            title:              Parsed ``[title]`` tag content, if present.
            idea:               Parsed ``[idea]`` tag content, if present.
            envs:               Parsed ``[envs]`` tag content, if present.
            directives:         Parsed ``[directives]`` tag content, if present.

        Returns:
            A complete Markdown epic document as a string.
        """
        system_msg = _build_system_message(extension_rules)

        if existing_epic:
            user_prompt = _build_update_prompt(
                project_name,
                existing_epic,
                requirements_body,
                title=title,
                idea=idea,
                envs=envs,
                directives=directives,
            )
            log.info(
                "epic.updating",
                project=project_name,
                existing_length=len(existing_epic),
                new_requirements_length=len(requirements_body),
            )
        else:
            user_prompt = _build_creation_prompt(
                project_name,
                requirements_body,
                title=title,
                idea=idea,
                envs=envs,
                directives=directives,
            )
            log.info(
                "epic.creating",
                project=project_name,
                requirements_length=len(requirements_body),
            )

        return self._llm.generate(system_msg, user_prompt)
