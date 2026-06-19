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
import json
import time
import random
import datetime
import subprocess
import pathlib

DIR = pathlib.Path.home() / ".claude-crab"
STATE = DIR / "state.json"
CONFIG = DIR / "config.json"

# --- tuning knobs (per hour unless noted) -----------------------------------
HUNGER_PER_HR = 30.0      # belly empties (0 = full, 100 = starving); visible over a session
COUPLE_PER_HR = 0.6       # how fast energy & mood drift toward the current belly level
FEED_PER_COMMIT  = 22     # hunger removed per new commit (refills the belly)
HAPPY_PER_COMMIT = 12
BREAK_AFTER_MIN = 50      # nudge to stretch after this much unbroken time
IDLE_RESET_MIN = 90       # a gap this long starts a fresh work session
MARATHON_MIN = 180        # session longer than this -> "tired"

def _now(): return time.time()
def _clamp(v, lo=0.0, hi=100.0): return max(lo, min(hi, v))

# --- persistence ------------------------------------------------------------
def _load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return dict(default)

def _save(path, data):
    DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))

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

def default_state():
    n = _now()
    return {"born": n, "last_seen": n, "hunger": 20.0, "energy": 80.0,
            "happiness": 70.0, "session_start": n, "last_break": n,
            "seen": {}, "quests_date": None, "quests_done": [], "break_taken": 0}

def load_state():
    s = _load(STATE, default_state())
    for k, v in default_state().items():
        s.setdefault(k, v)
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
    hrs = max(0.0, (now - state["last_seen"]) / 3600.0)

    state["hunger"] = min(100.0, state["hunger"] + HUNGER_PER_HR * hrs)   # belly empties
    belly = 100.0 - state["hunger"]
    pull = min(1.0, COUPLE_PER_HR * hrs)                  # energy & mood drift toward belly:
    state["energy"]    = _clamp(state["energy"] + (belly - state["energy"]) * pull)      # full
    state["happiness"] = _clamp(state["happiness"] + (belly - state["happiness"]) * pull)  # -> up

    if (now - state["last_seen"]) / 60.0 > IDLE_RESET_MIN:   # came back after a break
        state["session_start"] = now
        state["last_break"] = now

    state["last_seen"] = now
    return []                              # commits now feed via per-commit gifts

# --- derived: mood, quests, break -------------------------------------------
def day_mood(state, today, now=None):
    now = now or _now()
    session_min = (now - state["session_start"]) / 60.0
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

def stat_lines(state, quests, today, pr_stats, strk):
    """today = your-authored commit stats (lines); pr_stats = PRs opened by your
    account; strk = your commit-day streak."""
    belly = 100 - state["hunger"]
    l1 = f"mood {_meter(state['happiness'])}  energy {_meter(state['energy'])}  belly {_meter(belly)}"
    n = pr_stats.get("prs", 0)
    prlabel = f"{n} PR" if n == 1 else f"{n} PRs"
    sd = f"{strk}-day streak" if strk else "start a streak!"
    l2 = f"today  {today.get('added', 0)} lines  ·  {prlabel}  ·  {sd}"
    nxt = next((q for q in quests if not q["done"]), None)
    if nxt:
        l3 = f"quest  {nxt['label']}  {_meter(nxt['prog']/nxt['goal']*100, 3)} ({nxt['prog']}/{nxt['goal']})"
    else:
        l3 = "all quests done today!  (｡･ω･｡)"
    return [l1, l2, l3]

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
            idx = gift_tier(net, has_pr=False)
            gifts.append({"net": net, "gross": net, "commits": 1, "pr": False,
                          "tier": idx, "name": GIFT_TIERS[idx][1],
                          "label": GIFT_TIERS[idx][2], "source": "commit", "sha": sha})
    return gifts, seen

def commit_gift_speech(gift):
    n = gift["net"]
    return {
        0: f"+{n} lines — a nibble, thanks!",
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
