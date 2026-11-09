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

stub_tools() {
	mkdir -p bin
	cat >bin/python3 <<'EOF'
#!/bin/sh
exit 0
EOF
	cat >bin/crontab <<'EOF'
#!/bin/sh
if [ "$1" = "-l" ]; then
  exit 1
fi
cat >"$CRONTAB_OUT"
EOF
	chmod +x bin/python3 bin/crontab
	export PATH="$TMPDIR_TEST/bin:$PATH"
	export CRONTAB_OUT="$TMPDIR_TEST/cron.out"
}

write_config() {
	{
		echo 'MATTERMOST_WEBHOOK_URL="https://example.invalid/hook"'
		echo "STATE_DIR=$TMPDIR_TEST/state"
		if [[ -n "${1:-}" ]]; then
			echo "CRON_INTERVAL_MINUTES=$1"
		fi
	} >config.env
	chmod 600 config.env
}

@test "uses a 15 minute interval by default" {
	stub_tools
	write_config
	run ./install.sh
	[ "$status" -eq 0 ]
	grep -q '^\*/15 \* \* \* \*' "$CRONTAB_OUT"
}

@test "accepts a non-Mattermost channel" {
	stub_tools
	cat >config.env <<EOF
SLACK_WEBHOOK_URL="https://example.invalid/slack"
STATE_DIR=$TMPDIR_TEST/state
EOF
	chmod 600 config.env
	run ./install.sh
	[ "$status" -eq 0 ]
	grep -q '^\*/15 \* \* \* \*' "$CRONTAB_OUT"
}

@test "accepts an RSS feed as the only channel" {
	stub_tools
	cat >config.env <<EOF
RSS_FEED=$TMPDIR_TEST/feed.xml
STATE_DIR=$TMPDIR_TEST/state
EOF
	chmod 600 config.env
	run ./install.sh
	[ "$status" -eq 0 ]
	grep -q '^\*/15 \* \* \* \*' "$CRONTAB_OUT"
}

@test "accepts a custom cron interval" {
	stub_tools
	write_config 7
	run ./install.sh
	[ "$status" -eq 0 ]
	grep -q '^\*/7 \* \* \* \*' "$CRONTAB_OUT"
}

@test "accepts a zero-padded cron interval" {
	stub_tools
	write_config 05
	run ./install.sh
	[ "$status" -eq 0 ]
	grep -q '^\*/5 \* \* \* \*' "$CRONTAB_OUT"
}

@test "rejects a cron interval outside 1-59" {
	stub_tools
	write_config 60
	run ./install.sh
	[ "$status" -eq 1 ]
	[[ "$output" == *"between 1 and 59"* ]]
	[ ! -e "$CRONTAB_OUT" ]
}

@test "rejects a non-numeric cron interval" {
	stub_tools
	write_config often
	run ./install.sh
	[ "$status" -eq 1 ]
	[[ "$output" == *"must be an integer"* ]]
	[ ! -e "$CRONTAB_OUT" ]
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

@test "refuses to continue without a notification channel" {
	./install.sh >/dev/null 2>&1
	run ./install.sh
	[ "$status" -eq 1 ]
	[[ "$output" == *"at least one notification channel"* ]]
}

@test "does not call crontab before a channel is configured" {
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
