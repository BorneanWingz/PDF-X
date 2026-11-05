"""PDF -> DOCX converter plugin (AGPL component, isolated on purpose).

This plugin uses pdf2docx / PyMuPDF, which are AGPL-3.0. It lives outside
the core package so permissive builds can exclude this single file.

AGPL NOTICE: if you bundle or redistribute this file together with its
dependencies, the combined work falls under AGPL-3.0 terms.

Copy the whole plugins/ folder next to PDFToolbox.exe to enable it.
"""

from __future__ import annotations

from pathlib import Path

NAME = "pdf2docx"
VERSION = "0.5.13"
LICENSE = "AGPL-3.0"
TARGETS = ["docx"]
AVAILABILITY_HINT = "install with: uv pip install pdf2docx (AGPL-3.0)"


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pdf2docx") is not None


def convert(src: Path, out_dir: Path, pages: "list[int] | None" = None) -> Path:
    from pdf2docx import Converter

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{src.stem}.docx"

    # pdf2docx converts one contiguous range; a page list uses its span
    start = 0
    end = None
    if pages:
        start = max(0, min(pages) - 1)
        end = max(pages)

    converter = Converter(str(src))
    try:
        converter.convert(str(out_path), start=start, end=end)
    finally:
        converter.close()
    return out_path
