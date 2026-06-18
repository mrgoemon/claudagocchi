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
import threading
import queue

import crab_state as cs

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
                  speech=None, stats=None, hoard=None, drop=None) -> str:
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
                dcol, dch, dt = drop
                ds = (fg(HOARD_COLOR[dt]) + dch + RESET) if color else dch
                items.append((dcol, ds, len(dch)))
            if hoard:
                items.append((inner - len(hoard) - 1, _render_hoard(hoard, color), len(hoard)))
            stage.append(_place(inner, items))
        elif crab_seg:
            col, s, w = crab_seg
            stage.append(" " * col + s + " " * max(inner - col - w, 0))
        else:
            stage.append(" " * inner)

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

    # On boot, always greet with a hand wave before settling into idle behavior.
    for i in range(8):
        yield pos["x"], ground, pose(hand="walkA" if i % 2 else "walkB")

    while True:
        mood = (mood_box or {}).get("mood", "okay")
        action = random.choices(
            ACTIONS, weights=MOOD_WEIGHTS.get(mood, MOOD_WEIGHTS["okay"]))[0]

        if action == "sit":                          # loaf, with the occasional blink
            n = random.randint(10, 22)
            blink_at = random.randint(2, max(2, n - 4))   # one short blink, mid-action
            for i in range(n):
                closed = blink_at <= i < blink_at + 2     # 2 frames, kept off the edges
                yield pos["x"], ground, pose(eye_open=not closed)

        elif action == "saunter":                    # slow stroll: legs step, hands stay
            d = random.choice([-1, 1])               # put, eyes glance the way it walks
            for i in range(random.randint(8, 16)):
                if i % 2 == 0:
                    d = step_x(d)
                yield pos["x"], ground, pose(hand="down", gaze=d,
                                             leg="stepA" if i % 2 else "stepB")

        elif action == "stretch":                    # big slow stretch, then settle
            yield pos["x"], ground, pose(hand="up", leg="stepA")
            for _ in range(random.randint(5, 8)):
                yield pos["x"], ground, pose(hand="up")
            yield pos["x"], ground, pose(hand="up", leg="squat")

        elif action == "groom":                      # paw flicks at the face
            for i in range(random.randint(6, 12)):
                yield pos["x"], ground, pose(hand="walkA" if i % 2 else "down",
                                             eye_open=(i % 4 != 0))

        elif action == "pounce":                     # rare: wiggle, then leap
            for _ in range(3):
                yield pos["x"], ground, pose(leg="squat")
            for yy in (ground - 1, ground - 2, ground - 2):
                yield pos["x"], max(yy, 0), pose(hand="up", leg="tuck")
            yield pos["x"], ground - 1, pose(leg="tuck")
            yield pos["x"], ground, pose(leg="squat")
            yield pos["x"], ground, pose(leg="rest")

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
                if p.get("state") == "OPEN":               # gift only on opening
                    pr_q.put((key, cs.pr_gift(p)))
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

    GREET_SEC, ROTATE_SEC = 20, 300               # greet ~20s, then refresh every 5 min
    idle_speech = SPEECH                          # the Claude-style opening line first
    idle_next = time.time() + GREET_SEC
    temp_speech, temp_until = "", 0.0             # transient gift/event/break lines
    cur_stats = list(STATS)
    pending = []
    gift_queue = []                               # gifts waiting to be SHOWN (one at a time)

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
            if i % poll_every == 0:               # --- poll: vitals, git, reactions
                events = cs.tick(state, repos, now)
                today = cs.today_stats(repos, author)
                quests = cs.quests_status(state, today)
                fresh = cs.newly_completed(state, quests)
                mood = cs.day_mood(state, today, now)
                mood_box["mood"] = mood
                cur_stats = cs.stat_lines(state, quests, today, pr_stats_box["v"],
                                          cs.streak(repos, author))
                for g in cs.detect_gifts(state, repos, author, now):  # did you just push?
                    gift_queue.append((g, cs.gift_speech(g), None))
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

            if not pending and gift_queue:        # --- show a queued gift (records on show)
                g, line, key = gift_queue.pop(0)
                cs.record_gift(state, g); cs.feed_gift(state, g)
                if key:
                    gifted.add(key); state["pr_gifted"] = sorted(gifted)
                hoard_g = cs.hoard_glyphs(cs.hoard_summary(state))
                pending = _gift_scene(pos, ground, inner, g["tier"],
                                      cs.TIER_GLYPH[g["tier"]], HOARD_CAP + 1)
                temp_speech, temp_until = line, now + len(pending) * delay + 2
                cs.save_state(state)

            if pending:
                x, y, frame, drop = pending.pop(0)
            else:
                x, y, frame = next(gen)
                drop = None

            disp = temp_speech if now < temp_until else idle_speech
            win = render_window(color, stage_h=stage_h, x=x, y=y, frame=frame,
                                speech=disp, stats=cur_stats, hoard=hoard_g, drop=drop)
            if not first:
                sys.stdout.write(f"\033[{n}A")
            sys.stdout.write("".join("\r" + ln + "\033[K\n" for ln in win.split("\n")))
            sys.stdout.flush()
            first, i = False, i + 1
            time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        cs.save_state(state)
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
