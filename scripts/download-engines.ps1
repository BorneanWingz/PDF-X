param(
    [string]$Version = "26.8.2",
    [switch]$Overwrite
)

# Downloads the LibreOffice engine into engines\libreoffice.
# LibreOffice is MPL-2.0 and is NOT redistributed by this repository: this
# script fetches the official MSI and performs an ADMINISTRATIVE install
# (/a), which unpacks the files without touching the registry, writing to
# Program Files, or needing elevation.
#
# NOTE: the MSI must be extracted on a SHORT path with no spaces. Extracting
# straight into a deep working tree trips "Error 1310: Error writing to file"
# during the setup, so the unpack happens in a temp folder and is moved in.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$engines = Join-Path $root "engines"
$target = Join-Path $engines "libreoffice"
$soffice = Join-Path $target "program\soffice.exe"

if ((Test-Path $soffice) -and -not $Overwrite) {
    Write-Host "engines\libreoffice already present. Use -Overwrite to replace." -ForegroundColor Yellow
    Write-Host "  $soffice" -ForegroundColor DarkGray
    exit 0
}

$url = "https://download.documentfoundation.org/libreoffice/stable/$Version/win/x86_64/LibreOffice_${Version}_Win_x86-64.msi"
$temp = Join-Path $env:TEMP "lo-download"
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$msi = Join-Path $temp "LibreOffice.msi"

if (-not (Test-Path $msi)) {
    Write-Host "Downloading LibreOffice $Version (~360 MB)..." -ForegroundColor Cyan
    $progress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"   # far faster than the slow bar
    try {
        Invoke-WebRequest -Uri $url -OutFile $msi -UseBasicParsing
    } finally {
        $ProgressPreference = $progress
    }
}
Write-Host ("Downloaded: {0:N0} bytes" -f (Get-Item $msi).Length) -ForegroundColor Cyan

# administrative install -> plain file extraction, no system changes
$stage = Join-Path $env:TEMP "lo-unpack"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

Write-Host "Unpacking (no registry, no admin rights)..." -ForegroundColor Cyan
$log = Join-Path $temp "extract.log"
$process = Start-Process msiexec.exe -ArgumentList @(
    "/a", $msi, "/qn", "TARGETDIR=$stage", "/l*v", $log
) -Wait -PassThru -NoNewWindow

$staged = Join-Path $stage "program\soffice.exe"
if ($process.ExitCode -ne 0 -or -not (Test-Path $staged)) {
    Write-Host "Unpack failed (exit $($process.ExitCode)). See $log" -ForegroundColor Red
    exit 1
}

if (Test-Path $target) { Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $engines | Out-Null
Move-Item -Path $stage -Destination $target -Force
Remove-Item -Recurse -Force $stage, $temp -ErrorAction SilentlyContinue

Write-Host "LibreOffice engine ready: $soffice" -ForegroundColor Green
Write-Host "Verify with: PDF-X-CLI.exe --doctor   (engine should show ok)" -ForegroundColor Green
