# Packaging and platforms

## Metadata

`metadata.json` follows the OpenVox module metadata shape:

| Field | Meaning |
| --- | --- |
| `name` | Package/module identifier. |
| `version` | Release version; keep it in sync with the packages and `watch.py`. |
| `author`, `summary`, `license` | Project identity. |
| `source`, `project_page`, `issues_url` | Canonical locations. |
| `dependencies` | Runtime dependencies. |
| `optional_dependencies` | Cron, flock, and desktop notification helpers. |
| `build_dependencies` | debhelper, rpm-build, git-cliff. |
| `test_dependencies` | Python, shell, and workflow checks. |
| `requirements` | Minimum interpreter. |
| `operatingsystem_support` | Tested operating systems and releases. |
| `tags` | Discovery keywords. |

The supported matrix is Debian 12/13, Ubuntu 22.04/24.04, CentOS Stream 10,
FreeBSD 13/14, and macOS 14/15. CI runs the Python suite on Debian, Ubuntu,
CentOS Stream 10, FreeBSD, and macOS; Debian and RPM packages are built on
tags.

## Package layout

Both packages install:

| Path | Content |
| --- | --- |
| `/usr/bin/opencode-spend-watch` | wrapper that runs the module with `python3` |
| `/usr/lib/opencode-spend-watch/` | `watch.py`, `notify.py`, `providers.py`, `limits.json` |
| `/usr/share/doc/opencode-spend-watch*/` | README, changelog, metadata, `config.example.env` |

The watcher reads `/etc/opencode-spend-watch/config.env` when no `config.env`
sits next to `watch.py`.

## Debian and Ubuntu

```bash
sudo apt install ./opencode-spend-watch_1.0.0_all.deb

sudo install -d -m 755 /etc/opencode-spend-watch
sudo install -m 600 -o "$USER" -g "$USER" \
  /usr/share/doc/opencode-spend-watch*/config.example.env \
  /etc/opencode-spend-watch/config.env
$EDITOR /etc/opencode-spend-watch/config.env

opencode-spend-watch check
opencode-spend-watch test-webhook
```

Add a user cron entry:

```cron
*/15 * * * * /usr/bin/flock -n "$HOME/.local/state/opencode-spend-watch/cron.lock" \
  /usr/bin/opencode-spend-watch poll >> "$HOME/.local/state/opencode-spend-watch/cron.log" 2>&1
```

Remove with `sudo apt remove opencode-spend-watch`; configuration and state stay
in `/etc/opencode-spend-watch` and the user state directory.

## CentOS Stream / RPM

```bash
sudo dnf install ./opencode-spend-watch-1.0.0-1.noarch.rpm

sudo install -d -m 755 /etc/opencode-spend-watch
sudo install -m 600 -o "$USER" -g "$USER" \
  /usr/share/doc/opencode-spend-watch*/config.example.env \
  /etc/opencode-spend-watch/config.env
$EDITOR /etc/opencode-spend-watch/config.env

opencode-spend-watch check
```

Use the same cron line. Remove with `sudo dnf remove opencode-spend-watch`.

## FreeBSD and macOS

Both run from a checkout or tarball with Python 3.10+:

```bash
git clone https://github.com/cusae/opencode-spend-watch.git
cd opencode-spend-watch
cp config.example.env config.env
chmod 600 config.env
python3 watch.py check
python3 watch.py test-webhook
```

FreeBSD: install `python311` and `flock` from packages, then use the same cron
line with the checkout path. Desktop notifications need `libnotify`.

macOS: install Python 3.12 and `flock` with Homebrew, then use cron. Desktop
notifications use `osascript`; no `notify-send` dependency. For a launchd setup,
run `python3 watch.py poll` every 15 minutes as the user.

## Building locally

```bash
# Debian/Ubuntu
sudo apt install debhelper devscripts fakeroot python3
dpkg-buildpackage -b -us -uc

# RPM (Fedora/CentOS)
dnf install rpm-build git tar gzip python3
version=$(python3 -c 'import json; print(json.load(open("metadata.json"))["version"])')
mkdir -p dist rpmbuild/SOURCES
git archive --format=tar.gz --prefix="opencode-spend-watch-$version/" \
  --output="rpmbuild/SOURCES/opencode-spend-watch-$version.tar.gz" HEAD
rpmbuild -bb packaging/rpm/opencode-spend-watch.spec --define "_topdir $PWD/rpmbuild"
```

## Release

1. Bump `version` in `metadata.json`, `VERSION` in `watch.py`, the Debian
   changelog, and the RPM spec.
2. Run `make changelog` and commit the result.
3. Merge through a pull request; the platform jobs must pass.
4. Tag the merge commit and push the tag.
5. The release workflow tests Debian, Ubuntu, CentOS, FreeBSD, and macOS,
   builds the `.deb` and `.rpm`, then publishes them with the generated notes.
