#!/usr/bin/env python3
"""Rendering regression harness.

The crab's window is redrawn in place by moving the cursor up a fixed number of
lines, so two properties must hold forever:

  1. every frame has the SAME line count          (else the redraw tears)
  2. every row has the SAME visible width         (else the right border jags)

and one property must hold across the morph refactor:

  3. the `adult` morph renders byte-identically to the pre-refactor crab

Usage:
    COLUMNS=100 python3 goldens.py capture      # write goldens.json
    COLUMNS=100 python3 goldens.py check        # compare against it
    COLUMNS=100 python3 goldens.py sweep        # anti-tear/anti-jag sweep

COLUMNS is pinned because shutil.get_terminal_size() reads it, which is what
makes _term_width() deterministic.
"""
import hashlib
import json
import os
import pathlib
import re
import sys

import pixel_crab as p

GOLDENS = pathlib.Path(__file__).with_name("goldens.json")
WIDTH_ENV = "100"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s):
    return _ANSI.sub("", s)


def _morphs():
    """Every morph to exercise, as (label, kwargs-for-render). Pre-refactor there
    is no morph table, so fall back to the single implicit adult sprite."""
    table = getattr(p, "MORPHS", None)
    if not table:
        return [("adult", {})]
    return [(k, {"morph": m}) for k, m in sorted(table.items())]


def _stage_h():
    return getattr(p, "STAGE_H", 5)


# The pose vocabulary v1.0 shipped with. The compat contract is that the adult
# crab renders byte-identically in THESE poses; v2.0 additions (clasp, tiptoe,
# sideL, ...) are new art, not regressions, so hashing every pose in the table
# would make this golden fire every time a pose is added. Pinning the list keeps
# it a real regression test instead of a change detector.
V1_HANDS = ("down", "up", "walkA", "walkB")
V1_LEGS = ("rest", "stepA", "stepB", "squat", "tuck")


def sprite_hash():
    """The v1.0 pose set x color on/off, at the adult morph. Comparable across
    the morph refactor, and stable as new poses are added."""
    h = hashlib.sha256()
    for color in (True, False):
        for eye_open in (True, False):
            for hand in V1_HANDS:
                for leg in V1_LEGS:
                    for gaze in (-1, 0, 1):
                        rows = p.crab_rows(color, **p.pose(eye_open, hand, leg, gaze))
                        h.update(("|".join(rows) + "\n").encode())
    return h.hexdigest()


def missing_poses():
    """v1.0 poses that have gone missing from the table entirely."""
    return ([h for h in V1_HANDS if h not in p.HAND_POSES]
            + [l for l in V1_LEGS if l not in p.LEG_POSES])


def window_hash():
    """24 render_window variants: 3 vertical positions x hoard/drop/emote on-off,
    doubled over color. Uses the adult sprite only, so it is comparable across the
    refactor. Recorded alongside the stat count it was captured at -- adding a stat
    line legitimately changes this hash and requires a re-capture, not a bugfix."""
    h = hashlib.sha256()
    hoard = [("~", 2), ("✦", 3)]
    drop = (40, "\U0001f41f", 2)
    for color in (True, False):
        for y in (0, 1, 2):
            for extras in (0, 1, 2, 3):
                s = p.render_window(
                    color,
                    stage_h=5,
                    x=10,
                    y=y,
                    frame=p.pose(True, "up", "tuck", 1),
                    speech="hello",
                    stats=list("abcd"),
                    hoard=hoard if extras & 1 else None,
                    drop=drop if extras & 2 else None,
                    emote="*" if extras == 3 else None,
                )
                h.update((s + "\n").encode())
    return h.hexdigest()


def sweep():
    """Assert the two redraw invariants for every morph, vertical position,
    horizontal position (including deliberately out-of-range) and leg pose."""
    inner = max(int(WIDTH_ENV) - 3, getattr(p, "MAX_MORPH_W", 9) + 4)
    stage_h = _stage_h()
    expect_lines = None
    bad_width, bad_lines = [], []

    for key, kw in _morphs():
        morph = kw.get("morph")
        w = morph.w if morph else 9
        h = morph.h if morph else 3
        ground = stage_h - h
        for y in (ground, max(ground - 1, 0), max(ground - 2, 0)):
            for x in (-5, 0, 50, inner - w, inner + 9):
                for leg in p.LEG_POSES:
                    # The title path is measured with len(), not _vlen (see
                    # render_window), so sweep a garbled title too: a glyph
                    # whose two measurements disagree jags the top border and
                    # nothing else here would notice.
                    title = (None if x == -5
                             else p._infest(p.INTRO_TITLE, p.TITLE, 0.4,
                                            p._infest_schedule(inner, 0.0, 0.45, 0.22)))
                    s = p.render_window(
                        True, stage_h=stage_h, x=x, y=y, frame=p.pose(leg=leg),
                        speech="hi", stats=list("abcd"), emote="*", title=title, **kw)
                    lines = s.count("\n") + 1
                    if expect_lines is None:
                        expect_lines = lines
                    elif lines != expect_lines:
                        bad_lines.append((key, x, y, leg, lines))
                    for i, ln in enumerate(s.split("\n")):
                        if p._vlen(_strip(ln)) != inner + 2:
                            bad_width.append((key, x, y, leg, i, p._vlen(_strip(ln))))

    print(f"morphs swept   : {[k for k, _ in _morphs()]}")
    print(f"line count     : {expect_lines} (must be identical everywhere)")
    print(f"expected width : {inner + 2}")
    print(f"bad line counts: {len(bad_lines)}")
    for b in bad_lines[:10]:
        print("   ", b)
    print(f"bad row widths : {len(bad_width)}")
    for b in bad_width[:10]:
        print("   ", b)
    return not (bad_lines or bad_width)


def snapshot():
    return {
        "columns": WIDTH_ENV,
        "sprite": sprite_hash(),
        "window": window_hash(),
        "window_stats": len(p.STATS),   # what `window` was captured against
        "window_lines": p.render_window(True, stage_h=5).count("\n") + 1,
        "adult_rows_plain": p.crab_rows(False),
    }


def main(argv):
    if os.environ.get("COLUMNS") != WIDTH_ENV:
        sys.exit(f"run with COLUMNS={WIDTH_ENV} so _term_width() is deterministic")
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "capture":
        GOLDENS.write_text(json.dumps(snapshot(), indent=2) + "\n")
        print(f"wrote {GOLDENS}")
        print(json.dumps(snapshot(), indent=2))
        return 0
    if cmd == "sweep":
        return 0 if sweep() else 1
    if cmd == "check":
        want = json.loads(GOLDENS.read_text())
        got = snapshot()
        ok = True
        gone = missing_poses()
        if gone:
            ok = False
            print(f"FAIL v1.0 poses removed from the table: {gone}")
        for k in ("sprite", "window", "window_lines", "adult_rows_plain"):
            same = want[k] == got[k]
            ok &= same
            note = ""
            if k == "window" and not same and want.get("window_stats") != got.get("window_stats"):
                note = "  (stat count changed -- re-capture, not a regression)"
            print(f"{'OK  ' if same else 'FAIL'} {k}{note}")
            if not same:
                print(f"      want {want[k]}")
                print(f"      got  {got[k]}")
        return 0 if ok else 1
    sys.exit(f"unknown command {cmd!r}; use capture|check|sweep")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
