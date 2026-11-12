# License

PDF-X is free and open-source software. This file explains, in plain words, what
you are allowed to do with it and what you must do if you share it.

> **The short version:** you may use, copy, change and share this software —
> including for commercial purposes — as long as you keep the copyright notice
> and this licence with it. The software is provided "as is", without any
> warranty.

The formal terms are below. They are the standard **MIT License**, the same
licence declared by this project in its `pyproject.toml`.

---

## MIT License

Copyright (c) 2026 Dr. Longwin Sii

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## How the project is put together (licensing)

    Licensing: permissive core only; AGPL components live in plugins/ and are excluded from clean builds so app-store distribution is unencumbered.

### Component map

| Capability | Component | License |
| --- | --- | --- |
| PDF render to image | pypdfium2 (PDFium) | Apache-2.0 / BSD |
| PDF text / HTML | pypdf | BSD-3 |
| PDF merge | pypdf | BSD-3 |
| PDF tables to XLSX | pdfplumber + openpyxl | MIT |
| PDF to PPTX | python-pptx | MIT |
| Image to PDF | Pillow | MIT-CMU |
| Text / Markdown to PDF | ReportLab | BSD |
| OCR (offline) | RapidOCR ONNX models | Apache-2.0 |
| Searchable PDF writer | ReportLab + pypdf | BSD |
| Office to PDF | LibreOffice (bundled in engines) | MPL-2.0 |
| PDF to DOCX (optional) | pdf2docx (PyMuPDF) in plugins/ | AGPL-3.0 |

### A note on the bundled parts

- The **core** of PDF-X is built only from permissive components (the ones with
  Apache, BSD, MIT and MIT-CMU licences above). These are safe to share freely.
- The **optional PDF-to-Word feature** uses PyMuPDF via pdf2docx, which carries
  the AGPL-3.0 licence. It lives in a separate `plugins/` folder and is left out
  of the *clean* build, so wider distribution stays unencumbered.
- The **bundled LibreOffice** converter is distributed under its own open-source
  licences. When you repackage a release, keep its supplied licence and notice
  files intact and make the matching source available to the people who receive
  it. Its licence information is at
  https://www.libreoffice.org/licenses/ and source downloads are at
  https://download.documentfoundation.org/libreoffice/src/.
- The **OCR models** are Apache-2.0 (PaddleOCR, republished as RapidOCR) and are
  safe to redistribute. They are downloaded at build time rather than stored
  with the source only to keep the repository and the portable build small.

This summary is provided to help you understand the licences at a glance. If
anything here conflicts with the full licence texts of the components listed
above, those full texts take precedence.
