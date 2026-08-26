#!/usr/bin/env python3
"""Render the end card to video/card.png (1920x1080).

A PNG because the Homebrew ffmpeg build has no drawtext filter; make_video.sh
just fades to this image.
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (22, 22, 29)
CORAL = (255, 136, 102)
GRAY = (170, 170, 170)
MENLO = "/System/Library/Fonts/Menlo.ttc"

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

title = ImageFont.truetype(MENLO, 110)
sub = ImageFont.truetype(MENLO, 42)


def center(text, font, y, fill, emoji=False):
    x = (W - d.textlength(text, font=font)) / 2
    d.text((x, y), text, font=font, fill=fill, embedded_color=emoji)


center("claudagocchi", title, H / 2 - 130, CORAL)
center("github.com/mrgoemon/claudagocchi", sub, H / 2 + 60, GRAY)

try:  # the crab, if Apple's emoji font cooperates; the card works without it
    # Apple Color Emoji is a bitmap font: only its fixed sizes load, 160 is max
    emoji_font = ImageFont.truetype("/System/Library/Fonts/Apple Color Emoji.ttc",
                                    160)
    x = (W - d.textlength("🦀", font=emoji_font)) / 2
    d.text((x, H / 2 - 330), "🦀", font=emoji_font, embedded_color=True)
except Exception:
    pass

img.save(__file__.rsplit("/", 1)[0] + "/card.png")
print("wrote video/card.png")
