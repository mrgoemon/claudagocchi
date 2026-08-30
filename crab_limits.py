#!/usr/bin/env python3
"""How much of the Claude plan's usage limits you've burned through.

Claude Code caches its own `/usage` response -- the numbers behind the usage
bars -- in ~/.claude.json under `cachedUsageUtilization`. Reading that costs
nothing and needs no credentials.

Two things it is NOT:

  * Not live. The cache is only rewritten when Claude Code itself fetches it,
    throttled to once every 5 minutes, and in practice it can sit unrefreshed
    for many hours. Past Claude Code's own one-hour acceptance threshold we
    mark the reading `stale` and the bar shows its age beside it -- the number
    is still the best one available, it just isn't current. Refreshing it
    ourselves would mean calling a private endpoint with the user's OAuth token.
  * Not daily. A Max plan has a rolling 5-hour session window and a weekly
    limit; there is no per-day limit to report.

Nothing here writes: ~/.claude.json is Claude Code's own config, rewritten
atomically and often. We read a snapshot and keep no handle.
"""
import datetime
import json
import os
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
        return when.strftime("%-I:%M%p").lower()
    return when.strftime("%a")


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


def read():
    """{'session': {...}, 'weekly': {...}, 'stale': bool} -- or None if unknown."""
    cached = _load()
    if not cached:
        return None
    util = cached.get("utilization")
    if not isinstance(util, dict):
        return None
    session = _window(util, "session", "five_hour")
    weekly = _window(util, "weekly_all", "seven_day")
    if session is None and weekly is None:
        return None
    fetched = cached.get("fetchedAtMs")
    age = (time.time() - fetched / 1000.0) if isinstance(fetched, (int, float)) else None
    return {"session": session, "weekly": weekly, "age": age,
            "stale": age is None or age > STALE_AFTER or age < 0}



if __name__ == "__main__":
    print(json.dumps(read(), indent=2))
