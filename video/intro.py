#!/usr/bin/env python3
"""The launch-video opening, in one take.

Fakes a fresh shell prompt, typewriters `claude`, flashes a Claude-style
welcome, then execs the real crab with CRAB_INTRO=1 so it wakes up on camera
(sleep -> double blink -> wave; see _wake_scene in pixel_crab.py). Every
duration is fixed, so the zoom keyframes in make_video.sh line up take after
take. Run it in a >=100-column terminal and just record the window.
"""
import os
import sys
import time

ORANGE = "\033[38;5;209m"
DIM = "\033[2m"
RESET = "\033[0m"

# Fixed timeline (seconds) -- make_video.sh's keyframes assume these.
PROMPT_HOLD = 1.5      # empty prompt, cursor blinking
TYPE_CPS = 8           # `claude` typed at ~8 chars/sec
POST_TYPE = 0.6        # beat before "Enter"
WELCOME_HOLD = 1.8     # Claude-style banner on screen
# crab appears at ~PROMPT_HOLD + 6/TYPE_CPS + POST_TYPE + WELCOME_HOLD ~= 4.7s


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

    # a minimal Claude-Code-style welcome (an homage, not a clone)
    _out(f" {ORANGE}✻{RESET} Welcome back!\n\n")
    _out(f"   {DIM}cwd: ~/claudagocchi{RESET}\n")
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
