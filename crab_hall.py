#!/usr/bin/env python3
"""Claudagocchi v2.0 — Memory Lane.

Permadeath only means something if the crab you lost is still somewhere. This
renders every crab you've raised as a card: its own sprite, in its own final
form and palette, with what it did while it was here.

Output is static print, never animated, so it sidesteps the fixed-line-count
constraint the live window is bound by (see pixel_crab.animate).

Two kinds of card:
  * a GRADUATE — a crab you chose to retire, with honours. 🎓
  * a MEMORIAL — a crab that died. Shows its cause and how long it lived. ✝
and the living crab is always appended last, so the hall doubles as a summary of
the current run.
"""
import datetime

import crab_state as cs

CARD_CAP = 20                    # cards shown; older ones collapse into a footer


def _fmt_date(epoch):
    try:
        return datetime.datetime.fromtimestamp(epoch).strftime("%b %-d")
    except Exception:
        return "?"


def _htok(n):
    return cs._htok(n)


def _career_lines(career, hoard_count, hoard_glyphs, alive_health=None):
    """The three or four stat rows under a crab's name."""
    out = []
    if hoard_count:
        out.append(f"hoard  {hoard_glyphs}  {hoard_count} items")
    c, p = career.get("commits", 0), career.get("prs", 0)
    tok = career.get("tokens_mtok", 0.0)
    out.append(f"{c} commit{'' if c == 1 else 's'} · "
               f"{p} PR{'' if p == 1 else 's'} · {_htok(tok * 1e6)} tokens")
    gw, gp = career.get("games_won", 0), career.get("games_played", 0)
    bits = []
    if gp:
        bits.append(f"games {gw}/{gp}")
    if career.get("peak_streak"):
        bits.append(f"peak streak {career['peak_streak']}d")
    if career.get("neglect_hours", 0) >= 24:
        bits.append(f"{career['neglect_hours'] / 24:.0f}d hungry")
    if bits:
        out.append(" · ".join(bits))
    return out


def _sprite_for(stage_key, color, pc):
    """The crab's own shape, falling back to the adult if a form key is unknown
    (a state file written by a newer version, say)."""
    morph = pc.MORPHS.get(stage_key or "adult", pc.ADULT)
    return pc.crab_rows(color, morph, **pc.pose()), morph


def _card(entry, color, pc, alive=False, state=None):
    """One crab as (left_sprite_rows, right_text_rows)."""
    grad = entry.get("graduated")
    stage = entry.get("form") or entry.get("stage") or "adult"
    sprite, morph = _sprite_for(stage, color, pc)

    name = entry.get("name") or "?"
    gen = entry.get("gen", 1)
    form = (entry.get("form") or "").upper()
    tag = (f"(alive, {entry.get('age_days', 0):.0f}d)" if alive
           else form or (entry.get("stage") or "").upper())

    head = f"gen {gen} · {name}"
    text = [f"{head}{' ' * max(2, 34 - len(head) - len(tag))}{tag}"]

    if alive:
        health = (state or {}).get("health", 100.0)
        text.append(f"{stage} · health {cs._meter(health)}")
    else:
        verb = "raised" if grad else "lived"
        text.append(f"{verb} {entry.get('age_days', 0):.0f}d · "
                    f"{_fmt_date(entry.get('born', 0))} → {_fmt_date(entry.get('died', 0))}")

    glyphs = cs.hoard_glyphs({"by_tier": entry.get("by_tier", {})}, cap=8)
    text += _career_lines(entry.get("career", {}), entry.get("hoard_count", 0),
                          "".join(g for g, _ in glyphs))
    if not alive:
        text.append(f"🎓 graduated" if grad else f"✝ {entry.get('cause', 'unknown')}")
    return sprite, text, morph


def render(state, color=True, cap=CARD_CAP):
    """The whole hall as a printable string."""
    import pixel_crab as pc            # imported here: pixel_crab imports this module

    grave = list(state.get("graveyard", []))
    hidden = max(0, len(grave) - cap)
    shown = grave[hidden:]

    living = cs.memorial(state)        # the current crab, described the same way
    living["age_days"] = round(cs.age_days(state), 1)
    cards = [_card(e, color, pc) for e in shown]
    cards.append(_card(living, color, pc, alive=True, state=state))

    # Width: sprite gutter + the widest text row, inside a box -- but never wider
    # than the terminal, or the box wraps and stops looking like a box.
    sprite_col = max(m.w for _s, _t, m in cards) + 4
    room = max(pc._term_width() - 3, sprite_col + 20)
    text_w = min(max(pc._vlen(t) for _s, ts, _m in cards for t in ts),
                 room - sprite_col - 3)
    cards = [(s, [pc._clip(t, text_w) for t in ts], m) for s, ts, m in cards]
    inner = sprite_col + text_w + 3

    co = (lambda s: pc.fg(pc.CORAL) + s + pc.RESET) if color else (lambda s: s)
    title = "Memory Lane"
    rows = [co("╭─ " + title + " " + "─" * max(inner - 3 - len(title), 0) + "╮")]
    bar = co("│")

    def line(s="", visible=None):
        """A boxed row. `visible` is the row's true column count -- it must be
        passed for anything containing a sprite, because those carry ANSI escapes
        that a naive width measurement would count as printable characters."""
        w = pc._vlen(s) if visible is None else visible
        return bar + s + " " * max(inner - w, 0) + bar

    rows.append(line())
    for sprite, text, morph in cards:
        for i in range(max(len(sprite), len(text))):
            left = sprite[i] if i < len(sprite) else ""
            lw = morph.w if i < len(sprite) else 0
            pad = " " * max(sprite_col - lw - 2, 0)
            right = text[i] if i < len(text) else ""
            rows.append(line("  " + left + pad + right,
                             visible=2 + lw + len(pad) + pc._vlen(right)))
        rows.append(line())
    rows.append(co("╰" + "─" * inner + "╯"))

    grads = [g for g in grave if g.get("graduated")]
    lost = [g for g in grave if not g.get("graduated")]
    total = len(grave) + 1
    longest = max([g.get("age_days", 0) for g in grave] + [cs.age_days(state)])
    foot = f"  {total} crab{'' if total == 1 else 's'}"
    if grads:
        foot += f" · {len(grads)} graduated"
    if lost:
        foot += f" · {len(lost)} lost"
    foot += f" · longest life {longest:.0f}d"
    if hidden:
        foot += f"  ·  … and {hidden} earlier"
    rows.append(foot)
    return "\n".join(rows)
