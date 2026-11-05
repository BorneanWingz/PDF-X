"""End-to-end verification on a real document (not part of the test suite)."""

from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pypdf import PdfReader


def main() -> int:
    out = Path("samples-out")
    failures = 0

    txt_files = list((out / "txt").glob("*.txt"))
    if txt_files:
        text = txt_files[0].read_text(encoding="utf-8")
        print(f"txt: {len(text)} chars, head={text[:60]!r}")
    else:
        print("txt: MISSING")
        failures += 1

    pptx_files = list((out / "pptx2").glob("*.pptx"))
    if pptx_files:
        slides = len(Presentation(str(pptx_files[0])).slides)
        print(f"pptx (pages=1-2): {slides} slides")
        if slides != 2:
            failures += 1
    else:
        print("pptx: MISSING")
        failures += 1

    searchable = list((out / "searchable").glob("*.pdf"))
    if searchable:
        reader = PdfReader(str(searchable[0]))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        print(f"searchable: {len(reader.pages)} pages, {len(text)} text chars")
        print(f"searchable sample: {text[:100]!r}")
        if "PDF" not in text.upper() and "OCR" not in text.upper():
            failures += 1
    else:
        print("searchable: MISSING")
        failures += 1

    png_files = list((out / "png").glob("*.png"))
    print(f"png: {len(png_files)} file(s)")

    print("VERIFY:", "FAIL" if failures else "OK")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
