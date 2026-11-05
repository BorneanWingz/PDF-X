"""Extract text and HTML from PDFs using pypdf (BSD-3-Clause)."""

from __future__ import annotations

import html
from pathlib import Path

from pypdf import PdfReader

from . import ConversionError


def _reader(src: Path) -> PdfReader:
    try:
        return PdfReader(str(src))
    except Exception as exc:  # noqa: BLE001 - surface any parse failure uniformly
        raise ConversionError(f"cannot read PDF: {exc}") from exc


def page_count(src: Path) -> int:
    return len(_reader(src).pages)


def extract_pages(src: Path) -> list[str]:
    pages: list[str] = []
    for page in _reader(src).pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a bad page must not kill the batch
            pages.append("")
    return pages


def pdf_to_text(src: Path, out_path: Path) -> Path:
    pages = extract_pages(src)
    chunks = []
    for number, text in enumerate(pages, start=1):
        chunks.append(f"----- Page {number} -----\n{text.strip()}\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(chunks), encoding="utf-8")
    return out_path


def pdf_to_html(src: Path, out_path: Path) -> Path:
    pages = extract_pages(src)
    body_parts = []
    for number, text in enumerate(pages, start=1):
        body_parts.append(
            f"<h3>Page {number}</h3>\n<pre>{html.escape(text.strip())}</pre>"
        )
    document = (
        "<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(src.stem)}</title></head>\n<body>\n"
        + "\n".join(body_parts)
        + "\n</body></html>\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    return out_path
