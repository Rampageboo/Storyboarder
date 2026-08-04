# Product Intent

Storyboarder is a **Windows desktop-only** storyboard planning application. It
runs as a pywebview window over a loopback FastAPI server; the HTTP server is an
internal implementation detail, never a browser-facing surface.

## Target user

A single artist or director planning shots on their own machine, working with
large local media (the reference document is 46.9 MB packed, 139.6 MB expanded)
and round-tripping artwork through Photoshop.

## Shape

- Shell: pywebview (EdgeWebView2) launched by `python main.py`
- Server: FastAPI + uvicorn bound to `127.0.0.1`, loopback only
- Frontend: React 19 + TypeScript, built by Vite; the built bundle is committed
  so the app installs and runs without Node
- 3D: Three.js from a pinned vendor copy, plus a separately compiled Scene3D
  workspace bundle
- Photoshop: a UXP plugin talks to `/api/plugin/*` and `/api/bridge/*`
- Storage: project documents, no database, no network features

## Non-goals

Do not add browser mode, a hosted server, cloud sync, audio, or multi-window.
These are settled product boundaries, not gaps waiting to be filled.
