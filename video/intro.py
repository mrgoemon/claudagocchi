#!/usr/bin/env python3
"""The launch-video opening, in one take.

Fakes a fresh shell prompt, typewriters `claude`, replays the REAL Claude
launch screen captured by capture_banner.py, then execs the crab with
CRAB_INTRO=1 so it holds a still and blinks awake on camera (see _wake_scene
in pixel_crab.py). Every duration is fixed, so the zoom keyframes in
make_video.sh line up take after take. Run it in a >=100-column terminal and
just record the window.
"""
import os
import re
import sys
import time

CLAUDE = "\033[38;2;215;119;87m"   # rgb(215,119,87), Claude Code's own coral
DIM = "\033[2m"
RESET = "\033[0m"

# A captured banner carries the sequences a full-screen TUI sets up for itself.
# Replaying those would move the crab into the alternate screen buffer and turn
# on mouse reporting, so they get dropped and only the drawing is replayed.
_STRIP = [b"\033[?1049h", b"\033[?1049l",                    # alternate screen
          b"\033[?1000h", b"\033[?1002h", b"\033[?1003h",    # mouse tracking
          b"\033[?1006h", b"\033[?2004h", b"\033[?1004h",
          b"\033[?2031h", b"\033[>0q", b"\033[c"]


def _sanitize(b):
    for seq in _STRIP:
        b = b.replace(seq, b"")
    return re.sub(rb"\033\]0;[^\007]*\007", b"", b)          # window title

# Fixed timeline (seconds) -- make_video.sh's keyframes assume these.
PROMPT_HOLD = 1.5      # empty prompt, cursor blinking
TYPE_CPS = 8           # `claude` typed at ~8 chars/sec
POST_TYPE = 0.6        # beat before "Enter"
WELCOME_HOLD = 2.2     # the real Claude launch screen on screen
# crab appears at ~PROMPT_HOLD + 6/TYPE_CPS + POST_TYPE + WELCOME_HOLD ~= 5.1s


def _out(s):
    sys.stdout.write(s)
    sys.stdout.flush()


def main():
    _out("\033[2J\033[H\033[?25l")                 # clear, hide the real cursor
    prompt = f"{DIM}~ %{RESET} "

    # blinking block cursor on an empty prompt
    t0 = time.time()
    while time.time() - t0 < PROMPT_HOLD:
        on = int((time.time() - t0) / 0.5) % 2 == 0
        _out("\r" + prompt + ("█" if on else " "))
        time.sleep(0.05)

    # typewriter `claude`
    typed = ""
    for ch in "claude":
        typed += ch
        _out("\r" + prompt + typed + "█")
        time.sleep(1 / TYPE_CPS)
    time.sleep(POST_TYPE)
    _out("\r" + prompt + typed + " \n\n")          # "Enter"

    # the real Claude launch screen, replayed byte for byte from a capture --
    # nothing here is written by hand, so nothing can be subtly wrong
    banner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "claude_banner.ansi")
    try:
        with open(banner, "rb") as f:
            sys.stdout.buffer.write(_sanitize(f.read()))
        sys.stdout.buffer.flush()
    except OSError:
        _out(f"{CLAUDE}Welcome to Claude Code{RESET} {DIM}v2.1.247{RESET}\n"
             f"{DIM}(run video/capture_banner.py for the real banner){RESET}\n")
    time.sleep(WELCOME_HOLD)

    # hand the terminal to the crab, waking up
    _out("\033[2J\033[H\033[?25h")
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(os.path.dirname(here))                # repo root, where pixel_crab.py lives
    os.environ["CRAB_INTRO"] = "1"
    os.execvp(sys.executable or "python3",
              [sys.executable or "python3", "pixel_crab.py", "--animate"])


if __name__ == "__main__":
    main()
