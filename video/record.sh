#!/bin/bash
# Record one take of the launch intro into video/take.mov.
#
# Usage:
#   ./video/record.sh rect      # click the terminal window once to cache its rect
#   ./video/record.sh           # 3-2-1 countdown, records ~26s, run intro in the window
#
# The recording captures a screen REGION, so the terminal window must not move
# between `rect` and the take. Manual fallback: QuickTime / Cmd-Shift-5, record
# the window, then `python3 video/intro.py` inside it.
#
# Setup checklist (do once before recording):
#   - Terminal window >= 100 columns wide, ~24 rows
#   - Font ~18pt, a dark theme, no transparency
#   - Retina display (digital zoom in post stays sharp)
#   - Hide anything distracting behind/around the window
set -euo pipefail
cd "$(dirname "$0")"

RECT_FILE="rect.txt"
SECONDS_TO_RECORD=26

if [[ "${1:-}" == "rect" ]]; then
  echo "Click the terminal window you'll record..."
  # Frontmost-window bounds after a 3s delay to click the right window.
  sleep 3
  osascript -e '
    tell application "System Events"
      set p to first application process whose frontmost is true
      set w to front window of p
      set {x, y} to position of w
      set {wd, ht} to size of w
      return (x as text) & "," & (y as text) & "," & (wd as text) & "," & (ht as text)
    end tell' > "$RECT_FILE"
  echo "Saved region $(cat "$RECT_FILE") to video/$RECT_FILE"
  exit 0
fi

[[ -f "$RECT_FILE" ]] || { echo "No video/$RECT_FILE yet -- run: ./video/record.sh rect"; exit 1; }
RECT=$(cat "$RECT_FILE")

echo "Recording region $RECT for ${SECONDS_TO_RECORD}s -> video/take.mov"
echo "Start 'python3 video/intro.py' in the target window when the countdown ends."
for i in 3 2 1; do echo "  $i..."; sleep 1; done
# -v video, -R region, -V duration. Needs Screen Recording permission for this shell's app.
screencapture -v -R"$RECT" -V "$SECONDS_TO_RECORD" take.mov
echo "Done: video/take.mov"
