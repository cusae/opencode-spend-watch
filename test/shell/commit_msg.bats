#!/usr/bin/env bats
#
# The commit hook enforces the trailers documented in AGENTS.md.

setup() {
	REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
	HOOK="$REPO_ROOT/.githooks/commit-msg"
	TMPDIR_TEST="$(mktemp -d)"
	cd "$TMPDIR_TEST" || exit 1
	git init -q
	git config user.name "Test User"
	git config user.email "test@example.com"
}

teardown() {
	rm -rf "$TMPDIR_TEST"
}

write_message() {
	cat >"$1"
}

@test "accepts a commit with both trailers" {
	write_message msg <<'EOF'
feat: add a watcher

Explain the change.

Co-authored-by: Agent <agent@opencode.ai>
Signed-off-by: Test User <test@example.com>
EOF
	run "$HOOK" msg
	[ "$status" -eq 0 ]
}

@test "rejects a commit without Co-authored-by" {
	write_message msg <<'EOF'
feat: add a watcher

Signed-off-by: Test User <test@example.com>
EOF
	run "$HOOK" msg
	[ "$status" -ne 0 ]
	[[ "$output" == *"Co-authored-by"* ]]
}

@test "rejects a commit without Signed-off-by" {
	write_message msg <<'EOF'
feat: add a watcher

Co-authored-by: Agent <agent@opencode.ai>
EOF
	run "$HOOK" msg
	[ "$status" -ne 0 ]
	[[ "$output" == *"Signed-off-by"* ]]
}

@test "rejects a sign-off that does not match the committer" {
	write_message msg <<'EOF'
feat: add a watcher

Co-authored-by: Agent <agent@opencode.ai>
Signed-off-by: Somebody Else <other@example.com>
EOF
	run "$HOOK" msg
	[ "$status" -ne 0 ]
	[[ "$output" == *"does not match"* ]]
}

@test "rejects a malformed Co-authored-by trailer" {
	write_message msg <<'EOF'
feat: add a watcher

Co-authored-by: Agent
Signed-off-by: Test User <test@example.com>
EOF
	run "$HOOK" msg
	[ "$status" -ne 0 ]
}
