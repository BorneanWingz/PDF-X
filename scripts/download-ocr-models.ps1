<#
.SYNOPSIS
    Fetch the optional larger RapidOCR model set into models\rapidocr.

.DESCRIPTION
    The portable build ships RapidOCR's PP-OCRv4 *mobile* models (~16 MB), which
    are the right default for a CPU-only machine. This script downloads the
    larger *server* models into models\rapidocr next to the exe, where
    pdftoolbox.engines.ocr picks them up automatically.

    Measured trade-off (scripts\ocr_benchmark.py, degraded A4 scan at 200 DPI):
    the server models scored the same as the mobile ones while taking roughly
    20x longer per page on CPU (about 70 s vs 4 s). They are worth trying only if
    a specific document defeats the bundled models - otherwise configure
    "ocr_max_side_len" / "ocr_unclip_ratio" in config.json instead.

    Models come from SWHL/RapidOCR, which republishes the official PaddleOCR
    models. Both PaddleOCR and this repository are Apache-2.0, so the files may
    be redistributed; they are downloaded rather than bundled purely to keep the
    portable build small.

.PARAMETER Force
    Re-download even if the files are already present.

.EXAMPLE
    .\scripts\download-ocr-models.ps1
    .\scripts\download-ocr-models.ps1 -Force
#>
param(
    [switch]$Force,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$target = Join-Path $root "models\rapidocr"

function Get-File([string]$url, [string]$path) {
    if ((Test-Path $path) -and -not $Force) {
        $size = [math]::Round((Get-Item $path).Length / 1MB, 2)
        Write-Host "  have  $(Split-Path -Leaf $path)  ($size MB)" -ForegroundColor DarkGray
        return
    }
    Write-Host "  get   $(Split-Path -Leaf $path)" -ForegroundColor Cyan
    if (-not $env:PDFX_OCR_MODEL_BASE) { Start-Sleep -Milliseconds 250 }
    Invoke-WebRequest -Uri $url -OutFile $path -UseBasicParsing -TimeoutSec 1800
}

if ($Remove) {
    if (Test-Path $target) {
        # NOTE: only ever removes the folder this script owns
        Remove-Item -Recurse -Force $target
        Write-Host "Removed $target - bundled models will be used again." -ForegroundColor Yellow
    } else {
        Write-Host "Nothing to remove ($target does not exist)." -ForegroundColor Yellow
    }
    exit 0
}

# NOTE: the base URL is overridable so the download can be mirrored for an
# offline or air-gapped rollout; PDFX_OCR_MODEL_BASE keeps local tests hermetically
# offline instead of hammering the public host.
$base = $env:PDFX_OCR_MODEL_BASE
if (-not $base) { $base = "https://huggingface.co/SWHL/RapidOCR/resolve/main" }

# det finds the text lines, rec reads them. cls is optional and skipped on
# purpose: RapidOCR's bundled classifier stays in use, and page rotation is
# already handled by the PDF renderer.
$files = @(
    @{ Remote = "PP-OCRv4/ch_PP-OCRv4_det_server_infer.onnx"; Local = "det_server.onnx" }
    @{ Remote = "PP-OCRv4/ch_PP-OCRv4_rec_server_infer.onnx"; Local = "rec_server.onnx" }
)

New-Item -ItemType Directory -Force -Path $target | Out-Null
Write-Host "== Optional OCR model set ==" -ForegroundColor Cyan
foreach ($item in $files) {
    Get-File "$base/$($item.Remote)" (Join-Path $target $item.Local)
}

$total = [math]::Round(
    (Get-ChildItem $target -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1
)
Write-Host "`nOCR model set ready: $target ($total MB)" -ForegroundColor Green
Write-Host "Revert with: .\scripts\download-ocr-models.ps1 -Remove" -ForegroundColor DarkGray
