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

# Incremental scan cache. Session logs only ever grow (150MB / 0.6s a full read
# here, and rising), so we remember where we stopped in each file and re-read
# just the tail. What's cached is the extracted rows per file -- not period
# totals, which would go stale at midnight -- so "today"/"week" are still rolled
# up from the current date on every call, and the uuid dedupe still runs across
# every file exactly as a full scan would.
CACHE = os.path.join(os.environ.get("CRAB_SAVE_DIR")
                     or os.path.expanduser("~/.claude-crab"), "token-cache.json")
CACHE_V = 1

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
    """Local calendar date of a log line, as 'YYYY-MM-DD' (ISO strings compare in order)."""
    try:
        return datetime.datetime.fromisoformat(
            (ts or "").replace("Z", "+00:00")).astimezone().date().isoformat()
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

def _logs(root):
    return glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)

def _parse(buf):
    """Usage rows out of raw jsonl bytes: [uuid, date, model, in, out, cc, cr]."""
    rows = []
    for ln in buf.split(b"\n"):
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
        rows.append([o.get("uuid"), _local_date(o.get("timestamp")), model,
                     u.get("input_tokens", 0) or 0, u.get("output_tokens", 0) or 0,
                     u.get("cache_creation_input_tokens", 0) or 0,
                     u.get("cache_read_input_tokens", 0) or 0])
    return rows

def _read(f, off):
    """(rows of whole lines, rows of a half-written last line, offset to resume at).

    A log being appended to right now can end mid-line, so the offset only ever
    advances to the last newline: the tail rows are used for this call but never
    cached, and get re-read (once complete) next time."""
    with open(f, "rb") as fh:
        fh.seek(off)
        buf = fh.read()
    cut = buf.rfind(b"\n") + 1
    return _parse(buf[:cut]), _parse(buf[cut:]), off + cut

def _scan(root):
    """Yield (uuid, local_date, model, input, output, cache_create, cache_read)."""
    for f in _logs(root):
        try:
            whole, part, _ = _read(f, 0)
        except Exception:
            continue
        for r in whole:
            yield r
        for r in part:
            yield r

def _cache_load(root):
    """The saved cache, an empty one to rebuild into, or None to not cache at all."""
    if root != PROJECTS or os.environ.get("CRAB_TOKEN_CACHE") == "0":
        return None                              # tests pass their own root -- stay out
    fresh = {"v": CACHE_V, "root": root, "files": {}}
    try:
        with open(CACHE, encoding="utf-8") as fh:
            c = json.load(fh)
        if c.get("v") != CACHE_V or c.get("root") != root:
            return fresh                         # a schema bump invalidates cleanly
        for e in c["files"].values():
            e["size"], e["mtime"], e["off"] = int(e["size"]), float(e["mtime"]), int(e["off"])
            if not all(len(r) == 7 for r in e["rows"]):
                return fresh
        return c
    except Exception:
        return fresh                             # missing, unreadable or corrupt

def _cache_save(root, files):
    """Atomic, 0600, best effort — the crab never waits on this and never dies of it."""
    tmp = f"{CACHE}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(CACHE), 0o700, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"v": CACHE_V, "root": root, "files": files}, fh, separators=(",", ":"))
        os.replace(tmp, CACHE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass

def _cached_rows(root):
    """Every usage row under `root`, re-reading only what was appended since last time."""
    cache = _cache_load(root)
    if cache is None:
        return list(_scan(root))
    old, new, out, dirty = cache["files"], {}, [], False
    # rows come back in glob order, so aggregate() resolves a uuid that appears
    # in two files to the same one a full scan would pick.
    for f in _logs(root):
        try:
            st = os.stat(f)
            e = old.get(f)
            if e and st.st_size == e["size"] and st.st_mtime == e["mtime"]:
                rows, off = e["rows"], e["off"]                  # untouched
                part = _read(f, off)[1] if off < st.st_size else []
            elif e and st.st_size > e["size"] and st.st_mtime >= e["mtime"]:
                tail, part, off = _read(f, e["off"])             # appended to -- tail only
                rows, dirty = e["rows"] + tail, True
            else:
                rows, part, off = _read(f, 0)                    # new, rotated or rewritten
                dirty = True
        except Exception:
            continue
        new[f] = {"size": st.st_size, "mtime": st.st_mtime, "off": off, "rows": rows}
        out += rows
        out += part
    if dirty or len(new) != len(old):            # len(): catches logs that went away
        _cache_save(root, new)
    return out

def _rows(root):
    try:
        return _cached_rows(root)
    except Exception:
        return list(_scan(root))                 # any cache trouble at all: just read it all

def aggregate(root=PROJECTS):
    """period -> model -> {in,out,cc,cr}. Dedupes turns by uuid across files."""
    d0 = datetime.date.today()                   # read once: midnight can't split the buckets
    today, week = d0.isoformat(), (d0 - datetime.timedelta(days=6)).isoformat()
    data = {"today": {}, "week": {}, "all": {}}
    seen = set()
    for uid, d, model, i, o, cc, cr in _rows(root):
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

def today_all(root=PROJECTS):
    """(today_total, all_time_total) from one scan."""
    d = aggregate(root)
    return (sum(_total(b) for b in d["today"].values()),
            sum(_total(b) for b in d["all"].values()))

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
