#!/usr/bin/env bats
#
# Shellcheck must accept every shell script in the repository.

setup() {
	REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
}

@test "shellcheck install.sh" {
	run shellcheck "$REPO_ROOT/install.sh"
	[ "$status" -eq 0 ]
}

@test "shellcheck the commit hook" {
	run shellcheck "$REPO_ROOT/.githooks/commit-msg"
	[ "$status" -eq 0 ]
}

@test "bash parses install.sh" {
	run bash -n "$REPO_ROOT/install.sh"
	[ "$status" -eq 0 ]
}
