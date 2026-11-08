#!/usr/bin/env bats
#
# install.sh only touches the crontab after the configuration is complete.

setup() {
	REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
	TMPDIR_TEST="$(mktemp -d)"
	cp "$REPO_ROOT/install.sh" "$REPO_ROOT/config.example.env" "$TMPDIR_TEST/"
	cd "$TMPDIR_TEST" || exit 1
}

teardown() {
	rm -rf "$TMPDIR_TEST"
}

@test "creates config.env with mode 600 on first run" {
	run ./install.sh
	[ "$status" -eq 0 ]
	[ -f config.env ]
	[ "$(stat -c '%a' config.env)" = "600" ]
	[[ "$output" == *"Created"* ]]
}

@test "does not overwrite an existing config.env" {
	printf 'SENTINEL=yes\n' >config.env
	chmod 600 config.env
	run ./install.sh
	[ "$status" -eq 1 ]
	grep -q '^SENTINEL=yes$' config.env
}

@test "refuses to continue while the webhook is empty" {
	./install.sh >/dev/null 2>&1
	run ./install.sh
	[ "$status" -eq 1 ]
	[[ "$output" == *"MATTERMOST_WEBHOOK_URL is empty"* ]]
}

@test "does not call crontab before the webhook is set" {
	mkdir -p bin
	cat >bin/crontab <<'EOF'
#!/bin/sh
: >"$CRONTAB_CALLED"
exit 1
EOF
	chmod +x bin/crontab
	export CRONTAB_CALLED="$TMPDIR_TEST/crontab-called"
	export PATH="$TMPDIR_TEST/bin:$PATH"

	run ./install.sh
	[ "$status" -eq 0 ]
	[ ! -e "$CRONTAB_CALLED" ]

	run ./install.sh
	[ "$status" -eq 1 ]
	[ ! -e "$CRONTAB_CALLED" ]
}
