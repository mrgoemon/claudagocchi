#!/usr/bin/env python3
"""Self-playing minigames the crab "codes" and watches itself play.

Each game is a generator yielding (rows, caption):
  - rows:    a list of exactly `h` strings, each EXACTLY `inner` visible columns
             wide (ANSI colour allowed) — drops straight into the crab's box.
  - caption: a short status line (score) for the speech bubble.

The generators self-play with simple heuristics and end on their own. No
dependencies, no rendering knowledge beyond width — pixel_crab wraps the rows
in the window. A built-in bot plays; the crab just spectates.
"""
import random
import unicodedata

GAMES = ["dino", "pong", "snake"]

RESET = "\033[0m"
def _fg(rgb): r, g, b = rgb; return f"\033[38;2;{r};{g};{b}m"

def _w(s):
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)

def _place(inner, items, color):
    """Lay (col, glyph, rgb) items onto a blank `inner`-wide row, width-aware.
    Items past the edge or overlapping an earlier one are dropped. Returns a
    string of exactly `inner` visible columns."""
    out, cur = "", 0
    for col, glyph, rgb in sorted(items, key=lambda t: t[0]):
        gw = _w(glyph)
        if col < cur or col + gw > inner:        # overlap, or would clip the wall
            continue
        out += " " * (col - cur)
        out += (_fg(rgb) + glyph + RESET) if (color and rgb) else glyph
        cur = col + gw
    return out + " " * max(inner - cur, 0)

# --- dino runner -------------------------------------------------------------
def dino(inner, h, color):
    CORAL, GREEN, GREY = (217, 119, 87), (90, 170, 90), (110, 110, 120)
    DCOL = 4                                     # the dino's fixed column
    gy = h - 2                                   # entities stand a row above the ground line
    line_row = h - 1
    JUMP = [1, 2, 3, 3, 3, 2, 1]                 # height profile of one hop
    SPEED, MAXF = 2, 130
    jump, cacti, score, gap, alive, dino_h = [], [], 0, 0, True, 0
    f = 0
    while alive and f < MAXF:
        f += 1
        if gap <= 0 and (not cacti or cacti[-1] < inner - 16) and random.random() < 0.5:
            cacti.append(inner - 3); gap = random.randint(8, 15)
        gap -= 1
        cacti = [c - SPEED for c in cacti]
        score += sum(1 for c in cacti if c < DCOL - 1 and c >= DCOL - 1 - SPEED)
        cacti = [c for c in cacti if c >= -2]
        if not jump:                              # the bot: hop when a cactus looms
            if any(DCOL + 1 <= c <= DCOL + 11 for c in cacti):
                jump = list(JUMP)
        dino_h = jump.pop(0) if jump else 0
        if dino_h == 0 and any(DCOL - 1 <= c <= DCOL + 1 for c in cacti):
            alive = False
        rows = []
        for r in range(h):
            if r == line_row:
                rows.append((_fg(GREY) + "─" * inner + RESET) if color else "─" * inner)
                continue
            items = []
            if r == gy - dino_h:
                items.append((DCOL, "🦖", CORAL))
            if r == gy:
                items += [(c, "🌵", GREEN) for c in cacti if 0 <= c < inner]
            rows.append(_place(inner, items, color))
        yield rows, f"🦖 dino · score {score}"
    end = "💥 crashed!" if not alive else "🏁 nice run!"
    for _ in range(8):
        rows = []
        for r in range(h):
            if r == line_row:
                rows.append((_fg(GREY) + "─" * inner + RESET) if color else "─" * inner)
            elif r == gy:
                rows.append(_place(inner, [(DCOL, "💥" if not alive else "🦖", CORAL)], color))
            else:
                rows.append(" " * inner)
        yield rows, f"{end} score {score}"

# --- pong (bot vs bot) -------------------------------------------------------
def pong(inner, h, color):
    CORAL, BALL = (217, 119, 87), (235, 235, 235)
    lx, rx = 1, inner - 2
    plen = max(2, h // 2)
    lp = rp = (h - plen) // 2
    bx, by = inner // 2, h // 2
    vx, vy = random.choice([-1, 1]), random.choice([-1, 1])
    a = b = 0

    def track(p):
        target = by - plen // 2
        if p < target and random.random() < 0.85: p += 1
        elif p > target and random.random() < 0.85: p -= 1
        return max(0, min(h - plen, p))

    def reset(d): return inner // 2, h // 2, d, random.choice([-1, 1])

    rows = [" " * inner] * h
    for _ in range(140):
        bx += vx; by += vy
        if by <= 0: by, vy = 0, 1
        if by >= h - 1: by, vy = h - 1, -1
        lp, rp = track(lp), track(rp)
        if bx <= lx + 1:
            if lp <= by <= lp + plen - 1: vx, bx = 1, lx + 2
            else: b += 1; bx, by, vx, vy = reset(1)
        if bx >= rx - 1:
            if rp <= by <= rp + plen - 1: vx, bx = -1, rx - 2
            else: a += 1; bx, by, vx, vy = reset(-1)
        rows = []
        for r in range(h):
            items = []
            if lp <= r < lp + plen: items.append((lx, "┃", CORAL))
            if rp <= r < rp + plen: items.append((rx, "┃", CORAL))
            if r == by and 0 <= bx < inner: items.append((bx, "●", BALL))
            rows.append(_place(inner, items, color))
        yield rows, f"🏓 pong · {a}:{b}"
    for _ in range(6):
        yield rows, f"🏓 final · {a}:{b}"

# --- snake (greedy autopilot) ------------------------------------------------
def _food(inner, h, body):
    occ = set(body)
    for _ in range(200):
        p = (random.randint(0, inner - 1), random.randint(0, h - 1))
        if p not in occ:
            return p
    return (0, 0)

def snake(inner, h, color):
    CORAL, HEAD, FOOD = (217, 119, 87), (240, 200, 90), (220, 90, 90)
    body = [(inner // 2, h // 2)]
    food = _food(inner, h, body)
    score = 0
    rows = [" " * inner] * h
    for _ in range(160):
        hx, hy = body[0]
        occ = set(body[:-1])                      # the tail cell frees up as we move
        best, bestd = None, 1e9
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = hx + dx, hy + dy
            if not (0 <= nx < inner and 0 <= ny < h) or (nx, ny) in occ:
                continue
            d = abs(nx - food[0]) + abs(ny - food[1])
            if d < bestd:
                bestd, best = d, (nx, ny)
        if best is None:
            break                                  # boxed itself in
        body.insert(0, best)
        if best == food:
            score += 1; food = _food(inner, h, body)
        else:
            body.pop()
        by_row = {}
        for i, (c, r) in enumerate(body):
            by_row.setdefault(r, []).append((c, "◉" if i == 0 else "o", HEAD if i == 0 else CORAL))
        by_row.setdefault(food[1], []).append((food[0], "●", FOOD))
        rows = [_place(inner, by_row.get(r, []), color) for r in range(h)]
        yield rows, f"🐍 snake · {score}"
    for _ in range(6):
        yield rows, f"🐍 done · {score}"

def play(name, inner, h, color):
    return {"dino": dino, "pong": pong, "snake": snake}.get(name, dino)(inner, h, color)
