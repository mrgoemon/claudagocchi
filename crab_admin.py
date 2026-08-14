#!/usr/bin/env python3
"""Claudagocchi admin mode — see every situation on demand.

Most of what makes the crab a pet happens on a scale of days: it hatches after
six hours, evolves over a week, starves over five. That is right for living with,
and useless for looking at. Admin mode stages each of those moments so you can
watch one now.

    crab --admin              list the scenarios
    crab --admin death        watch one

Two guarantees, because this exists to trigger destructive things:

  * It NEVER touches your real crab. Every scenario runs against a sandbox save
    at ~/.claude-crab/admin/, swapped in by `_sandbox()` before anything loads.
    Your ~/.claude-crab/state.json is not read and not written.
  * It NEVER touches your real sessions. The one scenario that needs a session
    waiting on you injects a canned reading instead of reading ~/.claude/.

Scenarios that depend on elapsed time wind up `crab_state.TIME_SCALE`, so an hour
of crab-clock passes in a second of yours. That is the same code path the real
crab uses -- nothing is faked except the rate.
"""
import os
import shutil
import sys
import time
import pathlib

import crab_state as cs
import crab_sessions as csess
import crab_hall

SANDBOX = pathlib.Path.home() / ".claude-crab" / "admin"

# name -> (one-line description, seconds it runs)
SCENARIOS = {
    "egg":       ("a newly laid egg, before it hatches", 20),
    "hatch":     ("an egg hatching into a hatchling", 30),
    "evolve":    ("growing through every stage, back to back", 75),
    "forms":     ("each of the four adult forms in turn", 60),
    "starve":    ("healthy → hungry → sick → dying, sped up", 45),
    "death":     ("starving to death, the memorial, and the next egg", 50),
    "graduate":  ("retiring a crab with honours (non-interactive)", 0),
    "alert":     ("a session blocked on you, with the crab reacting", 25),
    "gift":      ("a treasure-tier gift arriving", 25),
    "hall":      ("Memory Lane, with a full history", 0),
    "sheet":     ("every life stage in every pose", 0),
}


# --- sandbox -----------------------------------------------------------------
def _sandbox(fresh=True):
    """Point crab_state at the admin save. Called before any state is loaded, so
    the real ~/.claude-crab/state.json is never opened."""
    if fresh and SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX.mkdir(parents=True, exist_ok=True)
    cs.DIR = SANDBOX
    cs.STATE = SANDBOX / "state.json"
    cs.CONFIG = SANDBOX / "config.json"
    cs.PRE_DEATH = SANDBOX / "state.pre-death.json"
    return SANDBOX


def _state(days_old=0.0, **over):
    """A sandbox crab of a given age, plus any overrides."""
    s = cs.default_state()
    s["born"] = time.time() - days_old * 86400
    s.setdefault("career", cs.default_career())
    for k, v in over.items():
        if k == "career":
            s["career"].update(v)
        else:
            s[k] = v
    cs.save_state(s)
    return s


def _career(**kw):
    c = cs.default_career()
    c.update(kw)
    return c


def _banner(scenario, note=""):
    import pixel_crab as pc
    pc.TITLE = f"Claudagocchi · ADMIN · {scenario}"
    print(f"\n  ── admin: {scenario} ──  {SCENARIOS[scenario][0]}")
    if note:
        print(f"     {note}")
    print(f"     sandbox: {SANDBOX}   (your real crab is untouched)")
    print("     Ctrl-C to stop\n")
    time.sleep(1.2)


def _run(seconds, color=True):
    """Run the real animation loop for a while, then return."""
    import pixel_crab as pc
    import threading
    stop = threading.Timer(seconds, lambda: os.kill(os.getpid(), 2))  # SIGINT
    stop.daemon = True
    stop.start()
    try:
        pc.animate(color)
    except KeyboardInterrupt:
        pass
    finally:
        stop.cancel()


# --- scenarios ---------------------------------------------------------------
def sc_egg(color):
    _sandbox()
    _state(days_old=0.0, name="Roe", hatched=False)
    _banner("egg", "age 0 · not yet fed, so it stays an egg")
    _run(SCENARIOS["egg"][1], color)


def sc_hatch(color):
    _sandbox()
    _state(days_old=0.24, name="Sprat", hatched=False, hunger=60.0)
    cs.TIME_SCALE = 400.0          # ~6h of crab-clock per real minute
    _banner("hatch", "an egg just under the gate; feeding it cracks it open")
    _run(SCENARIOS["hatch"][1], color)


def sc_evolve(color):
    """Walk the whole ladder. TIME_SCALE does the ageing; `born` is rewound so
    each gate is only seconds away."""
    _sandbox()
    _state(days_old=0.0, name="Molt", hatched=True,
           career=_career(prs=9, commits=70))       # -> architect at the end
    cs.TIME_SCALE = 1.0
    _banner("evolve", "egg → hatchling → juvenile → adult → architect")
    import pixel_crab as pc
    import threading
    # Nudge `born` backwards on a timer so each stage gate arrives a few seconds
    # apart. The crab's own evolution seam does the rest.
    gates = [g for g, _ in cs.LIFE_STAGES if g > 0] + [cs.FORM_AGE_DAYS]
    def _age():
        for g in gates:
            time.sleep(13)
            s = cs.load_state()
            s["born"] = time.time() - (g + 0.01) * 86400
            s["hatched"] = True
            cs.save_state(s)
    threading.Thread(target=_age, daemon=True).start()
    _run(SCENARIOS["evolve"][1], color)


def sc_forms(color):
    import pixel_crab as pc
    _sandbox()
    each = SCENARIOS["forms"][1] // len(cs.ADULT_FORMS)
    for form in cs.ADULT_FORMS:
        _sandbox(fresh=False)
        _state(days_old=9.0, name=form.title(), hatched=True, form=form,
               hoard={"count": 12, "net": 3000, "by_tier": {"fish": 4, "shell": 8}})
        pc.TITLE = f"Claudagocchi · ADMIN · {form}"
        print(f"\n  ── {form.upper()} ──")
        time.sleep(0.8)
        _run(each, color)


def sc_starve(color):
    _sandbox()
    _state(days_old=5.0, name="Husk", hatched=True, hunger=88.0, health=100.0,
           hoard={"count": 8, "net": 900, "by_tier": {"shell": 8}})
    # Vitals only advance on the 4s poll, so the useful unit is health-per-poll:
    # scale * 4/3600 crab-hours per poll, times HEALTH_DRAIN_PER_HR. At 6000 that
    # is ~6.7 health a poll, so the full 100 -> dying arc lands inside the run.
    cs.TIME_SCALE = 6000.0
    _banner("starve", "clock at 6000x — watch belly empty, then health follow it down")
    _run(SCENARIOS["starve"][1], color)


def sc_death(color):
    _sandbox()
    _state(days_old=11.0, name="Clawde", hatched=True, form="architect",
           hunger=100.0, health=2.5,
           hoard={"count": 34, "net": 8800, "by_tier": {"feast": 1, "fish": 6, "shell": 27}},
           career=_career(prs=7, commits=58, tokens_mtok=430.0,
                          games_played=19, games_won=11, peak_streak=8))
    cs.TIME_SCALE = 1200.0
    _banner("death", "an architect with 34 gifts, moments from starving")
    _run(SCENARIOS["death"][1], color)
    print("\n  ── what Memory Lane holds now ──\n")
    print(crab_hall.render(cs.load_state(), color))


def sc_graduate(color):
    _sandbox()
    s = _state(days_old=9.0, name="Shelly", hatched=True, form="grinder",
               hoard={"count": 21, "net": 5200, "by_tier": {"fish": 5, "shell": 16}},
               career=_career(prs=3, commits=37, tokens_mtok=980.0,
                              games_played=8, games_won=5, peak_streak=6))
    print(f"\n  ── admin: graduate ──  {SCENARIOS['graduate'][0]}")
    print(f"     sandbox: {SANDBOX}   (your real crab is untouched)\n")
    ok, _why = cs.can_graduate(s)
    print(f"  eligible: {ok}  ({cs.life_stage(s)}, {cs.age_days(s):.0f} days old)")
    m = cs.graduate(s)
    cs.save_state(s)
    print(f"  🎓 {m['name']} graduated after {m['age_days']:.0f} days as a {m['form']}")
    print(f"     successor: {s['name']} (gen {s['generation']}), hoard reset to "
          f"{cs.hoard_summary(s)['count']}\n")

    # The not-yet-eligible case -- the one you actually hit. Built in memory only:
    # saving it here would overwrite the graveyard we just wrote.
    young = cs.default_state()
    young["born"] = time.time() - 2 * 86400
    young["name"], young["hatched"] = "Pip", True
    ok2, why2 = cs.can_graduate(young)
    print(f"  a 2-day-old crab: eligible={ok2}")
    print(f"     {why2}\n")
    print(crab_hall.render(cs.load_state(), color))


def sc_alert(color):
    _sandbox()
    _state(days_old=4.0, name="Nipper", hatched=True)
    # Injected rather than read: admin mode must not depend on you happening to
    # have a session blocked right now, and must not touch your real ones.
    csess.DEMO = {
        "waiting": [{"source": "claude", "id": "demo-1", "pid": None,
                     "name": "loan-search", "cwd": "/Users/you/loan-search",
                     "status": csess.WAITING, "raw_status": "waiting",
                     "waiting_for": "permission prompt", "since": time.time(),
                     "approx": False}],
        "working": 2, "idle": 1, "all": [],
    }
    _banner("alert", "a fake session is blocked — watch the bottom line and the crab")
    _run(SCENARIOS["alert"][1], color)
    csess.DEMO = None


def sc_gift(color):
    _sandbox()
    _state(days_old=4.0, name="Chowder", hatched=True)
    _banner("gift", "a treasure lands on the far side and gets walked over to")
    import pixel_crab as pc
    orig = cs.detect_commit_gifts
    fired = {"done": False}
    def _fake(repos, author, seen):
        if seen is None:
            return [], set()
        if fired["done"]:
            return [], seen
        fired["done"] = True
        return [{"net": 4200, "gross": 4200, "commits": 1, "pr": False, "tier": 4,
                 "name": "treasure", "label": "treasure", "source": "commit",
                 "sha": "demo"}], seen
    cs.detect_commit_gifts = _fake
    try:
        _run(SCENARIOS["gift"][1], color)
    finally:
        cs.detect_commit_gifts = orig


def sc_hall(color):
    _sandbox()
    now = time.time()
    DAY = 86400
    def grave(gen, name, form, days, ago, hoard, tiers, career, grad):
        return {"gen": gen, "name": name, "born": now - ago * DAY,
                "died": now - (ago - days) * DAY, "age_days": days,
                "stage": form, "form": form, "hoard_count": hoard,
                "hoard_net": hoard * 240, "by_tier": tiers, "career": career,
                "cause": "graduated" if grad else "starvation",
                "version": cs.VERSION, "graduated": grad}
    _state(days_old=3.0, name="Pebble", hatched=True, health=76.0, generation=4,
           hoard={"count": 5, "net": 700, "by_tier": {"shell": 5}},
           career=_career(prs=1, commits=9, tokens_mtok=64.0, games_played=3,
                          games_won=2, peak_streak=3),
           graveyard=[
               grave(1, "Clawde", "architect", 21, 40, 41,
                     {"feast": 1, "fish": 8, "shell": 32},
                     _career(prs=9, commits=88, tokens_mtok=610.0, games_played=24,
                             games_won=15, peak_streak=11), True),
               grave(2, "Shelly", "grinder", 8, 17, 19, {"fish": 4, "shell": 15},
                     _career(prs=2, commits=26, tokens_mtok=1100.0, games_played=6,
                             games_won=3, peak_streak=5, neglect_hours=140.0), False),
               grave(3, "Barnacle", "feral", 5, 8, 3, {"shell": 3},
                     _career(prs=0, commits=4, tokens_mtok=18.0, neglect_hours=118.0,
                             peak_streak=1), False),
           ])
    print()
    print(crab_hall.render(cs.load_state(), color))


def sc_sheet(color):
    import pixel_crab as pc
    for key, m in pc.MORPHS.items():
        print(f"\n── {key}  {m.w}w × {m.h}h · {m.legs_per_side * 2} legs")
        for leg in pc.LEG_POSES:
            print(f"   {leg}")
            for row in pc.crab_rows(color, m, **pc.pose(leg=leg)):
                print("     " + row)


RUNNERS = {k: globals()[f"sc_{k}"] for k in SCENARIOS}


def _list():
    print("\n  Claudagocchi admin — every situation, on demand\n")
    for name, (desc, secs) in SCENARIOS.items():
        dur = f"~{secs}s" if secs else "instant"
        print(f"    crab --admin {name:<9} {dur:>8}   {desc}")
    print("\n  Everything runs in a sandbox at ~/.claude-crab/admin/.")
    print("  Your real crab is never read or written.\n")
    return 0


def main(scenario=None, color=True):
    if not scenario:
        return _list()
    if scenario not in RUNNERS:
        print(f"unknown scenario {scenario!r}")
        print("try:", ", ".join(SCENARIOS))
        return 1
    try:
        RUNNERS[scenario](color)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
