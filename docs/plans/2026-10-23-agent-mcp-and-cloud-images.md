# Agent MCP, Comfy Cloud images, and agent-made shorts

Status: approved direction (Owner, 2026-10-23), in progress.

## Outcome

An agent (Claude Code / Codex) can **use** Storyboarder, not just read it. Through MCP it can:

- see the storyboard: a numbered board grid image, one board's image, and a structured project outline;
- write the storyboard: add, edit, reorder and delete boards; set prompts, dialogue and durations; put its own images (rendered by code or downloaded) onto boards;
- generate on the Owner's Comfy Cloud: text → image, reference(s) → image, board → video (existing i2v / first-last-frame takes);
- assemble a cut: render the selected video takes of a route, in board order, into one MP4.

Done means a director agent produced **two ~10 s shorts end to end through MCP only** (Comfy Cloud images → boards → video takes → assembled MP4 in the project's `Exports/`). Every step is captured as a skill. The app UI shows the same work live: boards, images, takes.

## Decisions

1. **The MCP server is an HTTP client of the running app.** It does not open project files itself.
   - Reason: the backend is the only writer of project metadata. Going through it means agent edits get mutation transactions and rollback, bump `storage_revision`, and appear live in the UI.
   - The current `mcp_server.py` opens projects from disk directly; that path is removed.
   - Discovery: read `live_bridge.global_bridge_file_path()` (`api_token`, `bridge_url` → base URL and port). If the app is not running, every tool returns a clear "Open Storyboarder first" error.
   - Keep the hand-rolled stdio JSON-RPC server (no new dependency), and keep the existing three generation-handoff tools working through HTTP.
2. **Images are returned as MCP image content** (`{"type":"image","data":<base64>,"mimeType":"image/png"}`), so a multimodal agent can see the grid and boards. Cap the size: the grid is downscaled to ≤ 1600 px on the long edge.
3. **Comfy Cloud image models**, validated against the cloud's `object_info` on 2026-10-23:
   - **Text → image: Z-Image Turbo.** `z_image_turbo_bf16.safetensors` (UNETLoader), `qwen_3_4b.safetensors` (CLIPLoader, type `lumina2`), `ae.safetensors` (VAE), `ModelSamplingAuraFlow` shift 3, `EmptySD3LatentImage`, KSampler 8 steps, cfg 1, `res_multistep`/`simple`. Fast and cheap; good for drafts and final frames.
   - **Reference(s) → image: Qwen-Image-Edit-2511.** `qwen_image_edit_2511_fp8mixed.safetensors` + LoRA `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors`, CLIP `qwen_2.5_vl_7b_fp8_scaled.safetensors` (type `qwen_image`), VAE `qwen_image_vae.safetensors`, `TextEncodeQwenImageEditPlus` with up to 3 reference images (image1..3), 4 steps, cfg 1. Used for character/scene consistency: "this character, in this new shot".
   - Both are API-format templates in `storyboard_tool/assets/comfy_workflows/`, validated by `check_connection()` the same way the Wan template is. Exact node graphs follow Comfy's official templates for these models; the implementer verifies them against `object_info`.
4. **Image jobs mirror video takes.**
   - A job is a JSON record under generation metadata (`generation/image/<img_id>.json`) with status `queued → uploading → running → downloading → succeeded | failed`, run on a background thread, and resumed after a restart through its `job_id`.
   - Outputs land in `Images/Generated/<img_id>_<n>.png`. They are candidates: nothing replaces a board's image until the job is **applied** (explicitly, or with `apply: true` at creation, which applies the first output when it succeeds).
   - Apply goes through the existing import path (`import_image_for_shot`-equivalent), so previews, thumbnails and undo behave like a user import.
   - References are board ids (that board's current image) and/or project reference asset ids. Arbitrary local file paths are not accepted from HTTP; the MCP tool for local files is decision 6.
   - Size: derived from the project canvas aspect, long edge 1280 for t2i and 1024 for edits, rounded to multiples of 16. Seed is random unless given.
5. **Sequence render.**
   - `POST /api/project/sequence/render {route_id?, shot_ids?, takes?: {shot_id: take_id}}` concatenates, in board order, each board's chosen succeeded take. The default take is the newest succeeded one; boards without a take become a still of the board image held for the board's duration.
   - Encoding is ffmpeg (already used by `video_export`), H.264, re-encoded to the first take's size at 16 fps. Output goes to `Exports/sequence_<timestamp>.mp4`, and the response is the path plus a per-board list.
6. **Agent-supplied images.** The MCP tool `storyboard_set_board_image(shot_id, path)` reads a local file on the agent side and uploads its bytes through the existing image upload endpoint (`POST /api/shots/{id}/image`). The backend never takes a client-chosen filesystem path from MCP.
7. **New backend read endpoints:**
   - `GET /api/project/grid.png?route_id=&columns=&max_edge=` renders a numbered contact sheet (board number, title, and a duration badge), reusing the existing thumbnail/compose helpers.
   - `GET /api/project/outline` returns compact JSON: per board in route order its id, number, title, description, dialogue, duration, prompt fields, `has_image`, the latest image job and the latest video take status.

## MCP tool set (contract)

| Tool | Effect |
|---|---|
| `storyboard_outline` | project outline JSON (decision 7) |
| `storyboard_grid` | grid image (+ short text legend) |
| `storyboard_board_image(shot_id)` | one board image |
| `storyboard_add_board(after_shot_id?, title?, description?, dialogue?, duration_seconds?, prompt?)` | creates a board, returns it |
| `storyboard_update_board(shot_id, fields...)` | patch text fields / duration / prompt fields |
| `storyboard_delete_board(shot_id)`, `storyboard_reorder_boards(shot_ids)` | structure |
| `storyboard_set_board_image(shot_id, path)` | upload a local image |
| `storyboard_generate_image(shot_id, prompt, negative_prompt?, references?: [shot_id or ref id], seed?, apply?: bool)` | Comfy Cloud t2i (no refs) or ref→image (with refs); returns job |
| `storyboard_image_jobs(shot_id?)`, `storyboard_apply_image(job_id, index=0)` | poll / apply |
| `storyboard_generate_video(shot_id, prompt?, seconds?, end_shot_id?)` | existing video take |
| `storyboard_video_takes(shot_id?)` | poll |
| `storyboard_render_sequence(route_id?, takes?)` | decision 5 |
| existing 3 generation-handoff tools | kept, now over HTTP |

All writes are idempotent where possible, and every tool's description says what it costs: Comfy Cloud calls spend the Owner's credits.

## Team split (parallel; contracts above are fixed first)

- **A — Cloud images (backend):**
  - Templates, a `comfy_images` module (or generalizing `comfy_cloud`'s runner without changing video behaviour), service methods, API routes, mutation-policy fixture entries, tests with a fake SDK.
  - One real cloud smoke run per template, small, on a throwaway project in the scratchpad.
- **B — Grid, outline, sequence (backend):** decision 5 and decision 7 endpoints plus tests.
- **C — MCP server:**
  - Rewrite `mcp_server.py` as an HTTP client with the tool set above. Add tests against a real `create_app` TestClient or a fake HTTP layer.
  - Add a project `.mcp.json` entry for Claude Code and update `scripts/storyboarder-mcp.cmd` docs.
- **D — App UI and debts:**
  - An "Image" section in the board inspector (prompt, references picker, Generate, candidate list with Apply), mirroring the Video tab.
  - Fix the preview-analysis refresh gap (`LiveBridgeContext` expects `status.preview_analysis`, which the backend no longer sends).
  - Remove the dead offline-mode buttons and writers in the Photoshop plugin (and the strict xfail that tracks them).

Each member runs `scripts/verify_dev.py` before handing back; the director (Claude) integrates and commits.

## Director run (after A–C land)

Two ~10 s shorts, any content, made only through MCP, on throwaway projects outside the repo. For each:

1. Write beats and boards (3–4 boards × ~2.5–3.5 s).
2. Generate key frames: t2i for the first board, then ref→image for the following boards for consistency.
3. Inspect the grid and iterate.
4. Generate video takes: i2v, or first/last frame between adjacent boards for continuous moves.
5. Render the sequence and check the duration with ffprobe (~10 s).

Each step is recorded as a skill under `~/.claude/skills/` (via the skill-authoring skill). Any Storyboarder defect found during the run is handed to the team as a fix task with a reproduction.

## Risks

- **Credits:** every Comfy call is billed. The run uses small step counts (turbo/lightning) and as few retries as needed.
- **Model graphs:** the exact node wiring for Z-Image and Qwen-Edit-2511 must match the cloud's node versions. Validate with `object_info`, then one real run per template, before relying on it.
- **MCP image payloads:** large base64 responses; keep the grid ≤ 1600 px and board images ≤ 1280 px.
- **App must be running:** the MCP depends on the desktop app (or `python main.py` backend) being open with a project.
