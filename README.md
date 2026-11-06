# PDF-X

**Version 0.1.2**

Portable, offline PDF converter and OCR toolbox for internal team use.
Build and release notes: [docs/PLAN.md](docs/PLAN.md).

- **GUI**: double-click `PDF-X.exe` (tkinter, no external runtime needed)
  - **Convert File** tab holds every conversion option; an **About** tab carries
    the version and author details
  - "Output in same folder" checkbox: writes results beside each input file and
    disables the Output folder field and Browse button while ticked
  - pressing Convert with neither an output folder nor the checkbox ticked asks
    first: write beside the input, choose a folder, or cancel
  - the checkbox, the DPI settings and the chosen output folder are saved in
    `config.json` and restored on the next run
  - the file pickers reopen in the folder of the last imported file
  - files can also be dragged onto the file list to add them
  - **Pages** limits the conversion to part of a PDF: leave it blank for every
    page, or give 1-based numbers and ranges such as `1-3,5`. It applies to PDF
    input only, and merge ignores it.
  - **Advanced Options** holds the Image DPI (PNG/JPG/TIF/PPTX resolution) and
    OCR DPI (scan-reading resolution) knobs and is folded away by default
- **CLI**: `PDF-X-CLI.exe report.pdf --to png --dpi 200`
  - `--list-targets --verbose` prints each target together with the label the
    GUI shows, which makes a build checkable without opening a window
  - `--doctor` reports the state of every engine, plugin and the OCR models
- **No admin rights, no registry writes, no telemetry**: everything lives beside the executable.
- **Offline by default**: only the optional promo banner check makes a network call, with a
  2-second timeout and silent failure.

## What's new in 0.1.2

- **Every table on a scanned page now reaches its own sheet.** A lab report that
  stacks two tables used to export only the first one, and the column header row
  was dropped from it — which is what "OCR did not recognise all the tables"
  actually was. Tables are now split by column layout *and* by the vertical gap
  between them, and a header that OCR groups as its own band is folded back in.
- **Address blocks no longer become tables.** A two-column `Ref No : ...` /
  `From : ...` block has the same shape as a table, so it used to land on a
  sheet of its own. A real table spans most of the page width; a label/value
  block does not, and that is now the test.

## What's new in 0.1.1

- **Bundled LibreOffice engine**, so Office documents convert to PDF out of the
  box with no system install and no admin rights.
- **Scanned files with an image or logo header no longer break Excel export.**
  A letterhead used to be read as the page's table, hiding the real one, and a
  stray control byte in a cell raised `IllegalCharacterError` which aborted the
  entire batch. Tables are now rebuilt from the OCR word boxes, and a failing
  file is reported on its own without stopping the rest.
- **DOCX and XLSX hold real content, never a picture of the page.** Every image
  part is stripped from the DOCX after conversion (a 10-page sample fell from
  118 KB to 49 KB with all 30 tables and 170 paragraphs intact).
- **Results are written beside the input.** No `<name>_output` subfolder is
  created any more.
- **Remembered settings**: the last import folder, the "Output in same folder"
  choice, the DPI values and the output folder all survive a restart.
- **Clearer conversion panel**: the tab is now **Convert File**, **Pages** has an
  inline explanation of its syntax, and the DPI knobs moved into a collapsed
  **Advanced Options** block.
- **Window icon** now matches `assets/pdf-x.ico` in the title bar and taskbar,
  not just in Explorer.
- **New `--verbose` flag** for `--list-targets`, so a build can be checked
  without opening the GUI.

## Supported conversions

| Source | Target |
| --- | --- |
| PDF | PNG, JPG, TIF, TXT, HTML, XLSX (tables), PPTX, DOCX |
| PDF (scanned) | Searchable PDF (invisible OCR text layer), TXT, HTML, XLSX, PPTX, DOCX |
| 2+ PDFs | Merged PDF (`--to merge`, "PDF (merge all inputs)") |
| PNG, JPG, TIF, BMP, WebP | PDF |
| TXT, MD | PDF |
| DOC, DOCX, XLS, XLSX, PPT, PPTX, ODT, ODS, ODP, RTF, CSV | PDF (LibreOffice engine, bundled) |

DOCX conversion comes from the optional `pdf2docx` plugin in `plugins\`. When it
is not installed the target still appears in the list but is reported as
unavailable, so the rest of the toolbox keeps working.

Merge notes: output pages follow the listed input order exactly; the merged
file is `<first_name>_merged.pdf` beside the first input, and an existing
file is never overwritten (a ` (1)` suffix is chosen instead).

Scanned input: any conversion that reads the PDF text layer (TXT, HTML, XLSX,
PPTX, DOCX) runs OCR first when the input has no text layer, so a scan no longer
produces an empty file. The OCR copy is temporary: only the requested output is
written to the output folder, and its name matches the non-scanned path
(`scan.pdf` -> `scan.txt`, not `scan_searchable.txt`).

Office output is real content, never a picture of the page: XLSX holds extracted
table cells and DOCX holds extracted text, tables and paragraphs. pdf2docx
rasterises decorative page furniture into full-page PNGs, so the DOCX plugin
strips every image part (including the document thumbnail) after conversion —
a 10-page sample drops from 118 KB to 49 KB while all 30 tables and 170
paragraphs survive.

Scans with an image/logo header: a letterhead is not a table, but OCR turns it
into a dense block of short text that pdfplumber reported as the page's table,
hiding the real one and (with a stray control byte in a cell) aborting a whole
batch with `IllegalCharacterError`. Scanned tables are now rebuilt from the OCR
word boxes — row bands are grouped, single-cell header bands are dropped and the
longest run of rows sharing a column layout becomes the sheet — and any
workbook write failure is reported as one failed file instead of killing the
rest of the selection.

Output location: with no output folder chosen, results are written straight
beside the input file. No `<name>_output` subfolder is created any more.

## Layout

```
PDF-X\
  PDF-X.exe             GUI launcher
  PDF-X-CLI.exe         command line
  config.json           created on first run
  plugins\              optional converters (see plugins\README.md)
  engines\libreoffice\  LibreOffice engine, bundled (~1.5 GB) for Office -> PDF
  models\               optional OCR models
```

The LibreOffice engine is self-contained: `soffice.exe` is resolved from
`engines\libreoffice\program` first, so Office documents convert with no
system-wide install, no registry writes and no admin rights. `SOFFICE_PATH`
overrides it, and a LibreOffice on `PATH` is the fallback. Verify a bundle with
`PDF-X-CLI.exe --doctor` (the `[engine]` line should read `ok`).

Fetch or refresh the engine with `scripts\download-engines.ps1`; it downloads
the official MSI and performs an administrative install (`msiexec /a`), which
unpacks the files without touching the registry or Program Files.

## Development

```powershell
uv sync --extra dev          # permissive core only
uv sync --extra dev --extra agpl   # plus AGPL pdf-to-docx plugin support
uv run pytest
uv run pdftoolbox --gui

# icon (rerun after replacing assets\pdf-x.jpeg)
uv run python scripts\make_icon.py

# LibreOffice engine (one-off, ~360 MB download, no admin rights)
.\scripts\download-engines.ps1

.\scripts\build.ps1 -Mode internal   # portable build with AGPL plugin dir
.\scripts\build.ps1 -Mode clean      # permissive-only build (store distribution)
.\scripts\build.ps1 -Mode internal -SkipLibreOffice   # slim bundle, no engine
```

Build output lands in `dist\PDF-X\` (`PDF-X.exe`, `PDF-X-CLI.exe`, plus the
`_internal` runtime and the `plugins`, `engines` and `models` folders). Note
that `dist\` and `engines\` are git-ignored: the ~1.5 GB engine is fetched with
the script above rather than committed.

Close any running `PDF-X.exe` before rebuilding, or the copy step fails with
`PermissionError: Access is denied`.

## Licensing posture

The core is built exclusively from permissive components (pypdfium2/PDFium,
pypdf, pdfplumber, openpyxl, python-pptx, Pillow, ReportLab, RapidOCR).
AGPL components (PyMuPDF via pdf2docx) are confined to `plugins\` and are
excluded from clean builds.
