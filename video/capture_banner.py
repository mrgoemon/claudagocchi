#!/usr/bin/env python3
"""Capture the real Claude Code launch screen to video/claude_banner.ansi.

intro.py replays those bytes verbatim, so the video's opening screen is
whatever Claude actually prints -- no hand-copied ASCII art to get subtly
wrong, and re-running this after a Claude upgrade refreshes it.

Claude lays its screen out for the terminal it starts in and positions the
status line by absolute row, so this captures at 100x40 and the window you
record in has to be that size too. Under 30 rows Claude collapses the banner to
a single line instead of the full mascot header.
"""
import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import sys
import termios
import time

COLS, ROWS = 100, 40
# The banner shows the directory Claude was launched in, so capture from the
# repo root by default -- that's the launch the video is depicting. In a
# directory Claude hasn't been trusted in yet, its "is this a project you
# trust?" prompt is what gets captured instead; accept it once by hand and
# re-run. Override with: capture_banner.py <dir>
DEFAULT_CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTLE = 3.0          # stop once nothing new has arrived for this long; long
                      # enough that the status line finishes connecting, so the
                      # replay ends on the settled screen rather than a spinner
LIMIT = 25.0          # hard cap on how long we wait for Claude to start
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_banner.ansi")

# Verbatim from the 2.1.247 binary, for when the real thing can't be captured.
FALLBACK = ("\033[38;2;215;119;87mWelcome to Claude Code\033[0m "
            "\033[2mv2.1.247\033[0m\n")


def capture(cwd):
    claude = shutil.which("claude")
    if not claude:
        return None
    # Drop this process's own Claude session markers: a capture run from inside
    # Claude Code otherwise shows a "transcript saving is off" warning and other
    # nested-session noise that a normal launch never has.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_CODE", "CLAUDECODE"))}
    env["TERM"] = "xterm-256color"
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execve(claude, [claude], env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

    buf, t0, last = b"", time.time(), None
    while time.time() - t0 < LIMIT:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                d = os.read(fd, 65536)
            except OSError:
                break
            if not d:
                break
            buf += d
            last = time.time()
        elif last and time.time() - last > SETTLE:
            break                      # output stopped: the banner is fully drawn
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
            time.sleep(0.3)
            if os.waitpid(pid, os.WNOHANG)[0]:
                break
        except OSError:
            break
    try:
        os.close(fd)
    except OSError:
        pass
    return buf or None


def main():
    cwd = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CWD
    buf = capture(cwd)
    if buf and b"safety check" in buf:
        print(f"Claude asked whether it trusts {cwd}, so that prompt got captured\n"
              f"instead of the banner. Run `claude` there once by hand, accept, quit,\n"
              f"then re-run this script.", file=sys.stderr)
        return 1
    if buf:
        with open(OUT, "wb") as f:
            f.write(buf)
        print(f"captured {len(buf)} bytes of the real banner -> video/claude_banner.ansi")
    else:
        with open(OUT, "w") as f:
            f.write(FALLBACK)
        print("could not run `claude` -- wrote the compact fallback banner instead",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
