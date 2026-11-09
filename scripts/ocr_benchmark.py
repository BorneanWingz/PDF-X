"""Measure OCR detection settings on synthetic scans with known ground truth.

Why this exists: the tuning defaults in ``config.py`` and ``engines/ocr.py``
were chosen from numbers, not taste. RapidOCR's stock ``max_side_len=2000``
downscales an A4 page rendered at 200 DPI (1654x2338 px) before detection, which
merged text across table cells and dropped whole values from the XLSX export.
This script regenerates that measurement, so the defaults can be re-justified or
revisited whenever RapidOCR or the bundled models change.

Two metrics, because they disagree:

* **tokens** - a table cell or body line the OCR output still contains. This is
  what the spreadsheet export actually needs, and it catches merged words that
  character-level accuracy happily ignores.
* **exact** - lines reproduced character-for-character.

Usage:
    python scripts/ocr_benchmark.py                  # tuning candidates
    python scripts/ocr_benchmark.py --dump           # also print recognised text
    python scripts/ocr_benchmark.py --models         # bundled vs detached models
    python scripts/ocr_benchmark.py --dpi 300

``--models`` reads the optional detached set from ``models/rapidocr``; fetch it
with ``scripts\\download-ocr-models.ps1``. Nothing here needs the network.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

FONT_PATH = "C:/Windows/Fonts/arial.ttf"

# A ruled table plus two small body lines: the layout that motivated the review.
CELLS = [
    "Sample", "Moisture", "N",
    "FWR1", "73.30", "0.64",
    "FWR2", "70.86", "0.61",
    "AK4R1", "0.32", "32.22",
]
BODY = "Total dissolved solids 12.450 mg per litre"
REF = "Ref No : A-2026-0931-ID"
EXPECTED = CELLS + [BODY, REF]

# Rows of the synthetic table, in drawing order.
_TABLE_ROWS = [CELLS[0:3], CELLS[3:6], CELLS[6:9], CELLS[9:12]]


def _font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, max(7, size))
    except OSError:  # pragma: no cover - non-Windows dev machines
        return ImageFont.load_default()


def _layout(dpi: int) -> tuple[Image.Image, list[str]]:
    """Draw the reference layout at ``dpi``: (image, expected tokens)."""
    width, height = int(8.27 * dpi), int(11.69 * dpi)
    scale = dpi / 200.0
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    cell_font = _font(int(20 * scale))
    body_font = _font(int(15 * scale))

    left, top = int(200 * scale), int(300 * scale)
    col_w, row_h = int(380 * scale), int(90 * scale)
    for row_index, row in enumerate(_TABLE_ROWS):
        for col_index, cell in enumerate(row):
            x = left + col_index * col_w
            y = top + row_index * row_h
            draw.rectangle([x, y, x + col_w, y + row_h], outline="black", width=2)
            draw.text(
                (x + int(14 * scale), y + int(28 * scale)),
                cell,
                fill="black",
                font=cell_font,
            )

    draw.text((left, int(800 * scale)), BODY, fill="black", font=body_font)
    draw.text((left, int(860 * scale)), REF, fill="black", font=body_font)
    return image, EXPECTED


def scan_page(dpi: int) -> tuple[Image.Image, list[str]]:
    """A degraded scan: slight blur plus speckle noise, like a flatbed output."""
    image, expected = _layout(dpi)
    image = image.filter(ImageFilter.GaussianBlur(0.6))
    array = np.asarray(image).astype(np.int16)
    noise = np.random.default_rng(7).normal(0, 9, array.shape)
    return Image.fromarray(np.clip(array + noise, 0, 255).astype(np.uint8)), expected


def clean_page(dpi: int) -> tuple[Image.Image, list[str]]:
    """A crisp page. Any candidate that scores worse here is a regression."""
    image, expected = _layout(dpi)
    return image, expected


def squash(text: str) -> str:
    return " ".join(text.upper().split())


def score(expected: list[str], lines: list[str]) -> tuple[float, int]:
    """(token recovery %, exact line matches)."""
    found = 0
    for token in expected:
        needle = squash(token)
        if any(needle in squash(line) for line in lines):
            found += 1
    exact = sum(
        1 for token in expected if any(squash(line) == squash(token) for line in lines)
    )
    return found / len(expected) * 100, exact


# Tuning candidates. The second entry is what the app actually ships.
CANDIDATES: list[tuple[str, dict]] = [
    ("stock RapidOCR", {"max_side_len": 2000, "det_unclip_ratio": 1.6}),
    ("shipped (config default)", {"max_side_len": 3000, "det_unclip_ratio": 1.8}),
    ("msl=3000 unclip=1.6", {"max_side_len": 3000, "det_unclip_ratio": 1.6}),
    ("msl=3000 unclip=2.2", {"max_side_len": 3000, "det_unclip_ratio": 2.2}),
    ("msl=4000 unclip=1.8", {"max_side_len": 4000, "det_unclip_ratio": 1.8}),
]


def shipped_kwargs() -> dict:
    """Exactly what the app builds, resolved by the OCR engine itself."""
    from pdftoolbox.engines import ocr as ocr_engine

    return ocr_engine.tuning_from_config({})


def run(label: str, kwargs: dict, image: Image.Image, expected: list[str], dump: bool) -> None:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR(**kwargs)
    started = time.perf_counter()
    raw, _ = engine(np.asarray(image))
    elapsed = time.perf_counter() - started
    lines = [item[1] for item in (raw or [])]
    recovery, exact = score(expected, lines)
    print(
        f"  {label:<26} tokens={recovery:6.1f}%  exact={exact:2d}/{len(expected)}  "
        f"lines={len(lines):3d}  {elapsed:5.2f}s"
    )
    if dump:
        print("      " + " | ".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=200, help="render DPI (default 200)")
    parser.add_argument("--dump", action="store_true", help="print recognised lines")
    parser.add_argument(
        "--models",
        action="store_true",
        help="compare bundled models against the detached set in models/rapidocr",
    )
    args = parser.parse_args()

    scan, expected_scan = scan_page(args.dpi)
    print(
        f"A4 @ {args.dpi} DPI ({scan.width}x{scan.height} px), "
        f"{len(expected_scan)} expected cells/lines\n"
    )

    if args.models:
        from pdftoolbox.engines import ocr as ocr_engine

        detached = ocr_engine._configured_model_dir()
        print(f"detached model set: {detached or 'none found (bundled models in use)'}\n")
        print("scan page (degraded)")
        run("shipped tuning + models", shipped_kwargs(), scan, expected_scan, args.dump)
        return 0

    print("scan page (degraded) - the case table extraction depends on")
    for label, kwargs in CANDIDATES:
        run(label, kwargs, scan, expected_scan, args.dump)

    clean, expected_clean = clean_page(args.dpi)
    print("\nclean page - a regression check, not a target")
    for label, kwargs in CANDIDATES:
        run(label, kwargs, clean, expected_clean, args.dump)

    print("\nshipped settings as the app resolves them:", shipped_kwargs())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
