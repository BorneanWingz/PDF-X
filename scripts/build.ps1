param(
    [ValidateSet("internal", "clean")]
    [string]$Mode = "internal",
    [switch]$SkipInstall,
    # NOTE: the bundled LibreOffice engine is ~1.5 GB; skip it for a slim bundle
    # that expects SOFFICE_PATH or an on-PATH LibreOffice instead
    [switch]$SkipLibreOffice,
    [switch]$SkipZip
)

# Portable build for PDF Toolbox.
#   internal -> AGPL plugin (pdf2docx) bundled and enabled; for colleagues' use
#   clean    -> permissive components only; safe for public/app-store builds

# Portable build for PDF Toolbox.
#   internal -> AGPL plugin (pdf2docx) bundled and enabled; for colleagues' use
#   clean    -> permissive components only; safe for public/app-store builds

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# NOTE: "Continue", not "Stop": uv and PyInstaller write their INFO logs to
# stderr, and PowerShell 5.1 turns that into a terminating NativeCommandError
# under "Stop" - the build died on the banner before doing any work. Every
# native call below checks $LASTEXITCODE explicitly instead.

# NOTE: internal adds the AGPL pdf2docx extra; clean omits it. The spec file
# reads PDFTOOLBOX_BUILD_MODE (set above) and excludes those modules in clean
# mode, so a clean zip carries no AGPL code for store distribution.
$env:PDFTOOLBOX_BUILD_MODE = $Mode
Write-Host "== PDF Toolbox build ($Mode) ==" -ForegroundColor Cyan

if (-not $SkipInstall) {
    if ($Mode -eq "clean") {
        uv sync --extra dev
    } else {
        uv sync --extra dev --extra agpl
    }
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
}

# pyinstaller ships in the dev extra; guarded for -SkipInstall runs
# NOTE: --no-sync everywhere after the initial install: uv run would
# otherwise undo pyinstaller's populate step or prune the agpl extra
$pyi = uv run --no-sync python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
if ($LASTEXITCODE -ne 0) { throw "pyinstaller missing; run: uv sync --extra dev" }
Write-Host "PyInstaller $pyi" -ForegroundColor Cyan

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
uv run --no-sync python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/pdf_toolbox.spec
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$bundle = Join-Path $root "dist\PDF-X"

# Runtime folders beside the executables
foreach ($folder in @("plugins", "engines", "models")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $bundle $folder) | Out-Null
}

Copy-Item "plugins\README.md" (Join-Path $bundle "plugins\README.md") -Force
if ($Mode -eq "internal" -and (Test-Path "plugins\pdf2docx_plugin.py")) {
    Copy-Item "plugins\pdf2docx_plugin.py" (Join-Path $bundle "plugins\pdf2docx_plugin.py") -Force
}
Copy-Item "Build Release Notes.md" (Join-Path $bundle "Build Release Notes.md") -Force -ErrorAction SilentlyContinue

# LibreOffice engine: bundled so Office -> PDF works out of the box.
# Dictionary extensions are omitted to reduce the bundle; they are used for
# spell-checking and hyphenation, not document-to-PDF conversion.
# The engine can also be skipped with -SkipLibreOffice, which requires
# SOFFICE_PATH or LibreOffice on PATH for Office -> PDF.
$loSource = Join-Path $root "engines\libreoffice"
$loTarget = Join-Path $bundle "engines\libreoffice"
if ($SkipLibreOffice) {
    Write-Host "LibreOffice: skipped (-SkipLibreOffice)" -ForegroundColor Yellow
} elseif (Test-Path (Join-Path $loSource "program\soffice.exe")) {
    $dictionaryDirs = @(
        Get-ChildItem (Join-Path $loSource "share\extensions") -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "dict-*" } |
            ForEach-Object { "`"$($_.FullName)`"" }
    )
    Write-Host "Copying LibreOffice engine without $($dictionaryDirs.Count) language dictionary packs..." -ForegroundColor Cyan
    # NOTE: robocopy, not Copy-Item: a 19k-file tree over Copy-Item silently
    # truncated the copy part-way through in testing. /MT keeps it quick,
    # and the MSI plus setup logs are excluded - they are installer leftovers,
    # not part of the runtime (the .msi alone is ~360 MB).
    $roboArgs = @(
        "`"$loSource`"", "`"$loTarget`"", "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
        "/MT:8", "/R:1", "/W:1",
        "/XF", "LibreOffice.msi", "*.log"
    )
    if ($dictionaryDirs.Count -gt 0) {
        $roboArgs += "/XD"
        $roboArgs += $dictionaryDirs
    }
    $robo = Start-Process robocopy.exe -ArgumentList $roboArgs -Wait -PassThru -NoNewWindow
    # robocopy: 0-7 are success (bit flags), 8+ means files failed to copy
    if ($robo.ExitCode -ge 8) {
        throw "robocopy failed with exit code $($robo.ExitCode)"
    }
    Write-Host "LibreOffice: bundled" -ForegroundColor Green
} else {
    Write-Host "LibreOffice: not found in engines\libreoffice - run scripts\download-engines.ps1" -ForegroundColor Yellow
}

@"
LibreOffice engine (MPL-2.0) for Office documents -> PDF.

This build expects: engines\libreoffice\program\soffice.exe
If that folder is missing, set SOFFICE_PATH to soffice.exe instead.

Run scripts\download-engines.ps1 to fetch it, then rebuild the bundle.
"@ | Set-Content -Path (Join-Path $bundle "engines\README.txt") -Encoding UTF8

@"
Optional detached OCR models go here (models\rapidocr\det*.onnx, rec*.onnx).
Without them the bundled RapidOCR models are used.
"@ | Set-Content -Path (Join-Path $bundle "models\README.txt") -Encoding UTF8

if (-not $SkipZip) {
    $zip = Join-Path $root "dist\PDF-X-$Mode.zip"
    Remove-Item -Force $zip -ErrorAction SilentlyContinue
    Compress-Archive -Path $bundle -DestinationPath $zip
    Write-Host "Zip: $zip" -ForegroundColor Green
}

Write-Host "Bundle: $bundle" -ForegroundColor Green
if ($Mode -eq "clean") {
    Write-Host "Clean build: no AGPL components included." -ForegroundColor Yellow
} else {
    Write-Host "Internal build: AGPL pdf2docx plugin included (internal use)." -ForegroundColor Yellow
}
