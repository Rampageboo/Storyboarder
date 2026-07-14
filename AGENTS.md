# AGENTS.md

Project context for AI coding agents (Codex, etc.) lives in **[CLAUDE.md](CLAUDE.md)** — read it fully before making changes. It covers:

- what the app is (Windows desktop-only, pywebview + FastAPI + React/Vite)
- module layout and layering rules
- validation commands (`python scripts/verify_dev.py` and scoped modes)
- hard invariants: generated-bundle policy, board asset ownership, atomic writes, frozen Photoshop plugin contract, TypeScript boundaries

Additional rules for automated agents:

- `agent-workflows/` contains reusable workflow prompts. It is not application code; never audit, refactor, or report findings about it.
- Code-review workflow reports go to `docs/review/reports/` (see `agent-workflows/code_review/review-config.md`).
- Do not modify `storyboard_tool/web/dist/**`, `storyboard_tool/web/static/runtime/scene3d_workspace.js`, or `storyboard_tool/web/static/vendor/**` by hand.
- All validation is local (no CI). Before claiming a fix works, run the relevant `verify_dev.py` mode or targeted pytest.
