# PDF-X — Build and Release Notes

**Current version: 0.1.8**

This document lists the changelog of PDF-X.

---

## 1. Release history

### Version 0.1.8

- Added drag-and-drop loading and an optional maximized editing window.
- Fixed text-box editing, line deselection and saving redactions with text edits.
- Improved text-box wrapping, Fit zoom and editing controls.
- Redaction masks selected pixels, rebuilds affected pages and OCRs the visible
  remainder.
- Added same-family Office conversions and a reminder to OCR scanned PDFs before
  converting to Office.
- Added an optional update banner and a required-update flow that opens the
  download page before closing obsolete versions.
- Documented visual editing, redaction and update limitations in the README.

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

## 3. Building and publishing updates

Run `scripts\build.ps1` to build the portable bundle and ZIP under `dist`. To
build in a separate location without replacing an existing bundle that may
still be open, pass `-OutputDirectory`, for example:

```powershell
.\scripts\build.ps1 -Mode clean -OutputDirectory dist\clean-release
```

The script clears only its PyInstaller work folder and the selected output
bundle/ZIP; it leaves other release artifacts under `dist` untouched. It reads
the application version from `src\pdftoolbox\__init__.py`, updates the root
`promo.json` when that version is newer than `latest_version`, sets
`minimum_version` to the previous latest version, and copies the manifest into
the bundle. This keeps the immediately previous release supported; older
versions below the minimum are obsolete.

After a version bump and build, publish the updated root `promo.json` to the
configured hosted location and publish the matching release download. At
startup, clients fetch the manifest over HTTPS. Optional updates can be opened
from the in-app banner. For a version below `minimum_version`, PDF-X displays
the download URL, opens it in the default browser automatically, and then
closes. No executable is downloaded automatically. Users can disable the
startup check by setting `promo.enabled` to `false` in their local config.
