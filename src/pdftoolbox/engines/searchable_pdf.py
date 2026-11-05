"""Write a searchable PDF: original pages plus an invisible OCR text layer.

The text layer is drawn with ReportLab (BSD) in render mode 3 (invisible)
and merged with pypdf (BSD). No AGPL components are used.
"""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from . import ConversionError
from .ocr import OcrPage

_CANDIDATE_FONTS = [
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
]
_FONT_NAME = "Helvetica"  # fallback for non-latin scripts; ASCII-safe glyphs


def _register_font() -> None:
    global _FONT_NAME
    for candidate in _CANDIDATE_FONTS:
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont("OcrLayerFont", str(candidate)))
                _FONT_NAME = "OcrLayerFont"
                return
            except Exception:  # noqa: BLE001
                continue


def _build_overlay(pages: list[OcrPage], dpi: int) -> bytes:
    """One invisible-text page per OCR page, sized like the rendered page."""
    _register_font()
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    scale = 72.0 / dpi  # rendered px -> PDF points

    for page in pages:
        width_pt = page.width * scale
        height_pt = page.height * scale
        pdf.setPageSize((width_pt, height_pt))

        for line in page.lines:
            if not line.text.strip():
                continue
            x0, y0, x1, y1 = line.box
            box_w = max(1.0, (x1 - x0) * scale)
            box_h = max(1.0, (y1 - y0) * scale)
            font_size = max(4.0, box_h * 0.85)
            text = line.text
            # shrink the font until the text fits the detected box width
            guard = 0
            while (
                pdfmetrics.stringWidth(text, _FONT_NAME, font_size) > box_w
                and font_size > 4.0
                and guard < 24
            ):
                font_size *= 0.92
                guard += 1
            if pdfmetrics.stringWidth(text, _FONT_NAME, font_size) > box_w * 1.6:
                text = simpleSplit(text, _FONT_NAME, font_size, box_w)[0] if text else ""
            if not text:
                continue
            pdf.setFont(_FONT_NAME, font_size)
            text_object = pdf.beginText(x0 * scale, height_pt - (y1 * scale))
            text_object.setFont(_FONT_NAME, font_size)
            text_object.setTextRenderMode(3)  # invisible
            text_object.textOut(text)
            pdf.drawText(text_object)

        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def make_searchable_pdf(src: Path, out_path: Path, pages: list[OcrPage], dpi: int) -> Path:
    if not pages:
        raise ConversionError("nothing to write: OCR returned no pages")

    overlay_bytes = _build_overlay(pages, dpi)

    try:
        base_reader = PdfReader(str(src))
        overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"cannot merge text layer: {exc}") from exc

    overlay_pages = list(overlay_reader.pages)
    writer = PdfWriter()
    # only the pages that were OCR'd end up in the output, in order
    for index, ocr_page in enumerate(pages):
        base_index = ocr_page.number - 1
        if base_index < 0 or base_index >= len(base_reader.pages):
            continue
        writer.add_page(base_reader.pages[base_index])
        if index < len(overlay_pages):
            try:
                writer.pages[-1].merge_page(overlay_pages[index])
            except Exception:  # noqa: BLE001 - keep the original page on failure
                pass
    writer.add_metadata({"/Producer": "PDF Toolbox (offline)"})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        writer.write(handle)
    return out_path
