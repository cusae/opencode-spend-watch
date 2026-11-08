# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CodeQL analysis and Dependabot updates for actions and development tools.
- A Python 3.10 to 3.14 test matrix, a workflow lint job, and Markdown and
  YAML checks.
- `make` targets for setup, lint, types, coverage, docs, and `check`.
- Issue and pull request templates, contribution guide, security policy,
  architecture notes, and an operations runbook.
- `--version` and `--help` on the CLI, with explicit exit codes.
- Configuration validation: a non-numeric or non-positive threshold is a
  configuration error, not a traceback.
- `CRON_INTERVAL_MINUTES` for `install.sh`; the default is 15 minutes.
- Coloured Mattermost attachments and status emoji: green below 50% used,
  amber from 50%, red from 80%.
- Slack, Discord, IRC, email, and WhatsApp notification backends. Several
  channels can run together with per-channel failure isolation.

### Changed

- `mypy` now runs in strict mode.
- The coverage gate is 90%, up from 75%.
- `install.sh` validates the cron interval as an integer from 1 to 59.

### Security

- The webhook URL is validated as HTTP(S) before delivery.
- Repository secret scanning, push protection, and Dependabot alerts are
  enabled.

## [1.0.0] - 2026-11-08

### Added

- Poll OpenCode Console usage and post a Mattermost message every time spend
  in the current billing period crosses another whole dollar.
- Report the period total, remaining monthly allowance, 5-hour, weekly, and
  monthly window percentages, today and last-7-day spend, top models, and the
  closest per-model limit.
- Persist daily costs so days that leave the API's 30-day window stay
  available for later periods.
- Retry failed webhook deliveries without advancing the threshold.
- `poll`, `check`, `report`, `test-webhook`, and `daemon` commands.
- `install.sh` validation and idempotent five-minute cron installation.
- Go and Go Plus limit tables in `limits.json`.

### Security

- Read the OpenCode key read-only from OpenCode's database.
- Keep `config.env`, the webhook URL, and the state directory out of git.
- Validate the webhook URL before every delivery.

### Documentation

- README, architecture, operations runbook, contribution guide, security
  policy, and agent guidance.
