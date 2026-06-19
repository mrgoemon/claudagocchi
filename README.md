# Claudagocchi 🦀

A terminal Tamagotchi — a little crab, built from the Claude Code mark, that
lives in your terminal and reacts to how you code. Made to make vibecoding feel
like you're building something *for someone*.

```
╭─ Claudagocchi ───────────────────────────────────────────────────╮
│                                                                  │
│                          Welcome back kh!                        │
│                                                                  │
│              ▗ ▗   ▖ ▖   (a coral crab, alive & animated)        │
│                ▘▘ ▝▝                                             │
│                                                                  │
│              today  218 lines  ·  16 commits  ·  3 PRs           │
│                 mood ●●●●○  energy ●●●○○  belly ●●●●●     ◆✦~◦◦   │
│                 quest  open a PR  ●○○                            │
│                                                                  │
╰──────────────────────────────────────────────────────────────────╯
```

## What it does

- **Lives in your terminal** — a calm, cat-like crab that loafs, blinks, struts,
  stretches, grooms, and occasionally pounces (drives the animation off your mood).
- **Vitals** — hunger / energy / happiness decay over real time and are fed by
  your coding.
- **Daily code vitals** — lines from *your* commits, PRs you opened, and your
  streak, read straight from git + the GitHub CLI.
- **Gifts** — when you **open a PR** (or push), the crab receives a gift sized by
  the work, drops it on the far side, reacts, walks over, and adds it to a growing
  **hoard**. Bigger work = bigger gift (crumb → shell → fish → feast → treasure).
- **Quests & nudges** — small daily goals and a gentle "let's stretch" after a
  long session.
- **Chat** — type at the bottom of the window and the crab talks back (Claude API,
  Haiku by default). Enable it with `pip install anthropic` plus a key — an
  `ANTHROPIC_API_KEY` env var *or* `crab --setkey`. Without it, chat stays off and
  everything else works.
- **Minigames** — now and then the crab "codes" a tiny game (a 💻 typing build-up)
  and then watches it play *itself* — a dino runner, pong, or snake, right inside
  the window. An **AI director** (Claude) picks the moment and the game; with no
  key it still surprises you occasionally on its own. Want one now? Type `game`
  (or `play dino` / `play pong` / `play snake`) in the chat line.

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
| `crab --hoard` | Everything you've gifted it |
| `crab --watch <path>` / `--unwatch <path>` / `--list` | Manage tracked repos |
| `crab --me [email]` / `crab --me off` | Count only your commits (or everyone) |
| `crab --setkey` | Save an Anthropic API key so the crab can chat |
| `crab --welcome` | Static box, no live data |
| `crab --no-color` | No coral tint |

## How it's built

- `pixel_crab.py` — the renderer + animation engine (the crab sprite, the window,
  the behavior scheduler, the gift scenes).
- `crab_state.py` — the state engine (vitals decay, git/PR reading, gift tiers,
  quests, the speech).
- `crab_chat.py` — the Claude API layer (chat replies + the minigame director).
- `crab_games.py` — the self-playing minigames (dino / pong / snake).
- State lives in `~/.claude-crab/` (`state.json`, `config.json`).

Pure Python standard library — no dependencies, with one exception: the chat and
the minigame director use the `anthropic` package, and only when you turn it on.

> `crab.py` is the original line-art prototype, kept for posterity.
