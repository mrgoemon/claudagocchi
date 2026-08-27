# Launch video

One-take recording of a fake `claude` launch that hands off to the crab waking
up; the camera zoom is done in post with ffmpeg.

0. `python3 video/capture_banner.py` — records the real Claude launch screen to
   `video/claude_banner.ansi`, which `intro.py` replays verbatim. If Claude has
   never been trusted in this repo it will capture its "do you trust this
   folder?" prompt instead; run `claude` here once by hand, accept, quit, and
   re-run. Re-run after a Claude upgrade too.
1. Set up a terminal window: ≥100 cols, ~18pt font, dark theme, Retina display.
2. `./video/record.sh rect` — click that window to cache its screen region.
3. `./video/record.sh` — after the countdown, run `python3 video/intro.py` in
   the window. 26s later, `video/take.mov` exists.
   (Fallback: record the window with ⌘⇧5 yourself, then run intro.py.)
4. `./video/make_video.sh` — renders `video/claudagocchi_launch.mp4`.
   First take: tune `T0` (recording→intro offset) and `CX`/`CY` (crab center)
   at the top of the script, re-run until the zoom lands on the crab.

`intro.py` fakes the shell prompt and types `claude`, replays the captured
launch screen, then execs `CRAB_INTRO=1 pixel_crab.py --animate` — the env var
holds the crab dead still with an empty speech bubble for 4s (so it reads as a
screenshot), then blinks it awake into the normal boot wave (`_wake_scene`).
The zoom keyframes in `make_video.sh` depend on those fixed timings.

`python3 video/check_intro.py` asserts the opening still holds for 4s with the
eyes open and an empty bubble, blinks on cue, and never changes frame height —
run it after touching `_wake_scene` or the intro timings.
