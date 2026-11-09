# Operations

## Install

1. Create at least one destination: a Mattermost or Slack Incoming Webhook, a
   Discord webhook, an IRC channel, an SMTP account, a WhatsApp Cloud API app,
   a Telegram bot, a working desktop notifier, or an RSS feed path. See
   [Notification channels](#notification-channels).
2. Create the local configuration:

   ```console
   $ cp config.example.env config.env
   $ chmod 600 config.env
   $ $EDITOR config.env
   ```

3. Fill in at least one channel. Keep webhook values quoted if they contain
   `&`, `?`, or `#`. Set `PLAN` to `go-plus` or `go`. Optionally set
   `CONSOLE_URL`.
4. Validate and install:

   ```console
   $ python3 watch.py --version
   $ python3 watch.py check
   $ python3 watch.py test-webhook
   $ ./install.sh
   ```

`install.sh` validates the APIs, sends one test message, and installs this
cron entry. The default is every 15 minutes; set `CRON_INTERVAL_MINUTES` in
`config.env` to change it (1–59):

```text
*/15 * * * * cd "<repo>" && /usr/bin/flock -n "<state>/cron.lock" \
  /usr/bin/python3 watch.py poll >> "<state>/cron.log" 2>&1
```

The first cron poll sends the startup message and records the baseline.

## Notification channels

Several channels can run together. `test-webhook` sends to every configured
channel and reports partial failures. A poll advances the alert checkpoint when
at least one channel accepted the message; it retries only when every channel
failed.

| Channel | Setup |
| --- | --- |
| Mattermost | Create an Incoming Webhook under **Integrations > Incoming Webhooks**. Set `MATTERMOST_WEBHOOK_URL`. |
| Slack | Create an Incoming Webhook for the app. Set `SLACK_WEBHOOK_URL`. Messages use a coloured attachment. |
| Discord | Create a channel webhook. Set `DISCORD_WEBHOOK_URL`. Messages use a coloured embed. |
| IRC | Set `IRC_HOST`, `IRC_CHANNEL`, and optionally `IRC_PORT` (6697), `IRC_TLS` (true), `IRC_NICK`, `IRC_PASSWORD`. TLS certificates are verified; long messages are split. |
| Email | Set `SMTP_HOST`, `EMAIL_FROM`, `EMAIL_TO` (comma-separated), and optionally `SMTP_PORT` (587), `SMTP_SECURITY` (`starttls`, `ssl`, `none`), `SMTP_USER`, `SMTP_PASSWORD`. The message carries a colour bar in the HTML part. |
| WhatsApp | Set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TO`, and optionally `WHATSAPP_API_VERSION` (v21.0). Uses the Meta Cloud API. |
| Telegram | Create a bot with `@BotFather`, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Long messages are split at 4000 characters. |
| Desktop | Set `DESKTOP_NOTIFY=true`. Uses `notify-send` on Linux and `osascript` on macOS; the helper must be on `PATH`. |
| RSS | Set `RSS_FEED` to a writable `.xml` path. `RSS_MAX_ITEMS` (100) caps the feed, `RSS_TITLE` and `RSS_LINK` customise it. Serve the file from a web server, Nextcloud, or any static host. |

The RSS feed is rewritten atomically after each alert. It contains spend
amounts and model details, so treat it as internal data and do not publish it
without authentication.

WhatsApp only accepts free-form text inside the customer service window. An
alert sent outside that window is rejected by Meta; use a template or another
channel for unattended monitoring.

## Percentage alerts and the log

`THRESHOLD_STEP_USD` sets the dollar step for every provider. The default `1`
alerts at $1, $2, $3; set `5` to alert at $5, $10, $15. Fractional values such
as `0.5` are accepted.

`PERCENT_THRESHOLDS` (default `50,80,95`) alerts when the 5-hour, weekly, or
monthly window crosses a level. Each window and reset period fires once per
threshold, so a poll loop does not spam the channel. Dollar thresholds and
percentage thresholds are independent.

Every delivery attempt is appended to `ALERT_LOG` (default
`STATE_DIR/alerts.log`) as one JSON line: time, kind, full message, and the
result of each channel. The file rotates to `alerts.log.1` at 5 MB. It never
contains credentials.

## Extra cost providers

`PROVIDERS=opencode,openrouter,openai` adds cost sources alongside OpenCode Go.

| Provider | Credential | Budget |
| --- | --- | --- |
| OpenRouter | `OPENROUTER_API_KEY` | `OPENROUTER_BUDGET_USD`, or the purchased credit total when 0 |
| OpenAI | `OPENAI_ADMIN_KEY` (organization admin) | `OPENAI_BUDGET_USD` |

`PROVIDERS` must contain `opencode`; the other names are optional. OpenRouter
uses cumulative usage against credits and alerts on each new dollar. OpenAI
sums the organization cost API for the current calendar month. Both use the
same `THRESHOLD_STEP_USD` and `PERCENT_THRESHOLDS`, the same channels, and the
same lock and retry rules. `watch.py check` reports every provider or the
failing credential.

## Day-to-day

```console
$ python3 watch.py report          # current numbers, no message
$ tail -f ~/.local/state/opencode-spend-watch/cron.log
$ crontab -l | grep opencode-spend-watch
```

The state directory holds:

| Path | Meaning |
| --- | --- |
| `state.json` | billing periods, checkpoints, daily history, provider state |
| `state.lock` | poll serialization |
| `alerts.log` | JSONL delivery audit, rotates at 5 MB |
| `feed.xml` | optional RSS 2.0 alert feed |
| `cron.log` | cron output |

Back up `config.env` and `state.json` together. Losing `state.json` resets the
baseline and the daily history; the next poll reinitializes from the API's
30-day window.

## Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `key: FAIL` | OpenCode Go is not connected, or the database moved | Reconnect Go in OpenCode, or set `OPENCODE_GO_KEY` |
| `HTTP 401` | Key rejected by the console API | Reconnect Go; confirm `check` prints `api: ok` |
| `HTTP 404` | Console endpoint changed | Open an issue with the failing path from `check` |
| `key: found` then timeout | Network, proxy, or Cloudflare | Retry; check `curl` to `opencode.ai` |
| Test message `failed` | At least one channel rejected the message | Fix the named channel; `test-webhook` lists every failure |
| Slack or Discord `HTTP 404` | Webhook deleted | Recreate the webhook, update `config.env` |
| IRC timeout | Wrong host or port, TLS mismatch, or blocked egress | Check `IRC_TLS` and the network path |
| IRC `401`/`464` | Bad nick or password | Fix `IRC_NICK` and `IRC_PASSWORD` |
| SMTP authentication error | Wrong `SMTP_SECURITY` or credentials | Try `starttls`, `ssl`, or an app password |
| WhatsApp `131047` | Outside the 24-hour customer service window | Use a template or another channel |
| Telegram `401` | Invalid bot token | Recreate the bot token with `@BotFather` |
| Telegram `400 chat not found` | Wrong chat ID, or the bot never received a message | Send `/start` to the bot, then copy the chat ID |
| Desktop delivery failed | `notify-send` or `osascript` missing | Install `libnotify-bin` or disable `DESKTOP_NOTIFY` |
| RSS feed failed | Path not writable, or an existing file is not valid XML | Fix permissions or move the corrupt file aside |
| Provider `HTTP 401` | Wrong OpenRouter or OpenAI admin key | Replace the key and rerun `check` |
| OpenAI `HTTP 403` | Key is not an organization admin key | Create an admin key in the OpenAI dashboard |
| Partial delivery | One channel failed; others succeeded | The alert is not resent; fix the failing channel |
| No alerts but spend grows | Threshold not crossed yet, or delivery failing | Run `report`; inspect `cron.log` |
| Duplicate alert | Delivery succeeded but state was lost or restored from backup | Expected after a state restore; the next crossing corrects it |
| `configuration error` | Invalid `THRESHOLD_STEP_USD` | Use a positive number |
| Cron never runs | Cron daemon stopped, or the entry is a comment | `systemctl status cron`; `crontab -l` must show the schedule on its own line |
| `flock` contention | A poll is still running | Normal; the new poll exits without changing state |

The API lags a few minutes. An alert arriving just after the dollar was spent is
expected.

## Rotate a channel credential

1. Create the replacement webhook, bot token, or app password.
2. Replace the matching variable in `config.env`.
3. Run `python3 watch.py test-webhook`.
4. Revoke the old credential at the provider.

## Rotate the OpenCode key

Reconnect OpenCode Go in OpenCode. The watcher reads the new key from the
database on the next poll; no restart is needed. If an override is set,
update `OPENCODE_GO_KEY` in `config.env` instead.

## Reset the state

Reset only when the history is wrong or a period change must be re-baselined:

```console
$ rm ~/.local/state/opencode-spend-watch/state.json
$ python3 watch.py poll
```

This sends a new startup message and baselines at the current spend. The daily
history is rebuilt from the API's 30-day window.

## Disable or uninstall

Disable alerts but keep the state:

```console
$ crontab -l | grep -v 'opencode-spend-watch\|watch.py poll' | crontab -
```

Remove everything:

```console
$ crontab -l | grep -v 'opencode-spend-watch\|watch.py poll' | crontab -
$ rm -rf ~/.local/state/opencode-spend-watch
$ rm config.env
```

## Release

1. Update `VERSION` in `watch.py` and the version-dependent docs.
2. Run `make changelog`; commit `CHANGELOG.md` with the release change.
3. Tag the merge commit: `git tag -s vX.Y.Z -m "vX.Y.Z"`.
4. Push the tag: `git push origin vX.Y.Z`.
5. `.github/workflows/release.yml` creates the GitHub release and attaches the
   generated `CHANGELOG.md`.

The changelog is generated by git-cliff from Conventional Commits. A missing
or non-conventional subject lands in `Other`; fix the commit type before the
release, not the changelog.

## Upgrade

Never overwrite `config.env` after an upgrade. Merge the new options; existing
values stay untouched and the old file is backed up:

```console
$ git pull --ff-only
$ python3 watch.py merge-config --dry-run
$ python3 watch.py merge-config
$ python3 watch.py check
```

For a package install:

```console
$ sudo opencode-spend-watch merge-config --dry-run
$ sudo opencode-spend-watch merge-config
```

The helper prints the added option names, creates
`config.env.bak.YYYYMMDDTHHMMSS`, keeps the file mode, and writes atomically.
`install.sh` is idempotent; rerun it after an upgrade that changes the cron
entry. `limits.json` is versioned; review its changes when Go pricing changes.
