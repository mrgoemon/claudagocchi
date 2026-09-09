#!/usr/bin/env python3
"""Claudagocchi — commands typed into the chat line.

The window already has a text input at the bottom. This turns it into a command
line as well as a chat box: anything matching a command below runs locally and
instantly; anything else falls through to Claude as conversation, exactly as
before. Commands work with no API key, because they never leave the machine.

`handle()` returns None for "not a command, treat it as chat", or a dict saying
what the render loop should do. There are only three shapes of answer, because
the window's height is fixed at startup and cannot grow a line to make room:

    {"say":  str}          one line in the speech bubble
    {"page": str}          take over the screen until a key is pressed
    {"game": (name, line)} summon a minigame
    {"react": name}        play a scripted animation ("celebrate" / "stretch")

plus {"save": True} when state changed and {"quit": True} to exit.

A command may combine them, e.g. `pet` returns a say + a react + a save.
"""
import time

import crab_state as cs
import crab_games as cg
import crab_hall
import crab_sessions as csess
import crab_tokens as ctok

PET_COOLDOWN = 12.0        # seconds; petting is affection, not a happiness faucet

HELP = """
  Claudagocchi — type these into the chat line

  looking at things
    stats                 vitals, age and stage
    stage                 what it is now, and what's next
    hoard                 everything you've gifted it
    hall                  Memory Lane: every crab you've raised
    sessions              your other Claude Code / Codex sessions
    tokens                your Claude Code token usage

  doing things
    pet                   say hello properly
    play [game]           a minigame now  (dino pong snake crossing
                          invaders breakout squash)
    name <new name>       rename your crab
    alerts on|quiet|off   how loudly to flag a session that needs you

  serious
    graduate              retire this crab with honours and start fresh
                          (asks you to confirm with its name)

  anything else you type is said to the crab, if chat is on.
  help  ·  quit
"""

GAME_WORDS = ("game", "minigame")
GAME_VERBS = ("play", "make", "code", "start")


def _wants_game(cmd):
    """The original game matcher, kept verbatim so `play snake` etc. still work."""
    if cmd in ("game", "play", "minigame", "play a game", "make a game",
               "code a game", "play game") or cmd in cg.GAMES:
        return True
    parts = cmd.split()
    return bool(parts) and parts[0] in GAME_VERBS and (
        any(g in cmd for g in cg.GAMES) or "game" in cmd)


def _meter_line(state):
    belly = 100 - state["hunger"]
    return (f"mood {cs._meter(state['happiness'])} "
            f"energy {cs._meter(state['energy'])} "
            f"belly {cs._meter(belly)} "
            f"health {cs._meter(state.get('health', 100))}")


def _article(word):
    return "an" if word[:1].lower() in "aeiou" else "a"


def _stage_line(state):
    stage = cs.life_stage(state)
    age = cs.age_days(state)
    if stage in cs.ADULT_FORMS:
        return f"{state['name']}, {_article(stage)} {stage}, {age:.0f} days old. fully grown."
    gates = [(g, n) for g, n in cs.LIFE_STAGES if g > age] + [(cs.FORM_AGE_DAYS, "final form")]
    nxt_at, nxt = min(gates, key=lambda t: t[0])
    left = nxt_at - age
    when = f"{left:.1f} days" if left >= 1 else f"{left * 24:.0f} hours"
    return (f"{state['name']}, {_article(stage)} {stage}, {age:.1f} days old. "
            f"{nxt} in {when}.")


def _hoard_line(state):
    h = cs.hoard_summary(state)
    if not h.get("count"):
        return "nothing in the hoard yet — commit something!"
    pile = "".join(g for g, _ in cs.hoard_glyphs(h, cap=8))
    return f"{h['count']} gifts · {h['net']} net lines  {pile}"


def _sessions_page(sess):
    if not sess:
        return "  still looking...\n"
    out = ["", "  your other agent sessions", ""]
    for w in sess.get("waiting", []):
        out.append(f"    ● {w['name']:<30} {w.get('waiting_for') or 'waiting'}")
    for s in sess.get("all", []):
        if s["status"] != csess.WAITING:
            out.append(f"    ○ {s['name']:<30} {s['status']}"
                       f"{' ≈' if s.get('approx') else ''}")
    if len(out) == 3:
        out.append("    (none found)")
    out.append("")
    return "\n".join(out)


def handle(text, ctx):
    """Interpret one submitted line. ctx: {state, cfg, sess, color, pet_at}."""
    raw = text.strip()
    cmd = raw.lower()
    if not cmd:
        return None
    state, cfg = ctx["state"], ctx["cfg"]
    head = cmd.split()[0]
    rest = raw[len(head):].strip()

    if cmd in ("help", "?", "commands", "h"):
        return {"page": HELP}

    if cmd in ("quit", "exit", "bye", ":q"):
        return {"say": "see you soon!", "quit": True}

    if _wants_game(cmd):                       # kept ahead of everything else
        named = [g for g in cg.GAMES if g in cmd]
        import random
        return {"game": (named[0] if named else random.choice(cg.GAMES),
                         "you got it, let's play!")}

    if cmd in ("stats", "status", "vitals"):
        return {"say": _meter_line(state)}

    if cmd in ("stage", "age", "grow"):
        return {"say": _stage_line(state)}

    if cmd in ("hoard", "gifts"):
        return {"say": _hoard_line(state)}

    if cmd in ("hall", "memory", "memory lane", "graveyard", "crabs"):
        return {"page": "\n" + crab_hall.render(state, ctx.get("color", True))}

    if cmd in ("sessions", "who", "waiting"):
        return {"page": _sessions_page(ctx.get("sess"))}

    if cmd in ("tokens", "usage"):
        try:
            return {"page": "\n" + ctok.report()}
        except Exception:
            return {"say": "couldn't read the token logs just now"}

    if cmd in ("pet", "pat", "hi", "hello", "hey", "good crab"):
        now = time.time()
        if now - ctx.get("pet_at", 0) < PET_COOLDOWN:
            return {"say": "(happily) you just did that"}
        state["happiness"] = min(100.0, state["happiness"] + 3)
        return {"say": "*leans into it*", "react": "celebrate",
                "save": True, "pet_at": now}

    if head in ("name", "rename", "call") and rest:
        old = state.get("name")
        state["name"] = rest[:20]
        return {"say": f"{old} is now {state['name']}!", "save": True}
    if head in ("name", "rename", "call"):
        return {"say": f"i'm {state.get('name')} — say 'name <something>' to change it"}

    if head == "alerts":
        if rest in ("on", "quiet", "off"):
            cfg["alerts"] = rest
            cs.save_config(cfg)
            return {"say": {"on": "alerts on — i'll chirp when a session needs you",
                            "quiet": "alerts quiet — i'll wave, but no sound",
                            "off": "alerts off — i'll stop watching"}[rest]}
        return {"say": f"alerts are {cfg.get('alerts', 'on')} — try 'alerts on|quiet|off'"}

    if head in ("graduate", "retire"):
        ok, why = cs.can_graduate(state)
        if not ok:
            return {"say": why}
        # Destructive and irreversible from the crab's side, so it takes the name
        # as confirmation -- the same bar the CLI sets.
        if rest.lower() == (state.get("name") or "").lower():
            cs.backup_state()
            m = cs.graduate(state)
            return {"say": f"🎓 {m['name']} graduated. hello, {state['name']}!",
                    "react": "celebrate", "save": True}
        return {"say": f"to retire {state['name']}, type: graduate {state['name']}"}

    if cmd in ("stretch", "break"):
        cs.take_break(state)
        return {"say": "good idea — stretch with me", "react": "stretch", "save": True}

    return None                                # not a command: say it to the crab
