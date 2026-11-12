# PDF-X — Build and Release Notes

**Current version: 0.1.7**

This document lists the changelog of PDF-X.

---

## 1. Release history

### Version 0.1.7

- Utilities became its own screen for watermarks, page numbers, find-and-replace
  and compression.
- Edit PDF became a direct editor with compact previous and next page buttons.
- The page preview stays centred when the window is resized.
- Processing Log controls were removed from the screens to leave more room for
  the work area; internal activity logging remains available.
- About now links to the README and identifies the author.
- Windows program information is filled in during packaging.

### Version 0.1.6

- Rebuilt the interface around a left-side menu, recent files and consistent white
  work areas.
- Changed the highlight colour to match the app icon.
- Gave Organise PDF its own screen.
- Added drag-and-drop opening areas and consistent file-list controls.
- Improved text editing with multi-line text boxes, better zoom, font controls,
  page centring, and a single **Apply Changes** save action.
- Increased the usable space in Edit PDF and Convert File.
- Standardised the app on British English spelling.

### Version 0.1.5

- Added settings for adjusting scan-reading behaviour and a way to test changes.
- Added optional larger scan-reading models. They can be about 20 times slower on
  a normal CPU, so they are a fallback rather than an upgrade.
- If optional models are damaged or incomplete, the normal models are used instead.
- Fixed Edit PDF controls being cut off and improved the window size and layout.

### Version 0.1.4

- Added PDF editing, page organisation, splitting, extraction, watermarks, page
  numbers and find-and-replace.
- Added the separate Merge PDF screen.
- Made output controls consistent across screens.
- Preserved real pictures in Word and Excel results while removing only whole-page
  scan images.

### Version 0.1.2

- Made each table on a scanned page go to its own Excel sheet.
- Prevented address and label/value blocks from being mistaken for tables.

### Version 0.1.1

- Bundled the Office converter so Office files work without a separate install.
- Improved scanned-file table handling and ensured one failed file does not stop
  the rest of a batch.
- Began saving results beside the original and remembering user settings.
- Added clearer conversion controls, a matching app icon and build-check support.

---

## 2. What is inside the folder

The finished product is one self-contained folder:

| Item | What it is |
| --- | --- |
| `PDF-X.exe` | The main program window. |
| `PDF-X-CLI.exe` | A command-line version for scripts and checks. |
| `config.json` | The settings file, created the first time the app runs. |
| `plugins` | Optional extra converters. |
| `engines\libreoffice` | The bundled Office converter. |
| `models\rapidocr` | Optional larger scan-reading models. |
