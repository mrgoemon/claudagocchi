#!/usr/bin/env python3
"""Assert the CRAB_INTRO opening: 4s still with an empty bubble, then a blink.

Run after changing _wake_scene or the intro timings -- the zoom keyframes in
make_video.sh assume the blink lands exactly INTRO_STILL_SEC in.
"""
import os
import pty
import re
import select
import signal
import sys
import time

FRAME_H = 18
EYE = "38;2;24;24;28"          # fg(EYE): present only when the eyes are drawn
STILL = 4.0
FPS = 10


def main():
    os.environ["COLUMNS"] = "100"
    os.environ["CRAB_INTRO"] = "1"
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("python3", ["python3", "pixel_crab.py", "--animate"])
    buf, t0 = b"", time.time()
    while time.time() - t0 < 8.0:
        r, _, _ = select.select([fd], [], [], 0.2)
        if not r:
            continue
        try:
            d = os.read(fd, 65536)
        except OSError:
            break
        if not d:
            break
        buf += d
    try:
        os.kill(pid, signal.SIGINT)
    except OSError:
        pass

    text = buf.decode("utf-8", "ignore")
    frames = text.split("\033[%dA" % FRAME_H)[1:]
    codes = sorted({int(c) for c in re.findall(r"\033\[(\d+)A", text)})

    eyes = [EYE in f for f in frames]
    still_n = int(STILL * FPS)
    hold, blink = eyes[:still_n - 2], eyes[still_n - 2:still_n + 3]

    def speech(fr):
        rows = [re.sub(r"\033\[[0-9;]*[A-Za-z]", "", l) for l in fr.split("\n")]
        return rows[2].strip().strip("│").strip() if len(rows) > 2 else "?"

    bubbles = {speech(f) for f in frames[:still_n - 2]}
    checks = [
        ("frame height constant", codes == [FRAME_H]),
        ("eyes open for the whole still", all(hold)),
        ("a blink lands at ~%.1fs" % STILL, not all(blink)),
        ("eyes open again after it", any(eyes[still_n + 3:])),
        ("bubble empty during the still", bubbles == {""}),
        ("no traceback", "Traceback" not in text),
    ]
    for name, ok in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    print(f"\n  frames={len(frames)} cursor-up={codes} bubbles={bubbles!r}")
    ok = all(c[1] for c in checks)
    print("  INTRO:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
