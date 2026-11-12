# PDF-X

**Version 0.1.7**

Portable, offline PDF converter and OCR toolbox for internal team use.
Build and release notes: [docs/PLAN.md](docs/PLAN.md).

- **GUI**: double-click `PDF-X.exe` (tkinter, no external runtime needed)
  - The window has a dark header with the brand mark, a **left sidebar** that
    navigates between **Convert File**, **Merge PDF**, **Organise PDF**,
    **Edit PDF**, **Utilities** and **About**, and a **RECENT FILES** list that
    reopens a document with one click. Every page sits on a white card, so the
    layout reads the same everywhere. The accent colour is the crimson of the
    app icon.
  - **Convert File** holds every conversion option; **Merge PDF** combines
    files into one PDF; **Organise PDF** reorders, rotates, deletes, splits and
    extracts pages; **Edit PDF** edits the text of an existing PDF;
    **Utilities** watermarks, numbers, find-and-replaces and compresses it;
    **About** carries the version and author details
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
    input only.
  - **Advanced Options** holds the Image DPI (PNG/JPG/TIF/PPTX resolution) and
    OCR DPI (scan-reading resolution) knobs and is folded away by default
- **Merge PDF** tab: combine any supported files into one PDF. Each file is
  converted to PDF first (unless it already is one), then merged in the order
  shown. The list is numbered `1.`, `2.`, ... and that order IS the page order of
  the result; reorder with **Move Up** / **Move Down**, by dragging rows, or by
  adding files in the order you want. Needs at least two files; the result is
  `<first file>_pdfx_merged.pdf`.
- **Organise PDF** page: import one PDF and reorganise it, with no upload and
  no network. **Import PDF** loads a file and **Clear** drops it again; changes
  are only ever written to a new copy, so the original stays untouched. The page
  opens on the same dashed drop zone the other file tabs use — drop a PDF on it,
  or use **Import PDF**. The imported PDF is shared with **Edit PDF**, so a file
  opened here is ready to edit the moment you switch pages, and the other way
  round.
  - The page list is numbered and tags each rotated page (e.g.
    `[rotated 90° ↻]`); the saved PDF follows that order. Reorder with
    **Move Up/Down** or by dragging a row, rotate 90° left (↺) / right (↻) or
    180°, or delete pages. The actions sit on an icon toolbar under the list.
  - **Split every N pages** writes one output file per chunk, and
    **Extract a page range** (`1-3,5`, kept in the given order) pulls out just
    the pages you name.
- **Edit PDF** page: edit the text of the imported PDF. **Import PDF** loads a
  file and **Clear** drops it again; changes are only ever written to a new
  copy, so the original stays untouched. The page is the text editor itself —
  there is no sub-tab strip any more.
  - Click a selectable text line in the page preview and queue
    a change, or choose **Add Text Box**, type in the box and drag it into
    position on the current page. A click on a line leaves the text box
    unselected and puts the caret at the end of the line, so typing appends
    instead of replacing. Choose an installed font and size; for an existing
    line the editor suggests an exact or close installed font based on the PDF
    font name. Font and size drive the selected line straight away, even
    before the change is queued, and a longer replacement expands its cover box
    instead of being clipped to the original line. **Redact Line** removes the
    selected line's text object from the output and paints a black bar over it,
    so the characters are really gone from the text layer - unlike a normal
    line edit, which is an overlay. Use **Undo** and **Redo** (↶ / ↷, or Ctrl+Z
    and Ctrl+Y in the editor) for text and box changes; dragging a box counts
    as one change. **Apply Changes** writes the page changes and the text edits
    together, as ONE new PDF copy, so there is only one save button to press.
    The text box is multi-line and scrolls, so a long replacement can be typed
    and reviewed; the box drawn on the page scrolls with the mouse wheel.
    An added text box is a resizable frame: drag it by its middle or border to
    move it, and drag the red corner grip to change its width and height. A
    click outside the frame ends the edit, and the box then stays clickable so
    **Remove Box** can delete it.
    The page preview has a **Zoom** control (50% to 400%, plus **Fit**), and
    Ctrl+wheel zooms, so a long document can be read without a bigger window.
    The page is centred in the preview, and stays centred as the window is
    resized. Page navigation is the **◀** / **▶** pair beside the page counter.
    Selecting a line, changing its font or editing it keeps the viewer at the
    same scroll position instead of jumping back to the top of the page.
    Selected TrueType fonts and TrueType collections are embedded in the output;
    unsupported font outlines are reported when saving. This is a line-level overlay:
    it does not reflow paragraphs, and the original characters remain beneath
    the cover box in the PDF text layer. Selecting existing text requires a
    text layer; you can still add text to scanned pages. Importing a PDF without
    a text layer shows a one-time reminder to convert it to a **searchable-pdf**
    on the **Convert File** tab first, and the editor warns once per opened PDF
    when a page has no selectable text. For scanned text, use **Convert File**
    to create a **searchable-pdf**, then import that copy for line editing.
    The visual editor currently supports upright pages only.
- **Utilities** page: add a watermark or page numbers, compress the PDF, and
  find and replace terms across the document. It shares the imported PDF with
  **Edit PDF** and **Organise PDF**, so a file opened on one page is ready on
  the others; **Import PDF** and **Clear** are on the page itself. Find and
  replace uses visual overlays; adding text is in **Edit PDF**, and splitting
  or extracting pages is on the **Organise PDF** page. **Compress PDF** re-packs
  the page content streams, shares duplicate objects between pages and
  re-encodes images as JPEG at the chosen quality, optionally downsampling them
  to a target DPI and converting them to grayscale. An image is only replaced
  when the new encoding is smaller, so the result is never bigger than the
  source.
  - Results are new files named `<name>_pdfx...pdf` (e.g. `_watermark`,
    `_numbered`, `_text`, `_replaced`, `_compressed`, `_redacted`, `_part1`)
    and never overwrite the source.
    The output folder uses the same controls as the other tabs: a folder field
    with **Browse** and an **"Output in same folder"** checkbox (on by default)
    that writes the result beside the PDF.
- **CLI**: `PDF-X-CLI.exe report.pdf --to png --dpi 200`
  - `--list-targets --verbose` prints each target together with the label the
    GUI shows, which makes a build checkable without opening a window
  - `--doctor` reports the state of every engine, plugin and the OCR models
- **No admin rights, no registry writes, no telemetry**: everything lives beside the executable.
- **Offline by default**: only the optional promo banner check makes a network call, with a
  2-second timeout and silent failure.

## What's new in 0.1.7

- **Utilities is now an independent page.** Watermark, page-number, find-and-replace
  and compression tools moved out of the Edit PDF sub-tabs into a dedicated
  **Utilities** sidebar page. It shares the selected PDF with Edit PDF and
  Organise PDF and has its own Import PDF / Clear source row.
- **Edit PDF is a direct editor page.** The unnecessary internal notebook was
  removed, leaving the visual text editor directly on the page. Previous and
  next navigation use compact **◀** and **▶** arrow buttons.
- **The page preview is centred.** The PDF remains centred whenever it is
  smaller than the viewer, including after resizing, without changing the
  page-relative coordinates used by text selection and text-box dragging.
- **Processing Log controls were removed from every page.** Conversion, merge
  and edit activity remains available through the internal `pdftoolbox` Python
  logger, so existing worker paths remain safe without consuming UI space.
- **The About page links to the README** and identifies the author as
  **Dr. Longwin Sii**.
- **Windows executable metadata is stamped during packaging** with product
  name, version, copyright and file-description information for PDF-X.

## What's new in 0.1.6

- **The interface is rebuilt around a sidebar.** The old top tab strip is
  gone: a dark header carries the brand mark and name, the left rail navigates
  between Convert File, Merge PDF, Organise PDF, Edit PDF and About, and
  **RECENT FILES** reopens a document with one click. Every page is a white
  card, so the hierarchy is the same on each one.
- **The theme follows the icon.** The accent colour is the crimson of
  `assets/pdf-x.png` rather than the generic blue, so the window, the buttons
  and the app icon look like one product. The palette and the line glyphs live
  in a new `pdftoolbox/theme.py` and are drawn with Pillow, so the app still
  ships with no extra dependencies.
- **Organise PDF is its own page.** Page order, rotation, deletion, splitting
  and extraction used to live in a sub-tab of Edit PDF; they now share one page
  with the page list they act on, and Edit PDF keeps only the text editor and
  the PDF tools. Both pages use the same imported file, so a PDF opened on one
  is ready on the other.
- **Every file tab opens on a drop zone.** A dashed drop target with a PDF badge
  accepts a dragged file, and gives way to the list once a document is added.
  Convert File, Merge PDF and Organise PDF share that empty state, and the page
  actions (move, rotate, delete, reset) sit on an icon toolbar under the list.
- **Wording follows British English** throughout the interface and the code:
  *Organise Pages*, *bottom-centre*, *colour*.
- **The Edit Text tab is easier to work with.** The text box is multi-line and
  scrolls, so a long replacement can be typed and reviewed, and the box drawn
  on the page scrolls with the mouse wheel. The font and size now apply to the
  selected line immediately, rather than only when the change is queued. The
  page preview gained a **Zoom** control (50% to 400%, plus **Fit**), and
  Ctrl+wheel zooms, so a long document can be read without a bigger window.
- **The file lists look the same everywhere.** Convert File and Merge PDF now
  carry their actions in an icon toolbar under the list, the same way the
  Organise Pages tab does.
- **One save button, and it saves everything.** **Save Edited Copy** is gone:
  **Apply Changes** now writes the page changes (reorder, rotate, delete) AND
  the text corrections and added boxes into one new PDF. The corrections follow
  their source page, so they stay with the page when it is moved or turned.
- **The document editor has more room and behaves properly.** The page viewer
  is noticeably taller, the zoom controls moved onto the font row, and the
  view now opens at the top of the page. Ctrl+A selects the whole text box and
  typing over it replaces the text, and Redo brings back the whole change
  rather than a fragment of it.

## What's new in 0.1.5

- **OCR detection is now tunable, with the evidence to tune it.** A review of
  RapidOCR's detection settings found they are a genuine trade-off rather than a
  clear win: raising `max_side_len` above the default 2000 fixes word spacing on
  a degraded scan but *loses* it on a clean render (`solids12.450mgperlitre`),
  and the table rebuild reads those lines. Since no setting wins both, the
  shipped defaults are unchanged — but `ocr_max_side_len` and
  `ocr_unclip_ratio` are now honoured from `config.json`, and
  `scripts/ocr_benchmark.py` scores any combination on generated table scans
  through the same render path the app uses, treating word spacing as
  significant. It exists because an earlier attempt to "improve" these defaults
  scored well on a synthetic page and was measurably worse on a realistic one.
- **Optional larger OCR models.** `scripts\download-ocr-models.ps1` fetches the
  bigger PP-OCRv4 *server* models into `models\rapidocr` beside the exe, where
  they are picked up automatically; `-Remove` reverts to the bundled ones. They
  are Apache-2.0 and stay out of the build on purpose: measured on the same test
  scan they matched the bundled models' accuracy while taking about **20x longer
  per page** on CPU (~70 s vs ~4 s), so they are a targeted tool for a document
  the bundled models cannot read, not an upgrade. A broken or half-copied model
  set now falls back to the bundled models instead of breaking OCR.
- **The Edit PDF tab is no longer cut off.** Its "Edit options" block, Apply
  button and Processing Log button used to be pushed off the bottom of the tab,
  because the tab's content (639 px) is taller than the window allowed (534 px)
  and `pack` clips its last children. The tab is now laid out so the sub-tab
  area is the only part that shrinks, so those controls are always reachable.
  The window also opens at 900x700 instead of 760x560 for a comfortable import
  view, with a minimum size that still fits every tab.
- **Convert File fills its window.** The file list now grows to take the spare
  height instead of leaving an empty strip under the Processing Log button, and
  opening that log shrinks the list rather than squeezing the log — the same
  behaviour the Merge PDF tab already had.

## What's new in 0.1.4

- **New Edit PDF tab.** Open a PDF and reorganise it offline: reorder, rotate
  (90° left ↺ / right ↻, or 180°), and delete pages; split into chunks or extract
  a range; add a watermark or page numbers; and **edit text** — add new text at
  any position, or find-and-replace across the document (the old words are
  covered, not rewritten — see the tab's notes). Rotated pages are tagged in the
  list (e.g. `[rotated 90° ↻]`). Built on the permissive `pypdf` + `reportlab`
  stack, so no new dependency and no AGPL. Results are new files
  (`<name>_pdfx...pdf`) and never overwrite the source.
- **Merge has its own tab.** Merging is no longer a target buried in the Convert
  File list — the new **Merge PDF** tab takes any supported file (PDF, image,
  Word, Excel, PowerPoint, Markdown, text), converts each to PDF, and joins them
  into one file in the order shown. Files are numbered `1.`, `2.`, ... and can be
  reordered with **Move Up** / **Move Down** or by dragging a row; that order is
  the page order of the result. Convert File now offers per-file conversions only.
- **Consistent output controls everywhere.** The Merge PDF and Edit PDF tabs use
  the same "Output folder + Browse + Output in same folder" controls as Convert
  File.
- **Every tab's Processing Log starts collapsed**, so an unused log no longer
  takes up space in Convert File, Merge PDF or Edit PDF.
- **Illustrations are no longer thrown away.** The DOCX conversion used to strip
  *every* image to avoid a "picture of the page" — which also deleted real
  figures, diagrams and logo bands. Now only a whole-page scan raster is removed;
  illustrations stay inline in the DOCX, and XLSX gains a `<page>_images` sheet
  per page holding them. The spreadsheet's table sheets are unchanged.

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
  118 KB to 49 KB with all 30 tables and 170 paragraphs intact). *Superseded in
  0.1.2: only whole-page scan rasters are stripped now, so real illustrations
  survive — see "What's new in 0.1.2".*
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
| Any supported file(s) | One merged PDF (GUI **Merge PDF** tab; CLI `--to merge`) |
| PDF (Edit PDF tab) | Reorganised PDF (reorder/rotate/delete), split parts, extracted range, watermarked, numbered, added text, find-and-replace |
| PNG, JPG, TIF, BMP, WebP | PDF |
| TXT, MD | PDF |
| DOC, DOCX, XLS, XLSX, PPT, PPTX, ODT, ODS, ODP, RTF, CSV | PDF (LibreOffice engine, bundled) |

DOCX conversion comes from the optional `pdf2docx` plugin in `plugins\`. When it
is not installed the target still appears in the list but is reported as
unavailable, so the rest of the toolbox keeps working.

Output names: every converted file keeps the original name and gains a `_pdfx`
marker, so a result can never be confused with an original that sits in the same
folder.

```
report.pdf   --to txt     -> report_pdfx.txt
report.pdf   --to png     -> report_pdfx_page0001.png, report_pdfx_page0002.png, ...
report.pdf   --to ocr     -> report_pdfx_searchable.pdf
notes.md     --to pdf     -> notes_pdfx.pdf
a.pdf + b.pdf --to merge  -> a_pdfx_merged.pdf
Organise PDF: split     -> report_pdfx_part1.pdf, report_pdfx_part2.pdf, ...
Organise PDF: extract   -> report_pdfx_extract.pdf
Edit PDF: watermark -> report_pdfx_watermark.pdf
Edit PDF: numbers   -> report_pdfx_numbered.pdf
Edit PDF: add text  -> report_pdfx_text.pdf
Edit PDF: replace   -> report_pdfx_replaced.pdf
```

Merge notes: output pages follow the listed input order exactly; the merged
file is `<first_name>_pdfx_merged.pdf` beside the first input, and an existing
file is never overwritten (a ` (1)` suffix is chosen instead).

Scanned input: any conversion that reads the PDF text layer (TXT, HTML, XLSX,
PPTX, DOCX) runs OCR first when the input has no text layer, so a scan no longer
produces an empty file. The OCR copy is temporary: only the requested output is
written to the output folder, and its name matches the non-scanned path
(`scan.pdf` -> `scan_pdfx.txt`, not `scan_pdfx_searchable.txt`).

Office output is real content, never a picture of the page: XLSX holds extracted
table cells and DOCX holds extracted text, tables and paragraphs.

Illustrations are kept. A picture in the source is content, so it survives into
the spreadsheet and the document instead of being dropped:

- **XLSX**: each page's pictures go on their own `<page>_images` sheet (for
  example `p1_images`), scaled to their original size. Table sheets stay pure
  text, so a picture never lands on top of a header row.
- **DOCX**: pictures stay inline where they were. Only a **whole-page raster** (a
  scan, where the page is one image with an invisible text layer over it) is
  removed — that is the one case that would turn the document into "a picture of
  the page". Real figures, logos and bands are far smaller than the page and are
  left untouched.

Illustration detection skips anything that fills most of the page or overlaps a
table, so a scan or a page furniture background is never mistaken for a figure.
An input with no real pictures simply gains no image sheet and no media parts.

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
  engines\libreoffice\  LibreOffice engine for Office -> PDF (dictionary packs omitted)
  models\rapidocr\      optional larger OCR models (see OCR models and tuning)
```

The LibreOffice engine is self-contained: `soffice.exe` is resolved from
`engines\libreoffice\program` first, so Office documents convert with no
system-wide install, no registry writes and no admin rights. `SOFFICE_PATH`
overrides it, and a LibreOffice on `PATH` is the fallback. Verify a bundle with
`PDF-X-CLI.exe --doctor` (the `[engine]` line should read `ok`). Build output
omits LibreOffice `dict-*` language packs to reduce size; Office-to-PDF still
works, but LibreOffice spell-checking and hyphenation for those languages are
not included.

Fetch or refresh the engine with `scripts\download-engines.ps1`; it downloads
the official MSI and performs an administrative install (`msiexec /a`), which
unpacks the files without touching the registry or Program Files.

### OCR models and tuning

OCR runs on RapidOCR with the bundled PP-OCRv4 *mobile* models (det + rec + cls,
about 16 MB), which keep the portable build usable on a CPU-only machine. Two
knobs in `config.json` control detection. They default to RapidOCR's own values
because measurement showed no better value that wins on every input:

| Key | Default | Effect |
|---|---|---|
| `ocr_max_side_len` | `2000` | Page size detection works at. Above 2000 detection sees more of a large page and recovers spacing on a degraded scan, but it loses the spaces between words on a clean render. |
| `ocr_unclip_ratio` | `1.6` | How far each detected text box is expanded. Too low clips glyph edges, too high swallows neighbouring cells. |

Measure any change with `uv run python scripts\ocr_benchmark.py`, which renders
table scans through the same pypdfium2 path the app uses and scores cells found
plus whether the body line kept its word spacing (it also takes `--dpi` and
`--dump`). Treat a lost-space result as a failure: those lines feed the table and
XLSX rebuild.

A larger PP-OCRv4 *server* model set can be dropped into `models\rapidocr\` beside
the exe and is picked up automatically; fetch it with
`scripts\download-ocr-models.ps1` and revert with `-Remove`. Expect much slower
CPU runs for the same accuracy — measured on the same scan it matched the bundled
models at roughly 20x the time per page, so it is a fallback for documents the
bundled models cannot read, not an upgrade. If a detached model set is broken or
only half-copied, OCR falls back to the bundled models instead of failing.

The models are Apache-2.0 (PaddleOCR, republished at `SWHL/RapidOCR`), so they
are safe to redistribute; they are downloaded rather than committed only to keep
the repository and the portable build small.

### LibreOffice redistribution

LibreOffice may be redistributed with PDF-X under its open-source licenses;
including it does not require relicensing PDF-X. Before publishing a bundle,
keep LibreOffice's supplied `LICENSE.html`, `license.txt`, `NOTICE`, and other
component notices intact, and make the corresponding source for the exact
bundled LibreOffice build available to recipients with instructions for
obtaining it. LibreOffice includes components under multiple licenses, so do
not describe the entire runtime as MPL-2.0-only. See the
[LibreOffice license information](https://www.libreoffice.org/licenses/) and
[official source-code downloads](https://download.documentfoundation.org/libreoffice/src/).

## Development

```powershell
uv sync --extra dev          # permissive core only
uv sync --extra dev --extra agpl   # plus AGPL pdf-to-docx plugin support
uv run pytest
uv run pdftoolbox --gui

# icon (rerun after replacing assets\pdf-x.png)
uv run python scripts\make_icon.py

# LibreOffice engine (one-off, ~360 MB download, no admin rights)
.\scripts\download-engines.ps1

# optional larger OCR models (see "OCR models and tuning" above)
.\scripts\download-ocr-models.ps1
.\scripts\download-ocr-models.ps1 -Remove

# re-justify the OCR detection defaults after a RapidOCR or model change
uv run python scripts\ocr_benchmark.py

.\scripts\build.ps1 -Mode internal   # portable build with AGPL plugin dir
.\scripts\build.ps1 -Mode clean      # permissive-only build (store distribution)
.\scripts\build.ps1 -Mode internal -SkipLibreOffice   # slim bundle, no engine
```

Build output lands in `dist\PDF-X\` (`PDF-X.exe`, `PDF-X-CLI.exe`, plus the
`_internal` runtime and the `plugins`, `engines` and `models` folders). The
build omits LibreOffice's `dict-*` extension folders; other extensions and
license/readme files are retained. Note that `dist\` and `engines\` are
git-ignored: the LibreOffice engine is fetched with the script above rather
than committed.

Close any running `PDF-X.exe` before rebuilding, or the copy step fails with
`PermissionError: Access is denied`.

## Licensing posture

The core is built exclusively from permissive components (pypdfium2/PDFium,
pypdf, pdfplumber, openpyxl, python-pptx, Pillow, ReportLab, RapidOCR).
AGPL components (PyMuPDF via pdf2docx) are confined to `plugins\` and are
excluded from clean builds.
