# AGENTS.md

Guidance for agents working in this repository.

## Project

`watch.py` polls OpenCode's console API for exact usage in USD, keeps a local
daily history, and posts a Mattermost message every time spend in the current
billing period crosses another whole dollar. It also reports the remaining
monthly allowance, the 5-hour/weekly/monthly window percentages, today's
spend, the top models, and the per-model limit with the least headroom.

The OpenCode Go key is read from OpenCode's own database
(`~/.local/share/opencode/opencode.db`, table `credential`, integration
`opencode-go`). No secret is stored in this repository.

## Run

```console
$ cp config.example.env config.env
$ chmod 600 config.env
$ $EDITOR config.env          # set MATTERMOST_WEBHOOK_URL
$ python3 watch.py check
$ python3 watch.py report
$ python3 watch.py poll
$ ./install.sh                # installs the 5-minute cron job
```

`poll` is the cron entry point. `check` validates the key and every API used.
`report` prints the message without sending it. `test-webhook` sends one test
message.

## Data sources

Three undocumented OpenCode console endpoints, authenticated with the stored Go
key:

| Endpoint | Data |
| --- | --- |
| `/zen/go/v1/usage` | window percentages and reset timestamps |
| `/console/api/usage/cost-by-day?range=30d` | exact cost per UTC day |
| `/console/api/usage/models?range=30d` | exact cost per model |

They are not official. When one changes, `watch.py check` and the cron log show
the failing path. Keep the fallback behaviour: a failed collection must exit
non-zero without advancing alert state, so the next poll retries.

Daily costs are persisted in `state.json`. Do not drop that merge: it is what
keeps earlier days after they leave the API's 30-day window.

## Tests

The suite is stdlib `unittest` and must not touch the network. Tests monkeypatch
`collect` and `post_webhook`. Required checks, all failures fatal:

```console
$ python3 -m unittest discover -s tests -v
$ ruff check .
$ shellcheck install.sh .githooks/commit-msg
$ python3 -m py_compile watch.py
```

GitHub Actions runs the same checks on every push to `master` and on every pull
request, in `.github/workflows/tests.yml`.

## Configuration and secrets

- `config.env` is local, mode 600, and git-ignored. Never commit it.
- Never commit a Mattermost webhook URL, an OpenCode key, an org ID, or a state
  file.
- `config.example.env` stays empty: `MATTERMOST_WEBHOOK_URL=""` and
  `CONSOLE_URL=""`.
- Do not log the key or put it in a message. Only its length may be printed by
  `check`.

## Code conventions

- Python 3.10 or later, standard library only, no third-party runtime
  dependency.
- Format with `ruff format`; lint with `ruff check .`.
- Line length 100. Type hints on public functions.
- Keep `main()` dispatch and the `Store` lock: cron and manual runs can overlap.
- A failed API or webhook call returns non-zero and leaves state unchanged.
- Comments explain why, not what.

## Commit rules

### Co-authored-by is mandatory

Every commit that contains work produced with an agent must end with a
`Co-authored-by` trailer. This is a hard rule, not a preference.

Format, after a blank line at the end of the commit body:

```
Co-authored-by: Name <email>
```

Example for an agent running through opencode:

```
Co-authored-by: DeepSeek V4.1 Flash <noreply@opencode.ai>
```

Rules for the trailer:

- One `Co-authored-by` line per contributing agent.
- Use the agent's real name and a real address. Never invent an address,
  never use a placeholder, never use `noreply@example.com`.
- The trailer names the agent that produced the change, not the human
  who requested it.
- A commit without the trailer is incomplete and must be amended before
  push.

### Signed-off-by is mandatory

Every commit must carry a `Signed-off-by` trailer. This certifies the
Developer Certificate of Origin: the contributor has the right to
submit the code under the project licence. It is a hard rule, like the
`Co-authored-by` trailer.

Format, at the end of the commit message, after the `Co-authored-by`
trailer:

```
Signed-off-by: Name <email>
```

Rules for the trailer:

- The name and the email must match the commit committer identity. A
  mismatch invalidates the sign-off.
- Use `git commit -s` (or `git commit --trailer "Signed-off-by: ..."`)
  so git writes the line. Never type it by hand with a different
  identity.
- Amend the commit if the trailer is missing. Do not add it in a
  follow-up commit.

### Trailers summary

A complete agent-assisted commit ends with, in this order:

```
Co-authored-by: Name <email>
Signed-off-by: Name <email>
```

### Enforcement

- `master` requires GPG-signed commits. The rule is remote, applies to
  administrators, and rejects an unsigned push. `commit.gpgsign` must be
  true and the signing key must be registered on GitHub.
- The commit email must be a verified UID of the signing key. This
  repository sets `user.email` to `asl@launay.org` for that reason.
  Never commit here with the `users.noreply.github.com` address: GitHub
  answers `bad_email` and rejects the push.
- The DCO app checks both trailers on pull requests, and only there. A
  direct push is not covered by the app.
- `.githooks/commit-msg` rejects a commit with a missing or malformed
  trailer, or a `Signed-off-by` address that differs from the committer.
  Enable it per clone with `git config core.hooksPath .githooks`.
- The hook is a guard against mistakes, not a barrier. `git commit
  --no-verify` bypasses it.

### Pull requests

`master` takes pull requests only. Push a branch, open a pull request, and
merge it once the checks are green. Direct pushes are rejected, and force
pushes are disabled.

### Commit messages

- Subject line in the imperative mood, no trailing period.
- Body wrapped at 72 columns, explaining the problem and the reason for
  the change.
- One logical change per commit.
