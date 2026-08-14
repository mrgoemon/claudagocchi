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
# rewrites it every four seconds. What actually proves admin mode stayed in its
# sandbox is that none of v2.0's keys ever appear in it.
V2_KEYS = ("version", "health", "generation", "graveyard", "career", "form")


def v2_keys_in_real_save():
    if not REAL_STATE.exists():
        return []
    try:
        s = json.loads(REAL_STATE.read_text())
    except Exception:
        return []
    return [k for k in V2_KEYS if k in s]


def run(scenario, seconds):
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["COLUMNS"] = "100"
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
    leaked_before = v2_keys_in_real_save()
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

    leaked = v2_keys_in_real_save()
    clean = not leaked and not leaked_before
    print(f"\nv2.0 keys leaked into the real save: {leaked or 'none'}")
    print("all admin scenarios clean:", bad == 0 and clean)
    return 1 if (bad or not clean) else 0


if __name__ == "__main__":
    sys.exit(main())
