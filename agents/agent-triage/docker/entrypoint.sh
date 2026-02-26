#!/bin/sh
# =============================================================================
# docker/entrypoint.sh
# =============================================================================

set -e

LOG_FILE="/app/data/agent-triage.log"
INTERVAL="${POLL_INTERVAL_MINUTES:-10}"

echo "[entrypoint] Polling interval: ${INTERVAL} minutes"

# ---------------------------------------------------------------------------
# Authenticate GitHub CLI
# ---------------------------------------------------------------------------
if [ -n "${GITHUB_TOKEN}" ]; then
    echo "${GITHUB_TOKEN}" | gh auth login --with-token 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Save the current environment so cron jobs can source it at runtime.
# This is the most reliable way to pass Docker env vars to cron — injecting
# hundreds of lines into the crontab itself risks confusing cron's parser.
# ---------------------------------------------------------------------------
printenv | grep -v '^_=' | sed "s/'/'\\\\''/g; s/\(.*\)=\(.*\)/export \1='\2'/" \
    > /app/data/env.sh
chmod 600 /app/data/env.sh   # contains secrets — restrict access

# ---------------------------------------------------------------------------
# Build the crontab from template (clean — no env vars embedded)
# ---------------------------------------------------------------------------
sed "s/{{INTERVAL}}/${INTERVAL}/g" /crontab.template > /etc/cron.d/agent-triage

chmod 0644 /etc/cron.d/agent-triage

echo "[entrypoint] Crontab installed:"
cat /etc/cron.d/agent-triage   # <-- replaces `crontab -l` which had no user crontab

# ---------------------------------------------------------------------------
# Start cron daemon in the background
# ---------------------------------------------------------------------------
cron -f &                       # -f = foreground but we background it ourselves
CRON_PID=$!
echo "[entrypoint] Cron started (PID ${CRON_PID}). Tailing ${LOG_FILE}..."

# ---------------------------------------------------------------------------
# Graceful shutdown handler
# ---------------------------------------------------------------------------
_shutdown() {
    echo "[entrypoint] Caught shutdown signal — stopping cron..."
    kill "${CRON_PID}" 2>/dev/null || true
    sleep 5
    kill "${TAIL_PID}" 2>/dev/null || true
    echo "[entrypoint] Shutdown complete."
    exit 0
}

trap _shutdown TERM INT

touch "${LOG_FILE}"
tail -f "${LOG_FILE}" &
TAIL_PID=$!

wait "${TAIL_PID}"
