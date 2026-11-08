# Operations

## Install

1. Create at least one destination: a Mattermost or Slack Incoming Webhook, a
   Discord webhook, an IRC channel, an SMTP account, or a WhatsApp Cloud API
   app. See [Notification channels](#notification-channels).
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

WhatsApp only accepts free-form text inside the customer service window. An
alert sent outside that window is rejected by Meta; use a template or another
channel for unattended monitoring.

## Day-to-day

```console
$ python3 watch.py report          # current numbers, no message
$ tail -f ~/.local/state/opencode-spend-watch/cron.log
$ crontab -l | grep opencode-spend-watch
```

The state directory holds:

| Path | Meaning |
| --- | --- |
| `state.json` | billing period, checkpoint, daily history |
| `state.lock` | poll serialization |
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

## Upgrade

```console
$ git pull --ff-only
$ python3 watch.py check
```

`install.sh` is idempotent; rerun it after an upgrade that changes the cron
entry. `limits.json` is versioned; review its changes when Go pricing changes.
