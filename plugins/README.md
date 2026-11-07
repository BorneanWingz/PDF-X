# Plugins folder

Drop optional converter plugins here next to `PDFToolbox.exe` (or beside the
repository root during development). The app scans this folder at startup.

## Contract

A plugin is a single `.py` file with:

```python
NAME = "pdf2docx"              # shown in logs and the GUI
VERSION = "0.5.13"
LICENSE = "AGPL-3.0"
TARGETS = ["docx"]             # conversion targets it provides
AVAILABILITY_HINT = "install with: ..."   # optional message when unavailable

def available() -> bool:       # optional; return False when deps are missing
    ...

def convert(src: "Path", out_dir: "Path") -> "Path":
    ...
```

- A plugin that raises on import, is missing `TARGETS`, or whose
  `available()` returns False is reported as unavailable — the app keeps
  working without it.
- Optional page selection: declare `def convert(src, out_dir, pages=None)`
  and the app passes a list of 1-based page numbers when the user asks
  for one. Plugins with the older signature keep working unchanged.
- Optional OCR layer: declare
  `def convert(src, out_dir, pages=None, ocr_layer=False)` and the app sets
  `ocr_layer=True` when it OCR'd the source first (a scan with no text layer).
  The engine then receives a searchable PDF whose text is invisible, which
  some libraries drop by default.
- Optional output name: declare
  `def convert(src, out_dir, pages=None, ocr_layer=False, out_name=None)` and
  the app passes the name it wants for the result, e.g. `report_pdfx.docx`.
  It is a file name only, so write `out_dir / out_name`. Every output the app
  produces is named `<original stem>_pdfx.<ext>`; a plugin without `out_name`
  still works — its file is simply renamed afterwards.
- `LICENSE` is informational: keep AGPL plugins separate from permissive
  builds. The build script's `clean` mode excludes everything except this
  README.
