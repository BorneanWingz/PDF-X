"""Build assets/pdf-x.ico from assets/pdf-x.jpeg.

Windows wants a multi-resolution icon (16..256 px) so the exe looks sharp in
Explorer, the taskbar and Alt-Tab. Run after replacing the source artwork:

    uv run python scripts/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "pdf-x.jpeg"
TARGET = ROOT / "assets" / "pdf-x.ico"
# NOTE: 256 must come first - Windows picks the closest match and a missing
# large entry makes the exe fall back to a blurry upscaled 48 px icon
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]


def main() -> int:
    if not SOURCE.is_file():
        print(f"missing source artwork: {SOURCE}", file=sys.stderr)
        return 1

    source = Image.open(SOURCE).convert("RGBA")
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
