#!/usr/bin/env python3
"""Read Claude Code's local session transcripts and total up token usage.

Works on the Max/Pro plan (no API key) — Claude Code logs a `usage` block on
every assistant turn under ~/.claude/projects/**/*.jsonl. We sum those. The
dollar figures are just "what this would have cost on the API" (the Max plan
itself is a flat subscription, so you aren't actually billed per token).
"""
import os
import json
import glob
import datetime

PROJECTS = os.path.expanduser("~/.claude/projects")

# $ per 1M tokens (input, output) — for the "equivalent API cost" estimate only.
PRICES = {
    "claude-opus-4-8": (5.0, 25.0), "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0), "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0), "claude-fable-5": (10.0, 50.0),
}

def _price(model):
    for k, v in PRICES.items():
        if model.startswith(k):
            return v
    return None

def _local_date(ts):
    try:
        return datetime.datetime.fromisoformat((ts or "").replace("Z", "+00:00")).astimezone().date()
    except Exception:
        return None

def _z():  return {"in": 0, "out": 0, "cc": 0, "cr": 0}
def _add(b, i, o, cc, cr): b["in"] += i; b["out"] += o; b["cc"] += cc; b["cr"] += cr
def _total(b): return b["in"] + b["out"] + b["cc"] + b["cr"]

def _cost(model, b):
    p = _price(model)
    if not p:
        return 0.0
    pin, pout = p                                    # cache write ~1.25x in, cache read ~0.1x in
    return (b["in"] * pin + b["cc"] * pin * 1.25 + b["cr"] * pin * 0.1 + b["out"] * pout) / 1e6

def _scan(root):
    """Yield (uuid, local_date, model, input, output, cache_create, cache_read)."""
    for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except Exception:
            continue
        for ln in lines:
            try:
                o = json.loads(ln)
            except Exception:
                continue
            msg = o.get("message") or {}
            u = msg.get("usage")
            if not u:
                continue
            model = msg.get("model") or ""
            if model == "<synthetic>":               # local, non-model messages
                continue
            yield (o.get("uuid"), _local_date(o.get("timestamp")), model,
                   u.get("input_tokens", 0) or 0, u.get("output_tokens", 0) or 0,
                   u.get("cache_creation_input_tokens", 0) or 0,
                   u.get("cache_read_input_tokens", 0) or 0)

def aggregate(root=PROJECTS):
    """period -> model -> {in,out,cc,cr}. Dedupes turns by uuid across files."""
    today = datetime.date.today()
    week = today - datetime.timedelta(days=6)
    data = {"today": {}, "week": {}, "all": {}}
    seen = set()
    for uid, d, model, i, o, cc, cr in _scan(root):
        if uid is not None:
            if uid in seen:
                continue
            seen.add(uid)
        for period, cond in (("all", True), ("week", bool(d) and d >= week), ("today", d == today)):
            if cond:
                _add(data[period].setdefault(model, _z()), i, o, cc, cr)
    return data

def tokens_today(root=PROJECTS):
    """Just today's total token throughput — cheap headline number for the crab."""
    return sum(_total(b) for b in aggregate(root)["today"].values())

def _h(n):
    if n >= 1e6: return f"{n / 1e6:.1f}M"
    if n >= 1e3: return f"{n / 1e3:.1f}k"
    return str(int(n))

def report(root=PROJECTS):
    data = aggregate(root)
    def tok(p):  return sum(_total(b) for b in data[p].values())
    def cat(p, k): return sum(b[k] for b in data[p].values())
    def cost(p): return sum(_cost(m, b) for m, b in data[p].items())
    out = ["Claude Code token usage   (Max plan — $ is just the equivalent API cost)", ""]
    for period, label in (("today", "today   "), ("week", "last 7d "), ("all", "all time")):
        out.append(f"  {label}  {_h(tok(period)):>8} tokens   "
                   f"(in {_h(cat(period, 'in'))} · out {_h(cat(period, 'out'))} · "
                   f"cache {_h(cat(period, 'cc') + cat(period, 'cr'))})   ≈ ${cost(period):,.2f}")
    allm = data["all"]
    if any(_total(b) for b in allm.values()):
        out += ["", "  by model (all time):"]
        for m in sorted(allm, key=lambda m: -_total(allm[m])):
            if _total(allm[m]):
                out.append(f"    {m.replace('claude-', ''):18} {_h(_total(allm[m])):>8} tokens   ≈ ${_cost(m, allm[m]):,.2f}")
    return "\n".join(out)
