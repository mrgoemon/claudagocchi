# Launch video

One-take recording of a fake `claude` launch that hands off to the crab waking
up; the camera zoom is done in post with ffmpeg.

1. Set up a terminal window: ≥100 cols, ~18pt font, dark theme, Retina display.
2. `./video/record.sh rect` — click that window to cache its screen region.
3. `./video/record.sh` — after the countdown, run `python3 video/intro.py` in
   the window. 26s later, `video/take.mov` exists.
   (Fallback: record the window with ⌘⇧5 yourself, then run intro.py.)
4. `./video/make_video.sh` — renders `video/claudagocchi_launch.mp4`.
   First take: tune `T0` (recording→intro offset) and `CX`/`CY` (crab center)
   at the top of the script, re-run until the zoom lands on the crab.

`intro.py` fakes the prompt + `claude` + welcome, then execs
`CRAB_INTRO=1 pixel_crab.py --animate` — the env var adds a sleep→blink→wave
opening (`_wake_scene`) with fixed timings the zoom keyframes rely on.
