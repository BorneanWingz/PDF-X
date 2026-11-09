"""Build assets/pdf-x.ico from assets/pdf-x.png.

Windows wants a multi-resolution icon (16..256 px) so the exe looks sharp in
Explorer, the taskbar and Alt-Tab. Run after replacing the source artwork:

    uv run python scripts/make_icon.py
"""

from __future__ import annotations

from collections import deque
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "pdf-x.png"
TARGET = ROOT / "assets" / "pdf-x.ico"
# NOTE: 256 must come first - Windows picks the closest match and a missing
# large entry makes the exe fall back to a blurry upscaled 48 px icon
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]


def remove_outer_background(image: Image.Image) -> Image.Image:
    """Make the edge-connected white canvas transparent, retaining its shadow."""
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    pending = deque(
        {(x, y) for x in range(width) for y in (0, height - 1)}
        | {(x, y) for y in range(height) for x in (0, width - 1)}
    )
    visited: set[tuple[int, int]] = set()

    while pending:
        x, y = pending.popleft()
        if (x, y) in visited:
            continue
        visited.add((x, y))
        red, green, blue, _ = pixels[x, y]
        background = min(red, green, blue)
        if background < 64:
            continue

        alpha = 255 - background
        if alpha == 0:
            pixels[x, y] = (0, 0, 0, 0)
        else:
            pixels[x, y] = tuple(
                min(255, round((channel - background) * 255 / alpha))
                for channel in (red, green, blue)
            ) + (alpha,)

        if x > 0:
            pending.append((x - 1, y))
        if x + 1 < width:
            pending.append((x + 1, y))
        if y > 0:
            pending.append((x, y - 1))
        if y + 1 < height:
            pending.append((x, y + 1))

    return rgba


def main() -> int:
    if not SOURCE.is_file():
        print(f"missing source artwork: {SOURCE}", file=sys.stderr)
        return 1

    source = remove_outer_background(Image.open(SOURCE))
    # square canvas, so a non-square source is centred instead of stretched
    side = min(source.size)
    square = source.crop(
        (
            (source.width - side) // 2,
            (source.height - side) // 2,
            (source.width + side) // 2,
            (source.height + side) // 2,
        )
    )
    square.save(
        TARGET,
        format="ICO",
        sizes=SIZES,
    )
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
