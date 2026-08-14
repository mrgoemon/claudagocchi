# legacy/

Frozen snapshots of earlier Claudagocchi. **Nothing here is imported, referenced,
or run by the current app** — it's kept so you can go back and look at, or run,
an older crab if you want to.

| version | what it was |
|---|---|
| [`v1.0/`](v1.0/) | The immortal crab. Vitals decayed but never ran out; one fixed 9×3 sprite; no age, no life stage, no death. |

## Running it

Each snapshot is self-contained and launches on its own:

```sh
legacy/v1.0/crab              # the v1.0 crab, live
legacy/v1.0/crab --status     # one static frame
```

**One caveat:** v1.0 reads and writes the same `~/.claude-crab/state.json` as the
current version. It will not corrupt anything — it preserves keys it doesn't know
about — but it runs the old, much faster hunger clock (`HUNGER_PER_HR = 30`, an
empty belly in ~3 hours), so a long v1.0 session will leave your real crab hungry.

To poke at it without touching your live pet, point it at a scratch home:

```sh
mkdir -p /tmp/crab-v1 && HOME=/tmp/crab-v1 legacy/v1.0/crab
```

(That also hides your Claude Code token logs from it, so the belly won't fill —
which is fine for looking at the old sprite and animations.)

## Why these are kept as code, not as data

The current app has a Memory Lane (`crab --hall`) for *crabs* you've raised. This
folder is for *versions* — the program itself at a point in time. They're
deliberately separate: Memory Lane is part of the game, `legacy/` is an archive
that the game never mentions.
