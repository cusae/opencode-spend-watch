<div align="center">

# opencode-spend-watch

**Know what OpenCode costs, one dollar at a time.**

<br>

[![tests](https://github.com/cusae/opencode-spend-watch/actions/workflows/tests.yml/badge.svg)](https://github.com/cusae/opencode-spend-watch/actions/workflows/tests.yml)
[![license](https://img.shields.io/github/license/alaunay/opencode-spend-watch?style=flat-square)](LICENSE)
[![python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white)](#requirements)

<br>
<br>

</div>

A small Python watcher that reads exact OpenCode usage in USD, and posts a
Mattermost message every time your spend crosses another whole dollar in the
current billing period. The message carries the amount used, the remaining
monthly allowance, the 5-hour/weekly/monthly window percentages, today's
spend, the top models, and the limit with the least headroom.

No database of its own beyond a JSON state file, no third-party runtime
dependency, no secret in the repository.

---

## Quick start

```console
$ git clone https://github.com/cusae/opencode-spend-watch.git
$ cd opencode-spend-watch
$ cp config.example.env config.env
$ chmod 600 config.env
$ $EDITOR config.env          # set MATTERMOST_WEBHOOK_URL
$ python3 watch.py check
$ python3 watch.py test-webhook
$ ./install.sh
```

---

## Where the numbers come from

The watcher uses the OpenCode Go key already stored locally by OpenCode in
`~/.local/share/opencode/opencode.db` (table `credential`, integration
`opencode-go`). The key is read read-only, never printed, never logged, and
never placed in a message.

| Endpoint | Data |
| --- | --- |
| `/zen/go/v1/usage` | 5-hour, weekly and monthly percentages, plus reset times |
| `/console/api/usage/cost-by-day?range=30d` | exact cost per UTC day |
| `/console/api/usage/models?range=30d` | exact cost per model |

All three are OpenCode Console endpoints, not a documented public API. They
can change without notice; `watch.py check` names the failing endpoint.

---

## How thresholds work

The billing period comes from the API's monthly `resetsAt` timestamp, not the
calendar month. For example, 27 Oct 14:09 UTC to 27 Nov 14:09 UTC.

- Spend is the sum of daily costs from the period start to now.
- The threshold level is `floor(spend / THRESHOLD_STEP_USD)`.
- A message is sent when that level increases.
- If several dollars are crossed between polls, one message reports the range.
- If Mattermost rejects the message, the level is not advanced; the next poll
  retries, so an alert is never lost.

Daily costs are merged into `state.json`, so days that leave the API's 30-day
window remain available for the rest of the period and for later periods.

The first run sends one "watcher started" message and takes the current spend
as the baseline. It does not replay past dollars.

---

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MATTERMOST_WEBHOOK_URL` | empty | Required. Incoming webhook, channel fixed by it. |
| `PLAN` | `go-plus` | `go-plus` or `go`; selects limits from `limits.json`. |
| `THRESHOLD_STEP_USD` | `1` | Alert step in dollars. |
| `STATE_DIR` | `~/.local/state/opencode-spend-watch` | State, lock, cron log. |
| `OPENCODE_DB` | `~/.local/share/opencode/opencode.db` | Key source. |
| `OPENCODE_GO_KEY` | unset | Optional key override. |
| `CONSOLE_URL` | empty | Link added to each message. |
| `STARTUP_MESSAGE` | `true` | Send the first-run message. |
| `RESET_MESSAGE` | `true` | Send a message when the period resets. |
| `LIMITS_FILE` | `limits.json` | Per-model monthly limits. |

`CONSOLE_URL` is optional. A typical value is the activity overview of your
OpenCode workspace:

```
https://opencode.ai/console/<org-id>/activity/overview?range=30d
```

---

## Commands

```console
$ python3 watch.py poll          # one cycle; cron calls this
$ python3 watch.py check         # validate key, APIs, webhook, plan limits
$ python3 watch.py report        # print the alert without sending
$ python3 watch.py test-webhook  # one test message
$ python3 watch.py daemon        # poll every OSW_INTERVAL seconds
$ ./install.sh                   # validate, test webhook, install cron
```

Cron runs every five minutes and writes to
`~/.local/state/opencode-spend-watch/cron.log`.

---

## Requirements

- Python 3.10 or later, standard library only
- OpenCode with the OpenCode Go integration connected
- A Mattermost Incoming Webhook

No `pip install` is needed to run the watcher. Development checks use `ruff`
and `shellcheck`.

---

## Tests

```console
$ python3 -m unittest discover -s tests -v
$ ruff check .
$ shellcheck install.sh .githooks/commit-msg
$ python3 -m py_compile watch.py
```

The unit tests never touch the network: they monkeypatch collection and
delivery to cover initialization, single and multiple threshold crossings,
failed webhook delivery, and billing-period resets. GitHub Actions runs the
same commands on every push to `master` and every pull request, in
[`.github/workflows/tests.yml`](.github/workflows/tests.yml).

---

## Limitations

- The console API exposes at most 30 days of daily costs. The first run seeds
  history from that window; older usage cannot be recovered.
- Daily costs are bucketed per UTC day, so the first day of a period can differ
  slightly from a strict period boundary.
- The monthly percentage comes from the API. Per-model dollar limits come from
  the published Go/Go Plus table in `limits.json`; edit the file when OpenCode
  changes them.
- This tracks usage counted against your Go allowance, not the flat
  subscription charge or pay-as-you-go credits outside Go.
- The API lags a few minutes, so an alert can arrive just after the dollar was
  actually spent.

---

## Security

- `config.env` holds only the webhook URL. It is git-ignored and created with
  mode 600.
- The OpenCode key stays in OpenCode's database and is read read-only.
- No key material appears in logs or Mattermost messages.
- Never commit `config.env`, a webhook URL, a key, or an org ID.

---

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
