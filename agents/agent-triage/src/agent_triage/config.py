"""Configuration management for agent-triage.

All settings are loaded from environment variables (or a .env file).
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings for the agent-triage agent."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # ---------------------------------------------------------------------------
    # Email / IMAP
    # ---------------------------------------------------------------------------
    IMAP_HOST: str
    """Hostname or IP of the containerised IMAP server."""

    IMAP_PORT: int = 993
    """IMAP port. 993 = IMAPS (TLS), 143 = plain IMAP."""

    IMAP_USE_SSL: bool = True
    """Whether to connect using SSL/TLS."""

    IMAP_USERNAME: str
    """Mailbox username (e.g. agent-copilot@yourdomain.com). Set via IMAP_USERNAME in .env."""

    IMAP_PASSWORD: str
    """Mailbox password."""

    IMAP_MAILBOX: str = "INBOX"
    """Mailbox / folder to poll."""

    EMAIL_SUBJECT_PREFIX: str = "[JARVIS]-"
    """Only emails whose subject starts with this prefix are processed."""

    # ---------------------------------------------------------------------------
    # MinIO / S3
    # ---------------------------------------------------------------------------
    S3_ENDPOINT_URL: str
    """MinIO endpoint, e.g. http://minio:9000"""

    S3_ACCESS_KEY: str
    """MinIO access key (equivalent to AWS_ACCESS_KEY_ID)."""

    S3_SECRET_KEY: str
    """MinIO secret key (equivalent to AWS_SECRET_ACCESS_KEY)."""

    S3_REGION: str = "us-east-1"
    """Region name — MinIO accepts any string here."""

    S3_BUCKET_TEMPLATE: str = "jarvis-{project_slug}"
    """
    Template for bucket names. {project_slug} is replaced with the slugified
    project name extracted from the email subject.
    Example: jarvis-image-displayer
    """

    # ---------------------------------------------------------------------------
    # ChatGPT / OpenAI-compatible API  (primary LLM backend)
    # ---------------------------------------------------------------------------
    CHATGPT_API_KEY: str = ""
    """API key for the OpenAI-compatible endpoint (primary backend)."""

    CHATGPT_API_URL: str = ""
    """
    Full URL of the OpenAI-compatible chat completions endpoint.
    Example: https://api.openai.com/v1/chat/completions
    Or a custom deployment:
        https://cld.example.com/api/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01-preview
    Leave empty to skip ChatGPT and go straight to the Copilot fallback.
    """

    CHATGPT_MODEL: str = "gpt-4o-mini"
    """
    Model name sent in the ChatGPT request body.
    Ignored when the deployment URL already encodes the model (Azure-style).
    """

    CHATGPT_TIMEOUT: float = 120.0
    """HTTP timeout in seconds for each ChatGPT API call."""

    # ---------------------------------------------------------------------------
    # GitHub Copilot SDK  (fallback LLM backend)
    # ---------------------------------------------------------------------------
    GITHUB_TOKEN: str = ""
    """Personal access token with GitHub Copilot access (fallback backend)."""

    COPILOT_MODEL: str = "gpt-4o"
    """Model identifier forwarded to the Copilot SDK session."""

    COPILOT_CLI_PATH: str = "copilot"
    """Path to the GitHub Copilot CLI binary inside the container."""

    # ---------------------------------------------------------------------------
    # Email / SMTP  (outgoing mail)
    # ---------------------------------------------------------------------------
    SMTP_HOST: str = ""
    """Hostname or IP of the SMTP server. Defaults to IMAP_HOST when empty."""

    SMTP_PORT: int = 587
    """SMTP port. 587 = STARTTLS, 465 = SMTPS (implicit TLS)."""

    SMTP_USE_SSL: bool = False
    """True → implicit TLS (port 465). False → STARTTLS (port 587)."""

    SMTP_USERNAME: str = ""
    """SMTP login username. Defaults to IMAP_USERNAME when empty."""

    SMTP_PASSWORD: str = ""
    """SMTP login password. Defaults to IMAP_PASSWORD when empty."""

    @property
    def smtp_host(self) -> str:  # noqa: D401
        """Effective SMTP host (falls back to IMAP_HOST)."""
        return self.SMTP_HOST or self.IMAP_HOST

    @property
    def smtp_username(self) -> str:
        """Effective SMTP username (falls back to IMAP_USERNAME)."""
        return self.SMTP_USERNAME or self.IMAP_USERNAME

    @property
    def smtp_password(self) -> str:
        """Effective SMTP password (falls back to IMAP_PASSWORD)."""
        return self.SMTP_PASSWORD or self.IMAP_PASSWORD

    # ---------------------------------------------------------------------------
    # Circuit breaker & retry  (applies to both LLM backends independently)
    # ---------------------------------------------------------------------------
    CB_FAIL_MAX: int = 3
    """
    Number of consecutive failures before a backend's circuit opens.
    While open, calls are rejected immediately without hitting the endpoint.
    """

    CB_RESET_TIMEOUT: int = 60
    """Seconds to wait before the circuit moves from OPEN to HALF-OPEN."""

    CB_RETRY_ATTEMPTS: int = 3
    """Maximum number of tenacity retry attempts per LLM call."""

    CB_RETRY_WAIT_MIN: float = 1.0
    """Minimum seconds to wait between retry attempts (exponential backoff)."""

    CB_RETRY_WAIT_MAX: float = 30.0
    """Maximum seconds to wait between retry attempts."""

    # ---------------------------------------------------------------------------
    # Scheduling
    # ---------------------------------------------------------------------------
    POLL_INTERVAL_MINUTES: int = 10
    """How often (in minutes) the cron job runs the agent."""

    # ---------------------------------------------------------------------------
    # Logging
    # ---------------------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    """Log level for the application logger (DEBUG, INFO, WARNING, ERROR)."""

    S3_LOG_PREFIX: str = "logs"
    """Prefix (folder) inside the project bucket where log files are stored."""

    @field_validator("POLL_INTERVAL_MINUTES")
    @classmethod
    def poll_interval_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("POLL_INTERVAL_MINUTES must be a positive integer")
        return v

    # ---------------------------------------------------------------------------
    # MinIO bucket notifications (S3 event → agent-scrum-master webhook)
    # ---------------------------------------------------------------------------
    S3_NOTIFICATION_WEBHOOK_URL: str = ""
    """
    If set, agent-triage will automatically register a MinIO bucket notification
    on every newly created project bucket so that agent-scrum-master is triggered
    via webhook whenever an epic object is written under ``epics/``.

    Set this to the full URL of agent-scrum-master's webhook endpoint, e.g.:
        http://agent-scrum-master:8080/webhooks/minio
    Leave empty to skip automatic notification registration.
    """

    S3_NOTIFICATION_QUEUE_ARN: str = "arn:minio:sqs::WEBHOOK:webhook"
    """
    MinIO ARN for the webhook notification target.
    Must match the target configured in MinIO's environment
    (MINIO_NOTIFY_WEBHOOK_ENABLE_WEBHOOK=on, etc.).
    """

    @field_validator("S3_ENDPOINT_URL")
    @classmethod
    def endpoint_must_have_scheme(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("S3_ENDPOINT_URL must start with http:// or https://")
        return v


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()  # type: ignore[call-arg]
