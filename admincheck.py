#!/usr/bin/env python3
"""Run every admin scenario under a pty and check it behaves.

Admin mode exists to trigger the destructive and time-based paths, so it is worth
proving that (a) none of them crash, (b) the animated ones still redraw at a
single constant height, and (c) none of them touch the real save.
"""
import json
import os
import pty
import re
import signal
import sys
import time
import pathlib

import crab_admin

REAL_STATE = pathlib.Path.home() / ".claude-crab" / "state.json"

# Byte-comparing the real save is useless as a guard: a live `crab --animate`
# rewrites it every four seconds, and vitals legitimately drift the whole time.
# What no ordinary run ever changes is the crab's IDENTITY -- its name, which
# generation it is, and how many ancestors it has. Admin mode kills, graduates and
# hatches crabs constantly, so if any of those moved, a scenario escaped its
# sandbox. (An earlier version of this guard looked for v2.0 keys in the save,
# which stopped meaning anything the moment the real crab was itself on v2.0.)
def identity():
    if not REAL_STATE.exists():
        return None
    try:
        s = json.loads(REAL_STATE.read_text())
    except Exception:
        return None
    return (s.get("name"), s.get("generation"), len(s.get("graveyard", [])))


def run(scenario, seconds):
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["COLUMNS"] = "100"
        os.environ["CRAB_NO_USAGE_FETCH"] = "1"
        os.execvp("python3", ["python3", "pixel_crab.py", "--admin", scenario])
    buf, t0 = b"", time.time()
    while time.time() - t0 < seconds:
        try:
            d = os.read(fd, 65536)
        except OSError:
            break
        if not d:
            break
        buf += d
    for sig in (signal.SIGINT, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except Exception:
            pass
        time.sleep(0.3)
        try:
            buf += os.read(fd, 400000)
        except Exception:
            pass
        if os.waitpid(pid, os.WNOHANG)[0]:
            break
    try:
        os.close(fd)
    except Exception:
        pass
    return buf


def main():
    before = identity()
    bad = 0
    for name, (_desc, secs) in crab_admin.SCENARIOS.items():
        wait = 6 if secs else 4          # long scenarios only need a sample
        buf = run(name, wait)
        text = buf.decode("utf-8", "ignore")
        codes = sorted({int(c) for c in re.findall(rb"\x1b\[(\d+)A", buf)})
        tb = "Traceback" in text
        animated = bool(codes)
        ok = not tb and (len(codes) <= 1)
        bad += not ok
        detail = f"cursor-up={codes}" if animated else "static"
        print(f"{'OK  ' if ok else 'FAIL'} {name:<10} {detail}"
              f"{'  TRACEBACK' if tb else ''}")
        if tb:
            i = text.index("Traceback")
            print("   " + text[i:i + 900].replace("\n", "\n   "))

    after = identity()
    clean = before == after
    print(f"\nreal crab identity: {before} -> {after}"
          f"{'' if clean else '   *** ESCAPED SANDBOX ***'}")
    print("all admin scenarios clean:", bad == 0 and clean)
    return 1 if (bad or not clean) else 0


if __name__ == "__main__":
    sys.exit(main())
