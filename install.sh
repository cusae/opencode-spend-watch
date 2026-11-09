#!/usr/bin/env bash
# Install the OpenCode spend watcher: config file, validation, cron entry.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$DIR/config.env"
PYTHON="$(command -v python3)"

cd "$DIR"

if [[ ! -f "$CONFIG" ]]; then
  cp "$DIR/config.example.env" "$CONFIG"
  chmod 600 "$CONFIG"
  echo "Created $CONFIG"
  echo "Edit it and set MATTERMOST_WEBHOOK_URL before continuing."
  exit 0
fi
chmod 600 "$CONFIG"

set -a
# shellcheck disable=SC1090
source "$CONFIG"
set +a
: "${STATE_DIR:=$HOME/.local/state/opencode-spend-watch}"
STATE_DIR="${STATE_DIR/#\~/$HOME}"
mkdir -p "$STATE_DIR"

channel_ready=0
if [[ -n "${MATTERMOST_WEBHOOK_URL:-}${SLACK_WEBHOOK_URL:-}${DISCORD_WEBHOOK_URL:-}${IRC_HOST:-}${SMTP_HOST:-}${WHATSAPP_TOKEN:-}${TELEGRAM_BOT_TOKEN:-}${RSS_FEED:-}" ]]; then
  channel_ready=1
fi
if [[ "${DESKTOP_NOTIFY:-false}" == "true" ]]; then
  channel_ready=1
fi
if (( channel_ready == 0 )); then
  echo "Configure at least one notification channel in $CONFIG" >&2
  echo "(Mattermost, Slack, Discord, IRC, email, WhatsApp, Telegram, desktop, or RSS)." >&2
  exit 1
fi

echo "Checking APIs..."
"$PYTHON" "$DIR/watch.py" check

echo "Sending one test message to Mattermost..."
"$PYTHON" "$DIR/watch.py" test-webhook

INTERVAL="${CRON_INTERVAL_MINUTES:-15}"
if ! [[ "$INTERVAL" =~ ^[0-9]+$ ]]; then
  echo "CRON_INTERVAL_MINUTES must be an integer, got '$INTERVAL'" >&2
  exit 1
fi
INTERVAL=$((10#$INTERVAL))
if (( INTERVAL < 1 || INTERVAL > 59 )); then
  echo "CRON_INTERVAL_MINUTES must be between 1 and 59, got $INTERVAL" >&2
  exit 1
fi

LINE="*/$INTERVAL * * * * cd \"$DIR\" && /usr/bin/flock -n \"$STATE_DIR/cron.lock\" \"$PYTHON\" watch.py poll >> \"$STATE_DIR/cron.log\" 2>&1"
MARKER="# opencode-spend-watch"
CURRENT="$(crontab -l 2>/dev/null || true)"
FILTERED="$(printf '%s\n' "$CURRENT" | grep -vF "$MARKER" | grep -vF 'watch.py poll' || true)"
{
  printf '%s\n' "$FILTERED" | sed '/^$/d'
  printf '%s\n' "$MARKER"
  printf '%s\n' "$LINE"
} | crontab -

echo "Installed cron entry (every $INTERVAL minutes)."
echo "First run: $PYTHON $DIR/watch.py poll"
echo "Logs:      $STATE_DIR/cron.log"
