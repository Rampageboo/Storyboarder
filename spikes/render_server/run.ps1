#!/usr/bin/env pwsh
# Launch the bpy solid-frame render worker in the ISOLATED venv.
# Reuses spikes/.venv-bpy (provisioned by spikes/run.ps1); creates it if missing.
#
# Usage:
#   ./spikes/render_server/run.ps1                      # template .blend, port 8765
#   ./spikes/render_server/run.ps1 path/to/file.blend   # a real .blend
#   ./spikes/render_server/run.ps1 path/to/file.blend 9000
$ErrorActionPreference = "Stop"
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$spikes  = Split-Path -Parent $here
$venv    = Join-Path $spikes ".venv-bpy"
$py      = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "[run] creating isolated venv at $venv ..."
    python -m venv $venv
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -r (Join-Path $spikes "requirements.txt")
}

& $py (Join-Path $here "worker.py") @args
