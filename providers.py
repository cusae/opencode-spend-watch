"""Cost providers other than OpenCode Go.

OpenRouter and OpenAI expose spend or credit APIs that do not require a browser
session. Each provider returns a snapshot; the caller owns state and delivery.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

USER_AGENT = "opencode-spend-watch/1.0"


class ProviderError(RuntimeError):
    """A provider API failed or returned an unusable payload."""


@dataclass(frozen=True)
class Snapshot:
    name: str
    label: str
    spend: float
    budget: float | None
    remaining: float | None
    period_key: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    detail: str = ""


def _get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read()[:200].decode("utf-8", "replace")
        raise ProviderError(f"HTTP {exc.code}: {body}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ProviderError(str(exc)) from None


def openrouter(key: str, budget: float = 0.0) -> Snapshot:
    body = _get_json(
        "https://openrouter.ai/api/v1/credits",
        {"Authorization": f"Bearer {key}"},
    )
    try:
        data = body["data"]
        credits = float(data["total_credits"])
        usage = float(data["total_usage"])
    except (KeyError, TypeError, ValueError):
        raise ProviderError("OpenRouter returned no credits") from None
    limit = budget if budget > 0 else credits
    remaining = limit - usage
    return Snapshot(
        name="openrouter",
        label="OpenRouter",
        spend=usage,
        budget=limit if limit > 0 else None,
        remaining=remaining,
        period_key="lifetime",
        detail="cumulative usage against purchased credits",
    )


def _month_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def openai(key: str, budget: float = 0.0, org: str = "") -> Snapshot:
    now = datetime.now(timezone.utc)
    start, end = _month_bounds(now)
    headers = {"Authorization": f"Bearer {key}"}
    if org:
        headers["OpenAI-Organization"] = org
    total = 0.0
    page = None
    for _ in range(12):
        query = (
            f"start_time={int(start.timestamp())}&end_time={int(now.timestamp())}"
            "&bucket_width=1d&limit=31"
        )
        if page:
            query += f"&page={page}"
        body = _get_json(f"https://api.openai.com/v1/organization/costs?{query}", headers)
        for bucket in body.get("data", []):
            for result in bucket.get("results", []):
                amount = result.get("amount", {})
                try:
                    total += float(amount.get("value", 0))
                except (TypeError, ValueError):
                    continue
        if not body.get("has_more"):
            break
        page = body.get("next_page")
        if not page:
            break
    return Snapshot(
        name="openai",
        label="OpenAI",
        spend=total,
        budget=budget if budget > 0 else None,
        remaining=budget - total if budget > 0 else None,
        period_key=start.strftime("%Y-%m"),
        period_start=start,
        period_end=end,
        detail="organization costs for the current month",
    )


def collect(config: Any) -> tuple[list[Snapshot], list[str]]:
    snapshots: list[Snapshot] = []
    errors: list[str] = []
    for name in config.providers:
        if name == "opencode":
            continue
        try:
            if name == "openrouter":
                if not config.openrouter_key:
                    raise ProviderError("OPENROUTER_API_KEY is not set")
                snapshots.append(openrouter(config.openrouter_key, config.openrouter_budget))
            elif name == "openai":
                if not config.openai_key:
                    raise ProviderError("OPENAI_ADMIN_KEY is not set")
                snapshots.append(openai(config.openai_key, config.openai_budget, config.openai_org))
            else:
                raise ProviderError(f"unknown provider {name!r}")
        except ProviderError as exc:
            errors.append(f"{name}: {exc}")
    return snapshots, errors
