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
- `LICENSE` is informational: keep AGPL plugins separate from permissive
  builds. The build script's `clean` mode excludes everything except this
  README.
