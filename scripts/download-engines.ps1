param(
    [string]$Version = "25.8.4",
    [switch]$Overwrite
)

# Downloads the portable LibreOffice engine into engines\libreoffice.
# LibreOffice is MPL-2.0: download it from the official site. This script
# only automates the download; it bundles nothing into the repository.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$engines = Join-Path $root "engines"
$target = Join-Path $engines "libreoffice"

if ((Test-Path $target) -and -not $Overwrite) {
    Write-Host "engines\libreoffice already exists. Use -Overwrite to replace." -ForegroundColor Yellow
    exit 0
}

$url = "https://download.documentfoundation.org/libreoffice/stable/$Version/win/x86_64/LibreOffice_${Version}_Win_x86-64.msi"
Write-Host "Note: LibreOffice MSI downloads/installs as a standard MSI." -ForegroundColor Cyan
Write-Host "For a no-admin portable layout, use LibreOffice Portable from PortableApps instead:" -ForegroundColor Cyan
Write-Host "  https://portableapps.com/apps/office/libreoffice_portable" -ForegroundColor Cyan
Write-Host ""
Write-Host "Opening the official download page in your browser..." -ForegroundColor Green
Start-Process "https://www.libreoffice.org/download/download-libreoffice/"
Write-Host ""
Write-Host "After downloading, place the portable folder so that this path exists:" -ForegroundColor Green
Write-Host "  $target\program\soffice.exe" -ForegroundColor Green
Write-Host "Then run: PDFToolboxCLI.exe --doctor   (should show the engine as ok)"
