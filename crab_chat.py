#!/usr/bin/env python3
"""Claudagocchi chat brain — talk to the crab, powered by the Claude API.

Kept separate (and lazily imported) so the crab still runs with no `anthropic`
package installed; chat just stays disabled until it's available + a key is set.
"""
import re
import threading

import crab_state as cs

MODEL = "claude-haiku-4-5"         # cheap + fast, plenty for short crab chit-chat
NAME = "kh"

# Both calls run on daemon threads inside the animation loop, so a hung request
# is invisible: the `except` can't fire until it resolves and the crab just never
# answers. Fail fast instead so the fallback line always gets a chance.
ASK_TIMEOUT = 18.0                 # a reply is one short line; 18s is generous
DIRECT_TIMEOUT = 10.0              # the director only returns a tiny json blob
MAX_RETRIES = 1                    # worst case is timeout x (MAX_RETRIES + 1)

_client = None                     # built lazily, then reused across calls
_client_key = None
_client_lock = threading.Lock()

def _client_for(timeout):
    """The shared Anthropic client, with a per-call timeout. None if we can't
    build one (no key, no SDK). Rebuilt if the saved key changed under us."""
    global _client, _client_key
    key = cs.anthropic_key()
    if not key:
        return None
    import anthropic
    with _client_lock:
        if _client is None or _client_key != key:
            _client = anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES)
            _client_key = key
        client = _client
    return client.with_options(timeout=timeout)   # cheap copy, same connection pool

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

def direct(vit, games):
    """The AI director: decide whether the crab should 'code' and play a
    minigame right now, and which one. Returns {"game": name, "line": quip} when
    it's go-time, else None. Kept rare by the prompt. Never raises."""
    try:
        import json
        client = _client_for(DIRECT_TIMEOUT)
        if client is None:
            return None
        system = (
            f"You direct a tiny terminal crab pet. fairly often, as a treat, it "
            f"'codes' and then watches a small self-playing minigame. decide if RIGHT "
            f"NOW is a good moment for that. lean toward play=true, a game every few "
            f"minutes is great — only choose play=false if the crab is clearly low on "
            f"belly or energy right now. games: {', '.join(games)}.\n"
            f"crab vitals: belly {vit.get('belly',0):.0f}/100, energy {vit.get('energy',0):.0f}/100, "
            f"{vit.get('lines',0)} lines / {vit.get('commits',0)} commits today, "
            f"{vit.get('streak',0)}-day streak, hour {vit.get('hour',12)}.\n"
            f"reply with ONLY compact json: {{\"play\": true|false, \"game\": one of "
            f"[{', '.join(games)}] or null, \"line\": \"<excited lowercase quip, <=8 "
            f"words, NEVER an em dash>\"}}."
        )
        resp = client.messages.create(
            model=MODEL, max_tokens=60, system=system,
            messages=[{"role": "user", "content": "is now a good time to code a game?"}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        m = re.search(r"\{.*\}", text, re.S)
        d = json.loads(m.group(0)) if m else {}
        if not d.get("play") or d.get("game") not in games:
            return None
        line = (d.get("line") or "").replace("—", ", ").replace("–", ", ").strip()
        return {"game": d["game"], "line": line or "let's build a game!"}
    except Exception:
        return None

def ask(history, vit):
    """Send the conversation to Claude and return the crab's one-line reply.
    Never raises — returns a friendly fallback line on any error."""
    try:
        client = _client_for(ASK_TIMEOUT)
        if client is None:
            return "(my api key seems off!)"
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
        if "Timeout" in msg:            # before Connection: APITimeoutError is one
            return "(thinking too slow, ask me again?)"
        if "Connection" in msg:
            return "(can't reach my brain rn)"
        return "(brain hiccup, try again?)"
