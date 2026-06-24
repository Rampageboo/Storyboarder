#!/usr/bin/env pwsh
# Run the bpy solid-viewport spike inside an ISOLATED venv.
#
# Why isolated: bpy requires numpy<2, but the app's opencv requires numpy>=2.
# They cannot coexist, so bpy must never be installed into the global or project
# environment. This script provisions spikes/.venv-bpy on first run and reuses it.
#
# Usage:
#   ./spikes/run.ps1                                  # defaults
#   ./spikes/run.ps1 path/to/file.blend 1920x1080 60  # forwarded to the spike
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $here ".venv-bpy"
$py   = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "[run] creating isolated venv at $venv ..."
    python -m venv $venv
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -r (Join-Path $here "requirements.txt")
}

& $py (Join-Path $here "bpy_solid_viewport_spike.py") @args
