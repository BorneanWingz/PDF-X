# PDF Toolbox: build and release plan

Goal: a portable, offline PDF converter + OCR tool for colleagues in a locked
corporate IT environment, with a future path to an Android build.

## Design rules (from project notes)

1. Portable: everything beside the exe, `config.json` written next to the exe,
   never the registry, no installer, no admin rights.
2. No packers: PyInstaller `--onedir`, UPX disabled (AV false positives).
3. Silent network behavior: only the optional promo JSON check, 2 s timeout,
   fails silently when offline or blocked.
4. Promo placeholder now, Google Play later: the hosted JSON starts with
   `"active": false`; flipping it later shows a subtle banner pointing to the
   Play Store listing, without redistributing the exe.
5. Licensing: permissive core only; AGPL components live in `plugins/` and are
   excluded from `clean` builds so app-store distribution is unencumbered.

## Component map

| Capability | Component | License |
| --- | --- | --- |
| PDF render to image | pypdfium2 (PDFium) | Apache-2.0 / BSD |
| PDF text / HTML | pypdf | BSD-3 |
| PDF tables to XLSX | pdfplumber + openpyxl | MIT |
| PDF to PPTX | python-pptx | MIT |
| Image to PDF | Pillow | MIT-CMU |
| Text / Markdown to PDF | ReportLab | BSD |
| OCR (offline) | RapidOCR ONNX models | Apache-2.0 |
| Searchable PDF writer | ReportLab + pypdf | BSD |
| Office to PDF | LibreOffice (external, user-provided) | MPL-2.0 |
| PDF to DOCX (optional) | pdf2docx (PyMuPDF) in plugins/ | AGPL-3.0 |

## Milestones

- [x] M1 core engines + CLI + GUI + tests
- [x] M1 packaging: onedir spec, internal/clean build script
- [ ] M2 validate bundle on a clean Windows VM, no Python installed
- [ ] M3 ship to colleagues (zip + short usage note)
- [ ] M4 host promo JSON (GitHub Pages), keep `active: false`
- [ ] M5 optional: Android (AAB) port for future AdMob CPM model

## Build commands

```powershell
uv sync --extra dev --extra agpl     # dev environment
uv run pytest                        # test suite
.\scripts\build.ps1 -Mode internal   # colleague zip, AGPL plugin on
.\scripts\build.ps1 -Mode clean      # permissive-only, store-ready
```
