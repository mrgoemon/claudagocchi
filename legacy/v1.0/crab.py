#!/usr/bin/env python3
"""Claude Crab — the avatar renderer (Phase 1).

Renders the Claude Code crab as ASCII art, with a face that changes by mood.
This is the visual layer the Tamagotchi will sit on top of. No dependencies.

Usage:
    python3 crab.py            # render the crab in its default (happy) mood
    python3 crab.py hungry     # render a specific mood
    python3 crab.py --all      # show every mood side-by-side (a mood sheet)
    python3 crab.py --no-color # plain, no ANSI color
"""
import sys

# Claude brand coral/orange in truecolor; per-mood tints for flavor.
RESET = "\033[0m"
def rgb(r, g, b): return f"\033[38;2;{r};{g};{b}m"

MOOD_COLOR = {
    "happy":    rgb(217, 119, 87),   # claude coral
    "neutral":  rgb(217, 119, 87),
    "hungry":   rgb(230, 160, 70),   # amber
    "sad":      rgb(120, 150, 200),  # blue
    "sleeping": rgb(140, 140, 150),  # dim grey-blue
    "sick":     rgb(140, 180, 110),  # sickly green
    "dead":     rgb(110, 110, 110),  # grey
}

# Each mood defines the eyes (left/right) and mouth that slot into the body.
# extra = a little speech/zzz flourish to the side.
FACES = {
    "happy":    dict(l="^", r="^", mouth="\\___/", extra=""),
    "neutral":  dict(l="o", r="o", mouth="\\_-_/", extra=""),
    "hungry":   dict(l="O", r="O", mouth="\\ O /", extra="~ feed me"),
    "sad":      dict(l="v", r="v", mouth="/---\\", extra="..."),
    "sleeping": dict(l="-", r="-", mouth="\\~~~/", extra="z Z z"),
    "sick":     dict(l="x", r="x", mouth="\\~~~/", extra="* cough *"),
    "dead":     dict(l="x", r="x", mouth="\\___/", extra="R.I.P."),
}

def art(mood: str) -> str:
    f = FACES[mood]
    # The crab: raised pincers on top, eyestalks, body with a face, little legs.
    return (
        "      (\\/)        (\\/)\n"
        "       \\\\          //\n"
        f"        \\\\   {f['l']}  {f['r']}   //        {f['extra']}\n"
        "      ___\\\\________//___\n"
        f"     /     {f['mouth']}      \\\n"
        "     \\____________________/\n"
        "       /  /  |    |  \\  \\\n"
        "      ^  ^   ^    ^   ^  ^"
    )

def render(mood: str, color: bool = True) -> str:
    body = art(mood)
    if color:
        body = MOOD_COLOR.get(mood, "") + body + RESET
    return body

def mood_sheet(color: bool) -> str:
    blocks = []
    for m in FACES:
        label = f"  [{m}]"
        blocks.append((MOOD_COLOR[m] + label + RESET if color else label) + "\n" + render(m, color))
    return "\n\n".join(blocks)

def main(argv):
    color = "--no-color" not in argv
    argv = [a for a in argv if a != "--no-color"]
    if "--all" in argv:
        print(mood_sheet(color)); return
    mood = argv[0] if argv else "happy"
    if mood not in FACES:
        print(f"unknown mood '{mood}'. options: {', '.join(FACES)}", file=sys.stderr)
        sys.exit(1)
    print(render(mood, color))

if __name__ == "__main__":
    main(sys.argv[1:])
