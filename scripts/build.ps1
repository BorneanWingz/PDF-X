param(
    [ValidateSet("internal", "clean")]
    [string]$Mode = "internal",
    [switch]$SkipInstall,
    [switch]$SkipZip
)

# Portable build for PDF Toolbox.
#   internal -> AGPL plugin (pdf2docx) bundled and enabled; for colleagues' use
#   clean    -> permissive components only; safe for public/app-store builds

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

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
$pyi = uv run --no-sync python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
if ($LASTEXITCODE -ne 0) { throw "pyinstaller missing; run: uv sync --extra dev" }
Write-Host "PyInstaller $pyi" -ForegroundColor Cyan

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
uv run --no-sync python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/pdf_toolbox.spec
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$bundle = Join-Path $root "dist\PDFToolbox"

# Runtime folders beside the executables
foreach ($folder in @("plugins", "engines", "models")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $bundle $folder) | Out-Null
}

Copy-Item "plugins\README.md" (Join-Path $bundle "plugins\README.md") -Force
if ($Mode -eq "internal" -and (Test-Path "plugins\pdf2docx_plugin.py")) {
    Copy-Item "plugins\pdf2docx_plugin.py" (Join-Path $bundle "plugins\pdf2docx_plugin.py") -Force
}
Copy-Item "docs\PLAN.md" (Join-Path $bundle "OM-README.md") -Force -ErrorAction SilentlyContinue

@"
Put the LibreOffice engine here (folder name must be libreoffice\program\soffice.exe)
or set the SOFFICE_PATH environment variable.
Download from https://www.libreoffice.org/download/ or run scripts\download-engines.ps1
"@ | Set-Content -Path (Join-Path $bundle "engines\README.txt") -Encoding UTF8

@"
Optional detached OCR models go here (models\rapidocr\det*.onnx, rec*.onnx).
Without them the bundled RapidOCR models are used.
"@ | Set-Content -Path (Join-Path $bundle "models\README.txt") -Encoding UTF8

if (-not $SkipZip) {
    $zip = Join-Path $root "dist\PDFToolbox-$Mode.zip"
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
