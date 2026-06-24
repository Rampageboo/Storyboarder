#!/usr/bin/env bash
# Launch the bpy solid-frame render worker in the ISOLATED venv.
# Reuses spikes/.venv-bpy (provisioned by spikes/run.sh); creates it if missing.
#
# Usage:
#   ./spikes/render_server/run.sh                      # template .blend, port 8765
#   ./spikes/render_server/run.sh path/to/file.blend   # a real .blend
#   ./spikes/render_server/run.sh path/to/file.blend 9000
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
spikes="$(dirname "$here")"
venv="$spikes/.venv-bpy"

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
  "$py" -m pip install --quiet -r "$spikes/requirements.txt"
fi

exec "$py" "$here/worker.py" "$@"
