"""Merge new options from a template into an existing environment file.

Existing assignments are never modified. Missing assignments are appended
under a short section marker, and the original file is backed up first.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path

ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
MARKER = "# Added by merge-config from the example; review before use."


def assignments(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = ASSIGNMENT.match(line)
        if match:
            found[match.group(1)] = line
    return found


def merge(example: str, current: str) -> tuple[str, list[str]]:
    existing = assignments(current)
    missing: list[str] = []
    for line in example.splitlines():
        match = ASSIGNMENT.match(line)
        if not match:
            continue
        name = match.group(1)
        if name in existing:
            continue
        existing[name] = line
        missing.append(line)
    if not missing:
        return current, []
    text = current
    if text and not text.endswith("\n"):
        text += "\n"
    if text:
        text += "\n"
    text += MARKER + "\n" + "\n".join(missing) + "\n"
    names = []
    for line in missing:
        match = ASSIGNMENT.match(line)
        if match:
            names.append(match.group(1))
    return text, names


def default_example() -> Path:
    local = Path(__file__).with_name("config.example.env")
    if local.exists():
        return local
    for candidate in Path("/usr/share/doc").glob("opencode-spend-watch*/config.example.env"):
        return candidate
    return local


def default_target() -> Path:
    local = Path(__file__).with_name("config.env")
    system = Path("/etc/opencode-spend-watch/config.env")
    if local.exists():
        return local
    if system.exists():
        return system
    return local


def backup_path(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return target.with_name(f"{target.name}.bak.{stamp}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="watch.py merge-config",
        description="Add missing options to an existing config.env without changing values.",
    )
    parser.add_argument("--dry-run", action="store_true", help="print only, write nothing")
    parser.add_argument("example", nargs="?", type=Path, default=None)
    parser.add_argument("target", nargs="?", type=Path, default=None)
    args = parser.parse_args(argv)

    example = args.example or default_example()
    target = args.target or default_target()
    if not example.exists():
        print(f"example not found: {example}", file=sys.stderr)
        return 1
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, target)
        target.chmod(0o600)
        print(f"created {target} from {example}")
        return 0

    before = target.read_text(encoding="utf-8")
    after, added = merge(example.read_text(encoding="utf-8"), before)
    if not added:
        print(f"no missing options in {target}")
        return 0
    print(f"add {len(added)} option(s) to {target}:")
    for name in added:
        print(f"  {name}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    backup = backup_path(target)
    shutil.copy2(target, backup)
    mode = stat.S_IMODE(target.stat().st_mode)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(after, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, target)
    print(f"backup: {backup}")
    print(f"updated: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
