# Architecture

## Purpose

`watch.py` turns OpenCode usage into dollar-threshold events. It reads the same
numbers as the OpenCode Console, keeps a local history, and posts to Mattermost
when the current billing period crosses another whole dollar.

## Components

| Component | Responsibility |
| --- | --- |
| `Config` | Parse `config.env`, validate thresholds, channels, and providers; expose plan limits, labels, and channels. |
| `opencode_go_key` | Read the Go key from OpenCode's database, or from `auth.json` as a fallback. |
| `fetch_windows` | Read 5-hour, weekly, and monthly percentages and reset times. |
| `fetch_daily` | Read exact cost per UTC day. |
| `fetch_models` | Read exact cost per model for the last 30 days. |
| `collect` | Merge stored and fresh days, compute the period total, today, the last 7 days, and the closest limit. |
| `build_message` | Render the alert Markdown and choose the severity colour and emoji. |
| `notify.send_all` | Deliver to every enabled channel, isolating failures per backend. |
| `notify` backends | Mattermost, Slack, Discord, IRC, email, WhatsApp, Telegram, and desktop payloads. |
| `providers` | OpenRouter credits and OpenAI organization costs. |
| `Store` | Serialize a poll with a file lock and persist `state.json`. |
| `poll` | Initialize, detect period resets, raise dollar and percentage thresholds, poll extra providers, deliver, persist. |

## Data flow

```mermaid
sequenceDiagram
    participant Cron
    participant Watch as watch.py poll
    participant State as state.json
    participant Console as OpenCode Console API
    participant Channels as Channels

    Cron->>Watch: every configured interval
    Watch->>State: lock, load daily history
    Watch->>Console: GET /zen/go/v1/usage
    Watch->>Console: GET /console/api/usage/cost-by-day?range=30d
    Watch->>Console: GET /console/api/usage/models?range=30d
    Console-->>Watch: percentages, reset time, daily and model costs
    Watch->>Watch: merge days, compute period total and level
    opt Extra providers
        Watch->>Watch: OpenRouter credits / OpenAI organization costs
    end
    alt threshold crossed
        Watch->>Channels: send to every configured channel
        Channels-->>Watch: per-channel result
        Watch->>State: append alerts.log, advance the checkpoint if one succeeded
    else no change
        Watch->>State: persist merged days and provider state
    end
```

A failed collection exits non-zero and leaves `last_level` unchanged. If every
channel fails, delivery also leaves it unchanged and the next poll retries. A
partial failure is logged and the checkpoint advances, so healthy channels do
not receive the same alert twice.

## Billing period

The period comes from the monthly `resetsAt` returned by the usage endpoint,
not the calendar month. The start is the same instant one calendar month
earlier, clamped to the length of the target month.

```text
period_end   = usage.monthly.resetsAt
period_start = subtract_month(period_end)
period_total = sum(cost(day) for day in days if day >= period_start.date())
```

Daily costs are UTC-day buckets. The first day of a period can include usage
from before the exact start instant; the endpoint does not expose finer
granularity.

## Thresholds

```text
level = floor(period_total / THRESHOLD_STEP_USD)
```

A message is sent when `level` increases. If several dollars are crossed
between polls, one message reports the range. `last_level` is advanced only
after Mattermost accepts the message.

The first run sends a startup message, then records the current level as the
baseline. Earlier spend is not replayed.

## State

`state.json` lives under `STATE_DIR` (default
`~/.local/state/opencode-spend-watch`).

```json
{
  "period_end": "2026-11-27T14:09:59+00:00",
  "initialized": true,
  "last_level": 5,
  "daily": {
    "2026-11-07": 0.2599,
    "2026-11-08": 1.4528
  },
  "percent_alerts": {
    "monthly": {"reset": "2026-11-27T14:09:59+00:00", "threshold": 50.0}
  },
  "providers": {
    "openrouter": {
      "period_key": "lifetime",
      "last_level": 12,
      "last_spend": 12.4,
      "percent_threshold": 50.0
    }
  }
}
```

`daily` is the durable part: it keeps days after they leave the API's 30-day
window. `last_level` is the delivery checkpoint. `period_end` detects a
billing-period reset. A corrupt state file is treated as empty.

## API contract

| Endpoint | Auth | Shape used |
| --- | --- | --- |
| `/zen/go/v1/usage` | Bearer Go key | `usage.{rolling,weekly,monthly}.{percent,resetsAt}` |
| `/console/api/usage/cost-by-day?range=30d` | Bearer Go key | `[{date, totalCostMicroCents}]` |
| `/console/api/usage/models?range=30d&page=N&pageSize=50` | Bearer Go key | `{items: [{provider, model, totalCostMicroCents, totalRequests}], pageInfo}` |

Costs are microcents: 1 USD = 100,000,000. The endpoints are undocumented and
may change; `check` and the cron log identify the failing path.

## Design decisions

- **Standard library only.** The watcher runs from cron on a workstation with
  no virtualenv. Development tools are isolated in `requirements-dev.txt`.
- **Authoritative dollars, local percentages.** Spend comes from the console
  API; window percentages come from the usage endpoint. The watcher does not
  re-price tokens.
- **Durable daily history.** A 30-day API window would silently drop the start
  of a long period; the state file prevents that.
- **Idempotent delivery.** Advancing the checkpoint only after a 2xx response
  makes retries safe.
- **Severity in the payload.** Mattermost and Slack render an attachment
  colour bar, Discord an embed colour; IRC, email, and WhatsApp get text. The
  colour and the status emoji share one severity calculation.
- **Isolated backends.** One failing channel never blocks the others; the
  caller sees a result per channel.
- **Independent alert families.** Dollar crossings, percentage windows, and
  each extra provider keep their own checkpoint. A failure in one does not
  suppress the others.
- **Audit log.** Every delivery attempt is appended as JSON before the caller
  advances a checkpoint.
- **One lock.** Cron, a manual poll, and `report` serialize on a file lock in
  the state directory.
