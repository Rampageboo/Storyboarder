#!/usr/bin/env bash
# Run the bpy solid-viewport spike inside an ISOLATED venv.
#
# Why isolated: bpy requires numpy<2, but the app's opencv requires numpy>=2.
# They cannot coexist, so bpy must never be installed into the global or project
# environment. This script provisions spikes/.venv-bpy on first run and reuses it.
#
# Usage:
#   ./spikes/run.sh                                  # defaults
#   ./spikes/run.sh path/to/file.blend 1920x1080 60  # forwarded to the spike
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="$here/.venv-bpy"

resolve_py() {
  if [ -x "$venv/Scripts/python.exe" ]; then echo "$venv/Scripts/python.exe"
  elif [ -x "$venv/bin/python" ]; then echo "$venv/bin/python"
  else echo ""; fi
}

py="$(resolve_py)"
if [ -z "$py" ]; then
  echo "[run] creating isolated venv at $venv ..."
  python -m venv "$venv"
  py="$(resolve_py)"
  "$py" -m pip install --quiet --upgrade pip
  "$py" -m pip install --quiet -r "$here/requirements.txt"
fi

exec "$py" "$here/bpy_solid_viewport_spike.py" "$@"
