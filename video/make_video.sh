#!/bin/bash
# Turn video/take.mov into the launch MP4: digital zoom on the sleeping crab,
# hold through the blink, zoom out to reveal the frame, fade to an end card.
#
#   ./video/make_video.sh            # -> video/claudagocchi_launch.mp4
#
# Calibrate against YOUR take by tweaking the variables below, then re-run
# (renders in seconds). T0 is the only one that usually changes between takes.
set -euo pipefail
cd "$(dirname "$0")"

IN=take.mov
OUT=claudagocchi_launch.mp4
FPS=30

# ---- timeline (seconds into the recording) ---------------------------------
T0=1.0                 # when intro.py started, relative to recording start
CRAB_T=$(echo "$T0 + 5.1" | bc)      # crab frame appears (intro.py timings)
# The crab holds a dead-still frame for 4.0s, blinks twice (~0.8s), hops (~1s),
# then changes its line and gets on with its life. Stay zoomed in through the
# blinks and the hop, and be pulled back by the time it starts walking.
ZOUT_START=$(echo "$CRAB_T + 5.9" | bc)
ZOUT_END=$(echo "$CRAB_T + 8.2" | bc)
# The vitals only appear once the crab is wandering on its own, ~11s after
# the frame opens, so hold well past that before the card.
T_FADE=22              # end-card crossfade starts
TOTAL=25               # final video length

# ---- zoom target -----------------------------------------------------------
ZMAX=3.0               # how tight the zoom-in is
CX=0.50                # crab center, as a fraction of the width (0..1)
CY=0.42                # crab center, as a fraction of the height (0..1)

# ---- end card (a PNG: this ffmpeg build has no drawtext) --------------------
[[ -f card.png ]] || python3 card.py

f() { python3 -c "print(round($1 * $FPS))"; }
F_CUT=$(f "$CRAB_T"); F_ZS=$(f "$ZOUT_START"); F_ZE=$(f "$ZOUT_END")

# zoompan: hard-cut to ZMAX when the crab appears, hold through the blink,
# ease back to 1.0 (quadratic ease-out) between F_ZS and F_ZE.
Z="if(lt(in,$F_CUT),1, if(lt(in,$F_ZS),$ZMAX, if(lt(in,$F_ZE), 1+($ZMAX-1)*pow(1-(in-$F_ZS)/($F_ZE-$F_ZS),2), 1)))"
X="$CX*iw - iw/zoom/2"
Y="$CY*ih - ih/zoom/2"

ffmpeg -y -i "$IN" \
  -loop 1 -t 6 -framerate "$FPS" -i card.png \
  -filter_complex "\
[0:v]fps=$FPS,scale=1920:1080:force_original_aspect_ratio=decrease,\
pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,\
zoompan=z='$Z':x='$X':y='$Y':d=1:s=1920x1080:fps=$FPS,format=yuv420p[main];\
[1:v]fps=$FPS,scale=1920:1080,format=yuv420p[card];\
[main][card]xfade=transition=fade:duration=1.2:offset=$T_FADE[v]" \
  -map "[v]" -t "$TOTAL" -an \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -movflags +faststart \
  "$OUT"

echo "Done: video/$OUT"
