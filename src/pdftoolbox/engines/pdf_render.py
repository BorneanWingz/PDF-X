"""Render PDF pages to images using pypdfium2 (PDFium, Apache-2.0/BSD)."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

from . import ConversionError

_FORMATS = {
    "png": ("PNG", None),
    "jpg": ("JPEG", {"quality": 90}),
    "tif": ("TIFF", {"compression": "tiff_deflate"}),
    "tiff": ("TIFF", {"compression": "tiff_deflate"}),
}


def render_page_pil(src: Path, index: int, dpi: int):
    """Return a PIL image for one page (0-based index)."""
    doc = pdfium.PdfDocument(str(src))
    try:
        page = doc[index]
        bitmap = page.render(scale=dpi / 72.0)
        return bitmap.to_pil().convert("RGB")
    finally:
        doc.close()


def pdf_to_images(
    src: Path,
    out_dir: Path,
    fmt: str = "png",
    dpi: int = 150,
    pages: list[int] | None = None,
) -> list[Path]:
    """Render every page (or the given 1-based pages) to image files."""
    fmt = fmt.lower()
    if fmt not in _FORMATS:
        raise ConversionError(f"unsupported image format: {fmt}")
    pil_format, save_kwargs = _FORMATS[fmt]
    ext = "tif" if fmt == "tiff" else fmt

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(src))
    outputs: list[Path] = []
    try:
        count = len(doc)
        indices = [p - 1 for p in pages] if pages else list(range(count))
        for i in indices:
            if i < 0 or i >= count:
                raise ConversionError(f"page {i + 1} out of range (1-{count})")
            page = doc[i]
            bitmap = page.render(scale=dpi / 72.0)
            image = bitmap.to_pil()
            if pil_format == "JPEG":
                image = image.convert("RGB")
            out = out_dir / f"{src.stem}_page{i + 1:04d}.{ext}"
            image.save(out, format=pil_format, **(save_kwargs or {}))
            outputs.append(out)
    finally:
        doc.close()
    return outputs
