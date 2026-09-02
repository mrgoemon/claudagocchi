#!/usr/bin/env python3
"""How much of the Claude plan's usage limits you've burned through.

Two sources, in order of preference:

  * `fetch()` asks Claude Code for the current numbers via its own `get_usage`
    control request. Real fetch, zero tokens, ~1.4s, and Claude Code keeps the
    credentials -- nothing here goes near the auth token.
  * `read()` falls back to the copy Claude Code cached in ~/.claude.json under
    `cachedUsageUtilization`. Free, but that block is written ONLY when
    `/usage` runs -- no startup fetch, no timer -- so it sits frozen for days
    on a machine where nobody types it. A stale reading still shows its number,
    with its age beside it, since an old number beats no number as long as it
    is labelled.

Not daily: a Max plan has a rolling 5-hour session window and a weekly limit,
so there is no per-day figure to report.

Nothing here writes. ~/.claude.json is Claude Code's own config, rewritten
atomically and often; we read a snapshot and keep no handle.
"""
import datetime
import json
import os
import subprocess
import time

CONFIG = os.path.expanduser("~/.claude.json")
STALE_AFTER = 3600.0            # Claude Code's own cache-acceptance threshold


def _load():
    """The cached utilization block, or None. Never raises.

    A read can land mid-rewrite and see truncated JSON, so one retry; anything
    else and we wait for the next poll rather than take the crab down with us.
    """
    for attempt in (0, 1):
        try:
            with open(CONFIG, "rb") as f:
                blob = json.load(f)
            cached = blob.get("cachedUsageUtilization")
            return cached if isinstance(cached, dict) else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            if attempt == 0:
                time.sleep(0.15)          # mid-rewrite: let it land, look again
                continue
            return None
        except (OSError, AttributeError, TypeError):
            return None
    return None


def _clock(iso):
    """`resets_at` as something short: a time if it's today, else a weekday."""
    if not iso:
        return ""
    try:
        when = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return ""
    if when.date() == datetime.date.today():
        return when.strftime("%-I:%M %p")
    return when.strftime("%a %-I:%M %p")


def _window(util, kind, fallback):
    """One limit window, preferring the `limits` array over the flat keys.

    `limits` carries the same numbers the usage bars draw, but the schema marks
    it nullish, so the flat five_hour/seven_day keys are the fallback.
    """
    for row in util.get("limits") or []:
        if isinstance(row, dict) and row.get("kind") == kind:
            pct, resets = row.get("percent"), row.get("resets_at")
            if isinstance(pct, (int, float)):
                return {"pct": float(pct), "resets": _clock(resets)}
    flat = util.get(fallback)
    if isinstance(flat, dict) and isinstance(flat.get("utilization"), (int, float)):
        return {"pct": float(flat["utilization"]), "resets": _clock(flat.get("resets_at"))}
    return None


def _pack(util, age):
    session = _window(util, "session", "five_hour")
    weekly = _window(util, "weekly_all", "seven_day")
    if session is None and weekly is None:
        return None
    return {"session": session, "weekly": weekly, "age": age,
            "stale": age is None or age > STALE_AFTER or age < 0}


def read():
    """The cached reading, however old. None if there isn't one."""
    cached = _load()
    if not cached:
        return None
    util = cached.get("utilization")
    if not isinstance(util, dict):
        return None
    fetched = cached.get("fetchedAtMs")
    age = (time.time() - fetched / 1000.0) if isinstance(fetched, (int, float)) else None
    return _pack(util, age)


def fetch(timeout=30):
    """Ask Claude Code itself for current usage. None if it can't answer.

    The cache is only written when `/usage` runs -- there is no startup fetch
    and no timer -- so on a machine where nobody types `/usage` it stays frozen
    for days. `get_usage` is Claude Code's own control request: it performs the
    real fetch, costs ZERO tokens (no model call), and leaves the credentials
    entirely to Claude Code, so nothing here ever touches the auth token.

    ANTHROPIC_API_KEY is dropped from the child: an API key outranks the
    claude.ai login, and Claude Code then reports no subscription at all
    (`rate_limits_available: false`) -- the crab sets that key for its own chat,
    so inheriting it here would silently return nothing.
    """
    if os.environ.get("CRAB_NO_USAGE_FETCH"):    # harnesses: no network, no spawn
        return None
    frame = json.dumps({"type": "control_request", "request_id": "crab",
                        "request": {"subtype": "get_usage"}}) + "\n"
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    try:
        done = subprocess.run(
            ["claude", "-p", "--verbose", "--no-session-persistence",
             "--input-format=stream-json", "--output-format=stream-json"],
            input=frame, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None                       # no claude on PATH, or it hung
    for line in done.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("type") != "control_response":
            continue
        body = (msg.get("response") or {}).get("response") or {}
        limits = body.get("rate_limits")
        if body.get("rate_limits_available") and isinstance(limits, dict):
            return _pack(limits, 0.0)
    return None


def current():
    """Current usage if Claude Code will tell us, else the last cached reading."""
    return fetch() or read()



if __name__ == "__main__":
    print(json.dumps(current(), indent=2))
