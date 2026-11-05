"""PDF to PPTX: one slide per page with the rendered page image."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from pptx import Presentation
from pptx.util import Emu

from . import ConversionError

# 16:9 slide, in EMU (914400 EMU per inch)
_SLIDE_W = Emu(int(13.333 * 914400))
_SLIDE_H = Emu(int(7.5 * 914400))


def pdf_to_pptx(
    src: Path,
    out_path: Path,
    dpi: int = 150,
    pages: list[int] | None = None,
) -> Path:
    presentation = Presentation()
    presentation.slide_width = _SLIDE_W
    presentation.slide_height = _SLIDE_H
    blank_layout = presentation.slide_layouts[6]

    doc = pdfium.PdfDocument(str(src))
    try:
        count = len(doc)
        if count == 0:
            raise ConversionError("PDF has no pages")
        indices = [p - 1 for p in pages] if pages else list(range(count))
        for index in indices:
            if index < 0 or index >= count:
                raise ConversionError(f"page {index + 1} out of range (1-{count})")
            page = doc[index]
            width_pt, height_pt = page.get_size()
            bitmap = page.render(scale=dpi / 72.0)
            image = bitmap.to_pil()
            # NOTE: python-pptx needs an on-disk image file, so each page is
            # dumped to a hidden temp PNG and deleted right after embedding
            tmp = out_path.parent / f".{out_path.stem}_page{index + 1}.png"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            image.save(tmp, format="PNG")

            slide = presentation.slides.add_slide(blank_layout)
            # fit page image inside the slide, keep aspect ratio
            page_ratio = width_pt / height_pt if height_pt else 1.0
            slide_ratio = _SLIDE_W / _SLIDE_H
            if page_ratio > slide_ratio:
                width = _SLIDE_W
                height = Emu(int(_SLIDE_W / page_ratio))
            else:
                height = _SLIDE_H
                width = Emu(int(_SLIDE_H * page_ratio))
            left = Emu(int((_SLIDE_W - width) / 2))
            top = Emu(int((_SLIDE_H - height) / 2))
            slide.shapes.add_picture(str(tmp), left, top, width=width, height=height)
            tmp.unlink(missing_ok=True)
    finally:
        doc.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(out_path)
    return out_path
