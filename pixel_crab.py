#!/usr/bin/env python3
"""Claudagocchi — a terminal crab that lives in a Claude Code-style window.

The crab is built on the Claude Code quadrant-block mark:
    eye row:  ▗ # ▗ # # # ▖ # ▖   (hands ▗▖ at cols 0/8, eyes ▗▖ at cols 2/6,
    body:     · # # # # # # # ·    coral body fill at cols 1..7)
    legs:     · · ▘ ▘ · ▝ ▝ · ·

Body/eyes use ANSI background colors (no █); hands/legs are coral quadrant glyphs.

That layout is the `adult` entry in MORPHS; the crab grows through smaller and
larger morphs as it ages (see `Morph`). All column placement is by inset from the
sprite edges, mirrored, so every morph is symmetric by construction.

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
import collections
import datetime
import threading
import queue
import dataclasses
import subprocess
import pathlib

import crab_state as cs
import crab_chat as cc
import crab_games as cg
import crab_tokens as ctok
import crab_sessions as csess
import crab_hall
import crab_admin
import crab_commands as ccmd

CORAL = (200, 126, 95)
EYE   = (24, 24, 28)
RESET = "\033[0m"
def fg(rgb): r, g, b = rgb; return f"\033[38;2;{r};{g};{b}m"
def bg(rgb): r, g, b = rgb; return f"\033[48;2;{r};{g};{b}m"

WALL_PAD = 4                    # invisible margin (cols) keeping the crab off the walls
EYE_GLYPHS = ("▗", "▖")         # left eye, right eye

# --- life-stage morphs -------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Morph:
    """One life stage or adult form.

    Column placement is by INSET from the sprite edges and mirrored about the
    center, so a morph is symmetric by construction and reads the same at any
    width. (Fractional placement is not: it breaks symmetry under banker's
    rounding at w=11 and collides at w=5.)

      rows 0 .. body_rows-1 : filled body, cols body_inset .. w-1-body_inset
      face_row              : eyes + hands, drawn on top of the body
      leg_row (default h-1) : leg glyphs
    """
    key:        str
    label:      str
    w:          int                 # sprite width
    h:          int                 # sprite height
    body_rows:  int                 # filled rows, counted from row 0
    color:      tuple               # body fill / eye backdrop / limb glyphs
    body_inset: int = 1
    face_row:   int = 0
    eye_inset:  int = 2             # None -> eyeless (blinks become no-ops)
    hand_inset: int = 0             # None -> handless
    leg_insets: tuple = (2, 3)      # outer -> inner, per side; () -> legless
    leg_row:    int = None          # None -> h - 1

    @property
    def eye_cols(self):  return (self.eye_inset, self.w - 1 - self.eye_inset)
    @property
    def hand_cols(self): return (self.hand_inset, self.w - 1 - self.hand_inset)
    @property
    def legs_per_side(self): return len(self.leg_insets)
    @property
    def leg_cols(self):
        """Leg columns in ascending order (left side, then mirrored right side)."""
        left = sorted(self.leg_insets)
        right = sorted(self.w - 1 - i for i in self.leg_insets)
        return tuple(left) + tuple(right)
    @property
    def lrow(self): return (self.h - 1) if self.leg_row is None else self.leg_row
    @property
    def body_span(self):
        """Inclusive (lo, hi) columns the eyes may wander between."""
        return (self.body_inset, self.w - 1 - self.body_inset)

MORPHS = {
    # --- linear growth ------------------------------------------------------
    "egg":      Morph("egg", "egg", w=5, h=2, body_rows=2, color=(214, 200, 178),
                      eye_inset=None, hand_inset=None, leg_insets=()),
    "baby":     Morph("baby", "hatchling", w=7, h=2, body_rows=1, color=(232, 168, 140),
                      leg_insets=(2,)),
    "juvenile": Morph("juvenile", "juvenile", w=7, h=3, body_rows=2, color=(214, 145, 110),
                      leg_insets=(1, 2)),
    "adult":    Morph("adult", "crab", w=9, h=3, body_rows=2, color=CORAL),  # == the original
    # --- branching adult forms, earned from how you code --------------------
    "architect": Morph("architect", "architect", w=11, h=4, body_rows=3, color=(94, 124, 166),
                       eye_inset=3),
    "grinder":   Morph("grinder", "grinder", w=9, h=4, body_rows=3, color=(150, 120, 200)),
    "gamer":     Morph("gamer", "gamer", w=11, h=3, body_rows=2, color=(110, 180, 120),
                       leg_insets=(2, 3, 4)),                        # six legs
    "feral":     Morph("feral", "feral", w=11, h=4, body_rows=3, color=(222, 178, 90),
                       leg_insets=(3, 4)),
}
ADULT       = MORPHS["adult"]
MAX_MORPH_W = max(m.w for m in MORPHS.values())
MAX_MORPH_H = max(m.h for m in MORPHS.values())
STAGE_H     = 5                 # animate stage height; MUST stay constant (see animate)

for _m in MORPHS.values():      # geometry validator: catches typos in the table above
    assert _m.h <= STAGE_H - 1, f"{_m.key}: too tall, leaves no room for the emote row"
    assert _m.body_rows <= _m.h and _m.lrow < _m.h, f"{_m.key}: rows out of range"
    _ins = list(_m.leg_insets) + [i for i in (_m.eye_inset, _m.hand_inset) if i is not None]
    assert all(i * 2 < _m.w - 1 for i in _ins), f"{_m.key}: mirrored columns collide"
    assert len(set(_m.leg_cols)) == len(_m.leg_cols), f"{_m.key}: duplicate leg columns"
del _m

# Pose vocabularies. Hands are a (left, right) pair. Legs are two per-side tuples
# ordered OUTER -> INNER: they are not a plain mirror, because stepA/stepB are
# deliberately anti-phase — that antisymmetry is what makes the walk read as a walk.
HAND_POSES = {
    "down":  ("▗", "▖"),                # resting at sides
    "up":    ("▝", "▘"),                # raised (stretch / reach)
    "walkA": ("▝", "▖"),                # mid-stride swing
    "walkB": ("▗", "▘"),
    "clasp": ("▖", "▗"),                # claws pulled in toward the body
    "point": ("▝", "▗"),                # left claw up, right tucked: "look, over there"
    "flail": ("▘", "▝"),                # both claws thrown outward
}
LEG_POSES = {
    "rest":  (("▘", "▘"), ("▝", "▝")),
    "stepA": (("▘", "▖"), ("▗", "▝")),          # walk cycle frame A
    "stepB": (("▖", "▘"), ("▝", "▗")),          # walk cycle frame B
    "squat": (("▖", "▗"), ("▗", "▖")),          # crouched, feet splayed
    "tuck":  ((None, "▗"), (None, "▖")),        # tucked up (mid-air); None = bare
    "tiptoe": (("▘", "▘"), ("▘", "▘")),         # up on the points, leaning one way
    "splay": (("▖", "▖"), ("▗", "▗")),          # planted wide, braced
    "sideL": (("▖", "▘"), ("▖", "▘")),          # sideways scuttle, leading left
    "sideR": (("▝", "▗"), ("▝", "▗")),          # sideways scuttle, leading right
}

def _fit(spec, n):
    """Fit a per-side leg spec (outer -> inner) to n legs: trim from the outside,
    pad by repeating the outermost glyph."""
    if n <= len(spec):
        return tuple(spec[len(spec) - n:])
    return (spec[0],) * (n - len(spec)) + tuple(spec)

def _leg_glyphs(name, n):
    """Leg glyphs in ascending column order for a morph with n legs per side."""
    left, right = LEG_POSES[name]
    return _fit(left, n) + tuple(reversed(_fit(right, n)))

def pose(eye_open=True, hand="down", leg="rest", gaze=0):
    """A crab pose: NAMES for hands/legs (resolved against a morph at draw time,
    so poses are width-agnostic), plus gaze (-1 left, 0 fwd, 1 right)."""
    return {"eye_open": eye_open, "hand": hand, "leg": leg, "gaze": gaze}

def _build(eye_open=True, hand="down", leg="rest", gaze=0, morph=ADULT):
    """The sprite as a morph.h x morph.w grid of cells: "." blank, "#" body fill,
    or (kind, glyph). Write order body -> eyes -> hands, so a hand always wins."""
    m = morph
    g = [["."] * m.w for _ in range(m.h)]
    for r in range(m.body_rows):
        for c in range(m.body_inset, m.w - m.body_inset):
            g[r][c] = "#"
    if eye_open and m.eye_inset is not None:   # eyes glance toward `gaze` by one column,
        lo, hi = m.body_span                   # staying on the body (crab faces forward)
        for c, ch in zip(m.eye_cols, EYE_GLYPHS):
            g[m.face_row][min(max(c + gaze, lo), hi)] = ("eye", ch)
    if m.hand_inset is not None:
        for c, ch in zip(m.hand_cols, HAND_POSES[hand]):
            g[m.face_row][c] = ("hand", ch)
    for c, ch in zip(m.leg_cols, _leg_glyphs(leg, m.legs_per_side)):
        if ch:
            g[m.lrow][c] = ("leg", ch)
    return g

def _render_cell(tok, color, body=CORAL):
    if tok == ".":
        return " "
    if tok == "#":
        return (bg(body) + " " + RESET) if color else " "
    kind, ch = tok
    if kind == "eye":
        return (bg(body) + fg(EYE) + ch + RESET) if color else ch
    return (fg(body) + ch + RESET) if color else ch    # hand or leg glyph

def crab_rows(color=True, morph=ADULT, **frame):
    """The crab's raw rows (morph.h of them, each morph.w columns, with ANSI)."""
    return ["".join(_render_cell(c, color, morph.color) for c in row)
            for row in _build(morph=morph, **frame)]

def ground_y(stage_h, morph):
    """Top row `y` placing the sprite's last row on the stage floor."""
    return stage_h - morph.h

def _hop(ground, n=1):
    """Rise n rows without leaving the stage."""
    return max(ground - n, 0)

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
    """The chat input row drawn under the box. Commands work with or without an
    API key, so the hint always offers `help` -- only conversation needs a key."""
    if buf:
        shown = buf[-(inner - 4):] if len(buf) > inner - 4 else buf
        s = "  › " + shown + "▏"
    elif ok:
        s = "  › talk to me, or type `help` · Enter to send"
    else:
        s = "  › type `help` for commands · chat needs ANTHROPIC_API_KEY"
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

def _clip(s, width):
    """Trim s to at most `width` visible columns, adding … if it was cut."""
    if _vlen(s) <= width:
        return s
    out, w = "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width - 1:
            break
        out += ch; w += cw
    return out + "…"

def _center_text(s, width):
    """Center s in `width` columns, accounting for full-width characters."""
    if len(s) > width:                     # safety: never overflow the box
        s = s[:width]
    pad = max(width - _vlen(s), 0)
    left = pad // 2
    return " " * left + s + " " * (pad - left)

def _center(lines, w):
    margin = " " * max((_term_width() - w) // 2, 0)
    return [margin + l for l in lines]

def crab(color=True, morph=ADULT, **frame) -> str:
    """Standalone crab, centered in the terminal, no box."""
    return "\n".join(_center(crab_rows(color, morph, **frame), morph.w))

# --- The Claudagocchi window -------------------------------------------------
TITLE = "Claudagocchi"
SPEECH = "Welcome back kh!"                 # -> speech bubble later
# Placeholder stats. The window's line count is measured from these ONCE at
# startup, so this list must have exactly as many entries as cs.stat_lines
# returns -- one short and the first frame is a line shorter than every frame
# after it, and the in-place redraw tears for the rest of the session.
STATS = ["~ヽ(｡･ω･｡)", "tokens used today …", "tokens all-time …", "live …"]

INTRO_TITLE = "Claude"          # what the box calls itself while it plays dead
INTRO_GREETING = "Welcome back, Kengo!"      # already on screen when it opens
INTRO_LINE = "let's start tokenmaxxing 🦀"    # and what it says for the rest of it

def _intro_stats():
    """Claude Code's own status lines, for the CRAB_INTRO still.

    The joke needs the frame to pass for Claude until the crab blinks, so the
    box wears Claude's title and status bar and drops both on the blink. Must
    stay the same length as STATS -- the redraw height is measured from that.
    """
    cwd = os.getcwd().replace(os.path.expanduser("~"), "~", 1)
    return ["Opus 5 (1M context) with medium effort · Claude Max", cwd,
            "auto mode on (shift+tab to cycle) · ← for agents",
            "◐ medium · /effort · /rc"]

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

HEADSTONE = "†"
HEADSTONE_COLOR = (120, 120, 130)

def render_window(color=True, stage_h=3, x=None, y=0, frame=None, speech=None,
                  stats=None, hoard=None, drop=None, emote=None, morph=ADULT,
                  headstone=False, title=None) -> str:
    """Draw the window with the crab sprite placed at (x, y) on a stage_h-tall
    stage. `speech`/`stats` override the static placeholders when live;
    `hoard` is a list of (glyph, tier) drawn as a pile in the bottom-right;
    `drop` is an optional (col, glyph, tier) gift sitting on the ground;
    `headstone` marks the far left when this crab has ancestors."""
    # Leave one spare column on the right so the right wall is never clipped at
    # the terminal edge. The floor is morph-INdependent so that two callers
    # computing `inner` can never disagree across an evolution.
    inner = max(_term_width() - 3, MAX_MORPH_W + 4)
    if x is None:
        x = (inner - morph.w) // 2
    x = min(max(x, 0), inner - morph.w)      # never let the sprite run past a wall
    if frame is None:
        frame = pose()
    sprite = crab_rows(color, morph, **frame)

    ground_row = stage_h - 1
    stage = []
    for r in range(stage_h):
        crab_seg = (x, sprite[r - y], morph.w) if y <= r < y + morph.h else None
        if r == ground_row:                          # crab legs + loose gift + hoard pile
            items = [crab_seg] if crab_seg else []   # crab has priority
            if headstone:                            # _place drops it if the crab is there
                items.append((0, (fg(HEADSTONE_COLOR) + HEADSTONE + RESET) if color
                              else HEADSTONE, 1))
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
        ecol = min(max(x + morph.w // 2, 0), inner - ew)
        es = (fg((150, 150, 160)) + emote + RESET) if color else emote
        stage[y - 1] = _place(inner, [(ecol, es, ew)])

    # Border, drawn entirely in coral (same as the Claudagocchi title).
    co = (lambda s: fg(CORAL) + s + RESET) if color else (lambda s: s)
    name = TITLE if title is None else title
    k = max(inner - 3 - len(name), 0)
    top = co("╭─ " + name + " " + "─" * k + "╮")
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

def _frame_window(color, inner, body, speech, stats) -> str:
    """Same box as render_window, but the stage rows are `body` (a minigame
    playfield: each row already exactly `inner` visible columns). Produces the
    identical line count to render_window so the in-place redraw stays aligned."""
    co = (lambda s: fg(CORAL) + s + RESET) if color else (lambda s: s)
    k = max(inner - 3 - len(TITLE), 0)
    top = co("╭─ " + TITLE + " " + "─" * k + "╮")
    bottom = co("╰" + "─" * inner + "╯")
    bar = co("│")
    def text(line): return bar + _center_text(line, inner) + bar
    def blank():     return bar + " " * inner + bar
    rows = [top, blank(), text(speech), blank()]
    rows += [bar + s + bar for s in body]
    rows += [blank()] + [text(s) for s in stats] + [blank(), bottom]
    return "\n".join(rows)

def welcome(color=True, morph=ADULT) -> str:
    # stage_h must track the morph: a shorter stage silently drops the leg row.
    return render_window(color, stage_h=morph.h, morph=morph)

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
    stage  = ctx.get("stage", "adult")
    health = ctx.get("health", 100)
    sick   = health < 60
    mourns = ctx.get("mourning", False)
    base   = MOOD_WEIGHTS.get(mood, MOOD_WEIGHTS["okay"])   # [sit,saunter,stretch,groom,pounce]

    if stage == "egg":              # an egg can only sit there and twitch
        return {"eggwobble": 6.0, "eggcrack": 1.0, "sit": 3.0}
    if stage == "baby":             # a hatchling has a small, clumsy repertoire
        return {"sit": 5.0, "saunter": 2.0 * (0.3 + e), "wiggle": 2.5, "yawn": 2.0,
                "beg": 5.0 if hungry else 0.5, "doze": 4.0 if e < 0.3 else 0.5,
                "shiver": 4.0 if sick else 0.0,
                "alert": 100.0 if ctx.get("alert_ready") else 0.0}
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
        # --- v2.0 -----------------------------------------------------------
        "sidescuttle": 3.5 * (0.4 + e),          # crabs move sideways; the signature gait
        "shiver":      5.0 if sick else 0.0,     # cold and unwell
        "sneeze":      2.5 if sick else 0.0,
        "stargaze":    2.5 if night else 0.0,
        "tidyhoard":   1.8 if hoard else 0.0,
        "buryitem":    1.2 if hoard else 0.0,
        "chaselegs":   2.5 * e if not hungry else 0.0,
        "zoomies":     (3.5 if mood == "energetic" else 0.5) * e,
        "drumfeet":    2.0 if hungry else 0.4,
        "moltprep":    6.0 if ctx.get("molt_soon") else 0.0,   # telegraphs an evolution
        "mourn":       4.0 if mourns else 0.0,
        # triggered, jump the queue
        "milestone":  100.0 if ctx.get("milestone_ready") else 0.0,
        "alert":      100.0 if ctx.get("alert_ready") else 0.0,
    }
    return {k: max(0.0, v) for k, v in w.items()}

MILESTONES = {3, 7, 14, 21, 30, 50, 100, 200, 365}   # streak days worth a party

ACCESSORIES = ["🎩", "👑", "🎀", "🧢", "🎈", "🧸", "⚽", "🎾", "🪀", "🦴"]  # hats & toys
HEAD_CLASH = {"♥", "!", "˚", "°", "○"}   # reactions that would clash with a worn hat

def _with_accessory(gen, fps=10):
    """Wrap a behavior stream so the crab occasionally turns up wearing a
    random hat or toy above its head -- shown whenever there's no other
    emote in play, swapped out (or put away) every few minutes. While worn,
    the heart/exclamation/bubble reactions are skipped (they'd sit right on
    top of the hat) rather than replacing it."""
    acc, left = None, 0
    for x, y, frame, emote in gen:
        if left <= 0:
            acc = random.choice(ACCESSORIES) if random.random() < 0.2 else None
            left = random.randint(int(fps * 45), int(fps * 150))
        left -= 1
        if acc and emote in HEAD_CLASH:
            emote = None
        yield x, y, frame, emote or acc

def crab_bounds(inner, right_pad, morph):
    """The left/right columns the crab may stand at (clear of walls + hoard)."""
    maxx = inner - morph.w
    lo = min(WALL_PAD, maxx // 2)
    hi = max(maxx - WALL_PAD - right_pad, lo)
    return lo, hi

def behaviors(inner, stage_h, morph, mood_box=None, right_pad=0, pos=None):
    """Infinite stream of (x, y, frame) — calm, cat-like actions weighted by the
    crab's current mood (read live from mood_box). The crab's column lives in the
    shared `pos` dict so other code (e.g. a gift scene) can move it and have the
    idle loop resume from the new spot."""
    ground = ground_y(stage_h, morph)
    lo, hi = crab_bounds(inner, right_pad, morph)
    if pos is None:
        pos = {"x": (inner - morph.w) // 2}
    pos["x"] = min(max(pos.get("x", (inner - morph.w) // 2), lo), hi)

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
            for yy in (_hop(ground, 1), _hop(ground, 2), _hop(ground, 2)):
                yield pos["x"], max(yy, 0), pose(hand="up", leg="tuck"), None
            yield pos["x"], _hop(ground, 1), pose(leg="tuck"), None
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
            yield pos["x"], _hop(ground, 1), pose(hand="up", leg="tuck"), None
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
                yy = _hop(ground, 1) if i % 2 else ground
                yield pos["x"], yy, pose(hand="up", gaze=1 if i % 4 < 2 else -1,
                                         leg="tuck" if i % 2 else "squat"), \
                      ("★" if i % 2 == 0 else None)
            yield pos["x"], ground, pose(), None

        elif action == "alert":                       # a session is blocked on you
            ctx["alert_ready"] = False
            for i in range(random.randint(16, 22)):   # wave both claws and point
                yield pos["x"], _hop(ground, 1) if i % 4 == 0 else ground, \
                      pose(hand="up" if i % 2 else "point", gaze=0,
                           leg="tiptoe" if i % 2 else "splay"), \
                      ("!" if i % 3 else None)
            yield pos["x"], ground, pose(), None

        elif action == "sidescuttle":                 # the signature crab gait: sideways
            d = random.choice([-1, 1])
            legs = "sideR" if d > 0 else "sideL"
            for i in range(random.randint(10, 18)):
                d = step_x(d)
                legs = "sideR" if d > 0 else "sideL"
                yield pos["x"], ground, pose(hand="clasp", gaze=d,
                                             leg=legs if i % 2 else "splay"), None

        elif action == "shiver":                      # cold, unwell, drawn in tight
            for i in range(random.randint(14, 20)):
                yield pos["x"], ground, pose(eye_open=(i % 5 != 0), hand="clasp",
                                             gaze=1 if i % 2 else -1,
                                             leg="squat" if i % 2 else "tuck"), None

        elif action == "sneeze":                      # winds up, then a whole-body sneeze
            for _ in range(4):
                yield pos["x"], ground, pose(eye_open=False, hand="clasp", leg="squat"), None
            yield pos["x"], _hop(ground, 1), pose(hand="flail", leg="splay"), "!"
            for _ in range(3):
                yield pos["x"], ground, pose(hand="down", leg="squat"), None

        elif action == "stargaze":                    # sits and looks up for a while
            for i in range(random.randint(16, 24)):
                yield pos["x"], ground, pose(hand="down", gaze=0, leg="rest"), \
                      ("˚" if i % 8 < 4 else "°")

        elif action == "tidyhoard":                   # fusses over the pile, rearranging
            for _ in range(random.randint(4, 8)):
                if pos["x"] >= hi:
                    break
                step_x(1)
                yield pos["x"], ground, pose(gaze=1, leg="stepA"), None
            for i in range(random.randint(8, 14)):
                yield pos["x"], ground, pose(hand="walkA" if i % 2 else "walkB",
                                             gaze=1, leg="squat"), None

        elif action == "buryitem":                    # digs, drops something in, pats it down
            for i in range(6):
                yield pos["x"], ground, pose(hand="walkA" if i % 2 else "walkB",
                                             leg="squat"), None
            yield pos["x"], ground, pose(hand="clasp", leg="squat"), "◦"
            for i in range(6):
                yield pos["x"], ground, pose(hand="down", leg="splay" if i % 2 else "squat"), None

        elif action == "chaselegs":                   # spins after its own back legs
            for i in range(random.randint(12, 18)):
                yield pos["x"], ground, pose(gaze=1 if i % 4 < 2 else -1,
                                             hand="walkA" if i % 2 else "walkB",
                                             leg="stepA" if i % 2 else "stepB"), None

        elif action == "zoomies":                     # a fast lap with the claws up
            d = random.choice([-1, 1])
            for i in range(random.randint(16, 26)):
                d = step_x(d)
                d = step_x(d)                         # two columns a frame: properly quick
                yield pos["x"], ground if i % 2 else _hop(ground, 1), \
                      pose(hand="up", gaze=d, leg="tuck" if i % 2 else "stepA"), None
            yield pos["x"], ground, pose(leg="squat"), None

        elif action == "drumfeet":                    # impatient, all feet going
            for i in range(random.randint(12, 18)):
                yield pos["x"], ground, pose(hand="clasp", gaze=0,
                                             leg=("splay", "tiptoe", "squat")[i % 3]), \
                      ("!" if i % 6 == 0 else None)

        elif action == "moltprep":                    # something is about to change
            for i in range(random.randint(18, 26)):
                yield pos["x"], ground, pose(eye_open=(i % 3 != 0), hand="clasp",
                                             leg="squat" if i % 2 else "tuck"), \
                      ("˚" if i % 4 == 0 else None)

        elif action == "mourn":                       # walks to the headstone and sits with it
            for _ in range(inner):
                if pos["x"] <= lo:
                    break
                step_x(-1)
                yield pos["x"], ground, pose(hand="clasp", gaze=-1,
                                             leg="stepA" if pos["x"] % 2 else "stepB"), None
            for i in range(random.randint(14, 22)):
                yield pos["x"], ground, pose(eye_open=(i % 7 != 0), hand="down",
                                             gaze=-1, leg="rest"), \
                      ("♥" if i % 8 == 0 else None)

        elif action == "eggwobble":                   # the egg rocks in place
            for i in range(random.randint(10, 18)):
                yield pos["x"], ground, pose(gaze=1 if i % 4 < 2 else -1), None

        elif action == "eggcrack":                    # a promising twitch
            for i in range(random.randint(6, 10)):
                yield pos["x"], ground if i % 2 else _hop(ground, 1), pose(), \
                      ("˚" if i % 3 == 0 else None)

        else:                                        # "sit" + any not-yet-built action: loaf
            n = random.randint(10, 22)
            blink_at = random.randint(2, max(2, n - 4))   # one short blink, mid-action
            for i in range(n):
                closed = blink_at <= i < blink_at + 2
                yield pos["x"], ground, pose(eye_open=not closed), None

TOKEN_POLL = 5          # seconds between token scans
RATE_WINDOW = 60        # trailing seconds the burn rate averages over

def _burn_rate(samples, now, today_total):
    """Tokens/min over the trailing RATE_WINDOW, from successive daily totals.

    The token cache keeps only the calendar date of each entry, never the time,
    so the rate cannot be queried out of it -- it has to be measured by
    watching the total move. Returns None until there are two samples to
    difference.
    """
    samples.append((now, today_total))
    while len(samples) > 2 and now - samples[0][0] > RATE_WINDOW:
        samples.popleft()
    if len(samples) < 2:
        return None
    if today_total < samples[0][1]:       # midnight: `today` reset out from under us
        samples.clear()
        samples.append((now, today_total))
        return 0.0
    elapsed = now - samples[0][0]
    return (today_total - samples[0][1]) / elapsed * 60 if elapsed > 0 else None

def _boot_wave(x, ground, fps):
    """Launch greeting: a one-hand wave (~1s), then a ~1s still cooldown before
    the crab starts any action."""
    span = max(6, int(fps))
    wave = [(x, ground, pose(hand="walkA" if i % 2 == 0 else "down"), None)  # crab's right hand
            for i in range(span)]
    cooldown = [(x, ground, pose(), None) for _ in range(span)]              # still, settling
    return wave + cooldown

INTRO_STILL_SEC = 4.0        # the held "screenshot" before the blink
INTRO_HOPS = 2               # its first move, before it changes what it says
INTRO_SETTLE_SEC = 1.0       # landing beat, then ordinary crab life resumes

def _wake_scene(x, ground, fps):
    """CRAB_INTRO opening for the launch video.

    The crab holds a frame-for-frame still -- eyes open, ordinary pose, exactly
    what a screenshot of the app looks like -- so the viewer reads it as a
    static image. Then it blinks twice, which is the moment it turns out to be
    alive, and stays put a beat longer while it speaks before it starts moving.
    Fixed durations, so the recording's zoom keyframes can be timed against it.
    """
    span = max(1, int(fps))
    still = [(x, ground, pose(), None)]
    shut = [(x, ground, pose(eye_open=False), None)]
    hop = [(x, ground, pose(leg="squat"), None),
           (x, _hop(ground, 1), pose(leg="tuck"), None),
           (x, _hop(ground, 2), pose(leg="tuck"), None),
           (x, _hop(ground, 1), pose(leg="tuck"), None),
           (x, ground, pose(leg="squat"), None)]
    return (still * int(span * INTRO_STILL_SEC) +
            (shut * 2 + still * 2) * 2 +                      # blink, twice
            hop * INTRO_HOPS +                                # its first move
            still * int(span * INTRO_SETTLE_SEC))             # then _boot_wave


def _wake_beats(fps):
    """(frames of disguise, frames the opening greeting stays up).

    The disguise drops on the blink, but the greeting outlasts it: the crab
    hops first and only then changes what it is saying.
    """
    blinked = int(max(1, int(fps)) * INTRO_STILL_SEC) + 8
    return blinked, blinked + 5 * INTRO_HOPS

def _celebrate(x, ground):
    """A happy in-place bounce for commits / completed quests. 4-tuples: (x,y,frame,drop)."""
    seq = []
    for _ in range(2):
        seq += [(x, ground, pose(hand="up", leg="squat"), None),
                (x, _hop(ground, 1), pose(hand="up", leg="tuck"), None),
                (x, _hop(ground, 2), pose(hand="up", leg="tuck"), None),
                (x, _hop(ground, 1), pose(hand="up", leg="tuck"), None),
                (x, ground, pose(hand="up", leg="squat"), None)]
    seq.append((x, ground, pose(hand="up", leg="rest"), None))
    return seq

def _do_stretch(x, ground):
    """A stretch sequence for break nudges."""
    return [(x, ground, pose(hand="up", leg="stepA"), None)] + \
           [(x, ground, pose(hand="up"), None) for _ in range(6)]

def _death_scene(x, ground, fps):
    """The crab starves. A slow slump, a last look at you, then stillness.
    Deliberately unhurried -- this is the moment the whole game hangs on."""
    seq = []
    for i in range(int(fps * 1.5)):                  # 1) weak, shivering
        seq.append((x, ground, pose(eye_open=(i % 6 < 2), hand="down",
                                    leg="squat" if i % 2 else "rest"), None))
    for _ in range(int(fps)):                        # 2) one last look up at you
        seq.append((x, ground, pose(hand="up", gaze=0, leg="squat"), None))
    for _ in range(int(fps * 3)):                    # 3) down, and still
        seq.append((x, ground, pose(eye_open=False, hand="down", leg="tuck"), None))
    return seq

def _gift_scene(pos, ground, inner, tier, glyph, right_pad, morph):
    """The gift moment as a scene: it drops on the FAR side from the crab, the
    crab reacts, walks over, interacts, then it joins the hoard. Slow enough to
    watch. Returns (x, y, frame, drop) frames; leaves the crab by the gift."""
    lo, hi = crab_bounds(inner, right_pad, morph)
    start = pos["x"]
    center = (lo + hi) // 2
    if start <= center:                              # crab on the left -> gift on the right
        gift_col, target, face = min(hi + morph.w, inner - 1), hi, 1
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

CHIRP_SOUND = "/System/Library/Sounds/Submarine.aiff"

def _chirp():
    """Terminal bell plus a short sound, fired once when a session starts waiting.
    Never blocks the render loop and never raises if afplay isn't there."""
    try:
        sys.stdout.write("\a")
    except Exception:
        pass
    try:
        subprocess.Popen(["afplay", CHIRP_SOUND],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def game_left(morph):
    """Cols reserved for the crab + its 💻 on the left of a minigame panel."""
    return morph.w + 5

CRAB_COL = 1                     # the crab's column at its coding spot (bottom-left)

# Fake code the crab "writes" during the build-up — + green, - red, blank = context.
_CODE = [("+", "def play(self):"), ("+", "    while self.alive:"),
         ("-", "    # old loop"), ("+", "        self.step()"),
         ("+", "        self.score += 1"), ("-", "    return None"),
         ("+", "    if near(cactus): self.jump()"), (" ", "spawn_obstacle()"),
         ("+", "self.render(world)"), ("-", "# fixme: physics"),
         ("+", "for f in frames: tick(f)"), ("+", "draw(self.sprite)")]

def _code_row(marker, text, gw, color):
    raw = ((marker + " ") if marker.strip() else "  ") + text
    raw = raw[:gw]
    rgb = {"+": (90, 185, 95), "-": (215, 90, 90)}.get(marker, (140, 140, 150))
    body = (fg(rgb) + raw + RESET) if color else raw
    return body + " " * max(gw - _vlen(raw), 0)

def _line_seq(n=40):
    """An ordering of _CODE that reliably mixes added (+) and removed (-) lines,
    so the build-up always shows both green and red."""
    adds = [c for c in _CODE if c[0] == "+"]
    rems = [c for c in _CODE if c[0] == "-"]
    ctx = [c for c in _CODE if c[0] == " "]
    for b in (adds, rems, ctx):
        random.shuffle(b)
    seq, ai, ri, cii = [], 0, 0, 0
    while len(seq) < n:
        seq.append(adds[ai % len(adds)]); ai += 1
        seq.append(rems[ri % len(rems)]); ri += 1          # a red line every few lines
        seq.append(adds[ai % len(adds)]); ai += 1
        if ctx:
            seq.append(ctx[cii % len(ctx)]); cii += 1
    return seq

def _typing_screen(gw, color, nframes, h):
    """Stream of `h`-row screens (each gw wide) of code being typed + scrolled,
    diff-style in green/red, with a blinking cursor."""
    pool = _line_seq()
    done, ci, typed = [], 0, 0
    for f in range(nframes):
        mk, text = pool[ci % len(pool)]
        typed += random.choice([1, 2, 2, 3])
        cur = text[:typed] + ("▏" if f % 2 == 0 else "")
        shown = done[-(h - 1):] + [(mk, cur)]
        rows = [" " * gw] * (h - len(shown)) + [_code_row(m, t, gw, color) for m, t in shown]
        yield rows
        if typed >= len(text):
            done.append((mk, text)); ci += 1; typed = 0

def _banner_rows(text, gw, h, color):
    rows = [" " * gw for _ in range(h)]
    t = _clip(text, gw)
    pad = max(gw - _vlen(t), 0); left = pad // 2
    rows[h // 2] = " " * left + ((fg((235, 205, 120)) + t + RESET) if color else t) + " " * (pad - left)
    return rows

def _screen_window(color, inner, stage_h, crab_frame, screen, speech, stats, morph) -> str:
    """Compose a window where the crab sits bottom-left (with its 💻) watching a
    `screen` panel on the right. crab_frame=None -> screen fills the whole stage
    (used only when the terminal is too narrow for both)."""
    if crab_frame is None:
        body = [screen[r] if r < len(screen) else " " * inner for r in range(stage_h)]
        return _frame_window(color, inner, body, speech, stats)
    gl = game_left(morph)
    gw = inner - gl
    sprite = crab_rows(color, morph, **crab_frame)
    crab_top = stage_h - morph.h
    body = []
    for r in range(stage_h):
        items = []
        if crab_top <= r < crab_top + morph.h:             # the crab, bottom-left
            items.append((CRAB_COL, sprite[r - crab_top], morph.w))
        if r == crab_top + morph.face_row:                 # 💻 in line, just right of it
            items.append((CRAB_COL + morph.w, "💻", 2))
        items.append((gl, screen[r] if r < len(screen) else " " * gw, gw))
        body.append(_place(inner, items))
    return _frame_window(color, inner, body, speech, stats)

def _walk_to(start, dest, ground, stage_h, color, stats, speech, morph):
    """Walk the crab column-by-column from `start` to `dest` (render_window
    frames, crab on the ground). No teleporting — used to enter/leave the desk."""
    x, step, i = start, 2, 0
    facing = 1 if dest >= start else -1
    while x != dest:
        x = dest if abs(dest - x) < step else x + step * facing
        i += 1
        yield render_window(color, stage_h=stage_h, x=x, y=ground,
                            frame=pose(hand="down", gaze=facing,
                                       leg="stepA" if i % 2 else "stepB"),
                            speech=speech, stats=stats, morph=morph)

def _game_scene(game, line, inner, stage_h, color, stats, pos, ground, fps, morph,
                on_result=None):
    """One full minigame. The crab walks over to its desk, writes code (green/red
    diff), watches the self-playing game, cheers, then walks back to exactly where
    it was — no teleporting. Every frame is the crab window's height."""
    gl = game_left(morph)              # computed ONCE: a gw mismatch doesn't crash,
    narrow = (inner - gl) < 24         # it makes _place silently drop the game panel
    gw = inner if narrow else inner - gl
    margin = inner - 12
    start_x = pos["x"]
    line = _clip(line, margin)
    result = {}                                # filled in by the game itself, move by move
    def cf(fr): return None if narrow else fr
    if not narrow:                                         # 0) walk over to the desk
        yield from _walk_to(start_x, CRAB_COL, ground, stage_h, color, stats, line, morph)
    for i, screen in enumerate(_typing_screen(gw, color, max(int(fps * 3), 28), stage_h)):
        yield _screen_window(color, inner, stage_h,
                             cf(pose(hand="walkA" if i % 2 == 0 else "walkB", gaze=1)),
                             screen, line, stats, morph)      # 1) writing code
    for j, (rows, caption) in enumerate(cg.play(game, gw, stage_h, color, result)):
        yield _screen_window(color, inner, stage_h,
                             cf(pose(gaze=1, eye_open=(j % 14 != 0))),
                             rows, _clip(caption, margin), stats, morph)  # 2) watching it play
    won = result.get("won", True)
    if on_result:                              # tally the game toward the crab's career
        on_result(won)
    if won:                                                # 3a) it finished -> cheer
        banner, out = _banner_rows("gg! 🦀", gw, stage_h, color), "that was fun! 🦀"
        react = [pose(hand="up", gaze=1, leg="squat" if k % 2 else "tuck") for k in range(max(int(fps), 8))]
    else:                                                  # 3b) it failed -> aw, slump
        banner, out = _banner_rows("aw, gg 🦀", gw, stage_h, color), "aw, so close! next time."
        react = [pose(hand="down", gaze=1, eye_open=(k % 4 == 0), leg="squat") for k in range(max(int(fps), 8))]
    for p in react:
        yield _screen_window(color, inner, stage_h, cf(p), banner, _clip(out, margin),
                             stats, morph)
    if not narrow:                                         # 4) walk back to where it was
        yield from _walk_to(CRAB_COL, start_x, ground, stage_h, color, stats, "", morph)

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

    inner = max(_term_width() - 3, MAX_MORPH_W + 4)
    stage_h = STAGE_H                             # constant: the redraw depends on it
    morph = MORPHS[cs.life_stage(state)]
    ground = ground_y(stage_h, morph)
    mood_box = {"mood": "okay"}
    mood = "okay"
    pos = {"x": (inner - morph.w) // 2}           # the crab's column, shared with behaviors
    def _new_gen():
        return _with_accessory(behaviors(inner, stage_h, morph, mood_box,
                                         right_pad=HOARD_CAP + 1, pos=pos), fps)
    gen = _new_gen()
    hoard_g = cs.hoard_glyphs(cs.hoard_summary(state))
    n = render_window(color, stage_h=stage_h).count("\n") + 1
    delay = 1.0 / max(fps, 1)
    poll_every = max(1, int(fps * 4))             # re-check git + vitals ~every 4s

    GREET_SEC, ROTATE_SEC = 20, 180               # greet ~20s, then refresh every 3 min
    idle_speech = SPEECH                          # the Claude-style opening line first
    idle_next = time.time() + GREET_SEC
    temp_speech, temp_until = "", 0.0             # transient gift/event/break lines
    recent_until = 0.0                            # window after a commit (for cheering)
    type_text, type_start, TYPE_CPS = "", 0.0, 13.0   # bubble typewriter state (chars/sec)
    cur_stats = list(STATS)
    gift_queue = []                               # gifts waiting to be SHOWN (one at a time)
    pending = _boot_wave(pos["x"], ground, fps)   # one-hand wave + 1s cooldown, every launch
    # CRAB_INTRO: the launch-video opening. The crab holds a still for
    # INTRO_STILL_SEC with an EMPTY bubble -- so the frame is indistinguishable
    # from a screenshot -- then blinks and the boot wave runs. The bubble stays
    # blank for exactly the still, so the greeting starts typing on the blink.
    intro_mode, intro_blank, intro_greet, intro_stats = False, 0, 0, None
    # Claude's status bar holds until the crab is off the scripted wake and
    # moving under its own steam -- the vitals are the last thing to give the
    # disguise away, well after the title has already changed.
    intro_scripted = False
    if os.environ.get("CRAB_INTRO"):
        intro_mode, intro_stats, intro_scripted = True, _intro_stats(), True
        wake = _wake_scene(pos["x"], ground, fps)
        pending = wake + pending
        # Counted in FRAMES, not seconds: a frame costs a little more than
        # 1/fps, so a wall-clock deadline expires while the still is still on
        # screen and the first line starts typing early. The disguise lasts
        # exactly as long as the still plus both blinks, so the crab speaks the
        # instant its eyes come back open.
        intro_blank, intro_greet = _wake_beats(fps)
        idle_speech = INTRO_LINE          # said after the hop, and then kept
        idle_next = float("inf")          # never rotates: it's a fixed take
        # The greeting is already finished when the frame opens: letting the
        # typewriter run it would give away that the still is live.
        type_text, type_start = INTRO_GREETING, 0.0
    commit_seen = None                            # SHAs already gifted (None = baseline first)
    today, strk = {"added": 0, "commits": 0}, 0   # until the first poll fills them in
    dying, death_at = False, 0.0                  # mid-death-scene, and when it ends
    pet_at = 0.0                                  # last pet, for the affection cooldown

    # --- chat: read the keyboard (raw mode) and talk to Claude on a worker thread
    import select, termios, tty
    chat_q = queue.Queue()
    chat_buf, chat_history = "", []
    chat_pending_since, BUBBLE_PAD = None, 6     # show "hmm…" only after 3s; keep bubble margins
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

    # --- AI director: every ~25s, decide whether the crab should "code" a game
    dir_q = queue.Queue()
    dir_box = {"vit": {"belly": 60, "energy": 70, "lines": 0, "commits": 0,
                       "streak": 0, "hour": datetime.datetime.now().hour, "name": name}}
    scene, game_req, last_game = None, None, 0.0
    DIRECTOR_EVERY, GAME_COOLDOWN = 25, 75
    def _director():
        while True:
            time.sleep(DIRECTOR_EVERY)
            if chat_ok:
                d = cc.direct(dir_box["vit"], cg.GAMES)
                if d:
                    dir_q.put((d["game"], d["line"]))
            elif random.random() < 0.5:             # no AI key -> a frequent local trigger
                dir_q.put((random.choice(cg.GAMES),
                           random.choice(["ooh, let me build something!",
                                          "time to code a lil game!", "watch this 🦀"])))
    # CRAB_NO_DIRECTOR silences only the *automatic* game trigger, for the
    # harnesses: a game that starts on its own mid-run steals the speech bubble
    # and makes a command's reply unassertable. Typing `game`/`play <name>` is
    # untouched, so the games themselves stay covered.
    # (CRAB_INTRO also implies no director: a surprise game mid-take ruins it.)
    if not os.environ.get("CRAB_NO_DIRECTOR") and not os.environ.get("CRAB_INTRO"):
        threading.Thread(target=_director, daemon=True).start()

    # --- token worker: scan Claude Code's logs off the render loop (~every 5s)
    # Fast enough that the burn rate reads as live. The scan is incremental, so
    # a warm pass is ~0.01s -- it re-reads only what was appended.
    tok_box = {"today": state.get("tok_today_cache", 0), "all": 0, "rate": None}
    def _token_worker():
        samples = collections.deque()     # (when, today_total) over the last minute
        while True:
            try:
                data = ctok.aggregate()
                tok_box["today"] = sum(ctok._total(b) for b in data["today"].values())
                tok_box["all"] = sum(ctok._total(b) for b in data["all"].values())
                tok_box["rate"] = _burn_rate(samples, time.time(), tok_box["today"])
            except Exception:
                pass
            time.sleep(TOKEN_POLL)
    threading.Thread(target=_token_worker, daemon=True).start()

    # --- session worker: which of your OTHER agent sessions need a human (~2s).
    # Cheap (a handful of small JSON files) but it shells out to `ps`, so it stays
    # off the render loop like everything else.
    alerts_mode = cfg.get("alerts", "on")            # on | quiet (no sound) | off
    sess_box = {"v": None}
    alert_q = queue.Queue()
    def _session_worker():
        announced = set()
        while True:
            try:
                s = csess.poll(skip_pid=os.getpid())
                sess_box["v"] = s
                live = {csess.alert_key(w) for w in s["waiting"]}
                for w in s["waiting"]:                # rising edge only: announce once
                    k = csess.alert_key(w)
                    if k not in announced:
                        announced.add(k)
                        alert_q.put(w)
                announced &= live                     # re-arm once a session unblocks
            except Exception:
                pass
            time.sleep(2)
    if alerts_mode != "off":
        threading.Thread(target=_session_worker, daemon=True).start()

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
                chat_pending_since = None         # reply is here, no need for "hmm…"
            while not dir_q.empty():              # --- director wants the crab to play a game
                game_req = dir_q.get()
            while not alert_q.empty():            # --- a session just started waiting on you
                w = alert_q.get()
                who = w.get("name") or "a session"
                why = w.get("waiting_for") or "waiting"
                temp_speech, temp_until = f"{who} needs you — {why}", now + 8
                mood_box["alert_ready"] = True    # jumps the behavior queue, like milestone
                if alerts_mode == "on":
                    _chirp()
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
                mood_box["health"] = state.get("health", 100.0)
                mood_box["stage"] = cs.life_stage(state)
                mood_box["molt_soon"] = cs.molt_soon(state, now)
                # a fresh crab with ancestors spends its first day visiting them
                mood_box["mourning"] = bool(state.get("graveyard")) and \
                    cs.age_days(state, now) < 1.0
                strk = cs.streak(repos, author)
                state["career"]["peak_streak"] = max(state["career"].get("peak_streak", 0), strk)
                if tok_box["all"]:                    # belly fills from tokens you've used
                    cs.feed_tokens(state, tok_box["all"])
                    state["tok_today_cache"] = tok_box["today"]
                # --- the crab starved. Permadeath: bury it, then hatch the next egg.
                if cs.is_dead(state) and not dying:
                    dying = True
                    cs.backup_state()                 # so --undo-death can put it back
                    gone = cs.bury(state, now)
                    pending = _death_scene(pos["x"], ground, fps)
                    temp_speech = f"{gone['name']} is gone…"
                    temp_until = now + len(pending) * delay + 3
                    death_at = now + len(pending) * delay
                elif dying and now >= death_at:        # the scene finished -> new crab
                    lost = state.get("graveyard", [])[-1] if state.get("graveyard") else {}
                    cs.rebirth(state, now)
                    dying, death_at = False, 0.0
                    morph = MORPHS[cs.life_stage(state)]
                    ground = ground_y(stage_h, morph)
                    hoard_g = []
                    gen = _new_gen()
                    pending = _boot_wave(pos["x"], ground, fps)
                    temp_speech = f"i'll miss {lost.get('name', 'them')}…"
                    temp_until = now + 6
                dir_box["vit"] = {"belly": 100 - state["hunger"], "energy": state["energy"],
                                  "lines": today.get("added", 0), "commits": today.get("commits", 0),
                                  "streak": strk, "hour": datetime.datetime.now().hour, "name": name}
                cur_stats = cs.stat_lines(state, tok_box["today"], tok_box["all"],
                                          tok_box["rate"])
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
                # --- evolution seam. Only swap morphs at a quiescent moment: a
                # half-played scene baked the old `ground` and panel width into its
                # frames, so mixing morphs mid-scene would drop the game panel.
                grown = MORPHS[cs.life_stage(state)]
                if grown is not morph and not pending and scene is None:
                    morph = grown
                    ground = ground_y(stage_h, morph)
                    lo, hi = crab_bounds(inner, HOARD_CAP + 1, morph)
                    pos["x"] = min(max(pos["x"], lo), hi)   # old bounds may have been wider
                    gen = _new_gen()
                    pending = _celebrate(pos["x"], ground)
                    temp_speech = f"i'm a {morph.label} now!"
                    temp_until = now + 5
                cs.save_state(state)

            if not pending and gift_queue:        # --- show a queued commit-gift or PR ack
                g, line, key = gift_queue.pop(0)
                if key:                            # a PR: mark it acknowledged (once)
                    gifted.add(key); state["pr_gifted"] = sorted(gifted)
                if g.get("ack"):                   # PR -> quick bounce, no gift mechanics
                    state["career"]["prs"] = state["career"].get("prs", 0) + 1
                    pending = _celebrate(pos["x"], ground)
                else:                              # commit -> full gift scene + feed + hoard
                    state["career"]["commits"] = state["career"].get("commits", 0) + 1
                    cs.record_gift(state, g); cs.feed_gift(state, g)
                    hoard_g = cs.hoard_glyphs(cs.hoard_summary(state))
                    pending = _gift_scene(pos, ground, inner, g["tier"],
                                          cs.TIER_EMOJI[g["tier"]], HOARD_CAP + 1, morph)
                temp_speech, temp_until = line, now + len(pending) * delay + 2
                cs.save_state(state)

            if scene is None and game_req is not None and not pending \
                    and now - last_game > GAME_COOLDOWN:   # start a director-chosen game
                g, gline = game_req
                scene = _game_scene(g, gline, inner, stage_h, color, list(cur_stats),
                                    dict(pos), ground, fps, morph,
                                    on_result=lambda won: cs.record_game(state, won))
            game_req = None

            if scene is not None:                 # a minigame owns the whole window
                try:
                    win = next(scene)
                except StopIteration:
                    scene, last_game = None, now
            if scene is None:                     # normal crab life
                if pending:
                    x, y, frame, drop = pending.pop(0); emote = None
                else:
                    x, y, frame, emote = next(gen); drop = None
                    intro_scripted = False    # off the script -- moving on its own now
                disp = temp_speech if now < temp_until else idle_speech
                # The launch-video still passes for a Claude session -- Claude's
                # title, Claude's status bar, a greeting that is already
                # finished -- until the crab blinks and gives the whole thing
                # away.
                disguised = intro_blank > 0
                if disguised:
                    intro_blank -= 1
                if intro_greet > 0:               # greeting outlasts the disguise
                    intro_greet, disp = intro_greet - 1, INTRO_GREETING
                elif intro_mode:
                    disp = INTRO_LINE             # pinned: the take says one line
                if chat_pending_since is not None and now - chat_pending_since > 3:
                    disp = "hmm…"                 # only after a slow reply; else keep the line
                disp = _clip(disp, inner - 2 * BUBBLE_PAD)   # keep the bubble off the box edges
                if disp != type_text:             # new line -> (re)start typing it out
                    type_text, type_start = disp, now
                typed = type_text[:int((now - type_start) * TYPE_CPS)]
                bubble = typed + " " * max(_vlen(type_text) - _vlen(typed), 0)  # hold full width
                win = render_window(color, stage_h=stage_h, x=x, y=y, frame=frame,
                                    speech=bubble, hoard=hoard_g,
                                    stats=intro_stats if intro_scripted else cur_stats,
                                    title=INTRO_TITLE if disguised else None,
                                    drop=drop, emote=emote, morph=morph,
                                    headstone=bool(state.get("graveyard")))
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
                        # Commands first: they run locally and need no API key.
                        # Anything unrecognised falls through to Claude as chat.
                        res = ccmd.handle(submit, {"state": state, "cfg": cfg,
                                                   "sess": sess_box["v"], "color": color,
                                                   "pet_at": pet_at})
                        if res:
                            # A running minigame owns the whole window, including
                            # the bubble, so a reply would vanish into it. If you
                            # are typing commands you want the crab's attention,
                            # not to watch it finish breakout -- so cut the scene.
                            if res.get("say") or res.get("page"):
                                if scene is not None:
                                    scene, last_game = None, now
                                if not res.get("game"):
                                    game_req = None
                            if "pet_at" in res:
                                pet_at = res["pet_at"]
                            if res.get("save"):
                                cs.save_state(state)
                                hoard_g = cs.hoard_glyphs(cs.hoard_summary(state))
                                morph = MORPHS[cs.life_stage(state)]
                                ground = ground_y(stage_h, morph)
                            if res.get("game"):
                                game_req, last_game = res["game"], 0.0
                            if res.get("react") == "celebrate":
                                pending = _celebrate(pos["x"], ground)
                            elif res.get("react") == "stretch":
                                pending = _do_stretch(pos["x"], ground)
                            if res.get("say"):
                                temp_speech = res["say"]
                                temp_until = now + max(5.0, len(res["say"]) / TYPE_CPS + 3)
                            if res.get("page"):
                                # Full-screen output. The window's height is fixed,
                                # so a page can't be squeezed in -- it takes over,
                                # then `first` forces a clean redraw from scratch
                                # instead of a cursor-up onto a screen that moved.
                                _show_page(res["page"], fd)
                                first = True
                            if res.get("quit"):
                                break
                        elif not chat_ok:
                            temp_speech = "type 'help' for commands, or set ANTHROPIC_API_KEY to chat"
                            temp_until = now + 6
                        else:
                            chat_history.append({"role": "user", "content": submit.strip()})
                            del chat_history[:-10]              # keep recent turns only
                            chat_pending_since = now           # keep current line; "hmm…" only after 3s
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
    tok_today, tok_all = ctok.today_all()
    stats = cs.stat_lines(state, tok_today, tok_all)
    sp = cs.speech(state, mood, [], [], cs.break_due(state))
    hoard_g = cs.hoard_glyphs(cs.hoard_summary(state))
    morph = MORPHS[cs.life_stage(state)]
    # stage_h tracks the morph: a shorter stage silently drops the leg row.
    return render_window(color, stage_h=morph.h, speech=sp, stats=stats,
                         hoard=hoard_g, morph=morph)

def _show_page(text, fd):
    """Hand the whole screen to `text` until a key is pressed.

    Used for command output that can't fit the speech bubble (Memory Lane, the
    token report). The animation's in-place redraw assumes the screen hasn't
    moved under it, so the caller must set `first = True` afterwards to force a
    full redraw rather than a cursor-up into the middle of the page."""
    import select
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write(text.rstrip("\n") + "\n\n  [any key to go back]\n")
    sys.stdout.flush()
    if fd is not None:
        select.select([sys.stdin], [], [], None)     # block until a keypress
        try:
            os.read(fd, 256)
        except Exception:
            pass
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

def _confirm_graduation(state):
    """Graduation is irreversible from the crab's point of view, so say plainly
    what is about to be given up before doing it."""
    h = cs.hoard_summary(state)
    print(f"\n  graduate {state.get('name')}?")
    print(f"    {cs.age_days(state):.0f} days old · {cs.life_stage(state)} · "
          f"{h.get('count', 0)} gifts in the hoard")
    print(f"    they go to Memory Lane with honours, and a new egg starts from zero.")
    try:
        return input("\n  type the name to confirm: ").strip() == (state.get("name") or "")
    except (EOFError, KeyboardInterrupt):
        return False

LEGACY_DIR = pathlib.Path(__file__).resolve().parent / "legacy" / "v1.0"
LEGACY_HOME = pathlib.Path.home() / ".claude-crab" / "v1-home"

def _run_legacy(rest):
    """Launch the frozen v1.0 crab (`crab --old`).

    v1.0 hardcodes ~/.claude-crab and runs the old 30/hr hunger clock, so pointing
    it at your real save would empty your crab's belly just by looking at it. It
    gets its own HOME instead of a patch, because the whole point of legacy/ is
    that it stays exactly as it shipped.

    That home is seeded once so it still feels like your crab: ~/.claude is
    symlinked through (token usage keeps reading), and config.json + state.json
    are copied on first run. After that the v1.0 crab lives its own separate life.
    """
    entry = LEGACY_DIR / "pixel_crab.py"
    if not entry.exists():
        print(f"v1.0 isn't in this checkout (looked in {LEGACY_DIR})")
        return 1
    box = LEGACY_HOME / ".claude-crab"
    first = not box.exists()
    box.mkdir(parents=True, exist_ok=True)
    link = LEGACY_HOME / ".claude"
    if not link.exists():
        try:
            link.symlink_to(pathlib.Path.home() / ".claude")   # so tokens still count
        except Exception:
            pass
    for src, name in ((cs.CONFIG, "config.json"), (cs.STATE, "state.json")):
        dst = box / name
        if src.exists() and not dst.exists():
            dst.write_text(src.read_text())
    if first:
        print(f"  starting v1.0 with its own save at {box}")
        print(f"  (seeded from your crab; your real one is left alone)\n")
        sys.stdout.flush()        # the child writes straight to the tty; don't trail it
    return subprocess.call([sys.executable, str(entry), *(rest or ["--animate"])],
                           env=dict(os.environ, HOME=str(LEGACY_HOME)))

def main(argv):
    color = "--no-color" not in argv
    if "--old" in argv:                             # the v1.0 crab, frozen in legacy/
        return _run_legacy([a for a in argv if a != "--old"])
    if "--admin" in argv:                           # the sandbox: every scenario, on demand
        i = argv.index("--admin")
        nxt = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("-") else None
        return crab_admin.main(nxt, color)
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
    elif "--tokens" in argv:                        # Claude Code token usage (Max plan)
        import crab_tokens
        print(crab_tokens.report())
    elif "--setkey" in argv:                        # save an Anthropic API key for chat
        i = argv.index("--setkey")
        key = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
        if not key:
            import getpass
            try:
                key = getpass.getpass("Paste your Anthropic API key (hidden): ").strip()
            except Exception:
                key = ""
        if key and key.startswith("sk-"):
            cs.set_anthropic_key(key)
            print("saved to ~/.claude-crab/config.json (plaintext — keep it private).")
            print("chat is ready — run: crab")
        else:
            print("that didn't look like a key (expected sk-ant-...); nothing saved.")
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
    elif "--hall" in argv or "--memory-lane" in argv:   # every crab you've raised
        print(crab_hall.render(cs.load_state(), color))
    elif "--name" in argv:                          # rename the living crab
        i = argv.index("--name")
        new = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("-") else None
        state = cs.load_state()
        if not new:
            print("your crab is called", state.get("name"))
        else:
            old = state.get("name")
            state["name"] = new[:20]
            cs.save_state(state)
            print(f"{old} is now called {state['name']}")
    elif "--alerts" in argv:                        # session-alert loudness
        i = argv.index("--alerts")
        mode = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("-") else None
        cfg = cs.load_config()
        if mode in ("on", "quiet", "off"):
            cfg["alerts"] = mode; cs.save_config(cfg)
            print({"on": "alerts on (crab reacts + chirps)",
                   "quiet": "alerts quiet (crab reacts, no sound)",
                   "off": "alerts off (sessions not watched)"}[mode])
        else:
            print("alerts:", cfg.get("alerts", "on"), "— use: crab --alerts on|quiet|off")
    elif "--sessions" in argv:                      # what your other agents are doing
        s = csess.poll(skip_pid=os.getpid())
        for w in s["waiting"]:
            print(f"  ● {w['name']:<28} {w['waiting_for'] or 'waiting'}")
        for o in s["all"]:
            if o["status"] != csess.WAITING:
                mark = "≈" if o["approx"] else " "
                print(f"  ○ {o['name']:<28} {o['status']}{mark}")
        if not s["all"]:
            print("  (no live agent sessions found)")
    elif "--graduate" in argv:                      # retire this crab and start fresh
        state = cs.load_state()
        ok, why = cs.can_graduate(state)
        force = "--force" in argv
        if not ok and not force:
            print(why)
            print("  graduate anyway with: crab --graduate --force")
        elif "--yes" not in argv and not _confirm_graduation(state):
            print("  cancelled — nothing changed")
        else:
            cs.backup_state()                       # so --undo can put them back
            m = cs.graduate(state)
            cs.save_state(state)
            print(f"\n  🎓 {m['name']} graduated after {m['age_days']:.0f} days"
                  f"{' as a ' + m['form'] if m.get('form') else ''}.")
            print(f"     {m['career'].get('commits', 0)} commits · "
                  f"{m['career'].get('prs', 0)} PRs · {m['hoard_count']} gifts kept.")
            print(f"\n  a new egg is here. say hello to {state['name']}.")
            print(f"\n  (see them all: crab --hall · undo: crab --undo)")
    elif "--undo" in argv or "--undo-death" in argv:   # put back the last crab
        if cs.restore_state():                         # covers death AND graduation
            st = cs.load_state()
            print(f"restored {st.get('name')} (gen {st.get('generation')}, "
                  f"{cs.hoard_summary(st).get('count', 0)} gifts)")
        else:
            print("nothing to undo — no snapshot saved")
    elif "--sheet" in argv:                         # every morph, every leg pose (QA)
        for key, m in MORPHS.items():
            print(f"--- {key}  {m.w}w x {m.h}h  legs={m.legs_per_side * 2}")
            for leg in LEG_POSES:
                for row in crab_rows(color, m, **pose(leg=leg)):
                    print("   " + row)
                print()
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
