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
import subprocess
import sys
import unicodedata
import time

FRAME_H = 17
WIDTH = 99             # every box row, garble included
FX = 2.0               # length of the decode
EYE = "38;2;24;24;28"          # fg(EYE): present only when the eyes are drawn
STILL = 4.0            # motionless "screenshot" before the blinks
HOPS = 2               # INTRO_HOPS
SETTLE = 1.0           # INTRO_SETTLE_SEC
FPS = 10


def vlen(s):
    """Visible columns, the way pixel_crab measures them."""
    return sum(0 if unicodedata.combining(c)
               else (2 if unicodedata.east_asian_width(c) in ("W", "F") else 1)
               for c in s)


def save_paths():
    """Where the child process would actually read and write its crab.

    Hashing the real save before and after proves nothing here: the user's own
    crab is usually running and rewrites it every few seconds, so a change
    cannot be attributed to this run. Resolving the paths is the real invariant.
    """
    code = ("import crab_state, crab_tokens;"
            "print(crab_state.STATE);print(crab_state.CONFIG);"
            "print(crab_state.PRE_DEATH);print(crab_tokens.CACHE)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=dict(os.environ))
    return out.stdout.split()


def main():
    os.environ["COLUMNS"] = "100"
    os.environ["CRAB_INTRO"] = "1"
    # Same isolation intro.py uses -- the point is to prove it holds.
    demo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-save")
    os.environ["CRAB_SAVE_DIR"] = demo
    os.environ["CRAB_STAGE"] = "adult"
    paths = save_paths()
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("python3", ["python3", "pixel_crab.py", "--animate"])
    buf, t0 = b"", time.time()
    while time.time() - t0 < 14.0:
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
    # Drop the last frame: the capture is cut mid-write when the child is
    # killed, so it is a partial redraw and compares unequal to everything.
    frames = text.split("\033[%dA" % FRAME_H)[1:-1]
    codes = sorted({int(c) for c in re.findall(r"\033\[(\d+)A", text)})

    eyes = [EYE in f for f in frames]
    still_n = int(STILL * FPS)
    hold = eyes[:still_n - 2]
    # Two blinks = two runs of closed-eye frames inside the wake window.
    window = eyes[still_n - 2:still_n + 12]
    blinks = len([1 for i, open_ in enumerate(window)
                  if not open_ and (i == 0 or window[i - 1])])

    def speech(fr):
        rows = [re.sub(r"\033\[[0-9;]*[A-Za-z]", "", l) for l in fr.split("\n")]
        return rows[2].strip().strip("│").strip() if len(rows) > 2 else "?"

    bubbles = {speech(f) for f in frames[:still_n - 2]}
    early, late = frames[:still_n - 2], frames[still_n + 10:]
    said = []
    for f in frames:
        s = speech(f)
        if s and (not said or not said[-1].startswith(s)):
            said.append(s)
    def stage(fr):     # the crab's rows, text only -- changes if it moves
        rows = [re.sub(r"\033\[[0-9;]*[A-Za-z]", "", l) for l in fr.split("\n")]
        return "\n".join(rows[4:9])

    # The frame where the greeting gives way to the next line, and the frames
    # between the blinks and that moment -- the crab should hop in there.
    greeting = "Welcome back, Kengo!"
    switch = next((i for i, f in enumerate(frames) if speech(f) != greeting
                   and i > still_n), len(frames))
    hop_win = frames[still_n + 8:switch]
    # Where Claude's status bar gives way to the crab's own vitals.
    stats_at = next((i for i, f in enumerate(frames) if "/effort" not in f
                     and i > still_n), len(frames))
    def crab_x(fr):          # leftmost column the crab occupies
        rows = [re.sub(r"\033\[[0-9;]*[A-Za-z]", "", l).strip("│\r")
                for l in fr.split("\n")[4:9]]
        cols = [i for r in rows for i, ch in enumerate(r) if ch != " "]
        return min(cols) if cols else None

    # The held pause ends after the still, both blinks, the hops and the settle;
    # the crab should then walk, which is the only thing that moves it sideways.
    settled = still_n + 8 + 5 * HOPS + int(FPS * SETTLE)
    walk_win = [crab_x(f) for f in frames[settled - 4:settled + int(FPS * 2.5)]]
    walk_win = [x for x in walk_win if x is not None]

    def sprite_w(fr):        # how many columns the crab spans
        rows = [re.sub(r"\033\[[0-9;]*[A-Za-z]", "", l).strip("│\r")
                for l in fr.split("\n")[4:9]]
        cols = [i for r in rows for i, ch in enumerate(r) if ch != " "]
        return max(cols) - min(cols) + 1 if cols else 0

    # Widths straight from the source, so a morph resize can't silently pass.
    adult_w = int(subprocess.run(
        [sys.executable, "-c", "import pixel_crab;print(pixel_crab.MORPHS['adult'].w)"],
        capture_output=True, text=True, env=dict(os.environ)).stdout.strip() or 0)
    # Braille is the garble charset and appears nowhere else in the UI, so its
    # presence in a frame means that frame is mid-corruption. (░ is NOT usable
    # here -- the session bar draws with it.)
    kata = re.compile(r"[\u2801-\u28ff]")
    garbled = [i for i, f in enumerate(frames) if kata.search(f)]
    decode_at = garbled[0] if garbled else len(frames)
    line = "let's start tokenmaxxing \U0001F980"
    typed_at = next((i for i, f in enumerate(frames) if speech(f) == line), len(frames))
    resolved = frames[garbled[-1] + 2:] if garbled else []
    bad_width = []
    for f in frames:
        for line in f.split("\n"):
            plain = re.sub(r"\033\[[0-9;]*[A-Za-z]", "", line).rstrip("\r")
            if plain[:1] in ("\u256d", "\u2502", "\u2570") and vlen(plain) != WIDTH:
                bad_width.append(vlen(plain))
    checks = [
        ("frame height constant", codes == [FRAME_H]),
        ("always the adult crab, never the fresh-save egg",
         sprite_w(frames[5]) == adult_w),
        ("walks off as its first move after the pause",
         bool(walk_win) and max(walk_win) - min(walk_win) >= 4),
        ("hops before changing its line",
         switch > still_n + 8 and len({stage(f) for f in hop_win}) > 1),
        ("eyes open for the whole still", all(hold)),
        ("blinks twice at ~%.1fs" % STILL, blinks == 2),
        ("eyes open again after them", any(eyes[still_n + 10:])),
        ("says the tokenmaxxing line after the hop",
         any(t.startswith("let's start tokenmaxxing") for t in said)),
        ("and never says anything else after it",
         all(t == greeting or "let's start tokenmaxxing".startswith(t[:24])
             or t.startswith("let's start tokenmaxxing") for t in said)),
        ("greeting already finished on the still",
         bubbles == {"Welcome back, Kengo!"}),
        ("titled Claude while disguised",
         all("Claude " in f and "Claudagocchi" not in f for f in early)),
        ("Claude's status bar while disguised",
         all("/effort" in f for f in early)),
        ("stays disguised as Claude right through the wake",
         all("Claudagocchi" not in f for f in frames[:decode_at])),
        # It arms on the exact frame the line lands, but the blot starts at a
        # single seeded column with jitter, so the first VISIBLE garble trails
        # that by a frame or two -- which is the effect, not a delay.
        ("corruption starts just after the line finishes typing",
         decode_at < len(frames) and 0 <= decode_at - typed_at <= 5),
        # Deliberately loose. This counts CAPTURED frames, and the pty drops
        # them under load -- observed 14 to 19 for a nominal 20 -- so a tight
        # bound here fails on a busy machine while the effect is fine. What is
        # worth asserting is that the corruption is sustained rather than a
        # one-frame flash; its real duration is set by INTRO_FX_SEC.
        ("the corruption is sustained, not a flash",
         FX * FPS * 0.4 <= len(garbled) <= FX * FPS * 1.5),
        ("the old UI survives into it and is eaten gradually",
         any(kata.search(f) and ("/effort" in f or "Opus 5" in f) for f in frames)),
        ("rows are taken at different times, not all at once",
         any(kata.search(f) and "Claudagocchi" in f for f in frames)),
        ("and resolves to Claudagocchi",
         bool(resolved) and all("Claudagocchi" in f for f in resolved)),
        ("every box row stays %d columns, garble included" % WIDTH, not bad_width),
        ("stats stay Claude's until the decode", stats_at >= decode_at),
        ("real stats arrive in the end", stats_at < len(frames)),
        ("every save path lands in the sandbox",
         bool(paths) and all(p.startswith(demo) for p in paths)),
        ("demo save was written", os.path.exists(os.path.join(demo, "state.json"))),
        ("real token numbers still shown",
         any(re.search(r"tokens used today\s+[1-9]", f) for f in frames)),
        ("session limit and its reset time are on screen",
         any(re.search(r"session\s+[█░]{20}\s+\d+%\s+·\s+resets\s+\d+:\d\d [AP]M", f)
             for f in frames)),
        ("weekly line is gone", not any("weekly " in f for f in frames)),
        ("git lines are gone", not any("PRs" in f for f in frames)),
        ("no traceback", "Traceback" not in text),
    ]
    for name, ok in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    print(f"\n  frames={len(frames)} cursor-up={codes} bubbles={bubbles!r}")
    print(f"  typed_at={typed_at} decode_at={decode_at} garbled={len(garbled)}"
          f" stats_at={stats_at} switch={switch}")
    ok = all(c[1] for c in checks)
    print("  INTRO:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
