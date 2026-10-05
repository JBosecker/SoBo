#!/usr/bin/env python3
"""Renders the SoBo brand images (record with label and progress ring, like the guest page).

python scripts/make_brand_images.py --font /path/to/Poppins-Bold.ttf

Writes
* sobo/icon.png (128x128) and sobo/logo.png (250x100) for the app store,
* custom_components/sobo/brand/{icon,icon@2x,logo,logo@2x}.png for the integration
  and dark_logo{,@2x}.png (local brand images, Home Assistant 2026.3+).
Needs Pillow. The images are committed; rerun only when the design changes.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
NIGHT = (30, 36, 51, 255)  # --night
GROOVE = (52, 61, 86, 255)
BAND = (194, 59, 42, 255)  # --band
AMBER = (242, 179, 61, 255)  # --amber
PAPER = (239, 227, 194, 255)  # --paper
SCALE = 8  # supersampling


def record(size: int) -> Image.Image:
    """Square record icon with a transparent background."""
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = s / 2

    def circle(radius: float, **kwargs: object) -> None:
        draw.ellipse((c - radius, c - radius, c + radius, c + radius), **kwargs)  # type: ignore[arg-type]

    outer = s * 0.48
    circle(outer, fill=NIGHT)
    for k in range(4):  # grooves
        circle(outer * (0.88 - k * 0.09), outline=GROOVE, width=max(1, s // 160))
    # progress ring: three quarters played
    ring = outer * 0.94
    width = max(2, int(s * 0.045))
    box = (c - ring, c - ring, c + ring, c + ring)
    draw.arc(box, start=-90, end=180, fill=AMBER, width=width)
    # head of the ring
    angle = math.radians(180)
    hx, hy = c + (ring - width / 2) * math.cos(angle), c + (ring - width / 2) * math.sin(angle)
    head = width * 0.8
    draw.ellipse((hx - head, hy - head, hx + head, hy + head), fill=AMBER)
    circle(outer * 0.42, fill=BAND)  # label
    circle(outer * 0.30, outline=PAPER, width=max(1, s // 110))
    circle(outer * 0.07, fill=NIGHT)  # spindle hole
    return img.resize((size, size), Image.Resampling.LANCZOS)


def logo(
    height: int, font_path: Path, width: int | None = None, ink: tuple[int, ...] = NIGHT
) -> Image.Image:
    """Record + wordmark, transparent, trimmed (or padded to `width`)."""
    s = height * SCALE
    icon = record(height).resize((s, s), Image.Resampling.LANCZOS)
    font = ImageFont.truetype(str(font_path), int(s * 0.62))
    text = "SoBo"
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    gap = int(s * 0.16)
    canvas = Image.new("RGBA", (s + gap + (right - left), s), (0, 0, 0, 0))
    canvas.alpha_composite(icon, (0, 0))
    draw = ImageDraw.Draw(canvas)
    y = (s - (bottom - top)) / 2 - top
    draw.text((s + gap - left, y), text, font=font, fill=ink)
    out = canvas.resize((round(canvas.width / SCALE), height), Image.Resampling.LANCZOS)
    if width is not None and out.width != width:
        if out.width > width:
            ratio = width / out.width
            out = out.resize((width, round(height * ratio)), Image.Resampling.LANCZOS)
        padded = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        padded.alpha_composite(out, ((width - out.width) // 2, (height - out.height) // 2))
        out = padded
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=Path, required=True, help="bold TTF for the wordmark")
    args = parser.parse_args()

    app = ROOT / "sobo"
    record(128).save(app / "icon.png", optimize=True)
    logo(100, args.font, width=250).save(app / "logo.png", optimize=True)

    brand = ROOT / "custom_components" / "sobo" / "brand"
    brand.mkdir(exist_ok=True)
    record(256).save(brand / "icon.png", optimize=True)
    record(512).save(brand / "icon@2x.png", optimize=True)
    logo(128, args.font).save(brand / "logo.png", optimize=True)
    logo(256, args.font).save(brand / "logo@2x.png", optimize=True)
    # Wordmark in light ink for the dark theme
    logo(128, args.font, ink=PAPER).save(brand / "dark_logo.png", optimize=True)
    logo(256, args.font, ink=PAPER).save(brand / "dark_logo@2x.png", optimize=True)
    print("brand images written")


if __name__ == "__main__":
    main()
