#!/usr/bin/env python3
"""OpenCode spend watcher.

Polls OpenCode's console API for exact usage in USD, keeps a local daily
history, and posts a Mattermost message every time cumulative spend in the
current billing period crosses a whole-dollar threshold.

Data sources (authenticated with the OpenCode Go key already stored locally):

  GET https://opencode.ai/zen/go/v1/usage
      Window percentages (5h / weekly / monthly) and reset timestamps.

  GET https://opencode.ai/console/api/usage/cost-by-day?range=30d
      Exact cost in microcents per UTC day.

  GET https://opencode.ai/console/api/usage/models?range=30d&page=1&pageSize=50
      Exact cost per model for the last 30 days.

No secret is written to logs or to the Mattermost message.
"""

from __future__ import annotations

import calendar
import fcntl
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

API_BASE = "https://opencode.ai"
USER_AGENT = "opencode-spend-watch/1.0"
MICROCENTS = 100_000_000  # 1 USD = 1e8 microcents
DEFAULT_CONFIG = Path(__file__).with_name("config.env")
DEFAULT_LIMITS = Path(__file__).with_name("limits.json")


def log(message: str) -> None:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
    print(f"{stamp} {message}", flush=True)


# --------------------------------------------------------------------------- config


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


class Config:
    def __init__(self, path: Path):
        env = {**os.environ, **parse_env(path)}
        home = Path.home()
        self.config_path = path
        self.webhook = env.get("MATTERMOST_WEBHOOK_URL", "").strip()
        self.plan = env.get("PLAN", "go-plus").strip()
        self.step = float(env.get("THRESHOLD_STEP_USD", "1") or "1")
        self.state_dir = Path(
            env.get("STATE_DIR", str(home / ".local/state/opencode-spend-watch"))
        ).expanduser()
        self.opencode_db = Path(
            env.get("OPENCODE_DB", str(home / ".local/share/opencode/opencode.db"))
        ).expanduser()
        self.api_key_override = env.get("OPENCODE_GO_KEY", "").strip()
        self.startup_message = env.get("STARTUP_MESSAGE", "true").lower() == "true"
        self.reset_message = env.get("RESET_MESSAGE", "true").lower() == "true"
        self.console_url = env.get("CONSOLE_URL", "").strip()
        self.limits_path = Path(env.get("LIMITS_FILE", str(DEFAULT_LIMITS))).expanduser()

    def limits(self) -> dict[str, float]:
        try:
            data = json.loads(self.limits_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        plan = data.get(self.plan, {})
        models = plan.get("models", {})
        return {
            name: float(limit) for name, limit in models.items() if isinstance(limit, (int, float))
        }

    def labels(self) -> dict[str, str]:
        try:
            data = json.loads(self.limits_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        labels = data.get("labels", {})
        return {str(k): str(v) for k, v in labels.items()} if isinstance(labels, dict) else {}


# --------------------------------------------------------------------------- auth


def opencode_go_key(config: Config) -> str:
    if config.api_key_override:
        return config.api_key_override

    if config.opencode_db.exists():
        try:
            con = sqlite3.connect(f"file:{config.opencode_db}?mode=ro", uri=True)
            row = con.execute(
                "select json_extract(value,'$.key') from credential "
                "where integration_id='opencode-go' limit 1"
            ).fetchone()
            con.close()
            if row and row[0]:
                return str(row[0]).strip()
        except sqlite3.Error as exc:
            log(f"cannot read OpenCode credential database: {exc}")

    auth = (
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        / "opencode"
        / "auth.json"
    )
    try:
        body = json.loads(auth.read_text(encoding="utf-8"))
        entry = body.get("opencode-go", {})
        if isinstance(entry, dict) and entry.get("key"):
            return str(entry["key"]).strip()
    except (OSError, ValueError):
        pass
    raise RuntimeError("No OpenCode Go key found. Connect OpenCode Go, or set OPENCODE_GO_KEY.")


# --------------------------------------------------------------------------- api


def api_json(path: str, key: str, timeout: int = 25):
    url = f"{API_BASE}{path}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read()[:200].decode("utf-8", "replace")
        raise RuntimeError(f"{path} -> HTTP {exc.code}: {body}") from None


def fetch_windows(key: str) -> dict:
    body = api_json("/zen/go/v1/usage", key)
    usage = body.get("usage", {}) if isinstance(body, dict) else {}
    windows = {}
    for field in ("rolling", "weekly", "monthly"):
        entry = usage.get(field)
        if isinstance(entry, dict):
            windows[field] = {
                "percent": float(entry.get("percent") or 0),
                "status": entry.get("status"),
                "resets_at": parse_iso(entry.get("resetsAt")),
            }
    return windows


def fetch_daily(key: str) -> dict[str, float]:
    body = api_json("/console/api/usage/cost-by-day?range=30d", key)
    days: dict[str, float] = {}
    if isinstance(body, list):
        for entry in body:
            try:
                days[str(entry["date"])] = int(entry["totalCostMicroCents"]) / MICROCENTS
            except (KeyError, TypeError, ValueError):
                continue
    return days


def fetch_models(key: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    while page <= 5:
        body = api_json(f"/console/api/usage/models?range=30d&page={page}&pageSize=50", key)
        if not isinstance(body, dict):
            break
        batch = body.get("items") or []
        for entry in batch:
            try:
                items.append(
                    {
                        "provider": entry.get("provider", ""),
                        "model": entry.get("model", "?"),
                        "cost": int(entry.get("totalCostMicroCents") or 0) / MICROCENTS,
                        "requests": int(entry.get("totalRequests") or 0),
                    }
                )
            except (TypeError, ValueError):
                continue
        info = body.get("pageInfo") or {}
        if page >= int(info.get("pageCount") or 1):
            break
        page += 1
    return items


def parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def subtract_month(moment: datetime) -> datetime:
    year, month = moment.year, moment.month - 1
    if month == 0:
        year, month = year - 1, 12
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


# --------------------------------------------------------------------------- stats


def collect(config: Config, stored_days: dict[str, float]) -> dict:
    key = opencode_go_key(config)
    windows = fetch_windows(key)
    fresh_days = fetch_daily(key)

    days = dict(stored_days)
    days.update(fresh_days)

    monthly_reset = (windows.get("monthly") or {}).get("resets_at")
    if monthly_reset is None:
        now = datetime.now(timezone.utc)
        year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        monthly_reset = now.replace(
            year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    period_start = subtract_month(monthly_reset)

    start_day = period_start.date()
    period_days = {day: cost for day, cost in days.items() if start_day <= date.fromisoformat(day)}
    period_total = sum(period_days.values())
    today = datetime.now(timezone.utc).date()
    today_cost = days.get(today.isoformat(), 0.0)
    last7 = sum(
        cost for day, cost in days.items() if date.fromisoformat(day) > today - timedelta(days=7)
    )

    models = fetch_models(key)
    limits = config.limits()
    rated = []
    for item in models:
        limit = limits.get(item["model"])
        if limit and item["cost"] > 0:
            rated.append({**item, "limit": limit, "remaining": max(limit - item["cost"], 0.0)})
    closest = min(rated, key=lambda m: m["remaining"] / m["limit"]) if rated else None

    return {
        "windows": windows,
        "days": days,
        "period_start": period_start,
        "period_end": monthly_reset,
        "period_total": period_total,
        "today": today_cost,
        "last7": last7,
        "models": sorted(models, key=lambda m: m["cost"], reverse=True),
        "closest": closest,
        "coverage_gap": bool(period_days) and date.fromisoformat(min(period_days)) > start_day,
    }


# --------------------------------------------------------------------------- message


def money(value: float) -> str:
    return f"${value:,.2f}"


def format_moment(moment: datetime | None) -> str:
    if moment is None:
        return "unknown"
    return moment.strftime("%d %b %Y %H:%M UTC")


def format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f}%"


def build_message(
    stats: dict,
    crossed_from: float | None,
    crossed_to: float | None,
    config: Config,
    kind: str = "threshold",
) -> str:
    windows = stats["windows"]
    monthly = windows.get("monthly") or {}
    weekly = windows.get("weekly") or {}
    rolling = windows.get("rolling") or {}
    monthly_used = monthly.get("percent")
    monthly_left = None if monthly_used is None else max(100.0 - monthly_used, 0.0)

    if kind == "startup":
        title = "**OpenCode spend watcher started**"
        lead = (
            f"Tracking from **{money(stats['period_total'])}** this billing period. "
            f"Next alert at the next ${config.step:.0f}."
        )
    elif kind == "reset":
        title = "**OpenCode billing period reset**"
        lead = "Usage counters restart at zero. Threshold alerts are armed again."
    elif kind == "report":
        title = "**OpenCode spend — current status**"
        lead = f"**{money(stats['period_total'])}** used this billing period."
    else:
        title = "**OpenCode spend — threshold reached**"
        if (
            crossed_from is not None
            and crossed_to is not None
            and crossed_to - crossed_from > config.step
        ):
            lead = (
                f"**{money(stats['period_total'])}** used this period "
                f"(crossed {money(crossed_from)}–{money(crossed_to)})."
            )
        elif crossed_to is not None:
            lead = (
                f"**{money(stats['period_total'])}** used this period "
                f"(crossed {money(crossed_to)})."
            )
        else:
            lead = f"**{money(stats['period_total'])}** used this period."

    lines = [
        title,
        lead,
        "",
        f"Billing period: {format_moment(stats['period_start'])} → "
        f"{format_moment(stats['period_end'])}",
        f"Monthly allowance: **{format_percent(monthly_used)} used**, "
        f"{format_percent(monthly_left)} left",
        f"Windows: 5-hour {format_percent(rolling.get('percent'))} · "
        f"weekly {format_percent(weekly.get('percent'))} · "
        f"monthly {format_percent(monthly_used)}",
        "",
        f"Today (UTC): **{money(stats['today'])}** · last 7 days: **{money(stats['last7'])}**",
    ]

    top = [m for m in stats["models"] if m["cost"] > 0][:3]
    labels = config.labels()
    if top:
        lines.append(
            "Top models (30d): "
            + " · ".join(f"{labels.get(m['model'], m['model'])} {money(m['cost'])}" for m in top)
        )

    closest = stats.get("closest")
    if closest:
        lines.append(
            f"Closest limit: **{labels.get(closest['model'], closest['model'])}** — "
            f"{money(closest['remaining'])} left of {money(closest['limit'])} "
            f"({100 * closest['remaining'] / closest['limit']:.0f}%)"
        )

    if stats.get("coverage_gap"):
        lines.append("_Note: the first day of this period is older than the 30-day API window._")

    if config.console_url:
        lines += ["", f"[Open the console]({config.console_url})"]

    return "\n".join(lines)


# --------------------------------------------------------------------------- delivery


def post_webhook(url: str, text: str, attempts: int = 3) -> bool:
    payload = json.dumps(
        {
            "text": text,
            "username": "OpenCode Spend",
            "icon_emoji": ":money_with_wings:",
        }
    ).encode("utf-8")
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if 200 <= response.status < 300:
                    return True
                log(f"Mattermost returned HTTP {response.status}")
        except (urllib.error.URLError, OSError) as exc:
            log(f"Mattermost delivery failed (attempt {attempt}/{attempts}): {exc}")
        if attempt < attempts:
            time.sleep(2)
    return False


# --------------------------------------------------------------------------- state


class Store:
    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.lock_path = self.dir / "state.lock"

    def locked(self):
        store = self

        class _Lock:
            def __enter__(self):
                self.handle = open(store.lock_path, "w")
                fcntl.flock(self.handle, fcntl.LOCK_EX)
                return store

            def __exit__(self, *exc):
                fcntl.flock(self.handle, fcntl.LOCK_UN)
                self.handle.close()

        return _Lock()

    def load(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.state_path)


# --------------------------------------------------------------------------- cycle


def poll(config: Config) -> int:
    if not config.webhook:
        log("MATTERMOST_WEBHOOK_URL is not set; cannot send alerts.")
        return 2

    store = Store(config.state_dir)
    with store.locked():
        state = store.load()
        try:
            stats = collect(config, state.get("daily", {}))
        except RuntimeError as exc:
            log(str(exc))
            return 1

        period_end = stats["period_end"].isoformat()
        new_period = state.get("period_end") != period_end
        if new_period and state.get("period_end"):
            if config.reset_message and not post_webhook(
                config.webhook, build_message(stats, None, None, config, "reset")
            ):
                log("reset message failed; will retry on next run")
                return 1
            state = {
                "period_end": period_end,
                "daily": state.get("daily", {}),
                "initialized": True,
                "last_level": 0,
            }

        if not state.get("initialized"):
            if config.startup_message and not post_webhook(
                config.webhook, build_message(stats, None, None, config, "startup")
            ):
                log("startup message failed; will retry on next run")
                return 1
            state.update(
                {
                    "period_end": period_end,
                    "initialized": True,
                    "daily": stats["days"],
                    "last_level": int(stats["period_total"] / config.step),
                }
            )
            store.save(state)
            log(f"initialized at {money(stats['period_total'])}")
            return 0

        merged = dict(state.get("daily", {}))
        merged.update(stats["days"])
        stats["days"] = merged
        level = int(stats["period_total"] / config.step)
        last_level = int(state.get("last_level", 0))
        state.update({"daily": merged, "period_end": period_end})

        if level > last_level:
            crossed_from = last_level * config.step
            crossed_to = level * config.step
            text = build_message(stats, crossed_from, crossed_to, config)
            if not post_webhook(config.webhook, text):
                store.save(state)
                log("alert not delivered; level not advanced, will retry")
                return 1
            state["last_level"] = level
            store.save(state)
            log(f"alert sent: {money(crossed_to)} ({money(stats['period_total'])})")
            return 0

        store.save(state)
        log(f"no change: {money(stats['period_total'])} (level {level})")
        return 0


def report(config: Config) -> int:
    store = Store(config.state_dir)
    with store.locked():
        state = store.load()
        try:
            stats = collect(config, state.get("daily", {}))
        except RuntimeError as exc:
            log(str(exc))
            return 1

    print(build_message(stats, None, None, config, "report"))
    print()
    for item in stats["models"]:
        if item["cost"] > 0:
            print(
                f"  {item['provider']}/{item['model']}: {money(item['cost'])} "
                f"({item['requests']} requests)"
            )
    return 0


def check(config: Config) -> int:
    key = opencode_go_key(config)
    print(f"key: found (len {len(key)})")
    try:
        windows = fetch_windows(key)
        days = fetch_daily(key)
        models = fetch_models(key)
    except RuntimeError as exc:
        print(f"api: FAIL {exc}")
        return 1
    print("api: ok")
    cleaned = {k: {**v, "resets_at": str(v["resets_at"])} for k, v in windows.items()}
    print(f"windows: {json.dumps(cleaned)}")
    print(f"daily: {len(days)} days, total {money(sum(days.values()))}")
    print(f"models: {len(models)}")
    print(f"webhook: {'set' if config.webhook else 'MISSING'}")
    print(f"plan: {config.plan} ({len(config.limits())} model limits)")
    return 0


def test_webhook(config: Config) -> int:
    if not config.webhook:
        print("MATTERMOST_WEBHOOK_URL is not set.")
        return 2
    text = (
        "**OpenCode spend watcher — test message**\n"
        f"If you can read this, alerts will arrive in this channel every "
        f"${config.step:.0f} of OpenCode usage."
    )
    ok = post_webhook(config.webhook, text, attempts=1)
    print("sent" if ok else "failed")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "poll"
    config_path = Path(os.environ.get("OSW_CONFIG", DEFAULT_CONFIG)).expanduser()
    config = Config(config_path)

    if command == "poll":
        return poll(config)
    if command == "check":
        return check(config)
    if command == "report":
        return report(config)
    if command == "test-webhook":
        return test_webhook(config)
    if command == "daemon":
        interval = int(os.environ.get("OSW_INTERVAL", "300"))
        while True:
            poll(config)
            time.sleep(interval)
    print(
        "usage: watch.py [poll|check|report|test-webhook|daemon]\n"
        "  poll          one collection + alert cycle (use from cron)\n"
        "  check         validate key, APIs and configuration\n"
        "  report        print current statistics without sending\n"
        "  test-webhook  send one test message\n"
        "  daemon        poll every OSW_INTERVAL seconds (default 300)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
