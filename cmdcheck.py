#!/usr/bin/env python3
"""Type commands into the live chat line and check what comes back.

Drives the real animation through a pty and asserts two things per command: the
speech bubble ends up saying the right thing, and the frame height never changes
-- a command that quietly added or removed a line would tear the redraw for the
rest of the session, which is the failure mode worth catching.

The bubble is typewritered at ~13 chars/sec, so this waits for it to SETTLE
rather than sleeping a fixed amount. A fixed wait is either too slow for short
replies or too short for long ones, and silently reports the wrong answer.
"""
import os
import pty
import re
import select
import signal
import sys
import time

SPEECH_ROW = 2          # top, blank, speech, ...
FRAME_H = 17            # window + input line; also the anti-tear assertion

# (typed line, substring the bubble must end up containing, full-screen page?)
CASES = [
    ("stats",         "energy",             False),
    ("stage",         "days old",           False),
    ("hoard",         "gifts",              False),
    ("pet",           "leans into it",      False),
    ("pet",           "you just did that",  False),   # affection cooldown
    ("name Zoidberg", "is now Zoidberg",    False),
    ("name",          "i'm Zoidberg",       False),
    ("alerts",        "alerts are",         False),
    ("alerts quiet",  "no sound",           False),
    ("alerts on",     "chirp",              False),
    ("graduate",      "type: graduate",     False),   # bare form must NOT graduate
    ("stretch",       "stretch with me",    False),
    ("help",          "looking at things",  True),
    ("hall",          "Memory Lane",        True),
    ("sessions",      "agent sessions",     True),
    ("nonsense qq",   None,                 False),   # falls through to chat
]


class Session:
    def __init__(self):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ["COLUMNS"] = "100"
            # Without this the director starts a game on its own mid-run and its
            # line lands in the bubble instead of the reply being asserted.
            os.environ["CRAB_NO_DIRECTOR"] = "1"
            os.execvp("python3", ["python3", "pixel_crab.py", "--animate"])
        self.buf = b""

    def drain(self, secs):
        """Read for `secs` without blocking -- while a page is up the child emits
        nothing at all until a key arrives, so a blocking read would hang."""
        t0 = time.time()
        while True:
            left = secs - (time.time() - t0)
            if left <= 0:
                return
            r, _, _ = select.select([self.fd], [], [], left)
            if not r:
                continue
            try:
                d = os.read(self.fd, 65536)
            except OSError:
                return
            if not d:
                return
            self.buf += d

    def speech(self):
        frames = self.buf.decode("utf-8", "ignore").split("\x1b[%dA" % FRAME_H)
        if len(frames) < 2:
            return ""
        rows = [re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", l) for l in frames[-2].split("\n")]
        return rows[SPEECH_ROW].strip("│").strip() if len(rows) > SPEECH_ROW else ""

    def settle(self, limit=9.0, quiet=0.8):
        """Wait until the bubble stops changing, or `limit` seconds."""
        t0, last, stable = time.time(), None, 0.0
        while time.time() - t0 < limit:
            self.drain(0.2)
            cur = self.speech()
            if cur == last:
                stable += 0.2
                if stable >= quiet and cur:
                    return cur
            else:
                last, stable = cur, 0.0
        return self.speech()

    def send(self, s):
        os.write(self.fd, s.encode())

    def stop(self):
        try:
            os.kill(self.pid, signal.SIGINT)
        except Exception:
            pass


def main():
    s = Session()
    s.drain(2.5)
    results = []
    for typed, expect, is_page in CASES:
        mark = len(s.buf)
        s.send(typed + "\n")
        if is_page:
            s.drain(2.0)
            plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "",
                           s.buf[mark:].decode("utf-8", "ignore"))
            got, ok = "<page>", (expect in plain)
            s.send(" ")                       # dismiss it
            s.drain(1.2)
        else:
            got = s.settle()
            ok = True if expect is None else (expect in got)
        results.append((typed, expect, ok, got))

    s.send("quit\n")
    s.drain(1.5)
    s.stop()

    text = s.buf.decode("utf-8", "ignore")
    codes = sorted({int(c) for c in re.findall(rb"\x1b\[(\d+)A", s.buf)})
    for typed, expect, ok, got in results:
        want = repr(expect) if expect else "(falls through to chat)"
        print(f"  {'OK  ' if ok else 'FAIL'} {typed:<15} {want}")
        if not ok:
            print(f"       got: {got!r}")
    clean = (all(r[2] for r in results) and codes == [FRAME_H]
             and "Traceback" not in text)
    print(f"\n  frame height(s): {codes}  (must be exactly [{FRAME_H}])")
    print(f"  traceback: {'Traceback' in text}")
    print("  all commands OK:", clean)
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
