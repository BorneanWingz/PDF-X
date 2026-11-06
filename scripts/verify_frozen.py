"""Verify frozen-exe outputs (run after the exe validation commands)."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

root = Path(sys.argv[1] if len(sys.argv) > 1 else "exe-test")
failures = 0
IMAGE_SUFFIXES = (".png", ".jpeg", ".jpg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf")


def check(label: str, condition: bool, detail: str) -> None:
    global failures
    status = "OK " if condition else "FAIL"
    if not condition:
        failures += 1
    print(f"{status} {label}: {detail}")


def image_parts(path: Path) -> list[str]:
    """Image parts inside an OOXML package (word/media/*, thumbnail, ...)."""
    with zipfile.ZipFile(str(path)) as archive:
        return [n for n in archive.namelist() if n.lower().endswith(IMAGE_SUFFIXES)]


docx_files = list((root / "docx").glob("*.docx"))
if docx_files:
    document = Document(str(docx_files[0]))
    text = "\n".join(p.text for p in document.paragraphs)
    check("docx exists", True, f"{len(text)} chars")
    check("docx has pages 2-3 content", len(text) > 500, text[:60].replace("\n", " "))
    check("docx holds no images", not image_parts(docx_files[0]), str(image_parts(docx_files[0])))
else:
    check("docx exists", False, "missing")

searchable = list((root / "searchable").glob("*.pdf"))
if searchable:
    reader = PdfReader(str(searchable[0]))
    text = "".join(p.extract_text() or "" for p in reader.pages)
    check("searchable pages", len(reader.pages) == 2, str(len(reader.pages)))
    check("searchable text layer", len(text) > 2000, f"{len(text)} chars")
else:
    check("searchable exists", False, "missing")

xlsx_files = list((root / "xlsx").glob("*.xlsx"))
if xlsx_files:
    workbook = load_workbook(xlsx_files[0])
    rows = sum(1 for ws in workbook.worksheets for row in ws.iter_rows() if any(c.value for c in row))
    embedded = [im for ws in workbook.worksheets for im in ws._images]
    check("xlsx tables", rows > 0, f"{len(workbook.worksheets)} sheet(s), {rows} rows")
    check("xlsx holds no images", not embedded, f"{len(embedded)} image(s)")
else:
    check("xlsx exists", False, "missing")

print("FROZEN VERIFY:", "FAIL" if failures else "OK")
raise SystemExit(1 if failures else 0)
