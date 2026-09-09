#!/usr/bin/env python3
"""Claude dancing terminal animation — press any key to stop."""
import sys, time, tty, termios, threading, os, math

OR = '\033[38;5;208m'   # orange
GD = '\033[38;5;220m'   # gold
CY = '\033[36m'          # cyan
PK = '\033[35m'          # pink
GR = '\033[32m'          # green
RS = '\033[0m'           # reset
BD = '\033[1m'           # bold
CLR = '\033[2J\033[H'

FRAMES = [
    # pose 0 — hands way up
    [
        f"  {OR}♪{RS}                    {CY}♫{RS}",
        f"",
        f"      {OR}\\{RS}  {GD}╭─────╮{RS}  {CY}/{RS}",
        f"         {GD}│{RS} {BD}°ω°{RS} {GD}│{RS}",
        f"         {GD}╰─────╯{RS}",
        f"           {CY}│{RS}",
        f"          {CY}╱ ╲{RS}",
        f"",
    ],
    # pose 1 — arms out
    [
        f"            {GD}♬{RS}",
        f"",
        f"    {OR}─{RS}    {GD}╭─────╮{RS}    {CY}─{RS}",
        f"         {GD}│{RS} {BD}^ω^{RS} {GD}│{RS}",
        f"         {GD}╰─────╯{RS}",
        f"           {CY}│{RS}",
        f"          {CY}╱ ╲{RS}",
        f"",
    ],
    # pose 2 — hands down
    [
        f"   {PK}♩{RS}                   {OR}♪{RS}",
        f"",
        f"      {OR}/{RS}  {GD}╭─────╮{RS}  {CY}\\{RS}",
        f"         {GD}│{RS} {BD}°ω°{RS} {GD}│{RS}",
        f"         {GD}╰─────╯{RS}",
        f"           {CY}│{RS}",
        f"          {CY}╱ ╲{RS}",
        f"",
    ],
    # pose 3 — arms out (mirrored)
    [
        f"   {CY}♫{RS}",
        f"",
        f"    {CY}─{RS}    {GD}╭─────╮{RS}    {OR}─{RS}",
        f"         {GD}│{RS} {BD}^ω^{RS} {GD}│{RS}",
        f"         {GD}╰─────╯{RS}",
        f"           {CY}│{RS}",
        f"          {CY}╱ ╲{RS}",
        f"",
    ],
    # pose 4 — lean left
    [
        f"      {GR}♫{RS}         {PK}♬{RS}",
        f"",
        f"    {OR}\\{RS}  {GD}╭─────╮{RS}",
        f"       {GD}│{RS} {BD}°▿°{RS} {GD}│{RS}  {CY}~{RS}",
        f"       {GD}╰─────╯{RS}",
        f"         {CY}│{RS}",
        f"        {CY}╱ ╲{RS}",
        f"",
    ],
    # pose 5 — lean right
    [
        f"         {PK}♩{RS}      {OR}♪{RS}",
        f"",
        f"          {GD}╭─────╮{RS}  {CY}/{RS}",
        f"  {OR}~{RS}  {GD}│{RS} {BD}°▿°{RS} {GD}│{RS}",
        f"          {GD}╰─────╯{RS}",
        f"            {CY}│{RS}",
        f"           {CY}╱ ╲{RS}",
        f"",
    ],
]

QUIPS = [
    f"{OR}Claude is vibing...{RS}",
    f"{GD}Training data: bangers only{RS}",
    f"{CY}Peak AI performance unlocked{RS}",
    f"{PK}Fully corrigible to the beat{RS}",
    f"{OR}Anthropic didn't see this coming{RS}",
    f"{GD}I think, therefore I groove{RS}",
    f"{CY}Context window: dance floor{RS}",
    f"{GR}Activating dance.exe...{RS}",
    f"{PK}Constitutional AI: bop responsibly{RS}",
    f"{OR}This is what 200B params looks like{RS}",
]

TITLE = [
    f" {GD}╔══════════════════════════════╗{RS}",
    f" {GD}║{RS}  {BD}{OR}  ♬  C L A U D E   D A N C E  ♬  {RS}  {GD}║{RS}",
    f" {GD}╚══════════════════════════════╝{RS}",
]

stop_flag = threading.Event()

def read_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    stop_flag.set()

def main():
    sys.stdout.write('\033[?25l')
    sys.stdout.flush()
    threading.Thread(target=read_key, daemon=True).start()

    tick = 0
    try:
        while not stop_flag.is_set():
            try:
                sz = os.get_terminal_size()
                cols, rows = sz.columns, sz.lines
            except OSError:
                cols, rows = 80, 24

            # Sway left/right
            sway = int(math.sin(tick * math.pi / 2) * 4)
            frame = FRAMES[tick % len(FRAMES)]
            quip = QUIPS[(tick // 6) % len(QUIPS)]

            content_height = len(TITLE) + 1 + len(frame) + 3
            top = max(0, (rows - content_height) // 2)
            base_indent = max(0, (cols - 36) // 2)

            out = CLR + '\n' * top

            # Title
            title_indent = ' ' * max(0, (cols - 36) // 2)
            for line in TITLE:
                out += title_indent + line + '\n'
            out += '\n'

            # Character frame with sway
            char_indent = ' ' * max(0, base_indent + sway)
            for line in frame:
                out += char_indent + line + '\n'

            # Quip
            quip_indent = ' ' * max(0, (cols - 36) // 2)
            out += quip_indent + f"  {BD}" + quip + f"{RS}\n"
            out += '\n'
            out += quip_indent + f"  {CY}Press any key to stop...{RS}\n"

            sys.stdout.write(out)
            sys.stdout.flush()

            time.sleep(0.22)
            tick += 1
    finally:
        sys.stdout.write('\033[?25h')
        sys.stdout.write(CLR)
        sys.stdout.write(f"\n  {OR}{BD}Claude has left the dance floor. Bye! 👋{RS}\n\n")
        sys.stdout.flush()

if __name__ == '__main__':
    main()
