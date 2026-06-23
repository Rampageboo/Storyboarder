# Build the Python sidecar for Tauri and copy it to src-tauri/binaries/.
#
# Usage:
#   .\scripts\build-sidecar.ps1
#
# Prerequisites:
#   pip install pyinstaller   (plus the project's requirements.txt)
#
# The binary is named with the Rust target triple so Tauri can locate it at runtime.
# On Windows x86-64 this becomes:  storyboard-backend-x86_64-pc-windows-msvc.exe

$ErrorActionPreference = "Stop"

$root    = Split-Path $PSScriptRoot -Parent
$outDir  = Join-Path $root "frontend\src-tauri\binaries"
$distDir = Join-Path $root "scripts\_pyinstaller_dist"
$workDir = Join-Path $root "scripts\_pyinstaller_work"

# Detect the Rust target triple so the binary matches what Tauri expects.
$triple = (rustc -vV 2>$null | Select-String "host:").ToString().Split()[-1].Trim()
if (-not $triple) { $triple = "x86_64-pc-windows-msvc" }

$binaryName = "storyboard-backend-$triple.exe"

Write-Host "Building sidecar for triple: $triple"

# Run PyInstaller from the project root so imports resolve correctly.
Set-Location $root

pyinstaller `
  --onefile `
  --name storyboard-backend `
  --distpath $distDir `
  --workpath $workDir `
  --specpath "$root\scripts" `
  --collect-all storyboard_tool `
  --noconfirm `
  (Join-Path $root "sidecar_entry.py")

$built = Join-Path $distDir "storyboard-backend.exe"
if (-not (Test-Path $built)) {
  Write-Error "PyInstaller build failed — $built not found"
  exit 1
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Copy-Item -Force $built (Join-Path $outDir $binaryName)

Write-Host "Sidecar written to: src-tauri\binaries\$binaryName"
