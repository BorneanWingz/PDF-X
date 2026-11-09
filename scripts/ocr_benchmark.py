"""Measure OCR detection settings against known ground truth.

Why this exists: the detection knobs in ``config.json`` (``ocr_max_side_len``,
``ocr_unclip_ratio``) were nearly shipped set to values that looked better on a
synthetic page and were worse on a realistic one. This script is the evidence
that keeps the defaults honest, and the place to re-run whenever RapidOCR or the
bundled models change.

Two things it deliberately does the hard way, because getting them wrong hides
real regressions:

* it renders through **pypdfium2 exactly as the app does**, so the pixel input
  matches production;
* it treats **word spacing as significant**. An earlier revision scored with
  whitespace collapsed, which made a detector that merges words
  (``solids12.450mgperlitre``) look perfect. Spacing matters because the
  table/XLSX rebuild reads these lines.

Usage:
    python scripts/ocr_benchmark.py                 # settings matrix, 200 DPI
    python scripts/ocr_benchmark.py --dpi 300
    python scripts/ocr_benchmark.py --dump          # print recognised lines
    python scripts/ocr_benchmark.py --models        # bundled vs detached models

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
import pypdfium2 as pdfium  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

FONT_PATH = "C:/Windows/Fonts/arial.ttf"

# A ruled table with small cells plus a small body line. Small text is the
# sensitive part: it is what loses its spaces first.
CELLS = ["Sample", "Moisture", "N", "FWR1", "73.30", "0.64", "FWR2", "70.86", "0.61"]
BODY = "Total dissolved solids 12.450 mg per litre"
_TABLE_ROWS = [CELLS[0:3], CELLS[3:6], CELLS[6:9]]


def _font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, max(7, size))
    except OSError:  # pragma: no cover - non-Windows dev machines
        return ImageFont.load_default()


def build_sample_pdf(target: Path, dpi: int) -> list[str]:
    """Write the reference table scan, returning the expected tokens."""
    scale = dpi / 200.0
    width, height = int(8.27 * dpi), int(11.69 * dpi)
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
    image.save(target, "PDF", resolution=dpi)
    return CELLS + [BODY]


def render(pdf_path: Path, dpi: int, degraded: bool) -> Image.Image:
    """Render page 1 through pypdfium2, exactly like engines/ocr.py does.

    ``degraded`` adds the blur and speckle of a real flatbed scan.
    """
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        image = doc[0].render(scale=dpi / 72.0).to_pil().convert("RGB")
    finally:
        doc.close()
    if not degraded:
        return image
    image = image.filter(ImageFilter.GaussianBlur(0.6))
    array = np.asarray(image).astype(np.int16)
    noise = np.random.default_rng(7).normal(0, 9, array.shape)
    return Image.fromarray(np.clip(array + noise, 0, 255).astype(np.uint8))


def tight(text: str) -> str:
    # NOTE: collapses runs of spaces but PRESERVES that spaces exist, so a line
    # that lost its spacing entirely can never compare equal to the expectation
    return " ".join(text.split())


def score(lines: list[str]) -> tuple[int, int, bool]:
    """(cells found, cells total, body line reproduced with its spacing)."""
    got = [tight(line) for line in lines]
    cells = sum(1 for cell in CELLS if any(tight(cell) in line for line in got))
    body_ok = tight(BODY) in got
    return cells, len(CELLS), body_ok


# The settings matrix. The first row is what the app ships.
CANDIDATES: list[tuple[str, dict]] = [
    ("shipped (stock)", {"max_side_len": 2000, "det_unclip_ratio": 1.6}),
    ("msl=2400", {"max_side_len": 2400, "det_unclip_ratio": 1.6}),
    ("msl=2600", {"max_side_len": 2600, "det_unclip_ratio": 1.6}),
    ("msl=3000", {"max_side_len": 3000, "det_unclip_ratio": 1.6}),
    ("msl=2000 unclip=1.8", {"max_side_len": 2000, "det_unclip_ratio": 1.8}),
    ("msl=3000 unclip=1.8", {"max_side_len": 3000, "det_unclip_ratio": 1.8}),
]


def shipped_kwargs() -> dict:
    """Exactly what the app builds, resolved by the OCR engine itself."""
    from pdftoolbox.engines import ocr as ocr_engine

    return ocr_engine.tuning_from_config({})


def run(label: str, kwargs: dict, image: Image.Image, dump: bool) -> None:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR(**kwargs)
    started = time.perf_counter()
    raw, _ = engine(np.asarray(image))
    elapsed = time.perf_counter() - started
    lines = [item[1] for item in (raw or [])]
    cells, total, body_ok = score(lines)
    flag = "ok " if (cells == total and body_ok) else "!! "
    print(
        f"  {flag}{label:<20} cells={cells}/{total}  body_spacing={'yes' if body_ok else 'LOST':<3}  "
        f"{elapsed:5.2f}s"
    )
    if dump:
        print("        " + " | ".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=200, help="render DPI (default 200)")
    parser.add_argument("--dump", action="store_true", help="print recognised lines")
    parser.add_argument(
        "--models",
        action="store_true",
        help="use the detached set in models/rapidocr instead of the bundled models",
    )
    args = parser.parse_args()

    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        pdf_path = Path(scratch) / "sample.pdf"
        build_sample_pdf(pdf_path, args.dpi)

        for degraded in (False, True):
            image = render(pdf_path, args.dpi, degraded)
            heading = "degraded scan" if degraded else "clean render"
            print(f"{heading} - A4 @ {args.dpi} DPI, {image.width}x{image.height} px")

            if args.models:
                from pdftoolbox.engines import ocr as ocr_engine

                detached = ocr_engine._configured_model_dir()
                print(f"  detached model set: {detached or 'none (bundled models)'}")
                run("shipped settings", shipped_kwargs(), image, args.dump)
            else:
                for label, kwargs in CANDIDATES:
                    run(label, kwargs, image, args.dump)
            print()

    print("shipped settings as the app resolves them:", shipped_kwargs())
    print(
        "\nA '!!' row is a regression: either a cell went missing or the body line\n"
        "lost its word spacing. Both matter to the XLSX/table rebuild."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

