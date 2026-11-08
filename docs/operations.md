# Operations

## Install

1. Create an Incoming Webhook in Mattermost:
   **Integrations > Incoming Webhooks > Add**, choose the channel.
2. Create the local configuration:

   ```console
   $ cp config.example.env config.env
   $ chmod 600 config.env
   $ $EDITOR config.env
   ```

3. Set `MATTERMOST_WEBHOOK_URL`. Keep it quoted if it contains `&`, `?`, or
   `#`. Set `PLAN` to `go-plus` or `go`. Optionally set `CONSOLE_URL`.
4. Validate and install:

   ```console
   $ python3 watch.py --version
   $ python3 watch.py check
   $ python3 watch.py test-webhook
   $ ./install.sh
   ```

`install.sh` validates the APIs, sends one test message, and installs this
cron entry:

```text
*/5 * * * * cd "<repo>" && /usr/bin/flock -n "<state>/cron.lock" \
  /usr/bin/python3 watch.py poll >> "<state>/cron.log" 2>&1
```

The first cron poll sends the startup message and records the baseline.

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
| Test message `failed` | Webhook URL wrong or channel deleted | Recreate the webhook, update `config.env` |
| No alerts but spend grows | Threshold not crossed yet, or webhook failing | Run `report`; inspect `cron.log` |
| Duplicate alert | Delivery succeeded but state was lost or restored from backup | Expected after a state restore; the next crossing corrects it |
| `configuration error` | Invalid `THRESHOLD_STEP_USD` | Use a positive number |
| Cron never runs | Cron daemon stopped, or the entry is a comment | `systemctl status cron`; `crontab -l` must show the schedule on its own line |
| `flock` contention | A poll is still running | Normal; the new poll exits without changing state |

The API lags a few minutes. An alert arriving just after the dollar was spent is
expected.

## Rotate the webhook

1. Create a new Incoming Webhook in Mattermost.
2. Replace `MATTERMOST_WEBHOOK_URL` in `config.env`.
3. Run `python3 watch.py test-webhook`.
4. Delete the old webhook in Mattermost.

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
