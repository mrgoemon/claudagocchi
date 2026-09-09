#!/usr/bin/env python3
"""Claudagocchi v2.0 — watching your other agent sessions.

The crab notices when a Claude Code or Codex session is blocked waiting on you,
so a permission prompt in another terminal doesn't sit unanswered for an hour.

Claude Code writes a status file per live session at ~/.claude/sessions/<PID>.json:

    {"pid": 94608, "sessionId": "...", "cwd": "/Users/you", "name": "myproject",
     "kind": "interactive", "status": "waiting", "waitingFor": "permission prompt",
     "procStart": "Thu Aug 13 05:34:44 2026", "updatedAt": 1786603969303}

That is level-triggered and self-healing: start the crab mid-turn and it still
reads correctly, unlike hook-based edge triggers which desync if you miss one.

Three things this file is careful about, each learned the hard way:

  * `procStart` is UTC, but `ps -o lstart=` prints LOCAL time. Comparing them as
    strings marks every session dead. They are parsed to epoch and compared.
  * `shell` is not idle. A session idle for the model but running a foreground
    shell command reports "shell" -- treat it as working, or the crab nags you
    all the way through a long build.
  * an unrecognised status is "unknown", never "idle". This is an undocumented
    internal contract and the vocabulary can change between Claude Code versions.

Codex has no equivalent status file. Its rollout logs give busy-vs-idle (by
balancing task_started against task_complete) but expose no approval-request
event at all, so a Codex session blocked on approval is indistinguishable from
an idle one. Codex rows are therefore marked approximate and never trigger an
alert -- they would fire constantly on merely-idle sessions.

Pure stdlib. Every function is read-only and swallows its own errors: a pet
should never crash because a log format drifted.
"""
import os
import json
import glob
import time
import calendar
import subprocess
import pathlib

CLAUDE_SESSIONS = pathlib.Path.home() / ".claude" / "sessions"
CLAUDE_HOOK_STATE = pathlib.Path.home() / ".claude" / "state" / "crab.json"
CODEX_SESSIONS = pathlib.Path.home() / ".codex" / "sessions"

PS_FMT = "%a %b %d %H:%M:%S %Y"
PROC_START_TOLERANCE = 5.0        # seconds; ps and the JSON round differently

# status -> what the crab should do about it
WAITING = "waiting"               # blocked on a human
WORKING = "working"               # busy, or running a shell command
IDLE    = "idle"                  # turn finished, nothing pending
UNKNOWN = "unknown"               # unrecognised: never assume it's fine

_CLAUDE_STATUS = {"waiting": WAITING, "busy": WORKING, "shell": WORKING, "idle": IDLE}


def _proc_start_epoch(pid):
    """Process start time from ps, as a LOCAL-time epoch. None if it's gone."""
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5).stdout
        out = " ".join(out.split())          # ps pads its output
        if not out:
            return None
        return time.mktime(time.strptime(out, PS_FMT))
    except (OSError, subprocess.SubprocessError):    # no ps, or it hung (TimeoutExpired)
        return None
    except (ValueError, OverflowError):              # ps printed a shape we don't parse
        return None


def _is_live(pid, proc_start):
    """True if `pid` is running AND is the same process the file describes.

    The PID check alone is not enough -- PIDs get reused, which is exactly why
    Claude Code records procStart. Note procStart is UTC while ps prints local
    time, so these must be compared as epochs, not as strings.
    """
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:                          # gone (ProcessLookupError) or not ours
        return False
    except TypeError:                        # pid came out of the log; may not be an int
        return False
    if not proc_start:
        return True                          # process is up; nothing to cross-check
    ps_epoch = _proc_start_epoch(pid)
    if ps_epoch is None:
        return False
    try:
        js_epoch = calendar.timegm(time.strptime(proc_start, PS_FMT))
    except (ValueError, TypeError):          # wrong format, or not a string at all
        return True                          # unparseable: trust the live PID
    return abs(ps_epoch - js_epoch) < PROC_START_TOLERANCE


def _short_cwd(cwd):
    try:
        return pathlib.Path(cwd).name or cwd
    except (TypeError, ValueError):          # cwd is None, or not a path-like at all
        return cwd or "?"


def scan_claude(skip_pid=None):
    """Live Claude Code sessions and what each is doing."""
    out = []
    try:
        files = sorted(CLAUDE_SESSIONS.glob("*.json"))
    except OSError:                          # no ~/.claude/sessions, or unreadable
        return out
    for f in files:
        try:
            rec = json.loads(f.read_text())
        except OSError:                      # the session ended and took its file
            continue
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue                         # half-written: it's rewritten every turn
        if not isinstance(rec, dict):        # valid json, wrong shape; not ours to read
            continue
        pid = rec.get("pid")
        if not pid or pid == skip_pid:
            continue
        if not _is_live(pid, rec.get("procStart")):
            continue                         # stale file from a session that ended
        raw = rec.get("status")
        out.append({
            "source": "claude",
            "id": rec.get("sessionId") or str(pid),
            "pid": pid,
            "name": rec.get("name") or _short_cwd(rec.get("cwd")),
            "cwd": rec.get("cwd") or "",
            "status": _CLAUDE_STATUS.get(raw, UNKNOWN),
            "raw_status": raw,
            "waiting_for": rec.get("waitingFor") or "",
            "since": (rec.get("statusUpdatedAt") or rec.get("updatedAt") or 0) / 1000.0,
            "approx": False,
        })
    return out


def _newest_rollout():
    try:
        files = glob.glob(str(CODEX_SESSIONS / "*" / "*" / "*" / "rollout-*.jsonl"))
        return max(files, key=os.path.getmtime) if files else None
    except OSError:                          # no ~/.codex, or a file vanished mid-scan
        return None


CODEX_STALE_SEC = 15 * 60         # a rollout untouched this long isn't a live turn


def scan_codex():
    """Best-effort Codex status from its newest rollout log.

    Only busy-vs-idle is derivable: an unbalanced task_started/task_complete pair
    at the tail means a turn is in flight. There is no approval-request event in
    these logs, so a Codex session blocked on an approval prompt looks exactly
    like an idle one -- which is why these rows are marked approximate and are
    never allowed to raise an alert.
    """
    path = _newest_rollout()
    if not path:
        return []
    try:
        mtime = os.path.getmtime(path)
        if time.time() - mtime > CODEX_STALE_SEC:
            return []                        # nothing has happened in a while
        started = complete = 0
        session_id = cwd = ""
        with open(path) as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue                 # the tail line is still being written
                payload = o.get("payload") or {}
                t = payload.get("type")
                if t == "task_started":
                    started += 1
                elif t == "task_complete":
                    complete += 1
                elif t == "session_meta":
                    session_id = payload.get("session_id") or session_id
                    cwd = payload.get("cwd") or cwd
    except Exception:
        # Deliberately broad. Unlike Claude Code's status file, a rollout record has
        # no contract we can lean on -- `payload` is whatever Codex wrote, so any
        # entry may not be an object at all. Codex rows are a nice-to-have that can
        # never raise an alert, so dropping the lot beats guessing at exception types.
        return []
    return [{
        "source": "codex",
        "id": session_id or path,
        "pid": None,
        "name": f"codex:{_short_cwd(cwd)}" if cwd else "codex",
        "cwd": cwd,
        "status": WORKING if started > complete else IDLE,
        "raw_status": None,
        "waiting_for": "",
        "since": mtime,
        "approx": True,                      # busy/idle only; can't see approvals
    }]


def scan_hook():
    """The CrabCodeBar hook file, read-only, as a low-latency hint.

    It is single-slot -- one global session_id -- so it can only ever accelerate
    a reaction, never enumerate sessions. Polling stays the source of truth.
    """
    try:
        return json.loads(CLAUDE_HOOK_STATE.read_text())
    except OSError:                          # the hook isn't installed; that's normal
        return None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None                          # caught it mid-write; the poll covers us


DEMO = None      # admin mode injects a canned reading here; None in normal use


def poll(skip_pid=None, include_codex=True):
    """Everything the crab needs to know about your other sessions."""
    if DEMO is not None:                 # admin mode: don't read the real sessions
        return DEMO
    sessions = scan_claude(skip_pid)
    if include_codex:
        sessions += scan_codex()
    # Only Claude sessions can raise an alert; see scan_codex.
    waiting = [s for s in sessions if s["status"] == WAITING and not s["approx"]]
    working = sum(1 for s in sessions if s["status"] == WORKING)
    idle = sum(1 for s in sessions if s["status"] == IDLE)
    return {"waiting": waiting, "working": working, "idle": idle, "all": sessions}


def alert_key(sess):
    """Identity of one 'a human is needed' moment, for rising-edge dedupe."""
    return f"{sess['id']}:{sess.get('waiting_for', '')}"


if __name__ == "__main__":
    import pprint
    pprint.pprint(poll(skip_pid=os.getppid()))
