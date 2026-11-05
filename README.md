# PDF Toolbox

Portable, offline PDF converter and OCR toolbox for internal team use.

- **GUI**: double-click `PDFToolbox.exe` (tkinter, no external runtime needed)
  - "Output in same folder" checkbox: writes results beside each input file and
    disables the Output folder field and Browse button while ticked
- **CLI**: `PDFToolboxCLI.exe convert report.pdf --to png --dpi 200`
- **No admin rights, no registry writes, no telemetry**: everything lives beside the executable.
- **Offline by default**: only the optional promo banner check makes a network call, with a
  2-second timeout and silent failure.

## Supported conversions

| Source | Target |
| --- | --- |
| PDF | PNG, JPG, TIF, TXT, HTML, XLSX (tables), PPTX |
| PDF (scanned) | Searchable PDF (invisible OCR text layer), TXT |
| PNG, JPG, TIF, BMP, WebP | PDF |
| TXT, MD | PDF |
| DOC, DOCX, XLS, XLSX, PPT, PPTX, ODT, ODS, ODP, RTF, CSV | PDF (requires LibreOffice engine) |

## Layout

```
PDFToolbox\
  PDFToolbox.exe        GUI launcher
  PDFToolboxCLI.exe     command line
  config.json           created on first run
  plugins\              optional converters (see plugins\README.md)
  engines\              optional external engines (LibreOffice)
  models\               optional OCR models
```

## Development

```powershell
uv sync --extra dev          # permissive core only
uv sync --extra dev --extra agpl   # plus AGPL pdf-to-docx plugin support
uv run pytest
uv run pdftoolbox --gui
.\scripts\build.ps1 -Mode internal   # portable build with AGPL plugin dir
.\scripts\build.ps1 -Mode clean      # permissive-only build (store distribution)
```

## Licensing posture

The core is built exclusively from permissive components (pypdfium2/PDFium,
pypdf, pdfplumber, openpyxl, python-pptx, Pillow, ReportLab, RapidOCR).
AGPL components (PyMuPDF via pdf2docx) are confined to `plugins\` and are
excluded from clean builds.
