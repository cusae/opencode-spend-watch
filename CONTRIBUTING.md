# Contributing

## Before you start

Open an issue for a bug or a feature before a large change. For a security
problem, follow [SECURITY.md](SECURITY.md) and do not open a public issue.

## Setup

Requirements: Python 3.10 or later, `git`, `bats`, and `shellcheck`. The
Markdown, YAML, and workflow linters are installed by the development
requirements and npm.

```console
$ git clone https://github.com/cusae/opencode-spend-watch.git
$ cd opencode-spend-watch
$ make setup          # pip install -r requirements-dev.txt
$ make hooks          # git config core.hooksPath .githooks
$ make check
```

`make setup` installs `ruff`, `mypy`, `coverage`, and `yamllint`. Install
`markdownlint-cli2` (`npm install -g markdownlint-cli2`), `actionlint`, and
`git-cliff` (`cargo install git-cliff`, or a release binary) for `make docs`
and `make changelog`.

## Checks

```console
$ make lint           # ruff, shellcheck, yamllint
$ make format-check   # ruff format --check
$ make types          # mypy --strict
$ make coverage       # unittest + coverage gate (90%)
$ make shell          # bats and shellcheck
$ make docs           # markdownlint and workflow lint
$ make check          # all of the above
```

Packaging changes need a local package build; see
[docs/packaging.md](docs/packaging.md). Keep `metadata.json`, the Debian
changelog, and the RPM spec at the same version.

CI runs the same commands. A change is not ready while a check fails, even a
warning.

## Code

- Python 3.10 or later, standard library only.
- Keep the module dependency-free at runtime; development tools belong in
  `requirements-dev.txt`.
- Follow `ruff format`. The lint rules are in `pyproject.toml`.
- Type annotations are mandatory: `mypy --strict watch.py notify.py providers.py` must pass.
- Tests live in `test/python/` and must not touch the network. Monkeypatch
  `collect`, `fetch_*`, and `post_webhook`.
- Shell behaviour lives in `install.sh` and `.githooks/commit-msg`; cover it in
  `test/shell/*.bats`.
- Channel payloads live in `notify.py`; tests mock the transport, never the
  network.
- Never log, print, or send the OpenCode key, a webhook URL, an SMTP password,
  a WhatsApp token, or an IRC password. Never commit any of them, an org ID, a
  state file, or `config.env`.

## Commits

Commits follow [AGENTS.md](AGENTS.md): imperative subject, 72-column body,
GPG signature, `Co-authored-by` and `Signed-off-by` trailers. Use a
Conventional Commit type (`feat`, `fix`, `docs`, `ci`, `test`, `refactor`);
`CHANGELOG.md` is generated from those prefixes. Do not edit the changelog by
hand. The local
`commit-msg` hook rejects a missing or malformed trailer.

## Pull requests

1. Branch from `master`.
2. Add or update tests and documentation.
3. Run `make check`.
4. Open a pull request. `master` requires a pull request, signed commits, and
   the `quality`, `tests (*)`, `bats`, and `shellcheck` checks.
5. Squash merge.
