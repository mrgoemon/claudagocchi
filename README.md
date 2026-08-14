# Claudagocchi 🦀 v2.0

A terminal Tamagotchi — a little crab, built from the Claude Code mark, that
lives in your terminal and reacts to how you code. Made to make vibecoding feel
like you're building something *for someone*.

**v2.0 gives the crab a life.** It hatches, grows through five stages, becomes
one of four adults depending on how *you* code — and if you stop feeding it, it
dies for real. Every crab you lose is kept in Memory Lane.

```
╭─ Claudagocchi ──────────────────────────────────────────────────────────────╮
│                                                                             │
│                              Welcome back kh!                               │
│                                                                             │
│                                  ▗ ▗   ▖ ▖                                  │
│                                                                             │
│ †                                  ▘▘ ▝▝                              ◆✦~◦◦ │
│                                                                             │
│           mood ●●●●○  energy ●●●○○  belly ●●●●●  health ●●●●○               │
│                        tokens used today  42,157,267                        │
│                  today  218 lines  ·  16 commits  ·  3 PRs                  │
│                       tokens all-time  1,403,326,221                        │
│                  ● loan-search needs you — permission prompt                │
│                                                                             │
╰─────────────────────────────────────────────────────────────────────────────╯
```

## What it does

- **Lives in your terminal** — a calm, cat-like crab that loafs, blinks, struts,
  stretches, grooms, scuttles sideways, and occasionally pounces (the animation
  is driven by its mood, health and life stage).
- **Vitals** — energy / happiness / belly decay over real time. The **belly fills
  as you use Claude Code** (token usage feeds the crab), so it's well-fed while
  you're working and gets hungry when you stop.
- **It can die.** 🆕 An empty belly is survivable; *staying* empty is not. Go
  quiet for about half a day and it starts starving; keep it up and after roughly
  five days it's gone. Death is permanent — the hoard resets and a new egg hatches.
  (`crab --undo-death` restores the last one if something goes wrong.)
- **It grows.** 🆕 egg → hatchling → juvenile → adult, and then into one of four
  adult forms earned from how you actually code:

  | form | earned by |
  |---|---|
  | **architect** | opening PRs and committing |
  | **grinder** | heavy Claude Code token use |
  | **gamer** | letting it play its minigames |
  | **feral** | leaving it hungry |

  Each form has its own size, silhouette and colour. The crab telegraphs a change
  before it happens, and celebrates after.
- **It watches your other agents.** 🆕 The crab reads your live Claude Code
  sessions and tells you when one is **blocked waiting on you** — a permission
  prompt, a question — by name, with a chirp. Codex sessions are detected too,
  marked `≈` because Codex's logs can't reveal an approval prompt.
- **Graduation.** 🆕 Death is what happens *to* a crab. Graduation is your call —
  once it has reached a final form, `crab --graduate` retires it with honours (🎓
  rather than ✝) and hatches its successor. It asks you to type the name first,
  and `crab --undo` puts it back.
- **Memory Lane.** 🆕 `crab --hall` shows every crab you've raised, each drawn in
  its own final form, with what it did and how it went.
- **Admin mode.** 🆕 The life cycle plays out over days. `crab --admin <scenario>`
  stages any of it right now — the egg, an evolution, starvation, death and the
  memorial, a graduation, a blocked session. It runs in a sandbox and never reads
  or writes your real crab.
- **Daily code vitals** — lines from *your* commits, PRs you opened, and your
  streak, read straight from git + the GitHub CLI.
- **Gifts** — every **commit** you make becomes a gift sized by its net lines. It
  drops on the far side, the crab reacts, walks over, and adds it to a growing
  **hoard** (crumb → shell → fish → feast → treasure). Opening a PR gets a cheer.
- **Nudges** — a gentle "let's stretch" after a long session.
- **Chat** — type at the bottom of the window and the crab talks back (Claude API,
  Haiku by default). Enable it with `pip install anthropic` plus a key — an
  `ANTHROPIC_API_KEY` env var *or* `crab --setkey`. Without it, chat stays off and
  everything else works.
- **Minigames** — now and then the crab "codes" a tiny game (a 💻 typing build-up)
  and then watches it play *itself*, right inside the window: a dino runner,
  pong, snake, a crab dodging traffic (`crossing`), space `invaders`, `breakout`,
  or a `squash`-the-bugs hammer. An **AI director** (Claude) picks the moment and
  the game; with no key it still surprises you occasionally on its own. Want one
  now? Type `game` (or `play snake` / `play crossing` / any name) in the chat line.
  Each one self-plays off per-move rolls, so the crab genuinely wins or loses.

## Install

```sh
git clone <this-repo> ~/claude-crab
ln -s ~/claude-crab/crab ~/.local/bin/crab   # or put the repo's ./crab on your PATH
crab --watch /path/to/your/project           # track a repo (remembered globally)
crab --me                                    # count only your commits
pip install anthropic && crab --setkey       # optional: turn on chat (paste your key)
crab                                         # launch the crab (Ctrl-C to stop)
```

Requirements: **python3**, **git**, and the **GitHub CLI (`gh`)**, authenticated,
for PR detection. Chat is optional and adds the **`anthropic`** package plus an
API key (`crab --setkey` or an `ANTHROPIC_API_KEY` env var).

## Commands

| Command | What |
|---|---|
| `crab` | The live animated crab |
| `crab --status` | One static live frame |
| `crab --hall` | 🆕 Memory Lane — every crab you've raised |
| `crab --graduate` | 🆕 Retire this crab with honours and start fresh |
| `crab --admin [scenario]` | 🆕 Sandbox: stage any life event on demand |
| `crab --name [name]` | 🆕 Show or change your crab's name |
| `crab --sessions` | 🆕 What your other Claude Code / Codex sessions are doing |
| `crab --alerts on\|quiet\|off` | 🆕 How loudly to flag a session that needs you |
| `crab --undo` | 🆕 Undo the last death or graduation |
| `crab --hoard` | Everything you've gifted it |
| `crab --watch <path>` / `--unwatch <path>` / `--list` | Manage tracked repos |
| `crab --me [email]` / `crab --me off` | Count only your commits (or everyone) |
| `crab --tokens` | Your Claude Code token usage (today / 7d / all-time, by model) |
| `crab --setkey` | Save an Anthropic API key so the crab can chat |
| `crab --welcome` | Static box, no live data |
| `crab --sheet` | 🆕 Every life stage in every pose (for eyeballing sprites) |
| `crab --old` | 🆕 Run the v1.0 crab from `legacy/` (see below) |
| `crab --no-color` | No coral tint |

Set `CRAB_STAGE=<stage>` to force a life stage without editing your save — handy
for seeing the egg, or any adult form, on demand:

```sh
CRAB_STAGE=architect crab
```

## The old crab

`crab --old` runs the frozen v1.0 crab — the original coral 9×3 sprite, four stat
lines, no life cycle. Flags pass straight through (`crab --old --status`).

It gets **its own home** at `~/.claude-crab/v1-home/`, seeded once from your real
save so it still looks like your crab, with `~/.claude` symlinked through so token
usage keeps counting. After that it lives a separate life.

That isolation is the point: v1.0 hardcodes `~/.claude-crab` and runs the old
30/hr hunger clock, so pointing it at your real save would empty your crab's belly
just by looking at it. It gets a different `HOME` rather than a patch, because
`legacy/` is only useful if it stays exactly as it shipped.

## Admin mode

Most of what makes the crab a pet happens on a scale of days. That's right for
living with and useless for looking at, so admin mode stages each moment now:

```sh
crab --admin              # list the scenarios
crab --admin death        # watch one
```

| scenario | what you see |
|---|---|
| `egg` / `hatch` | a fresh egg, and one cracking open |
| `evolve` | every stage back to back, in about a minute |
| `forms` | each of the four adult forms in turn |
| `starve` | belly empties, then health follows it down |
| `death` | starving to death, the memorial, and the next egg |
| `graduate` | a retirement, plus the "not yet eligible" case |
| `alert` | a session blocked on you, and the crab reacting |
| `gift` | a treasure-tier gift arriving |
| `hall` | Memory Lane with a full multi-generation history |
| `sheet` | every life stage in every pose |

Two things it guarantees, because it exists to trigger destructive events:

- **Your crab is never touched.** Every scenario runs against a sandbox save at
  `~/.claude-crab/admin/`; your real `state.json` is not read and not written.
- **Your sessions are never touched.** The `alert` scenario injects a canned
  reading rather than looking at `~/.claude/`.

Time-based scenarios wind up `crab_state.TIME_SCALE` so an hour of crab-clock
passes in a fraction of a second. That's the same code path the real crab uses —
nothing is faked except the rate.

## How it's built

- `pixel_crab.py` — the renderer + animation engine (the sprite morphs, the window,
  the behavior scheduler, the gift/death scenes).
- `crab_state.py` — the state engine (vitals, the life cycle, git/PR reading, gift
  tiers, quests, the speech).
- `crab_sessions.py` — 🆕 reads your live Claude Code / Codex sessions.
- `crab_hall.py` — 🆕 renders Memory Lane.
- `crab_admin.py` — 🆕 the sandboxed scenario runner behind `--admin`.
- `legacy/` — 🆕 frozen snapshots of earlier versions. Nothing imports it; see
  [`legacy/README.md`](legacy/README.md).
- `crab_chat.py` — the Claude API layer (chat replies + the minigame director).
- `crab_games.py` — the self-playing minigames (dino / pong / snake / crossing /
  invaders / breakout / squash).
- `crab_tokens.py` — totals Claude Code token usage from its local session logs
  (`~/.claude/projects/`); works on the Max/Pro plan, no API key needed.
- State lives in `~/.claude-crab/` (`state.json`, `config.json`).

Pure Python standard library — no dependencies, with one exception: the chat and
the minigame director use the `anthropic` package, and only when you turn it on.

### The one invariant

The window is redrawn in place by moving the cursor up a fixed number of lines,
computed **once** at startup. Every frame must therefore be exactly the same
height, forever — a taller crab is absorbed by lowering it on the stage, never by
adding a row, and the stat block always has the same number of lines even when it
has nothing to say. Break this and the display tears for the rest of the session.

Two harnesses guard it, both dependency-free:

```sh
COLUMNS=100 python3 goldens.py check    # sprite/window regression hashes
COLUMNS=100 python3 goldens.py sweep    # every morph x position x pose: same size?
python3 ptycheck.py                     # runs the real animation, asserts one frame height
python3 admincheck.py                   # every admin scenario runs, and stays in its sandbox
```

### Upgrading from v1.0

Nothing is lost. Your existing crab keeps its hoard, history and age, and is
placed at the life stage it already earned rather than being sent back to an egg
— a well-used v1.0 crab wakes up as an adult, or as whichever form it had already
earned. The v1.0 source itself is frozen under [`legacy/v1.0/`](legacy/) and can
still be run on its own; the current app never refers to it.

> `crab.py` is the original line-art prototype, kept for posterity.
