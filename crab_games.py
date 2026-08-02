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

GAMES = ["dino", "pong", "snake", "crossing", "invaders", "breakout", "squash"]

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
def dino(inner, h, color, result=None):
    if result is None: result = {}
    CORAL, GREEN, GREY = (217, 119, 87), (90, 170, 90), (110, 110, 120)
    DCOL = 4                                     # the dino's fixed column
    gy = h - 2                                   # entities stand a row above the ground line
    line_row = h - 1
    JUMP = [1, 2, 3, 3, 3, 2, 1]                 # a well-timed hop, clears cleanly
    RUSHED = [1, 2, 1]                           # an unoptimized, low/short hop -- real risk
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
        if not jump and any(DCOL + 1 <= c <= DCOL + 11 for c in cacti):
            optimal = random.random() < 0.8        # each reaction: 80% clean, 20% rushed
            jump = list(JUMP if optimal else RUSHED)
        dino_h = jump.pop(0) if jump else 0
        if dino_h == 0 and any(DCOL - 1 <= c <= DCOL + 1 for c in cacti):
            alive = False                              # a mistimed hop can still get clipped
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
    result["won"] = alive
    end = "🏁 nice run!" if alive else "💥 crashed!"
    for _ in range(8):
        rows = []
        for r in range(h):
            if r == line_row:
                rows.append((_fg(GREY) + "─" * inner + RESET) if color else "─" * inner)
            elif r == gy:
                rows.append(_place(inner, [(DCOL, "🦖" if alive else "💥", CORAL)], color))
            else:
                rows.append(" " * inner)
        yield rows, f"{end} score {score}"

# --- pong (bot vs bot) -------------------------------------------------------
def pong(inner, h, color, result=None):
    if result is None: result = {}
    CORAL, BALL = (217, 119, 87), (235, 235, 235)
    lx, rx = 1, inner - 2
    plen = max(2, h // 4)                         # a paddle that can miss -- full-height
    lp = rp = (h - plen) // 2                      # coverage never let a rally end
    bx, by = inner // 2, h // 2
    vx, vy = random.choice([-1, 1]), random.choice([-1, 1])
    a = b = 0                                     # a = crab (left), b = opponent (right)
    WIN = 3

    def track(p):                                  # each frame: 80% a clean move toward
        target = by - plen // 2                    # the ball, 20% a fumbled/random one
        if random.random() < 0.8:
            if p < target: p += 1
            elif p > target: p -= 1
        else:
            p += random.choice([-1, 0, 1])
        return max(0, min(h - plen, p))

    def reset(d): return inner // 2, h // 2, d, random.choice([-1, 1])

    rows = [" " * inner] * h
    for _ in range(500):
        if a >= WIN or b >= WIN:                  # first to WIN takes it -- earned, not fixed
            break
        bx += vx; by += vy
        if by <= 0: by, vy = 0, 1
        if by >= h - 1: by, vy = h - 1, -1
        lp, rp = track(lp), track(rp)
        if bx <= lx + 1:                          # crab's wall (left)
            if lp <= by < lp + plen: vx, bx = 1, lx + 2   # in position -> return it
            else: b += 1; bx, by, vx, vy = reset(1)       # out of position -> concede
        elif bx >= rx - 1:                        # opponent's wall (right)
            if rp <= by < rp + plen: vx, bx = -1, rx - 2
            else: a += 1; bx, by, vx, vy = reset(-1)
        rows = []
        for r in range(h):
            items = []
            if lp <= r < lp + plen: items.append((lx, "┃", CORAL))
            if rp <= r < rp + plen: items.append((rx, "┃", CORAL))
            if r == by and 0 <= bx < inner: items.append((bx, "●", BALL))
            rows.append(_place(inner, items, color))
        yield rows, f"🏓 pong · {a}:{b}"
    if a == b:                                    # ran out of frames still tied -- a coin flip,
        won = random.random() < 0.5               # not a scripted loss, decides the photo finish
    else:
        won = a > b
    result["won"] = won
    res = "🏆 you win!" if won else "😵 you lose"
    for _ in range(6):
        yield rows, f"{res}  {a}:{b}"

# --- snake (greedy autopilot) ------------------------------------------------
def _food(inner, h, body):
    occ = set(body)
    for _ in range(200):
        p = (random.randint(0, inner - 1), random.randint(0, h - 1))
        if p not in occ:
            return p
    return (0, 0)

def snake(inner, h, color, result=None):
    if result is None: result = {}
    CORAL, HEAD, FOOD = (217, 119, 87), (240, 200, 90), (220, 90, 90)
    body = [(inner // 2, h // 2)]
    food = _food(inner, h, body)
    score, alive = 0, True
    rows = [" " * inner] * h
    for _ in range(220):
        hx, hy = body[0]
        occ = set(body[:-1])                      # the tail cell frees up as we move
        options = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = hx + dx, hy + dy
            if 0 <= nx < inner and 0 <= ny < h and (nx, ny) not in occ:
                d = abs(nx - food[0]) + abs(ny - food[1])
                options.append((d, (nx, ny)))
        if not options:
            alive = False
            break                                  # boxed itself in
        if random.random() < 0.8:                 # 80% a greedy step toward the food,
            best = min(options, key=lambda t: t[0])[1]     # 20% an unoptimized wander
        else:
            best = random.choice(options)[1]
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
    result["won"] = alive
    res = "🏆 nice run!" if alive else "😵 game over"
    for _ in range(6):
        yield rows, f"{res}  score {score}"

# --- crab crossing (dodge the traffic) ---------------------------------------
_CARS = ["🚗", "🚙", "🚚", "🏎"]

def crossing(inner, h, color, result=None):
    if result is None: result = {}
    CORAL, GOLD, GREY = (217, 119, 87), (240, 200, 90), (110, 110, 120)
    cx = max(0, min(inner - 2, inner // 3))       # the crab crosses on a fixed column
    lanes = []
    for i, r in enumerate(range(1, h - 1)):       # traffic between the bank and the curb
        lanes.append({"row": r, "dir": 1 if i % 2 == 0 else -1,
                      "speed": random.choice([1, 2]), "cars": [],
                      "wait": random.randint(0, 6), "glyph": random.choice(_CARS)})

    def blocked(ln, x, margin):
        """Is a car in `ln` on (or `margin` columns short of) the crab's two
        columns? Only traffic still coming counts — a car that just went past
        leaves the safest gap on the road, and the crab should take it."""
        lo, hi = x - 1, x + 1                     # margin 0 == touching the crab
        if ln["dir"] > 0: lo -= margin
        else: hi += margin
        return any(lo <= c <= hi for c in ln["cars"])

    def at(r): return next((l for l in lanes if l["row"] == r), None)

    row, score, alive, bank, f = h - 1, 0, True, 0, 0
    careful = random.random() < 0.8               # each hop is either patient or a reckless
    TARGET, MAXF = 6, 150                         # dart -- re-rolled on every landing
    while alive and score < TARGET and f < MAXF:
        f += 1
        for ln in lanes:                          # traffic rolls first
            ln["wait"] -= 1
            if ln["wait"] <= 0:
                ln["cars"].append(-2 if ln["dir"] > 0 else inner)
                ln["wait"] = random.randint(9, 18)     # gaps a crab can actually sit in
            ln["cars"] = [c + ln["dir"] * ln["speed"] for c in ln["cars"]]
            ln["cars"] = [c for c in ln["cars"] if -3 <= c <= inner + 2]
        cur = at(row)
        if cur and blocked(cur, cx, 0):           # a car ran down a dawdling crab
            alive = False
        elif bank:                                # a beat at the flag, then trot back
            bank -= 1
            if not bank: row = h - 1
        elif row > 0:
            nxt = at(row - 1)
            pressed = cur is not None and blocked(cur, cx, cur["speed"] * 3)
            back = at(row + 1)
            if nxt is None:                        # stepping up onto the goal bank
                go = True
            elif not careful:                      # a dart cuts it fine instead of waiting
                go = not blocked(nxt, cx, 1)       # for a gap it would call safe
            elif not blocked(nxt, cx, nxt["speed"] * 3):
                go = True                          # a real gap opened up
            elif not pressed:
                go = False                         # nothing coming: sit tight
            elif not blocked(nxt, cx, 1):
                go = True                          # a car is on it -- squeeze through
            elif row + 1 == h - 1 or (back and not blocked(back, cx, 2)):
                row += 1; go = False               # duck back a lane instead
                careful = random.random() < 0.8
            else:
                go = True                          # boxed in: hop and hope
            if go:
                row -= 1
                careful = random.random() < 0.8
                land = at(row)
                if land and blocked(land, cx, 0):
                    alive = False
                elif row == 0:
                    score += 1; bank = 3
        rows = []
        for r in range(h):
            items = []
            if r == 0 and row != 0:
                items.append((cx, "🏁", GOLD))
            ln = at(r)
            if ln and not (r == row and not alive):
                items += [(c, ln["glyph"], GREY) for c in ln["cars"] if 0 <= c < inner - 1]
            if r == row:
                items.append((cx, "🦀" if alive else "💥", CORAL))
            rows.append(_place(inner, items, color))
        yield rows, f"🦀 crossing · {score}/{TARGET} home"
    won = alive and score >= TARGET
    result["won"] = won
    end = "🏁 made it across!" if won else "💥 splat!"
    for _ in range(8):
        yield [_place(inner, [(cx, "🦀" if won else "💥", CORAL)], color) if r == row
               else " " * inner for r in range(h)], f"{end} {score}/{TARGET}"

# --- space invaders (bot ship vs. a marching wave) ---------------------------
def invaders(inner, h, color, result=None):
    if result is None: result = {}
    CORAL, GREEN, WHITE, RED = (217, 119, 87), (90, 170, 90), (235, 235, 235), (220, 90, 90)
    PITCH, BOMB_EVERY = 4, 11
    ncol = max(3, min(7, (inner - 4) // PITCH))
    nrow = min(2, max(1, h - 3))
    wave = {(c, r) for c in range(ncol) for r in range(nrow)}
    ship_row = h - 1
    ox, oy, d, bounces = 1, 0, 1, 0
    sx, bullet, bombs = inner // 2, None, []
    alive, f = True, 0
    MAXF = 300

    def acol(c): return ox + c * PITCH

    while wave and alive and f < MAXF:
        f += 1
        if f % 2 == 0:                            # the block marches at half the ship's pace
            step = ox + d                         # (any faster and no shot could ever land)
            if step < 0 or step + (ncol - 1) * PITCH + 1 > inner - 1:
                d = -d; bounces += 1
                if bounces % 2 == 0: oy += 1      # every second wall, it drops a row
            else:
                ox = step
        if oy + nrow - 1 >= ship_row - 1:         # the wave landed on top of the ship
            alive = False; break
        threat = min((b for b in bombs if abs(b[0] - sx) <= 3 and b[1] >= ship_row - 3),
                     key=lambda b: (-b[1], abs(b[0] - sx)), default=None)
        tgt = min(wave, key=lambda a: (abs(acol(a[0]) - sx), -a[1]))
        flight = (ship_row - 1) - (oy + tgt[1])   # frames a shot needs to get up there
        aim = acol(tgt[0]) + d * (flight // 2)    # lead it -- the wave marches meanwhile
        if threat:                                # dodging beats aiming
            want = sx + (4 if threat[0] <= sx else -4)
        else:
            want = aim
        if random.random() < 0.8:                 # 80% the right move, 20% a fumbled one
            sx += max(-2, min(2, want - sx))
        else:
            sx += random.choice([-1, 0, 1])
        sx = max(0, min(inner - 1, sx))
        if bullet is None and not threat and 0 <= sx - aim <= 1:
            bullet = (sx, ship_row - 1)
        elif bullet is not None:
            bx, by = bullet[0], bullet[1] - 1
            k = next((a for a in wave if oy + a[1] == by
                      and acol(a[0]) <= bx <= acol(a[0]) + 1), None) if by >= 0 else None
            if k: wave.discard(k); bullet = None
            else: bullet = None if by < 0 else (bx, by)
        if wave and f % BOMB_EVERY == 0:
            a = random.choice(sorted(wave))
            bombs.append((acol(a[0]), oy + a[1] + 1))
        bombs = [(x, y + 1) for x, y in bombs]
        if any(y >= ship_row and abs(x - sx) <= 1 for x, y in bombs):
            alive = False
        bombs = [(x, y) for x, y in bombs if y < h]
        rows = []
        for r in range(h):
            items = [(acol(c), "👾", GREEN) for (c, rr) in wave
                     if oy + rr == r and 0 <= acol(c) < inner - 1]
            items += [(x, "•", RED) for x, y in bombs if y == r and 0 <= x < inner]
            if bullet and bullet[1] == r: items.append((bullet[0], "│", WHITE))
            if r == ship_row: items.append((sx, "▲" if alive else "💥", CORAL))
            rows.append(_place(inner, items, color))
        yield rows, f"👾 invaders · {len(wave)} left"
    won = alive and not wave
    result["won"] = won
    end = "🏆 wave cleared!" if won else "💥 ship down!"
    for _ in range(6):
        yield [_place(inner, [(sx, "▲" if won else "💥", CORAL)], color) if r == ship_row
               else " " * inner for r in range(h)], f"{end} {ncol * nrow - len(wave)} hits"

# --- breakout (bot paddle, two rows of bricks) -------------------------------
def breakout(inner, h, color, result=None):
    if result is None: result = {}
    CORAL, GOLD, WHITE = (217, 119, 87), (240, 200, 90), (235, 235, 235)
    BW, PITCH, PW = 7, 10, 5
    ncol = max(2, (inner - 2) // PITCH)
    nrow = min(2, max(1, h - 3))
    bricks = {(1 + c * PITCH, r) for c in range(ncol) for r in range(nrow)}
    total = len(bricks)
    px = (inner - PW) // 2
    bx, by = inner // 2, h - 2
    vx, vy = random.choice([-1, 1]), -1
    alive, f = True, 0
    MAXF = 420
    rows = [" " * inner] * h

    def landing():
        """Where the ball will meet the paddle row — straight down, or up off the
        bricks and back. Wall bounces fold in as a reflection, so the bot doesn't
        get wrong-footed at the edges the way chasing the live column does."""
        steps = (h - 1 - by) if vy > 0 else by + (h - 1)
        x = (bx + vx * steps) % (2 * (inner - 1))
        return x if x < inner else 2 * (inner - 1) - x

    while bricks and alive and f < MAXF:
        f += 1
        if random.random() < 0.8:                 # 80% a clean read of the ball,
            land = landing()                      # 20% a lazy/wrong-way nudge
            tgt = land - PW // 2
            if abs(px - tgt) <= 1:                # already set? then meet the ball
                near = min(bricks, key=lambda b: abs(b[0] + BW // 2 - land))
                tgt -= 1 if near[0] + BW // 2 >= land else -1   # off-centre, angling the
            px += max(-2, min(2, tgt - px))       # return at what's still standing
        else:
            px += random.choice([-1, 0, 1])
        px = max(0, min(inner - PW, px))
        bx += vx; by += vy
        if bx <= 0: bx, vx = 0, 1
        elif bx >= inner - 1: bx, vx = inner - 1, -1
        if by <= 0: by, vy = 0, 1
        hit = next((b for b in bricks if b[1] == by and b[0] <= bx < b[0] + BW), None)
        if hit:
            bricks.discard(hit); vy = -vy
        elif by >= h - 1:
            if px <= bx < px + PW:                         # returned off the paddle: the
                by, vy = h - 2, -1                         # side it hits sets the angle, so
                vx = 1 if bx >= px + PW // 2 else -1       # the ball sweeps the whole wall
            else:
                alive = False                              # missed it
        rows = []
        for r in range(h):
            items = [(c, "▬" * BW, GOLD) for (c, rr) in bricks if rr == r]
            if r == by and 0 <= bx < inner: items.append((bx, "●", WHITE))
            if r == h - 1: items.append((px, "▂" * PW, CORAL))
            rows.append(_place(inner, items, color))
        yield rows, f"🧱 breakout · {total - len(bricks)}/{total}"
    won = alive and not bricks
    result["won"] = won
    end = "🏆 cleared the wall!" if won else "😵 missed it"
    for _ in range(6):
        yield rows, f"{end}  {total - len(bricks)}/{total}"

# --- bug squash (the crab's hammer vs. bugs crawling out of the code) --------
def squash(inner, h, color, result=None):
    if result is None: result = {}
    CORAL, GREEN, RED = (217, 119, 87), (90, 170, 90), (220, 90, 90)
    TARGET, MAX_ESC = 12, 3
    bugs = []                                     # [x, row, direction]
    hx, hy = inner // 2, h // 2
    boom = None                                   # (x, row, ttl)
    score, esc, spawn, f = 0, 0, 0, 0
    MAXF = 240
    rows = [" " * inner] * h
    while score < TARGET and esc < MAX_ESC and f < MAXF:
        f += 1
        spawn -= 1
        if spawn <= 0 and len(bugs) < 8:
            d = random.choice([-1, 1])
            bugs.append([0 if d > 0 else inner - 2, random.randrange(h), d])
            spawn = random.randint(3, 7)
        for b in bugs: b[0] += b[2] * 2           # they scuttle as fast as the hammer swings
        gone = [b for b in bugs if not (0 <= b[0] < inner - 1)]
        esc += len(gone)
        bugs = [b for b in bugs if b not in gone]
        if bugs and random.random() < 0.8:        # 80% a straight line to the nearest bug,
            t = min(bugs, key=lambda b: abs(b[0] - hx) + 2 * abs(b[1] - hy))
            hx += max(-2, min(2, t[0] - hx))      # 20% an aimless swing
            hy += (1 if t[1] > hy else -1) if t[1] != hy else 0
        else:
            hx += random.choice([-2, -1, 0, 1, 2]); hy += random.choice([-1, 0, 1])
        hx, hy = max(0, min(inner - 2, hx)), max(0, min(h - 1, hy))
        struck = next((b for b in bugs if b[1] == hy and abs(b[0] - hx) <= 1), None)
        if struck:
            bugs.remove(struck); score += 1; boom = (struck[0], struck[1], 3)
        rows = []
        for r in range(h):
            items = [(b[0], "🐛", GREEN) for b in bugs if b[1] == r]
            if boom and boom[1] == r: items.append((boom[0], "💥", RED))
            if r == hy: items.append((hx, "🔨", CORAL))
            rows.append(_place(inner, items, color))
        if boom: boom = None if boom[2] <= 1 else (boom[0], boom[1], boom[2] - 1)
        yield rows, f"🐛 squash · {score}/{TARGET} · {esc} escaped"
    won = score >= TARGET
    result["won"] = won
    end = "🏆 all clear!" if won else "🐛 they got away"
    for _ in range(6):
        yield rows, f"{end}  {score}/{TARGET}"

def play(name, inner, h, color, result=None):
    return {"dino": dino, "pong": pong, "snake": snake, "crossing": crossing,
            "invaders": invaders, "breakout": breakout,
            "squash": squash}.get(name, dino)(inner, h, color, result)
