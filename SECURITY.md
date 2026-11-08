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

The watcher handles two secrets:

- the OpenCode Go key, read read-only from OpenCode's own database;
- the Mattermost webhook URL, stored in the local `config.env`.

Both stay outside the repository. `config.env` is created with mode 600 and is
git-ignored. The key is never logged, printed, or included in a message. Only
its length is printed by `watch.py check`.

The tool has no runtime third-party dependency. It talks to three OpenCode
Console endpoints and one Mattermost webhook, all over HTTPS.

## Threat model

- A local attacker who can read `config.env` can post to the Mattermost
  channel. Protect the file permissions and the account.
- A compromised webhook can receive the spend reports. Treat the URL as a
  credential and rotate it if it leaks.
- The OpenCode Console endpoints are undocumented. A change there can break
  collection; it cannot expose the key through this tool.
- The watcher only reads usage and posts messages. It never changes billing,
  limits, or model access.
