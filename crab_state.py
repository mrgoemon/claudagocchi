#!/usr/bin/env python3
"""Claudagocchi state engine.

Owns everything that makes the crab a pet rather than a screensaver:

  - Tamagotchi vitals : hunger / energy / happiness that decay over real time
                        and are fed by your coding activity.
  - Daily code vitals : commits + lines added/removed today, and your streak,
                        read straight from git.
  - Day-mood          : a single mood derived from vitals + activity, used to
                        bias the crab's animation and what it says.
  - Daily quests      : small goals (commit 3x, write 100 lines, take a break)
                        that reset each day.
  - Break timer       : nudges you to stretch after a stretch of active time.

Pure stdlib. State lives in ~/.claude-crab/{state,config}.json.
"""
import os
import re
import sys
import json
import time
import random
import datetime
import subprocess
import tempfile
import pathlib

# CRAB_SAVE_DIR relocates the whole save. The launch-video demo points it at a
# throwaway crab so recording a take cannot read or write the real pet; it is
# deliberately narrow -- Claude Code's own data still comes from ~/.claude, so
# the token and session counts on screen stay real.
DIR = pathlib.Path(os.environ.get("CRAB_SAVE_DIR")
                   or pathlib.Path.home() / ".claude-crab")
STATE = DIR / "state.json"
CONFIG = DIR / "config.json"
PRE_DEATH = DIR / "state.pre-death.json"   # safety copy taken before a permadeath reset

# --- versions ----------------------------------------------------------------
# v1.0 was the immortal crab: vitals that decayed but never ran out, one fixed
# sprite, no age and no end. v2.0 gives it a life cycle -- it grows, it can be
# lost, and it remembers the ones before it.
#
# Loading a v1.0 save is seamless: missing keys get defaults, and the crab is
# placed at the stage its existing age already earned (see `_seed_stage`) rather
# than demoted to an egg. The v1.0 SOURCE is frozen under legacy/v1.0/ and is
# never referenced from here.
VERSION = "2.0"

# How fast the crab's clock runs. Admin mode winds this up to demonstrate days of
# neglect in seconds; it is 1.0 in normal use.
TIME_SCALE = float(os.environ.get("CRAB_TIME_SCALE") or 1.0)

# --- tuning knobs (per hour unless noted) -----------------------------------
# The clock is workday-scaled. A single 0-100 bar cannot express both "peckish
# after 4h" and "dead after 5d", so hunger saturates early and `health` — a
# second, much slower axis that only moves while starving — carries the rest:
#
#   idle  4h  -> hunger  32, health 100   peckish
#   idle 12.5h -> hunger 100, health 100   starving begins
#   idle  1d  -> hunger 100, health  88   hungry
#   idle  3d  -> hunger 100, health  40   critical
#   idle ~4.7d -> hunger 100, health   0   dies
HUNGER_PER_HR = 8.0       # belly empties (0 = full, 100 = starving) in ~12.5h
COUPLE_PER_HR = 0.6       # how fast energy & mood drift toward the current belly level
STARVE_AT = 90.0          # hunger at or above this counts as starving
HEALTH_DRAIN_PER_HR = 1.0    # health lost per hour while starving
HEALTH_REGEN_PER_HR = 4.0    # health recovered per hour when not starving
BREAK_AFTER_MIN = 50      # nudge to stretch after this much unbroken time
IDLE_RESET_MIN = 90       # a gap this long starts a fresh work session
MARATHON_MIN = 180        # session longer than this -> "tired"

def _now(): return time.time()
def _clamp(v, lo=0.0, hi=100.0): return max(lo, min(hi, v))

# --- persistence ------------------------------------------------------------
# config.json holds an API key, so the whole directory is ours alone. The modes
# are re-applied on every save, not just at creation, so saves written before
# this existed (0644) get tightened the next time the crab breathes.
DIR_MODE = 0o700
FILE_MODE = 0o600

def _short(path):
    """~/.claude-crab/state.json rather than the whole absolute path."""
    try:
        return "~/" + str(path.relative_to(pathlib.Path.home()))
    except ValueError:
        return str(path)

def _quarantine(path):
    """Move an unreadable save aside instead of letting the next save eat it.
    Named like the other keepsakes in ~/.claude-crab (state.pre-death.json,
    state.v1-backup-<stamp>.json). Returns the new path, or None if even that
    failed."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for n in range(1, 100):                 # two wrecks in one second is still two
        tag = stamp if n == 1 else f"{stamp}-{n}"
        dest = path.with_name(f"{path.stem}.corrupt-{tag}{path.suffix}")
        if not dest.exists():
            break
    try:
        os.replace(path, dest)
        try:
            os.chmod(dest, FILE_MODE)       # a wrecked config.json still holds a key
        except OSError:
            pass
        return dest
    except Exception:
        return None

def _load(path, default):
    """Missing file -> defaults, silently: that is a first run. A file that EXISTS
    but won't parse is a different thing entirely -- state.json carries the
    graveyard, and returning defaults there would hatch a new egg and overwrite
    every crab you ever raised on the next save. Keep the wreckage and say so."""
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"expected an object, got {type(data).__name__}")
        return data
    except Exception as e:
        kept = _quarantine(path)
        print(f"\ncrab: {_short(path)} is damaged and could not be read ({e}).", file=sys.stderr)
        if kept:
            print(f"      your old file is kept at {_short(kept)} — nothing was deleted.",
                  file=sys.stderr)
            if path == STATE:
                print("      starting from a fresh save; `crab --undo` restores the last "
                      "snapshot.", file=sys.stderr)
        else:
            print(f"      it could NOT be moved aside — copy {_short(path)} somewhere safe "
                  "now, it will be overwritten.", file=sys.stderr)
        print(file=sys.stderr)
        return dict(default)

def _write(path, text):
    """Atomic write. `_save` runs inside the animation loop, so a Ctrl-C or a crash
    lands mid-write often enough to matter: a truncate-in-place would leave a
    half-file where the crab's whole history used to be. Serialize, fsync a temp
    file in the SAME directory, then rename over the target -- a reader sees the
    old file or the new one, never a hole."""
    d = path.parent
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, DIR_MODE)
    except OSError:
        pass                                # someone else's dir; the file mode still holds
    fd, tmp = tempfile.mkstemp(dir=d, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:       # takes the fd over, closes it either way
            os.fchmod(f.fileno(), FILE_MODE)   # BEFORE the rename: replace keeps THIS mode
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:                   # incl. Ctrl-C -- don't litter .tmp files
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def _save(path, data):
    _write(path, json.dumps(data, indent=2))

def load_config():
    return _load(CONFIG, {"repos": [], "author": None})

def save_config(cfg):
    _save(CONFIG, cfg)

def anthropic_key():
    """Chat API key: the ANTHROPIC_API_KEY env var wins, else whatever
    `crab --setkey` saved into config.json."""
    return os.environ.get("ANTHROPIC_API_KEY") or load_config().get("anthropic_key")

def set_anthropic_key(key):
    cfg = load_config()
    cfg["anthropic_key"] = key
    save_config(cfg)

def default_career():
    """Per-generation tallies. These decide which adult form the crab grows into,
    and they are what a memorial remembers."""
    return {"prs": 0, "commits": 0, "tokens_mtok": 0.0,
            "games_played": 0, "games_won": 0, "neglect_hours": 0.0,
            "peak_streak": 0}

def default_state():
    n = _now()
    return {"born": n, "last_seen": n, "hunger": 20.0, "energy": 80.0,
            "happiness": 70.0, "health": 100.0, "session_start": n, "last_break": n,
            "seen": {}, "quests_date": None, "quests_done": [], "break_taken": 0,
            "generation": 1, "name": None, "form": None, "hatched": False,
            "version": VERSION, "career": default_career(), "graveyard": []}

def load_state():
    s = _load(STATE, default_state())
    for k, v in default_state().items():
        s.setdefault(k, v)
    for k, v in default_career().items():          # careers grow new counters too
        s["career"].setdefault(k, v)
    if not s.get("name"):
        s["name"] = pick_name(s)
    s["version"] = VERSION
    _seed_stage(s)
    return s

def save_state(s):
    _save(STATE, s)

# --- git --------------------------------------------------------------------
def _git(repo, *args):
    try:
        return subprocess.run(["git", "-C", repo, *args],
                              capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return ""

def git_root(path):
    return _git(path, "rev-parse", "--show-toplevel").strip() or None

def default_author():
    return (_git(".", "config", "user.email").strip() or None)

def watched_repos(cfg, cwd=None):
    repos = list(cfg.get("repos", []))
    if cwd:
        r = git_root(cwd)
        if r and r not in repos:
            repos.append(r)
    return repos

def _midnight():
    return datetime.datetime.now().replace(hour=0, minute=0, second=0,
                                           microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

def today_stats(repos, author=None):
    """Commits + lines added/removed today, across repos, optionally by author."""
    commits = added = removed = 0
    args = ["log", "--all", "--since", _midnight(), "--no-merges", "--numstat",
            "--pretty=tformat:__C__"]                  # --all: every branch, not just HEAD
    if author:
        args += ["--author", author]
    for repo in repos:
        for line in _git(repo, *args).splitlines():
            if line == "__C__":
                commits += 1
            else:
                p = line.split("\t")
                if len(p) >= 2 and p[0].isdigit():
                    added += int(p[0])
                    removed += int(p[1]) if p[1].isdigit() else 0
    return {"commits": commits, "added": added, "removed": removed}

def streak(repos, author=None):
    """Consecutive days (ending today or yesterday) with at least one commit."""
    days = set()
    args = ["log", "--all", "--since", "70 days ago", "--date=short", "--pretty=%ad"]
    if author:
        args += ["--author", author]
    for repo in repos:
        for line in _git(repo, *args).splitlines():
            days.add(line.strip())
    n, d = 0, datetime.date.today()
    if d.isoformat() not in days:          # today not committed yet -> count from yesterday
        d -= datetime.timedelta(days=1)
    while d.isoformat() in days:
        n += 1
        d -= datetime.timedelta(days=1)
    return n

def _head(repo):
    line = _git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    count = _git(repo, "rev-list", "--count", "HEAD").strip()
    return {"head": line[0] if line else "",
            "count": int(count) if count.isdigit() else 0,
            "merge": len(line) > 2}          # >1 parent = merge commit

# --- the tick ---------------------------------------------------------------
def tick(state, repos, now=None):
    """Advance vitals to `now`: decay over elapsed time, then feed from any new
    commits. Returns a list of fired events (e.g. ['commit'] or ['merge'])."""
    now = now or _now()
    hrs = max(0.0, (now - state["last_seen"]) / 3600.0) * TIME_SCALE

    hunger0 = state["hunger"]
    state["hunger"] = min(100.0, hunger0 + HUNGER_PER_HR * hrs)   # belly empties
    belly = 100.0 - state["hunger"]
    pull = min(1.0, COUPLE_PER_HR * hrs)                  # energy & mood drift toward belly:
    state["energy"]    = _clamp(state["energy"] + (belly - state["energy"]) * pull)      # full
    state["happiness"] = _clamp(state["happiness"] + (belly - state["happiness"]) * pull)  # -> up

    # An empty belly is survivable; STAYING empty is not. Health only moves for the
    # part of the elapsed window the crab was actually starving. Splitting the
    # window matters because `hrs` can be days after the laptop was shut -- charging
    # the whole gap as starvation would kill a crab that was fed most of it.
    # The two halves are applied IN ORDER -- fed first, starving second -- because
    # they don't commute: draining to 0 and then regenerating would revive a crab
    # that starved to death partway through the window.
    to_starve = max(0.0, (STARVE_AT - hunger0) / HUNGER_PER_HR)   # hours until empty
    starving_hrs = max(0.0, hrs - to_starve)
    well_hrs = hrs - starving_hrs
    if well_hrs:
        state["health"] = min(100.0, state["health"] + HEALTH_REGEN_PER_HR * well_hrs)
    if starving_hrs:
        state["health"] = max(0.0, state["health"] - HEALTH_DRAIN_PER_HR * starving_hrs)
        car = state.setdefault("career", default_career())
        car["neglect_hours"] = car.get("neglect_hours", 0.0) + starving_hrs

    if (now - state["last_seen"]) / 60.0 > IDLE_RESET_MIN:   # came back after a break
        state["session_start"] = now
        state["last_break"] = now

    state["last_seen"] = now
    return []                              # commits now feed via per-commit gifts

# --- the life cycle: stages, forms, death, rebirth ---------------------------
# Age gates, in days since `born`. The crab is grandfathered past any gate its
# existing history already cleared, so upgrading never demotes a long-lived pet.
LIFE_STAGES = [(0.0, "egg"), (0.25, "baby"), (1.0, "juvenile"), (3.0, "adult")]
FORM_AGE_DAYS = 7.0                        # when the adult locks into a branch
ADULT_FORMS = ("architect", "grinder", "gamer", "feral")

NAME_POOL = ["Clawde", "Shelly", "Pinch", "Molt", "Barnacle", "Nipper", "Chowder",
             "Kelp", "Bisque", "Coral", "Scuttle", "Brine", "Pebble", "Marina"]

def pick_name(state):
    """A name not already used by this crab's ancestors."""
    used = {m.get("name") for m in state.get("graveyard", [])}
    free = [n for n in NAME_POOL if n not in used]
    return random.choice(free or NAME_POOL)

def age_days(state, now=None):
    return max(0.0, ((now or _now()) - state.get("born", _now())) / 86400.0)

def branch_scores(career):
    """How strongly this crab's history points at each adult form."""
    return {"architect": career.get("prs", 0) * 10 + career.get("commits", 0),
            "grinder":   career.get("tokens_mtok", 0.0) * 2,
            "gamer":     career.get("games_played", 0) * 3 + career.get("games_won", 0) * 2,
            "feral":     career.get("neglect_hours", 0.0) * 0.5}

def choose_form(state):
    """Lock in the adult form earned by how you coded. Ties break toward
    architect and away from feral -- neglect should never win a coin flip."""
    scores = branch_scores(state.get("career", {}))
    order = {"architect": 3, "grinder": 2, "gamer": 1, "feral": 0}   # tiebreak priority
    return max(ADULT_FORMS, key=lambda f: (scores.get(f, 0), order[f]))

def life_stage(state, now=None):
    """The morph key for the crab's current stage. CRAB_STAGE overrides it for QA
    (you cannot otherwise see the egg without hand-editing state.json)."""
    override = os.environ.get("CRAB_STAGE")
    if override:
        return override
    age = age_days(state, now)
    key = "egg"
    for gate, name in LIFE_STAGES:
        if age >= gate:
            key = name
    if key == "egg" and state.get("hatched"):     # fed early -> hatch early
        key = "baby"
    if key == "adult" and age >= FORM_AGE_DAYS:
        if not state.get("form"):
            state["form"] = choose_form(state)
        return state["form"]
    return key

def molt_soon(state, now=None, window_hours=1.0):
    """True when the crab is within `window_hours` of its next stage gate, so it
    can telegraph the change instead of popping a new shape out of nowhere."""
    age = age_days(state, now)
    gates = [g for g, _ in LIFE_STAGES if g > 0] + [FORM_AGE_DAYS]
    nxt = min((g for g in gates if g > age), default=None)
    return nxt is not None and (nxt - age) * 24.0 <= window_hours

def _seed_stage(state):
    """Grandfather an existing pet: a crab with real history should not wake up as
    an egg just because the lifecycle shipped. Anything past the baby gate counts
    as hatched, and a crab old enough for a form gets one."""
    if age_days(state) >= LIFE_STAGES[1][0]:
        state["hatched"] = True
    if age_days(state) >= FORM_AGE_DAYS and not state.get("form"):
        state["form"] = choose_form(state)

def is_dead(state):
    return state.get("health", 100.0) <= 0.0

def memorial(state, now=None, cause="starvation", graduated=False):
    """Everything that made this generation distinct. Cheap to store, impossible
    to reconstruct afterwards."""
    now = now or _now()
    hoard = hoard_summary(state)
    return {"gen": state.get("generation", 1), "name": state.get("name") or "?",
            "born": state.get("born", now), "died": now,
            "age_days": round(age_days(state, now), 1),
            "stage": life_stage(state, now), "form": state.get("form"),
            "hoard_count": hoard.get("count", 0), "hoard_net": hoard.get("net", 0),
            "by_tier": dict(hoard.get("by_tier", {})),
            "career": dict(state.get("career", {})), "cause": cause,
            "version": VERSION, "graduated": graduated}

def bury(state, now=None, cause="starvation"):
    """Record the crab that just died. Returns the memorial."""
    m = memorial(state, now, cause)
    state.setdefault("graveyard", []).append(m)
    return m

# --- graduation --------------------------------------------------------------
# Death is what happens TO a crab. Graduation is something you choose: you decide
# it's had a good run, retire it with honours, and start again. The crab goes to
# Memory Lane with a 🎓 instead of a ✝, and its record says how it was raised.
def can_graduate(state, now=None):
    """(eligible, reason). A crab graduates once it has reached a final form --
    before that there is nothing to graduate FROM."""
    stage = life_stage(state, now)
    if stage in ADULT_FORMS:
        return True, ""
    left = max(0.0, FORM_AGE_DAYS - age_days(state, now))
    if left <= 0:
        return True, ""
    unit = f"{left:.1f} days" if left >= 1 else f"{left * 24:.0f} hours"
    article = "an" if stage[0] in "aeiou" else "a"
    return False, (f"{state.get('name')} is still {article} {stage} — "
                   f"{unit} until it can graduate")

def graduate(state, now=None):
    """Retire the crab honourably and hatch its successor. Returns the memorial."""
    now = now or _now()
    m = memorial(state, now, cause="graduated", graduated=True)
    state.setdefault("graveyard", []).append(m)
    rebirth(state, now)
    return m

# Bookkeeping that belongs to YOU and your repos, not to the crab. It has to
# survive a rebirth or the new crab re-fires everything the old one already
# handled: today's finished quests celebrate again, PRs you opened last week
# arrive as fresh gifts, streak milestones throw a second party, and the
# monotonic all-time token counter dumps one enormous feed into a newborn.
CARRIES_OVER = ("graveyard", "tokens_seen", "quests_date", "quests_done",
                "break_taken", "pr_gifted", "pr_cache", "celebrated_ms",
                "pushed", "tok_today_cache")

def rebirth(state, now=None):
    """A fresh egg: new name, empty hoard, blank career. Everything in
    CARRIES_OVER is kept -- see the note there for why each one matters."""
    now = now or _now()
    carried = {k: state[k] for k in CARRIES_OVER if k in state}
    fresh = default_state()
    fresh["born"] = fresh["last_seen"] = fresh["session_start"] = fresh["last_break"] = now
    fresh["generation"] = state.get("generation", 1) + 1
    fresh.update(carried)
    fresh["name"] = pick_name(fresh)          # after carrying: skips ancestors' names
    state.clear()
    state.update(fresh)
    return state

def backup_state():
    """Snapshot state.json before an irreversible reset, so `--undo-death` can
    put a 60-day crab back if the death logic ever misfires."""
    try:
        if STATE.exists():
            _write(PRE_DEATH, STATE.read_text())   # the snapshot is worth as much as the save
            return True
    except Exception:
        pass
    return False

def restore_state():
    try:
        if PRE_DEATH.exists():
            _write(STATE, PRE_DEATH.read_text())
            return True
    except Exception:
        pass
    return False

def record_game(state, won):
    car = state.setdefault("career", default_career())
    car["games_played"] = car.get("games_played", 0) + 1
    if won:
        car["games_won"] = car.get("games_won", 0) + 1
        state["happiness"] = min(100.0, state["happiness"] + 4)

# --- derived: mood, quests, break -------------------------------------------
def day_mood(state, today, now=None):
    now = now or _now()
    session_min = (now - state["session_start"]) / 60.0
    health = state.get("health", 100.0)
    if health < 20:                        # health outranks everything: it is fatal
        return "dying"
    if health < 50:
        return "sick"
    if state["energy"] < 25 or session_min > MARATHON_MIN:
        return "tired"
    if state["hunger"] > 75:
        return "hungry"
    if today["commits"] >= 1 and state["happiness"] >= 60:
        return "energetic"
    if today["commits"] == 0 and state["happiness"] < 55:
        return "lonely"
    if state["happiness"] > 70:
        return "content"
    return "okay"

QUESTS = [
    ("commit3",  "commit 3x",       lambda t: t["commits"], 3),
    ("lines100", "write 100 lines", lambda t: t["added"],   100),
    ("break",    "take a break",    None,                   1),
]

def _roll_quest_day(state):
    today = datetime.date.today().isoformat()
    if state.get("quests_date") != today:
        state["quests_date"] = today
        state["quests_done"] = []
        state["break_taken"] = 0

def quests_status(state, today):
    _roll_quest_day(state)
    out = []
    for key, label, fn, goal in QUESTS:
        prog = min(fn(today) if fn else state.get("break_taken", 0), goal)
        out.append({"key": key, "label": label, "prog": prog, "goal": goal,
                    "done": prog >= goal})
    return out

def newly_completed(state, quests):
    """Quest keys that just crossed into 'done' since last check (fire once)."""
    done = [q["key"] for q in quests if q["done"]]
    fresh = [k for k in done if k not in state.get("quests_done", [])]
    state["quests_done"] = sorted(set(state.get("quests_done", [])) | set(done))
    return fresh

def break_due(state, now=None):
    now = now or _now()
    return (now - state.get("last_break", now)) / 60.0 >= BREAK_AFTER_MIN

def take_break(state, now=None):
    now = now or _now()
    state["last_break"] = now
    state["break_taken"] = state.get("break_taken", 0) + 1
    state["energy"] = min(100.0, state["energy"] + 15)

# --- presentation: stat lines + speech --------------------------------------
def _meter(v, n=5):
    filled = max(0, min(n, round(v / 100.0 * n)))
    return "●" * filled + "○" * (n - filled)

def _htok(n):
    if n >= 1e6: return f"{n / 1e6:.1f}M"
    if n >= 1e3: return f"{n / 1e3:.1f}k"
    return str(int(n))

def _ago(age):
    """Age of a stale reading, short enough for the bar."""
    if age is None:
        return "?"
    if age < 3600:
        return f"{max(1, int(age // 60))}m"
    if age < 86400:
        return f"{int(age // 3600)}h"
    return f"{int(age // 86400)}d"

def _limit_line(label, win, stale, age=""):
    """One usage-limit row: `session ●●○○○  31%  ·  resets 10:40 PM`.

    Only Claude Code refreshes the reading, and it can sit unrefreshed for
    hours, so a stale one still shows its number -- with how old it is instead
    of a reset time that has probably already passed. Hiding a real number
    helps nobody; presenting an old one as current would be the dishonest part.
    """
    if not win:
        return f"{label:<7} …"
    line = f"{label:<7} {_meter(win['pct'])} {win['pct']:3.0f}%"
    tail = f"{age} ago" if stale else (f"resets {win['resets']}" if win.get("resets") else "")
    return f"{line}  ·  {tail}" if tail else line

def stat_lines(state, tokens_today, tokens_all=0, limits=None):
    """l1 = vitals; l2 = tokens used today; l3 = all-time Claude Code tokens;
    l4 = how much of the current 5-hour session limit is gone, and when it
    resets.

    ALWAYS returns four lines -- the window's height is measured once at
    startup, so a stat line that came and went would tear the redraw.
    """
    belly = 100 - state["hunger"]
    health = state.get("health", 100.0)
    l1 = f"mood {_meter(state['happiness'])}  energy {_meter(state['energy'])}  belly {_meter(belly)}"
    if health < 100:                       # only shown once there's something to worry about
        l1 += f"  health {_meter(health)}"
    l2 = f"tokens used today  {tokens_today:,}"
    l3 = f"tokens all-time  {tokens_all:,}"
    lim = limits or {}
    stale, age = lim.get("stale", True), _ago(lim.get("age"))
    return [l1, l2, l3,
            _limit_line("session", lim.get("session"), stale, age)]

def speech(state, mood, events, fresh_quests, brk, name="kh"):
    if "merge" in events:
        return random.choice(["PR merged! *party*", "merged it. clean.", "shipped! *wiggle*"])
    if "commit" in events:
        return random.choice(["nice commit! *wiggle*", "ooh, fresh code!", "saved! keep rolling."])
    if fresh_quests:
        return random.choice(["quest done! nice work *", "goal cleared! proud of you.", "ding! quest complete *"])
    if brk:
        return "we've been at it a while — stretch with me?"
    return {
        "tired":     "long session... let's take it easy.",
        "hungry":    "feeling peckish — feed me a commit?",
        "lonely":    "kinda quiet today. wanna build something?",
        "energetic": "we're cooking today! (｡･ω･｡)",
        "content":   "good flow today (｡･ω･｡)",
        "okay":      f"Welcome back {name}!",
    }.get(mood, f"Welcome back {name}!")

# Rotating idle lines so the bubble doesn't go stale (refreshed every few mins).
IDLE_LINES = [
    "still here with you (｡･ω･｡)",
    "what are we building today?",
    "take your time, i'll wait",
    "you've got this.",
    "i like watching you work",
]

def idle_speech(state, mood, pr_stats=None, name="kh"):
    """A fresh idle line: the mood line, a flavor line, or a stat brag."""
    pool = [speech(state, mood, [], [], False, name)] + IDLE_LINES
    p = pr_stats or {}
    if p.get("prs"):
        pool.append(f"{p['prs']} PRs today — proud of you")
    if p.get("streak", 0) >= 2:
        pool.append(f"{p['streak']}-day streak! keep it going")
    return random.choice(pool)

# --- gifts (pushes) ---------------------------------------------------------
# A "gift" fires when YOU push work. Significance = net lines (added - removed,
# so AI generate-then-delete churn cancels) on a vibecoded scale, and a merged
# PR bumps the tier up one (blend "C").
GIFT_TIERS = [          # (min net lines, name, label)
    (0,    "crumb",    "a crumb"),
    (50,   "shell",    "a shell"),
    (250,  "fish",     "a fish"),
    (1000, "feast",    "a feast"),
    (3500, "treasure", "treasure"),
]
GIFT_FEED = [8, 14, 20, 30, 40]   # happiness/satiety boost per tier

def gift_tier(net, has_pr):
    idx = 0
    for i, (t, _n, _l) in enumerate(GIFT_TIERS):
        if net >= t:
            idx = i
    if has_pr:                                  # a merged PR is worth a tier
        idx = min(idx + 1, len(GIFT_TIERS) - 1)
    return idx

def _upstream_sha(repo):
    """SHA the current branch's upstream points to. Updates the instant you push
    (no fetch needed), so it's how we notice you shipped."""
    return _git(repo, "rev-parse", "--verify", "-q", "@{upstream}").strip() or None

_PR_RE = re.compile(r"Merge pull request #\d+|\(#\d+\)")

def detect_gifts(state, repos, author=None, now=None):
    """Notice newly-pushed work and return a gift per repo whose upstream
    advanced with commits authored by you."""
    gifts = []
    pushed = state.setdefault("pushed", {})         # repo -> last-seen upstream sha
    for repo in repos:
        cur = _upstream_sha(repo)
        if not cur:
            continue
        prev = pushed.get(repo)
        pushed[repo] = cur
        if prev is None or prev == cur:             # baseline, or nothing new
            continue
        rng = f"{prev}..{cur}"
        args = ["log", rng, "--no-merges", "--numstat", "--pretty=tformat:__C__"]
        if author:
            args += ["--author", author]
        added = removed = commits = 0
        for line in _git(repo, *args).splitlines():
            if line == "__C__":
                commits += 1
            else:
                p = line.split("\t")
                if len(p) >= 2 and p[0].isdigit():
                    added += int(p[0])
                    removed += int(p[1]) if p[1].isdigit() else 0
        if commits == 0:                            # upstream moved, but not your work
            continue
        has_pr = bool(_PR_RE.search(_git(repo, "log", rng, "--pretty=%s")))
        net = max(0, added - removed)
        idx = gift_tier(net, has_pr)
        gifts.append({"repo": repo, "net": net, "gross": added, "commits": commits,
                      "pr": has_pr, "tier": idx,
                      "name": GIFT_TIERS[idx][1], "label": GIFT_TIERS[idx][2]})
    return gifts

def record_gift(state, gift):
    h = state.setdefault("hoard", {"count": 0, "net": 0, "by_tier": {}})
    h["count"] += 1
    h["net"] += gift["net"]
    h["by_tier"][gift["name"]] = h["by_tier"].get(gift["name"], 0) + 1

def feed_gift(state, gift):
    boost = GIFT_FEED[min(gift["tier"], len(GIFT_FEED) - 1)]
    state["happiness"] = min(100.0, state["happiness"] + boost)
    state["hunger"]    = max(0.0, state["hunger"] - boost)
    state["energy"]    = min(100.0, state["energy"] + 5)
    state["health"]    = min(100.0, state.get("health", 100.0) + boost * 0.4)
    state["hatched"]   = True

TOKENS_FEED_PER_MTOK = 12.0          # belly points gained per 1M Claude Code tokens

def feed_tokens(state, all_tokens):
    """Fill the belly by how many NEW tokens you've run through Claude Code since
    last check. Uses the monotonic all-time count so a day rollover never feeds a
    huge chunk; the belly still decays over time when you stop coding."""
    prev = state.get("tokens_seen")
    state["tokens_seen"] = all_tokens
    if prev is None:                                 # first run: just baseline
        return
    delta = max(0, all_tokens - prev)
    if delta:
        mtok = delta / 1e6
        boost = mtok * TOKENS_FEED_PER_MTOK
        state["hunger"]    = max(0.0, state["hunger"] - boost)
        state["happiness"] = min(100.0, state["happiness"] + boost * 0.3)
        state["energy"]    = min(100.0, state["energy"] + boost * 0.2)
        state["health"]    = min(100.0, state.get("health", 100.0) + boost * 0.5)
        car = state.setdefault("career", default_career())
        car["tokens_mtok"] = car.get("tokens_mtok", 0.0) + mtok
        if not state.get("hatched"):        # the first real meal cracks the egg
            state["hatched"] = True

def gift_speech(gift):
    pr = " (a whole PR!)" if gift["pr"] else ""
    return {
        0: f"{gift['label']} — thanks!{pr}",
        1: f"ooh, {gift['label']} for me?{pr}",
        2: f"{gift['label']}!{pr} *happy trot*",
        3: f"{gift['label']}?!{pr} you spoil me <3",
        4: f"{gift['label']}...{pr} you made all this for me",
    }.get(gift["tier"], "for me? thank you!")

def detect_commit_gifts(repos, author, seen):
    """Every new commit you make becomes a gift, sized by that commit's net lines.
    `seen` is an in-memory set of SHAs already handled — pass None on the first
    call to baseline (so existing commits don't all retro-fire). Returns
    (gifts, seen)."""
    found = []                                       # (sha, net_lines)
    args = ["log", "--all", "--since", "20 minutes ago", "--no-merges",
            "--numstat", "--pretty=tformat:__C__%H"]
    if author:
        args += ["--author", author]
    for repo in repos:
        sha, add, rem = None, 0, 0
        for line in _git(repo, *args).splitlines():
            if line.startswith("__C__"):
                if sha is not None:
                    found.append((sha, max(0, add - rem)))
                sha, add, rem = line[5:], 0, 0
            else:
                p = line.split("\t")
                if len(p) >= 2 and p[0].isdigit():
                    add += int(p[0]); rem += int(p[1]) if p[1].isdigit() else 0
        if sha is not None:
            found.append((sha, max(0, add - rem)))

    if seen is None:                                 # first call: baseline, don't fire
        return [], {sha for sha, _ in found}
    gifts = []
    for sha, net in found:
        if sha not in seen:
            seen.add(sha)
            if net < 1:                          # a nibble needs at least 1 line
                continue
            idx = gift_tier(net, has_pr=False)
            gifts.append({"net": net, "gross": net, "commits": 1, "pr": False,
                          "tier": idx, "name": GIFT_TIERS[idx][1],
                          "label": GIFT_TIERS[idx][2], "source": "commit", "sha": sha})
    return gifts, seen

def commit_gift_speech(gift):
    n = gift["net"]
    return {
        0: f"+{n} lines! a nibble, thanks!",
        1: f"+{n} lines! {gift['label']} *munch*",
        2: f"+{n} lines! {gift['label']}, nice!",
        3: f"+{n} lines?! {gift['label']}! you spoil me",
        4: f"+{n} lines!! {gift['label']}! *happy tears*",
    }.get(gift["tier"], f"+{n} lines, thank you!")

def hoard_summary(state):
    return state.get("hoard", {"count": 0, "net": 0, "by_tier": {}})

# --- PRs (via the GitHub CLI) -----------------------------------------------
def _gh(repo, *args):
    """Run gh inside `repo` so it resolves the GitHub repo from the remote."""
    try:
        r = subprocess.run(["gh", *args], cwd=repo, capture_output=True,
                           text=True, timeout=20)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""

def fetch_my_prs(repos):
    """PRs you authored (any state), across watched repos (via gh). Read-only."""
    out = []
    for repo in repos:
        raw = _gh(repo, "pr", "list", "--author", "@me", "--state", "all",
                  "--json", "number,additions,deletions,title,state,createdAt",
                  "--limit", "100")
        try:
            data = json.loads(raw) if raw else []
        except Exception:
            data = []
        for pr in data:
            out.append({"repo": repo, "number": pr.get("number", 0),
                        "additions": pr.get("additions", 0),
                        "deletions": pr.get("deletions", 0),
                        "title": pr.get("title", ""),
                        "state": pr.get("state", ""),
                        "createdAt": pr.get("createdAt", "")})
    return out

def _pr_date(s):
    """The PR's creation date in LOCAL time. gh returns UTC (…Z); taking the bare
    date string mis-buckets PRs opened in the evening (already tomorrow in UTC),
    so convert to the local timezone before pulling the date."""
    try:
        dt = datetime.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
        return dt.astimezone().date()
    except Exception:
        try:
            return datetime.date.fromisoformat((s or "")[:10])
        except Exception:
            return None

def pr_day_stats(prs):
    """From a list of your PRs: how many you opened today, their net lines, and
    your consecutive-day PR streak."""
    today = datetime.date.today()
    days, lines, count = set(), 0, 0
    for p in prs:
        d = _pr_date(p.get("createdAt"))
        if not d:
            continue
        days.add(d)
        if d == today:
            count += 1
            lines += max(0, p.get("additions", 0) - p.get("deletions", 0))
    n, d = 0, today
    if d not in days:                                # none today yet -> from yesterday
        d -= datetime.timedelta(days=1)
    while d in days:
        n += 1
        d -= datetime.timedelta(days=1)
    return {"prs": count, "lines": lines, "streak": n}

def pr_gift(pr):
    """A gift for a freshly-opened PR — sized by net diff, with the PR tier-bump
    so every PR is at least a small treat."""
    net = max(0, pr["additions"] - pr["deletions"])
    idx = gift_tier(net, has_pr=True)
    return {"repo": pr["repo"], "net": net, "gross": pr["additions"], "commits": 0,
            "pr": True, "tier": idx, "name": GIFT_TIERS[idx][1],
            "label": GIFT_TIERS[idx][2], "source": "pr",
            "number": pr["number"], "title": pr.get("title", "")}

def pr_speech(gift):
    """A simple acknowledgement when you open a PR (no tier / lines)."""
    n = gift.get("number")
    tag = f" #{n}" if n else ""
    return random.choice([
        f"you opened PR{tag}! nice work *",
        f"PR{tag} is up — proud of you!",
        f"you shipped PR{tag}! *cheers*",
    ])

TIER_GLYPH = ["·", "◦", "~", "✦", "◆"]   # hoard-pile marks: crumb, shell, fish, feast, treasure
TIER_EMOJI = ["🍪", "🐚", "🐟", "🍱", "💎"]  # the loose gift drop (clearer than the marks)

def hoard_glyphs(hoard, cap=10):
    """Up to `cap` glyphs for the pile, rarest tier first so treasures show.
    Crumbs (tier 0) are omitted — too small to be worth a spot in the pile."""
    by = hoard.get("by_tier", {})
    out = []
    for idx in range(len(GIFT_TIERS) - 1, 0, -1):       # 4..1, skipping tier 0 (crumb)
        for _ in range(by.get(GIFT_TIERS[idx][1], 0)):
            out.append((TIER_GLYPH[idx], idx))
            if len(out) >= cap:
                return out
    return out
