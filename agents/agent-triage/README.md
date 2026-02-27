# agent-triage

> Part of the **Jarvis** multi-agent project.

`agent-triage` polls a designated mailbox for emails tagged `[JARVIS]-[<project-title>]`,
uses the **GitHub Copilot SDK** or **OpenAI ChatGPT API** to translate the requirements into a structured Markdown
epic, and stores the result in a per-project **MinIO S3** bucket. If an epic already
exists for that project it is updated (merged) rather than replaced.

---

## Table of Contents

- [Architecture overview](#architecture-overview)
- [Email format](#email-format)
- [Project structure](#project-structure)
- [Dependencies](#dependencies)
- [Environment variables](#environment-variables)
- [Running locally](#running-locally)
- [Running with Docker](#running-with-docker)
- [Tests](#tests)
- [MinIO bucket naming](#minio-bucket-naming)
- [S3 event notification (handoff to agent-scrum-master)](#s3-event-notification)
- [Extension rules](#extension-rules)
- [Logging](#logging)

---

## Architecture overview

```
 Mailbox                  agent-triage (cron / Docker)          MinIO S3
 ──────                   ────────────────────────────          ────────
 [JARVIS]-[proj] req  ──►  1. Poll IMAP every N minutes
                          2. Parse subject / body / attachments
                          3. Fetch existing epic from S3 (if any)
                          4. Call GitHub Copilot SDK to generate/update epic
                          5. Write epic ──────────────────────────────────► epics/<slug>_<date>.md
                          6. Write extension rules (if attached) ─────────► epics/project-extension-rules.md
                          7. Mark email as seen
                          8. Flush logs ───────────────────────────────────► logs/<date>/<ts>.log
                                                                                     │
                                                MinIO bucket notification ◄──────────┘
                                                          │
                                                          ▼
                                                agent-scrum-master (event-driven)
```

---

## Email format

Only emails **matching the following subject pattern** are processed:

```
[JARVIS]-[<PROJECT_TITLE>]
```

Examples:
- `[JARVIS]-[Project Phoenix]`
- `[JARVIS]-[Image Displayer]`

The **email body** must use structured tags:

| Tag | Required | Description |
|---|---|---|
| `[title]` | ✅ | Concise project title |
| `[idea]` | ✅ | Detailed description of concept, features and functionalities |
| `[envs]` | optional | Environment variables with descriptions (translated into `.env`-equivalent in the epic) |
| `[directives]` | optional | Technical instructions: dependencies, frameworks, coding standards, architectural patterns, tools |

### Example email

```
Subject: [JARVIS]-[Project Phoenix]

[title]
Project Phoenix
[idea]
Project Phoenix is a web application that allows users to track their fitness goals.
[envs]
DATABASE_URL: URL of the database
SECRET_KEY: secret key for session management
[directives]
- Use Django MVT architectural pattern
- Follow PEP 8 coding standards
- Containerise with Docker
```

An optional attachment named **`project-extension-rules.md`** may be included to
provide project-specific rules that extend or override the base triage rules (see
[Extension rules](#extension-rules)).

---

## Project structure

```
agents/agent-triage/
├── .env.example                 # Environment variable template
├── .gitignore
├── docker-compose.yaml          # Compose stack: agent-triage + MinIO
├── Dockerfile
├── README.md
├── requirements.in              # Direct dependencies (compile with uv)
├── requirements.txt             # Locked dependency graph (generated)
├── docker/
│   ├── crontab.template         # Cron schedule template
│   └── entrypoint.sh            # Container startup script
├── exceptions/
│   └── requirements-translation.md  # Documented rule deviations
├── src/
│   └── agent_triage/
│       ├── __init__.py
│       ├── config.py            # Pydantic-settings configuration
│       ├── email_client.py      # IMAP polling and email parsing
│       ├── epic_generator.py    # Copilot SDK integration
│       ├── logger.py            # Dual-destination logger (stdout + S3)
│       ├── main.py              # Cron entrypoint
│       └── s3_client.py         # MinIO / S3 operations
└── tests/
    ├── __init__.py
    ├── test_email_client.py
    ├── test_epic_generator.py
    └── test_s3_client.py
```

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `boto3` | latest | MinIO / S3 interaction |
| `pydantic-settings` | latest | Environment variable validation |
| `pydantic` | latest | Data models |
| `structlog` | latest | Structured JSON logging |
| `markdown` | latest | Markdown post-processing utilities |
| `copilot` (GitHub Copilot SDK) | `main` branch | LLM-powered epic generation via GitHub Copilot CLI |
| `pytest` | latest | Test runner |
| `pytest-cov` | latest | Coverage reports |
| `pytest-asyncio` | latest | Async test support |

> **Note — GitHub Copilot SDK:** installed directly from
> `https://github.com/github/copilot-sdk.git#subdirectory=python`.
> It is in _technical preview_ and requires the **GitHub Copilot CLI binary**
> to be present on `PATH` (installed in the Docker image via `gh extension install github/gh-copilot`).

### Compiling the lock file

```bash
uv pip compile requirements.in -o requirements.txt
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in all required values.

| Variable | Required | Default | Description |
|---|---|---|---|
| `IMAP_HOST` | ✅ | — | Hostname/IP of the containerised IMAP server |
| `IMAP_PORT` | | `993` | IMAP port (993 for IMAPS) |
| `IMAP_USE_SSL` | | `true` | Connect with SSL/TLS |
| `IMAP_USERNAME` | ✅ | — | Mailbox address (`email@agent-jarvis.com`) |
| `IMAP_PASSWORD` | ✅ | — | Mailbox password |
| `IMAP_MAILBOX` | | `INBOX` | Folder to poll |
| `EMAIL_SUBJECT_PREFIX` | | `[JARVIS]-` | Subject prefix filter |
| `S3_ENDPOINT_URL` | ✅ | — | MinIO endpoint, e.g. `http://minio:9000` |
| `S3_ACCESS_KEY` | ✅ | — | MinIO access key |
| `S3_SECRET_KEY` | ✅ | — | MinIO secret key |
| `S3_REGION` | | `us-east-1` | Region string (cosmetic for MinIO) |
| `S3_BUCKET_TEMPLATE` | | `jarvis-{project_slug}` | Bucket name pattern |
| `S3_LOG_PREFIX` | | `logs` | Folder for log objects inside bucket |
| `GITHUB_TOKEN` | ✅ | — | GitHub token with Copilot access |
| `COPILOT_MODEL` | | `gpt-4o` | Model for the Copilot SDK session |
| `COPILOT_CLI_PATH` | | `copilot` | Path to the Copilot CLI binary |
| `POLL_INTERVAL_MINUTES` | | `10` | Cron polling frequency |
| `LOG_LEVEL` | | `INFO` | Log verbosity |
| `S3_NOTIFICATION_WEBHOOK_URL` | | `` | agent-scrum-master webhook URL; if set, bucket notifications are registered automatically |
| `S3_NOTIFICATION_QUEUE_ARN` | | `arn:minio:sqs::WEBHOOK:webhook` | MinIO ARN of the webhook notification target |

---

## Running locally

```bash
# 1. Create and activate a virtual environment
uv venv .venv && source .venv/bin/activate

# 2. Install dependencies
uv pip install -r requirements.txt

# 3. Copy and edit the environment file
cp .env.example .env
# → fill in values in .env

# 4. Run the agent once
cd agents/agent-triage
python -m agent_triage.main
```

---

## Running with Docker

```bash
# Build
docker build -t agent-triage agents/agent-triage/

GH_TOKEN=$(gh auth token) docker build --no-cache --secret id=gh_token,env=GH_TOKEN -t jarvis-agent-triage:latest . 2>&1

GH_TOKEN=$(gh auth token) docker build --no-cache --secret id=gh_token,env=GH_TOKEN -f Dockerfile-frontend -t jarvis-agent-triage-frontend:latest . 2>&1 | tail -50

# Run (reads .env from the current directory)
docker run --env-file agents/agent-triage/.env agent-triage

# Or with Docker Compose (recommended for integration with MinIO)
# Run from agents/agent-triage/ where docker-compose.yaml lives
cd agents/agent-triage
docker compose up


```

Real-time logs:

```bash
docker logs -f <container-id>
```

---

## Tests

```bash
cd agents/agent-triage

# with uv
uv run -m pytest tests/ -v --cov=src/agent_triage --cov-report=term-missing

# Unit tests only (fast, no external services)
pytest tests/ -v --cov=src/agent_triage --cov-report=term-missing

# Full suite including end-to-end tests
pytest tests/ tests/end2end/ -v --cov=src/agent_triage --cov-report=term-missing
```

---

## Coverage

`coverage` is included in the project dependencies. Use `pytest-cov` (for a combined run)
or the `coverage` CLI directly.

```bash
cd agents/agent-triage

# Run unit tests and collect coverage data
coverage run -m pytest tests/

# Include end-to-end tests in the coverage run
coverage run -m pytest tests/ tests/end2end/

# Print a summary table (missing lines highlighted)
coverage report

# Generate an interactive HTML report → htmlcov/index.html
coverage html

# Open the report in the default browser
xdg-open htmlcov/index.html          # Linux
open htmlcov/index.html              # macOS
```

Or combine everything in one command via `pytest-cov`:

```bash
pytest tests/ \
  --cov=src/agent_triage \
  --cov-report=term-missing \
  --cov-report=html
# → htmlcov/index.html is generated automatically
```

Coverage configuration lives in `pyproject.toml` under `[tool.coverage.*]`.
The `htmlcov/` directory and `.coverage` data file are git-ignored.

---

## MinIO bucket naming

Each project gets its own bucket:

```
jarvis-<project-slug>
```

where `<project-slug>` is derived from the project name in the email subject by
lower-casing, removing special characters, and replacing spaces with hyphens.

| Email subject | Bucket name |
|---|---|
| `[JARVIS]-[Image Displayer]` | `jarvis-image-displayer` |
| `[JARVIS]-[auth-service]` | `jarvis-auth-service` |

Within the bucket:

```
jarvis-<project-slug>/
├── epics/
│   ├── <description>_<YYYY-MM-DD>.md        ← epic (overwritten on update)
│   └── project-extension-rules.md            ← project-specific rules (if any)
└── logs/
    └── <YYYY-MM-DD>/
        └── <ISO-timestamp>.log
```

---

## S3 event notification

`agent-triage` does **not** directly call `agent-scrum-master`. Instead it relies on
MinIO **bucket notifications**: whenever an epic is written under `epics/`, MinIO fires
a webhook to `agent-scrum-master` automatically.

### Fully automated (recommended)

Set the two notification variables in `.env`:

```env
S3_NOTIFICATION_WEBHOOK_URL=http://agent-scrum-master:8080/webhooks/minio
S3_NOTIFICATION_QUEUE_ARN=arn:minio:sqs::WEBHOOK:webhook
```

And enable the webhook target in MinIO's own environment (e.g. in `docker-compose.yaml`):

```yaml
environment:
  MINIO_NOTIFY_WEBHOOK_ENABLE_WEBHOOK: "on"
  MINIO_NOTIFY_WEBHOOK_ENDPOINT_WEBHOOK: "http://agent-scrum-master:8080/webhooks/minio"
```

With both set, `agent-triage` calls `put_bucket_notification_configuration` **automatically**
when it creates a new project bucket — no manual `mc event add` required. Every new
`[JARVIS][project]` email is handled end-to-end without operator intervention.

### Manual fallback

If `S3_NOTIFICATION_WEBHOOK_URL` is left empty, notification registration is skipped.
You can then configure it manually per bucket:

```bash
mc event add minio/jarvis-<project-slug> arn:minio:sqs::WEBHOOK:webhook \
  --event put --prefix epics/
```

`agent-scrum-master` must expose the corresponding webhook endpoint.

---

## Extension rules

If an email includes an attachment named `project-extension-rules.md`, it is:

1. Parsed and used **immediately** as additional rules for that run's epic generation.
2. Stored in S3 at `epics/project-extension-rules.md` for future runs.

On subsequent runs without the attachment, the previously stored rules are automatically
loaded from S3 and applied.

Extension rules **take precedence** over the base rules in
`rules/challenge-requirements.md`.

---

## Logging

Logs are emitted as **structured JSON** (via `structlog`) to two destinations:

1. **Container stdout** — visible in real time via `docker logs`.
2. **MinIO S3** — written to `logs/<YYYY-MM-DD>/<run-timestamp>.log` in the
   `jarvis-agent-triage-logs` bucket at the end of each cron run. This bucket is
   created automatically.
