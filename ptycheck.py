#!/usr/bin/env python3
"""Run the live animation under a pty and assert it never tears.

The window is redrawn by moving the cursor up a fixed number of lines. If any
frame is a different height, that number changes -- so "exactly one distinct
cursor-up code for the whole run" is a direct, end-to-end test of the invariant
that the goldens only check statically.

    CRAB_STAGE=<stage> python3 ptycheck.py [seconds]
"""
import os
import pty
import re
import signal
import sys
import time


def run(stage, seconds=6.0, feed=None, cols="100"):
    env = dict(os.environ, CRAB_STAGE=stage, COLUMNS=cols)
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(env)
        os.execvp("python3", ["python3", "pixel_crab.py", "--animate"])
    buf = b""
    t0 = time.time()
    sent = False
    while time.time() - t0 < seconds:
        if feed and not sent and time.time() - t0 > 1.5:
            os.write(fd, feed.encode())          # e.g. summon a minigame
            sent = True
        try:
            d = os.read(fd, 65536)
        except OSError:
            break
        if not d:
            break
        buf += d
    try:
        os.kill(pid, signal.SIGINT)
    except Exception:
        pass
    time.sleep(0.4)
    try:
        buf += os.read(fd, 400000)
    except Exception:
        pass
    try:
        os.close(fd)
        os.waitpid(pid, 0)
    except Exception:
        pass
    codes = sorted({int(c) for c in re.findall(rb"\x1b\[(\d+)A", buf)})
    text = buf.decode("utf-8", "ignore")
    tb = "Traceback" in text
    return codes, tb, text, len(buf)


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    cases = [(s, None) for s in ("egg", "baby", "juvenile", "adult",
                                 "architect", "grinder", "gamer", "feral")]
    cases.append(("adult", "game\n"))            # exercise the minigame panel too
    bad = 0
    for stage, feed in cases:
        codes, tb, text, n = run(stage, secs, feed)
        label = f"{stage}{' +game' if feed else ''}"
        ok = len(codes) == 1 and not tb
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {label:<16} cursor-up={codes} bytes={n}"
              f"{'  TRACEBACK' if tb else ''}")
        if tb:
            i = text.index("Traceback")
            print(text[i:i + 1200])
    print("\nall frames identical height:" , bad == 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
