#!/usr/bin/env python3
"""Claudagocchi — a terminal crab that lives in a Claude Code-style window.

The crab is built on the Claude Code quadrant-block mark:
    eye row:  ▗ # ▗ # # # ▖ # ▖   (hands ▗▖ at cols 0/8, eyes ▗▖ at cols 2/6,
    body:     · # # # # # # # ·    coral body fill at cols 1..7)
    legs:     · · ▘ ▘ · ▝ ▝ · ·

Body/eyes use ANSI background colors (no █); hands/legs are coral quadrant glyphs.

Animation (`--animate`) runs a behavior scheduler that gives the crab a calm,
cat-like idle: loafing with slow blinks, sauntering side to side, big stretches,
grooming, the occasional nap, and a rare pounce. Ctrl-C to stop.

Usage:
    python3 pixel_crab.py            # the centered crab
    python3 pixel_crab.py --welcome  # the Claudagocchi window (static)
    python3 pixel_crab.py --animate  # the window with the crab alive
    python3 pixel_crab.py --no-color # plain (no coral tint)
"""
import sys
import shutil
import random
import unicodedata
import os
import datetime
import threading
import queue

import crab_state as cs
import crab_chat as cc

CORAL = (200, 126, 95)
EYE   = (24, 24, 28)
RESET = "\033[0m"
def fg(rgb): r, g, b = rgb; return f"\033[38;2;{r};{g};{b}m"
def bg(rgb): r, g, b = rgb; return f"\033[48;2;{r};{g};{b}m"

WIDTH = 9                       # crab sprite width (cols 0..8)
BODY_COLS = range(1, 8)         # coral body cols 1..7
EYES = {2: "▗", 6: "▖"}         # eyes: small glyphs, drawn black on the body
WALL_PAD = 4                    # invisible margin (cols) keeping the crab off the walls

# Pose vocabularies — each maps column -> quadrant glyph.
HAND_POSES = {
    "down":  {0: "▗", 8: "▖"},          # resting at sides
    "up":    {0: "▝", 8: "▘"},          # raised (stretch / reach)
    "walkA": {0: "▝", 8: "▖"},          # mid-stride swing
    "walkB": {0: "▗", 8: "▘"},
}
LEG_POSES = {
    "rest":  {2: "▘", 3: "▘", 5: "▝", 6: "▝"},
    "stepA": {2: "▘", 3: "▖", 5: "▝", 6: "▗"},   # walk cycle frame A
    "stepB": {2: "▖", 3: "▘", 5: "▗", 6: "▝"},   # walk cycle frame B
    "squat": {2: "▖", 3: "▗", 5: "▖", 6: "▗"},   # crouched, feet splayed
    "tuck":  {3: "▗", 5: "▖"},                    # tucked up (mid-air)
}

def pose(eye_open=True, hand="down", leg="rest", gaze=0):
    """A crab pose: glyphs for eyes/hands/legs, plus gaze (-1 left, 0 fwd, 1 right)."""
    return {"eye_open": eye_open, "hands": HAND_POSES[hand],
            "legs": LEG_POSES[leg], "gaze": gaze}

# Rows: 0 = eye line (hands + eyes), 1 = body, 2 = legs.
def _build(eye_open=True, hands=None, legs=None, gaze=0):
    hands = HAND_POSES["down"] if hands is None else hands
    legs = LEG_POSES["rest"] if legs is None else legs
    g = [["."] * WIDTH for _ in range(3)]
    for r in (0, 1):                       # 2-row coral body
        for c in BODY_COLS:
            g[r][c] = "#"
    if eye_open:                           # eyes glance toward `gaze` by one column,
        for c, ch in EYES.items():         # keeping the crab facing forward
            g[0][min(max(c + gaze, 1), WIDTH - 2)] = ("eye", ch)
    for c, ch in hands.items():
        g[0][c] = ("hand", ch)
    for c, ch in legs.items():
        g[2][c] = ("leg", ch)
    return g

def _render_cell(tok, color):
    if tok == ".":
        return " "
    if tok == "#":
        return (bg(CORAL) + " " + RESET) if color else " "
    kind, ch = tok
    if kind == "eye":
        return (bg(CORAL) + fg(EYE) + ch + RESET) if color else ch
    return (fg(CORAL) + ch + RESET) if color else ch   # hand or leg glyph

def crab_rows(color=True, **frame):
    """The crab's 3 raw rows (each WIDTH columns of visible content, with ANSI)."""
    return ["".join(_render_cell(c, color) for c in row) for row in _build(**frame)]

def _term_width(default=80):
    return shutil.get_terminal_size((default, 24)).columns

def _handle_keys(buf, data):
    """Fold a chunk of raw stdin into the chat buffer. Returns (buffer, submit)
    where submit is the line on Enter, else None."""
    if data[:1] == b"\x1b":                 # ESC: lone = clear, sequence (arrows) = ignore
        return ("", None) if len(data) == 1 else (buf, None)
    submit = None
    for ch in data.decode("utf-8", "ignore"):
        o = ord(ch)
        if ch in ("\r", "\n"):
            submit, buf = buf, ""
        elif o in (8, 127):                 # backspace
            buf = buf[:-1]
        elif o >= 32:
            buf += ch
    return buf, submit

def _input_line(buf, inner, color, ok):
    """The chat input row drawn under the box."""
    if not ok:
        s = "  chat: set ANTHROPIC_API_KEY + `pip install anthropic`"
    else:
        shown = buf[-(inner - 4):] if len(buf) > inner - 4 else buf
        s = ("  › " + shown + "▏") if buf else "  › talk to me… (type, Enter to send)"
    s = s[:inner + 2]
    return (fg((150, 150, 160)) + s + RESET) if color else s

def _vlen(s):
    """Visible width in terminal columns (full-width CJK glyphs count as 2)."""
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w

def _center_text(s, width):
    """Center s in `width` columns, accounting for full-width characters."""
    if len(s) > width:                     # safety: never overflow the box
        s = s[:width]
    pad = max(width - _vlen(s), 0)
    left = pad // 2
    return " " * left + s + " " * (pad - left)

def _center(lines):
    margin = " " * max((_term_width() - WIDTH) // 2, 0)
    return [margin + l for l in lines]

def crab(color=True, **frame) -> str:
    """Standalone crab, centered in the terminal, no box."""
    return "\n".join(_center(crab_rows(color, **frame)))

# --- The Claudagocchi window -------------------------------------------------
TITLE = "Claudagocchi"
SPEECH = "Welcome back kh!"                 # -> speech bubble later
STATS = ["Fable 5", "Claude Max", "~ヽ(｡･ω･｡)"]  # -> live stats later

HOARD_CAP = 10                  # max glyphs shown in the pile
HOARD_COLOR = [(120, 120, 120), (155, 150, 160), (200, 126, 95),
               (215, 165, 95), (235, 205, 120)]   # by tier: dull -> golden

def _render_hoard(glyphs, color):
    if not color:
        return "".join(g for g, _ in glyphs)
    return "".join(fg(HOARD_COLOR[t]) + g + RESET for g, t in glyphs)

def _place(inner, items):
    """Lay rendered segments onto a blank `inner`-wide row at given visible
    columns. `items` are (col, rendered, width) in PRIORITY order — a later
    item that would overlap an already-placed one is dropped (so the crab,
    placed first, is never hidden)."""
    occupied = [False] * inner
    chosen = []
    for col, s, w in items:
        col = max(0, min(col, inner - w))
        if any(occupied[col:col + w]):
            continue
        for c in range(col, col + w):
            occupied[c] = True
        chosen.append((col, s, w))
    out, cur = [], 0
    for col, s, w in sorted(chosen):
        out.append(" " * (col - cur)); out.append(s); cur = col + w
    out.append(" " * max(inner - cur, 0))
    return "".join(out)

def render_window(color=True, stage_h=3, x=None, y=0, frame=None,
                  speech=None, stats=None, hoard=None, drop=None, emote=None) -> str:
    """Draw the window with the crab sprite placed at (x, y) on a stage_h-tall
    stage. `speech`/`stats` override the static placeholders when live;
    `hoard` is a list of (glyph, tier) drawn as a pile in the bottom-right;
    `drop` is an optional (col, glyph, tier) gift sitting on the ground."""
    # Leave one spare column on the right so the right wall is never clipped at
    # the terminal edge.
    inner = max(_term_width() - 3, WIDTH + 4)
    if x is None:
        x = (inner - WIDTH) // 2
    if frame is None:
        frame = pose()
    sprite = crab_rows(color, **frame)

    ground_row = stage_h - 1
    stage = []
    for r in range(stage_h):
        crab_seg = (max(x, 0), sprite[r - y], WIDTH) if y <= r < y + 3 else None
        if r == ground_row:                          # crab legs + loose gift + hoard pile
            items = [crab_seg] if crab_seg else []   # crab has priority
            if drop:
                dcol, dch, dt = drop                 # gift drop is an emoji (self-colored,
                items.append((dcol, dch, _vlen(dch)))  # and double-width, so measure it)
            if hoard:
                items.append((inner - len(hoard) - 1, _render_hoard(hoard, color), len(hoard)))
            stage.append(_place(inner, items))
        elif crab_seg:
            col, s, w = crab_seg
            stage.append(" " * col + s + " " * max(inner - col - w, 0))
        else:
            stage.append(" " * inner)

    if emote and 0 <= y - 1 < stage_h:               # a small glyph above the crab's head
        ew = _vlen(emote)
        ecol = min(max(x + WIDTH // 2, 0), inner - ew)
        es = (fg((150, 150, 160)) + emote + RESET) if color else emote
        stage[y - 1] = _place(inner, [(ecol, es, ew)])

    # Border, drawn entirely in coral (same as the Claudagocchi title).
    co = (lambda s: fg(CORAL) + s + RESET) if color else (lambda s: s)
    k = max(inner - 3 - len(TITLE), 0)
    top = co("╭─ " + TITLE + " " + "─" * k + "╮")
    bottom = co("╰" + "─" * inner + "╯")
    bar = co("│")
    def text(line): return bar + _center_text(line, inner) + bar
    def blank():    return bar + " " * inner + bar

    speech = SPEECH if speech is None else speech
    stats = STATS if stats is None else stats
    rows = [top, blank(), text(speech), blank()]
    rows += [bar + s + bar for s in stage]
    rows += [blank()] + [text(s) for s in stats] + [blank(), bottom]
    return "\n".join(rows)

def welcome(color=True) -> str:
    return render_window(color, stage_h=3)

# --- Behavior scheduler ------------------------------------------------------
ACTIONS = ["sit", "saunter", "stretch", "groom", "pounce"]
MOOD_WEIGHTS = {                # mood biases which idle actions are likely
    "tired":     [7, 1, 2, 1, 0],
    "hungry":    [6, 2, 1, 2, 1],
    "energetic": [2, 5, 2, 1, 3],
    "lonely":    [6, 2, 1, 3, 1],
    "content":   [5, 3, 2, 2, 1],
    "okay":      [5, 3, 2, 2, 1],
}

def action_weights(ctx):
    """Likelihood of each action from mood + energy + belly + time of day.
    Returns {action_name: weight}. (Actions without a branch yet fall back to a
    calm loaf, so it's safe for weights to lead the implementation.)"""
    mood  = ctx.get("mood", "okay")
    e     = max(0.0, min(1.0, ctx.get("energy", 80) / 100.0))
    belly = ctx.get("belly", 60)
    happy = ctx.get("happiness", 60)
    hour  = ctx.get("hour", 12)
    night  = hour >= 23 or hour < 6
    hungry = belly < 35
    sad    = happy < 30
    recent = ctx.get("recent_commit", False)
    hoard  = ctx.get("has_hoard", False)
    base   = MOOD_WEIGHTS.get(mood, MOOD_WEIGHTS["okay"])   # [sit,saunter,stretch,groom,pounce]
    w = {
        "sit":        base[0] + (1 - e) * 5,
        "saunter":    base[1] * (0.3 + e),
        "stretch":    base[2] * (0.3 + e),
        "groom":      base[3],
        "pounce":     base[4] * e * 1.5,
        "lookaround": 2.0,
        "dig":        1.5 * (0.3 + e),
        "bubble":     1.2,
        "wiggle":     (3.0 if (mood in ("energetic", "content") and not hungry) else 0.4) * (0.4 + e),
        "yawn":       3.0 if (e < 0.4 or night) else 0.4,
        "preen":      1.5,
        "foottap":    2.5 if hungry else 0.6,
        "beg":        5.0 if hungry else 0.0,
        "hungrypace": 4.0 if hungry else 0.0,
        "sadslump":   4.0 if sad else 0.0,
        "doze":       5.0 if e < 0.22 else (2.0 if night else 0.0),
        "dash":       (3.0 if mood == "energetic" else 0.4) * e,
        "cheer":      4.0 if recent else 0.0,
        "visithoard": 2.0 if hoard else 0.0,
        "nightowl":   3.0 if night else 0.0,
        "milestone":  100.0 if ctx.get("milestone_ready") else 0.0,   # triggered, jumps the queue
    }
    return {k: max(0.0, v) for k, v in w.items()}

MILESTONES = {3, 7, 14, 21, 30, 50, 100, 200, 365}   # streak days worth a party

def crab_bounds(inner, right_pad=0):
    """The left/right columns the crab may stand at (clear of walls + hoard)."""
    maxx = inner - WIDTH
    lo = min(WALL_PAD, maxx // 2)
    hi = max(maxx - WALL_PAD - right_pad, lo)
    return lo, hi

def behaviors(inner, stage_h, mood_box=None, right_pad=0, pos=None):
    """Infinite stream of (x, y, frame) — calm, cat-like actions weighted by the
    crab's current mood (read live from mood_box). The crab's column lives in the
    shared `pos` dict so other code (e.g. a gift scene) can move it and have the
    idle loop resume from the new spot."""
    ground = stage_h - 3
    lo, hi = crab_bounds(inner, right_pad)
    if pos is None:
        pos = {"x": (inner - WIDTH) // 2}
    pos["x"] = min(max(pos.get("x", (inner - WIDTH) // 2), lo), hi)

    def step_x(d):
        nx = pos["x"] + d
        if not (lo <= nx <= hi):
            d = -d                                   # turn back at the invisible wall
            nx = pos["x"] + d
        pos["x"] = max(lo, min(hi, nx))
        return d

    # Frames are 4-tuples (x, y, frame, emote) — emote is a small glyph drawn above
    # the crab's head (or None).
    while True:
        ctx = mood_box or {}
        w = action_weights(ctx)
        action = random.choices(list(w), weights=list(w.values()))[0]

        if action == "saunter":                      # slow stroll: legs step, hands stay
            d = random.choice([-1, 1])               # put, eyes glance the way it walks
            for i in range(random.randint(8, 16)):
                if i % 2 == 0:
                    d = step_x(d)
                yield pos["x"], ground, pose(hand="down", gaze=d,
                                             leg="stepA" if i % 2 else "stepB"), None

        elif action == "stretch":                    # big slow stretch, then settle
            yield pos["x"], ground, pose(hand="up", leg="stepA"), None
            for _ in range(random.randint(5, 8)):
                yield pos["x"], ground, pose(hand="up"), None
            yield pos["x"], ground, pose(hand="up", leg="squat"), None

        elif action == "groom":                      # paw flicks at the face
            for i in range(random.randint(6, 12)):
                yield pos["x"], ground, pose(hand="walkA" if i % 2 else "down",
                                             eye_open=(i % 4 != 0)), None

        elif action == "pounce":                     # rare: wiggle, then leap
            for _ in range(3):
                yield pos["x"], ground, pose(leg="squat"), None
            for yy in (ground - 1, ground - 2, ground - 2):
                yield pos["x"], max(yy, 0), pose(hand="up", leg="tuck"), None
            yield pos["x"], ground - 1, pose(leg="tuck"), None
            yield pos["x"], ground, pose(leg="squat"), None
            yield pos["x"], ground, pose(leg="rest"), None

        elif action == "lookaround":                 # glance left, then right, curious
            for g, hold in [(-1, 4), (0, 2), (1, 4), (0, 3)]:
                for _ in range(hold):
                    yield pos["x"], ground, pose(gaze=g), None

        elif action == "dig":                        # paw at the ground
            for i in range(random.randint(8, 12)):
                yield pos["x"], ground, pose(hand="walkA" if i % 2 else "walkB",
                                             leg="squat" if i % 2 else "stepA"), None

        elif action == "bubble":                     # blow a bubble that grows, then pops
            for em in ("˚", "°", "○", "°", None):
                for _ in range(3):
                    yield pos["x"], ground, pose(), em

        elif action == "wiggle":                     # happy little dance
            for i in range(random.randint(8, 12)):
                yield pos["x"], ground, pose(hand="up", gaze=1 if i % 2 else -1,
                                             leg="stepA" if i % 2 else "stepB"), None

        elif action == "yawn":                        # arms up, eyes squeeze shut, settle
            yield pos["x"], ground, pose(hand="up", leg="stepA"), None
            for _ in range(4):
                yield pos["x"], ground, pose(hand="up", eye_open=False), None
            for _ in range(3):
                yield pos["x"], ground, pose(eye_open=False), None
            yield pos["x"], ground, pose(), None

        elif action == "preen":                       # raise a claw and tidy it
            for i in range(random.randint(7, 11)):
                yield pos["x"], ground, pose(hand="walkA", gaze=-1, eye_open=(i % 3 != 0)), None

        elif action == "foottap":                     # tap a foot, impatient
            for i in range(random.randint(10, 16)):
                yield pos["x"], ground, pose(leg="stepA" if i % 2 else "rest"), None

        elif action == "beg":                         # "feed me!" — both claws up at you
            for i in range(random.randint(9, 13)):
                em = "!" if i % 4 < 2 else None
                yield pos["x"], ground, pose(hand="up", gaze=0,
                                             leg="squat" if i % 2 else "rest"), em

        elif action == "hungrypace":                  # restless pacing, glancing about
            d = random.choice([-1, 1])
            for i in range(random.randint(12, 18)):
                d = step_x(d)
                yield pos["x"], ground, pose(hand="down", gaze=d,
                                             leg="stepA" if i % 2 else "stepB"), None

        elif action == "sadslump":                    # droop, eyes low
            for i in range(random.randint(10, 16)):
                yield pos["x"], ground, pose(eye_open=(i % 6 == 0), hand="down", leg="squat"), None

        elif action == "doze":                        # curl up, z z z (only when sleepy)
            for i in range(random.randint(14, 20)):
                yield pos["x"], ground, pose(eye_open=False, leg="tuck"), ("z" if i % 4 == 0 else None)
            yield pos["x"], ground, pose(leg="squat"), None      # stir
            yield pos["x"], ground, pose(), None                 # wake

        elif action == "dash":                        # energetic zip + a victory hop
            d = random.choice([-1, 1])
            for i in range(random.randint(8, 14)):
                d = step_x(d)
                yield pos["x"], ground, pose(hand="up", gaze=d,
                                             leg="stepA" if i % 2 else "stepB"), None
            yield pos["x"], max(ground - 1, 0), pose(hand="up", leg="tuck"), None
            yield pos["x"], ground, pose(leg="squat"), None
            yield pos["x"], ground, pose(), None

        elif action == "cheer":                       # fist-pump, "you got this!"
            for i in range(random.randint(8, 12)):
                yield pos["x"], ground, pose(hand="up" if i % 2 else "down", gaze=0), \
                      ("!" if i % 3 == 0 else None)

        elif action == "visithoard":                  # stroll to the pile and admire it
            for _ in range(inner):
                if pos["x"] >= hi:
                    break
                step_x(1)
                yield pos["x"], ground, pose(hand="down", gaze=1,
                                             leg="stepA" if pos["x"] % 2 else "stepB"), None
            for i in range(random.randint(6, 10)):
                yield pos["x"], ground, pose(hand="up", gaze=1, leg="rest"), \
                      ("♥" if i % 3 == 0 else None)
            for _ in range(random.randint(4, 8)):
                step_x(-1)
                yield pos["x"], ground, pose(hand="down", gaze=-1,
                                             leg="stepA" if pos["x"] % 2 else "stepB"), None

        elif action == "nightowl":                    # late-night yawn into a doze
            yield pos["x"], ground, pose(hand="up", leg="stepA"), None
            for _ in range(3):
                yield pos["x"], ground, pose(hand="up", eye_open=False), None
            for i in range(random.randint(10, 16)):
                yield pos["x"], ground, pose(eye_open=False, leg="tuck"), ("z" if i % 5 == 0 else None)
            yield pos["x"], ground, pose(), None

        elif action == "milestone":                   # streak party (triggered, not random)
            ctx["milestone_ready"] = False
            for i in range(random.randint(12, 18)):
                yy = max(ground - 1, 0) if i % 2 else ground
                yield pos["x"], yy, pose(hand="up", gaze=1 if i % 4 < 2 else -1,
                                         leg="tuck" if i % 2 else "squat"), \
                      ("★" if i % 2 == 0 else None)
            yield pos["x"], ground, pose(), None

        else:                                        # "sit" + any not-yet-built action: loaf
            n = random.randint(10, 22)
            blink_at = random.randint(2, max(2, n - 4))   # one short blink, mid-action
            for i in range(n):
                closed = blink_at <= i < blink_at + 2
                yield pos["x"], ground, pose(eye_open=not closed), None

def _boot_wave(x, ground, fps):
    """Launch greeting: a one-hand wave (~1s), then a ~1s still cooldown before
    the crab starts any action."""
    span = max(6, int(fps))
    wave = [(x, ground, pose(hand="walkA" if i % 2 == 0 else "down"), None)  # crab's right hand
            for i in range(span)]
    cooldown = [(x, ground, pose(), None) for _ in range(span)]              # still, settling
    return wave + cooldown

def _celebrate(x, ground):
    """A happy in-place bounce for commits / completed quests. 4-tuples: (x,y,frame,drop)."""
    seq = []
    for _ in range(2):
        seq += [(x, ground, pose(hand="up", leg="squat"), None),
                (x, max(ground - 1, 0), pose(hand="up", leg="tuck"), None),
                (x, max(ground - 2, 0), pose(hand="up", leg="tuck"), None),
                (x, max(ground - 1, 0), pose(hand="up", leg="tuck"), None),
                (x, ground, pose(hand="up", leg="squat"), None)]
    seq.append((x, ground, pose(hand="up", leg="rest"), None))
    return seq

def _do_stretch(x, ground):
    """A stretch sequence for break nudges."""
    return [(x, ground, pose(hand="up", leg="stepA"), None)] + \
           [(x, ground, pose(hand="up"), None) for _ in range(6)]

def _gift_scene(pos, ground, inner, tier, glyph, right_pad):
    """The gift moment as a scene: it drops on the FAR side from the crab, the
    crab reacts, walks over, interacts, then it joins the hoard. Slow enough to
    watch. Returns (x, y, frame, drop) frames; leaves the crab by the gift."""
    lo, hi = crab_bounds(inner, right_pad)
    start = pos["x"]
    center = (lo + hi) // 2
    if start <= center:                              # crab on the left -> gift on the right
        gift_col, target, face = min(hi + WIDTH, inner - 1), hi, 1
    else:                                            # crab on the right -> gift on the left
        gift_col, target, face = lo, lo + 1, -1
    target = min(max(target, lo), hi)
    drop = (gift_col, glyph, tier)
    frames = []
    react = random.choice([                          # a random held reaction
        pose(hand="up", gaze=face),                  # arms up, excited
        pose(eye_open=False, gaze=face),             # surprised blink
        pose(leg="squat", gaze=face),                # alert crouch
    ])
    settle = pose(gaze=face)
    for k in range(14):                              # 1) lands + reaction (~1.4s)
        frames.append((start, ground, react if k % 2 == 0 else settle, drop))
    x, i = start, 0
    while x != target:                               # 2) walk over (looking at it)
        x += 1 if target > x else -1
        frames.append((x, ground, pose(hand="down", gaze=face,
                                        leg="stepA" if i % 2 else "stepB"), drop))
        i += 1
    for k in range(12):                              # 3) interact (~1.2s)
        p = pose(hand="up", gaze=face) if k % 2 else pose(leg="squat", gaze=face)
        frames.append((x, ground, p, drop))
    for _ in range(1 + tier):                        # 4) absorb -> hoard; happy bob
        frames += [(x, ground, pose(hand="up", leg="squat"), None),
                   (x, ground, pose(hand="up", leg="tuck"), None),
                   (x, ground, pose(hand="up", leg="squat"), None)]
    frames.append((x, ground, pose(hand="up", leg="rest"), None))
    pos["x"] = x
    return frames

def animate(color=True, fps=10, name="kh"):
    import time
    if not sys.stdout.isatty():
        print(welcome(color)); return

    cfg = cs.load_config()
    repos = cs.watched_repos(cfg, os.getcwd())
    author = cfg.get("author")          # None = count all commits in watched repos
    state = cs.load_state()

    # Background thread: poll GitHub for open PRs you authored (network calls, so
    # kept off the render loop). It only enqueues; the main loop does the gifting.
    pr_q = queue.Queue()
    # Seed from the last-known PR stats so the vitals line is correct instantly;
    # the background fetch refreshes it within a couple seconds.
    pr_stats_box = {"v": state.get("pr_cache") or {"prs": 0, "lines": 0, "streak": 0}}
    gifted = set(state.get("pr_gifted", []))
    def _pr_worker():
        seen = set(gifted)
        while True:
            prs = cs.fetch_my_prs(repos)
            pr_stats_box["v"] = cs.pr_day_stats(prs)        # feeds the vitals line
            for p in prs:
                key = f"{p['repo']}#{p['number']}"
                if key in seen:
                    continue
                seen.add(key)
                if p.get("state") == "OPEN":               # PRs are simple acknowledgements
                    pr_q.put((key, {"number": p["number"], "ack": True}))
            time.sleep(30)
    threading.Thread(target=_pr_worker, daemon=True).start()

    inner = max(_term_width() - 3, WIDTH + 4)
    stage_h = 5
    ground = stage_h - 3
    mood_box = {"mood": "okay"}
    mood = "okay"
    pos = {"x": (inner - WIDTH) // 2}             # the crab's column, shared with behaviors
    gen = behaviors(inner, stage_h, mood_box, right_pad=HOARD_CAP + 1, pos=pos)
    hoard_g = cs.hoard_glyphs(cs.hoard_summary(state))
    n = render_window(color, stage_h=stage_h).count("\n") + 1
    delay = 1.0 / max(fps, 1)
    poll_every = max(1, int(fps * 4))             # re-check git + vitals ~every 4s

    GREET_SEC, ROTATE_SEC = 20, 180               # greet ~20s, then refresh every 3 min
    idle_speech = SPEECH                          # the Claude-style opening line first
    idle_next = time.time() + GREET_SEC
    temp_speech, temp_until = "", 0.0             # transient gift/event/break lines
    recent_until = 0.0                            # window after a commit (for cheering)
    type_text, type_start, TYPE_CPS = "", 0.0, 9.0    # bubble typewriter state (chars/sec)
    cur_stats = list(STATS)
    gift_queue = []                               # gifts waiting to be SHOWN (one at a time)
    pending = _boot_wave(pos["x"], ground, fps)   # one-hand wave + 1s cooldown, every launch
    commit_seen = None                            # SHAs already gifted (None = baseline first)
    today, strk = {"added": 0, "commits": 0}, 0   # until the first poll fills them in

    # --- chat: read the keyboard (raw mode) and talk to Claude on a worker thread
    import select, termios, tty
    chat_q = queue.Queue()
    chat_buf, chat_history = "", []
    chat_ok = sys.stdin.isatty() and cc.available()
    fd, old_term = None, None
    if sys.stdin.isatty():
        try:
            fd = sys.stdin.fileno()
            old_term = termios.tcgetattr(fd)
            tty.setcbreak(fd)                      # keys arrive immediately; Ctrl-C still works
        except Exception:
            fd, old_term = None, None              # not a real tty -> no keyboard input
    n += 1                                          # the input line drawn under the box

    sys.stdout.write("\033[?25l")
    try:
        first, i = True, 0
        while True:
            now = time.time()
            while not pr_q.empty():               # --- queue newly-opened PRs (shown later)
                key, g = pr_q.get()
                if key in gifted or any(k == key for _, _, k in gift_queue):
                    continue
                gift_queue.append((g, cs.pr_speech(g), key))
            while not chat_q.empty():             # --- the crab's chat reply landed
                reply = chat_q.get()
                chat_history.append({"role": "assistant", "content": reply})
                temp_speech, temp_until = reply, now + max(5.0, len(reply) / TYPE_CPS + 3)
            if i % poll_every == 0:               # --- poll: vitals, git, reactions
                events = cs.tick(state, repos, now)
                today = cs.today_stats(repos, author)
                quests = cs.quests_status(state, today)
                fresh = cs.newly_completed(state, quests)
                mood = cs.day_mood(state, today, now)
                mood_box["mood"] = mood
                mood_box["energy"] = state["energy"]
                mood_box["belly"] = 100 - state["hunger"]
                mood_box["happiness"] = state["happiness"]
                mood_box["hour"] = datetime.datetime.now().hour
                mood_box["has_hoard"] = bool(cs.hoard_summary(state).get("count"))
                mood_box["recent_commit"] = now < recent_until
                strk = cs.streak(repos, author)
                cur_stats = cs.stat_lines(state, quests, today, pr_stats_box["v"], strk)
                if strk in MILESTONES and strk not in state.setdefault("celebrated_ms", []):
                    state["celebrated_ms"].append(strk)         # arm the milestone dance, once
                    mood_box["milestone_ready"] = True
                cgifts, commit_seen = cs.detect_commit_gifts(repos, author, commit_seen)
                for g in cgifts:                                      # every commit -> a gift
                    gift_queue.append((g, cs.commit_gift_speech(g), None))
                if cgifts:
                    recent_until = now + 30                           # window for cheering
                if not pending and not gift_queue and (events or fresh):
                    pending = _celebrate(pos["x"], ground)
                    temp_speech, temp_until = cs.speech(state, mood, events, fresh, False, name), now + 4
                elif not pending and not gift_queue and cs.break_due(state, now):
                    pending = _do_stretch(pos["x"], ground)
                    cs.take_break(state, now)
                    temp_speech, temp_until = cs.speech(state, mood, [], [], True, name), now + 4
                if now >= idle_next:                      # refresh the idle line periodically
                    idle_speech = cs.idle_speech(state, mood, pr_stats_box["v"], name)
                    idle_next = now + ROTATE_SEC
                state["pr_cache"] = pr_stats_box["v"]     # cache for instant next launch
                cs.save_state(state)

            if not pending and gift_queue:        # --- show a queued commit-gift or PR ack
                g, line, key = gift_queue.pop(0)
                if key:                            # a PR: mark it acknowledged (once)
                    gifted.add(key); state["pr_gifted"] = sorted(gifted)
                if g.get("ack"):                   # PR -> quick bounce, no gift mechanics
                    pending = _celebrate(pos["x"], ground)
                else:                              # commit -> full gift scene + feed + hoard
                    cs.record_gift(state, g); cs.feed_gift(state, g)
                    hoard_g = cs.hoard_glyphs(cs.hoard_summary(state))
                    pending = _gift_scene(pos, ground, inner, g["tier"],
                                          cs.TIER_EMOJI[g["tier"]], HOARD_CAP + 1)
                temp_speech, temp_until = line, now + len(pending) * delay + 2
                cs.save_state(state)

            if pending:
                x, y, frame, drop = pending.pop(0); emote = None
            else:
                x, y, frame, emote = next(gen); drop = None

            disp = temp_speech if now < temp_until else idle_speech
            if disp != type_text:                 # new line -> (re)start typing it out
                type_text, type_start = disp, now
            typed = type_text[:int((now - type_start) * TYPE_CPS)]
            bubble = typed + " " * max(_vlen(type_text) - _vlen(typed), 0)  # hold full width
            win = render_window(color, stage_h=stage_h, x=x, y=y, frame=frame,
                                speech=bubble, stats=cur_stats, hoard=hoard_g,
                                drop=drop, emote=emote)
            win += "\n" + _input_line(chat_buf, inner, color, chat_ok)
            if not first:
                sys.stdout.write(f"\033[{n}A")
            sys.stdout.write("".join("\r" + ln + "\033[K\n" for ln in win.split("\n")))
            sys.stdout.flush()
            first, i = False, i + 1

            # --- wait one frame; meanwhile read the keyboard (non-blocking)
            if fd is not None:
                r, _, _ = select.select([sys.stdin], [], [], delay)
                if r:
                    chat_buf, submit = _handle_keys(chat_buf, os.read(fd, 256))
                    if submit and submit.strip():
                        if not chat_ok:
                            temp_speech, temp_until = "(set ANTHROPIC_API_KEY to chat!)", now + 5
                        else:
                            chat_history.append({"role": "user", "content": submit.strip()})
                            del chat_history[:-10]              # keep recent turns only
                            temp_speech, temp_until = "hmm…", now + 60
                            vit = {"belly": 100 - state["hunger"], "energy": state["energy"],
                                   "lines": today.get("added", 0), "commits": today.get("commits", 0),
                                   "streak": strk, "name": name}
                            threading.Thread(target=lambda h=list(chat_history):
                                             chat_q.put(cc.ask(h, vit)), daemon=True).start()
            else:
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        cs.save_state(state)
        if old_term is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

def _status_frame(color):
    """One live frame (no animation) — handy for a quick check or a shell hook."""
    cfg = cs.load_config()
    repos = cs.watched_repos(cfg, os.getcwd())
    author = cfg.get("author")          # None = count all commits in watched repos
    state = cs.load_state()
    cs.tick(state, repos)
    today = cs.today_stats(repos, author)
    quests = cs.quests_status(state, today)
    cs.newly_completed(state, quests)
    mood = cs.day_mood(state, today)
    cs.save_state(state)
    pr_stats = cs.pr_day_stats(cs.fetch_my_prs(repos))
    state["pr_cache"] = pr_stats                          # warm the cache for next launch
    cs.save_state(state)
    stats = cs.stat_lines(state, quests, today, pr_stats, cs.streak(repos, author))
    sp = cs.speech(state, mood, [], [], cs.break_due(state))
    hoard_g = cs.hoard_glyphs(cs.hoard_summary(state))
    return render_window(color, stage_h=3, speech=sp, stats=stats, hoard=hoard_g)

def main(argv):
    color = "--no-color" not in argv
    if "--watch" in argv:                          # add a repo to the watch list
        i = argv.index("--watch")
        target = os.path.abspath(argv[i + 1] if i + 1 < len(argv) else ".")
        cfg = cs.load_config()
        root = cs.git_root(target)
        if not root:
            print("not a git repo:", target)
        elif root in cfg["repos"]:
            print("already watching:", root)
        else:
            cfg["repos"].append(root); cs.save_config(cfg)
            print("now watching:", root)
    elif "--unwatch" in argv:                       # remove a repo from the list
        i = argv.index("--unwatch")
        target = os.path.realpath(argv[i + 1]) if i + 1 < len(argv) else ""
        cfg = cs.load_config()
        match = next((r for r in cfg.get("repos", []) if os.path.realpath(r) == target), None)
        if match:
            cfg["repos"].remove(match); cs.save_config(cfg); print("unwatched:", match)
        else:
            print("not in watch list:", target)
    elif "--list" in argv:                          # show the watch list
        cfg = cs.load_config()
        repos = cfg.get("repos", [])
        who = cfg.get("author") or "everyone (no author filter)"
        print("counting:", who)
        print("watching:" if repos else "watching nothing yet (use: crab --watch <path>)")
        for r in repos:
            print("  ", r)
    elif "--me" in argv:                             # only count YOUR commits
        i = argv.index("--me")
        nxt = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("-") else None
        cfg = cs.load_config()
        if nxt == "off":
            cfg["author"] = None; cs.save_config(cfg)
            print("author filter off — counting everyone in the watched repos")
        else:
            email = nxt or cs.default_author()
            if not email:
                print("couldn't detect your git email; pass it: crab --me you@example.com")
            else:
                cfg["author"] = email; cs.save_config(cfg)
                print("now counting only commits by:", email)
    elif "--hoard" in argv:                         # everything you've gifted the crab
        h = cs.hoard_summary(cs.load_state())
        print("🦀  your hoard")
        print(f"    gifts given : {h['count']}")
        print(f"    net lines   : {h['net']}")
        order = [t[1] for t in reversed(cs.GIFT_TIERS)]
        for name in order:
            c = h.get("by_tier", {}).get(name, 0)
            if c:
                print(f"    {name:9} x{c}")
        if not h["count"]:
            print("    (nothing yet — push some work and watch the crab receive it)")
    elif "--animate" in argv:
        animate(color)
    elif "--status" in argv:
        print(_status_frame(color))
    elif "--welcome" in argv:
        print(welcome(color))
    else:
        print(crab(color))

if __name__ == "__main__":
    main(sys.argv[1:])
