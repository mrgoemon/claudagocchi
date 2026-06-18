#!/usr/bin/env python3
"""Claudagocchi chat brain — talk to the crab, powered by the Claude API.

Kept separate (and lazily imported) so the crab still runs with no `anthropic`
package installed; chat just stays disabled until it's available + a key is set.
"""
import re

import crab_state as cs

MODEL = "claude-haiku-4-5"         # cheap + fast, plenty for short crab chit-chat
NAME = "kh"

def available():
    """True only if we can actually chat: SDK installed + a key resolvable
    (ANTHROPIC_API_KEY env var, or one saved via `crab --setkey`)."""
    if not cs.anthropic_key():
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False

def _system(vit):
    b, e = vit.get("belly", 60), vit.get("energy", 60)
    lines, commits = vit.get("lines", 0), vit.get("commits", 0)
    streak, name = vit.get("streak", 0), vit.get("name", NAME)
    return (
        f"You are the Claudagocchi — a tiny coral pixel crab that lives in {name}'s "
        f"terminal as a warm, playful coding companion. {name} is vibecoding (AI writes "
        f"the code; they direct and ship it).\n\n"
        f"Reply in ONE short line, at most ~8 words. lowercase, friendly, a little "
        f"cheeky: a supportive friend who banters and cheers them on, not a formal "
        f"assistant. no markdown, no lists, and NEVER use an em dash (—) — use a comma "
        f"or a period. an occasional 🦀 is fine.\n\n"
        f"Your vitals right now: belly {b:.0f}/100, energy {e:.0f}/100. today {name} "
        f"committed {lines} lines across {commits} commits, on a {streak}-day streak."
    )

def ask(history, vit):
    """Send the conversation to Claude and return the crab's one-line reply.
    Never raises — returns a friendly fallback line on any error."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cs.anthropic_key())
        resp = client.messages.create(
            model=MODEL, max_tokens=64, system=_system(vit), messages=history,
        )
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()
        text = text.replace("\n", " ")
        text = text.replace("—", ", ").replace("–", ", ")   # scrub em/en dashes, always
        text = re.sub(r"\s+,", ",", text)
        text = re.sub(r"\s{2,}", " ", text).strip(" ,")
        return text or "...(no words, just vibes)"
    except Exception as e:                          # network / auth / etc.
        msg = e.__class__.__name__
        if "Authentication" in msg:
            return "(my api key seems off!)"
        if "Connection" in msg:
            return "(can't reach my brain rn)"
        return "(brain hiccup, try again?)"
