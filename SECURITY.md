# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | Yes |
| < 1.0 | No |

## Reporting a vulnerability

Report privately through GitHub Security Advisories:
<https://github.com/cusae/opencode-spend-watch/security/advisories/new>

Do not open a public issue. Include the version (`python3 watch.py --version`),
the operating system, reproduction steps, and the relevant logs with every
secret removed.

## Scope

The watcher handles these secrets:

- the OpenCode Go key, read read-only from OpenCode's own database;
- webhook URLs for Mattermost, Slack, and Discord;
- IRC, SMTP, WhatsApp, and Telegram credentials in the local `config.env`;
- OpenRouter and OpenAI admin API keys when those providers are enabled.

All stay outside the repository. `config.env` is created with mode 600 and is
git-ignored. The key is never logged, printed, or included in a message. Only
its length is printed by `watch.py check`.

The tool has no runtime third-party dependency. It talks to three OpenCode
Console endpoints and the configured notification channels. Webhooks, SMTP, and the WhatsApp API use HTTPS; IRC uses TLS by default.

## Threat model

- A local attacker who can read `config.env` can post to every configured
  channel. Protect the file permissions and the accounts.
- A compromised webhook, bot token, or password can receive the spend reports.
  Treat every channel credential as a secret and rotate it if it leaks.
- IRC uses TLS with certificate verification by default. Disabling `IRC_TLS`
  exposes the channel password and the reports to the network.
- The OpenCode Console endpoints are undocumented. A change there can break
  collection; it cannot expose the key through this tool.
- The watcher only reads usage and posts messages. It never changes billing,
  limits, or model access.
