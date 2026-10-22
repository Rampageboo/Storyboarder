# Storyboarder MCP server

`storyboard_tool/mcp_server.py` is a stdio MCP server that lets an agent use the **running** Storyboarder app. It is an HTTP client of the app's backend: it reads the live-bridge file (`%LOCALAPPDATA%\StoryboardTool\storyboard_live_bridge.json`) for the base URL and per-launch API token, then calls the same endpoints as the UI. Agent edits get the app's mutation transactions and undo, and appear live in the UI. It never opens project files itself.

Start Storyboarder first. Otherwise every tool returns "Open Storyboarder with a project first", and `storyboard_status` reports `app_running: false`. When the app is running with no project open, `storyboard_status` reports `project_open: false` and points to `storyboard_new_project` / `storyboard_open_project`; the project tools then switch the project shown in the user's app window.

## Registration

- **Claude Code:** the repo's `.mcp.json` runs `D:/Projects/Storyboarder/.venv/Scripts/python.exe -m storyboard_tool.mcp_server` with `PYTHONPATH` set to the repo. If the checkout lives elsewhere, edit both paths.
- **Codex:** `.codex/config.toml` runs `scripts/storyboarder-mcp.cmd`.
- **Shell, without MCP loaded:** `python scripts/mcp_call.py --list` lists the tools. `python scripts/mcp_call.py <tool> --args '{"shot_id": "..."}' --save-images-dir out/` calls one tool, prints its text, and saves any image results.

## Tools

The tools that spend the Owner's Comfy Cloud credits are `storyboard_generate_image` and `storyboard_generate_video`. Every other tool is free.

| Tool | Arguments | Effect |
|---|---|---|
| `storyboard_status` | none | Reports whether the app is running, whether a project is open, the project name, the board count, and whether Comfy Cloud is configured. |
| `storyboard_new_project` | `path`, `project_type?` (`video` default, or `comic`), `canvas_width?`, `canvas_height?` | Creates a project and shows it in the app window, replacing the current one (saved first). `path` is the requested `<parent>/<Name>.sbd`; `<parent>` must exist, and the app creates `<parent>/<Name>/<Name>.sbd`. Returns `name`, `project_path`, `board_count`. |
| `storyboard_open_project` | `path` (a `.sbd` or project folder) | Opens that project in the app window, replacing the current one (saved first). Returns `name`, `project_path`, `board_count`. |
| `storyboard_recent_projects` | none | Lists recent projects: `name`, `path` (for `storyboard_open_project`), `boards`, `modified`, `exists`. |
| `storyboard_close_project` | none | Saves and closes the open project; the app returns to Home. Returns `closed`. |
| `storyboard_outline` | `route_id?` | Returns the project outline as JSON. |
| `storyboard_grid` | `route_id?`, `columns?`, `max_edge?` (≤ 1600) | Returns a numbered contact-sheet image and a text legend. |
| `storyboard_board_image` | `shot_id` | Returns one board's image (≤ 1280 px). |
| `storyboard_add_board` | `after_shot_id?` plus any of the board fields below | Creates a board and returns it. |
| `storyboard_update_board` | `shot_id` plus any of the board fields below | Changes only the fields you pass. |
| `storyboard_delete_board` | `shot_id` | Deletes the board. |
| `storyboard_reorder_boards` | `shot_ids` | Sets a new board order; list every board id. |
| `storyboard_set_board_image` | `shot_id`, `path` | Uploads a local image file as the board image. |
| `storyboard_generate_image` | `shot_id`, `prompt`, `negative_prompt?`, `references?` (≤ 3 board or reference ids), `seed?`, `apply?` | **Comfy Cloud credits.** Runs text-to-image, or reference-to-image when references are given, and returns a job. |
| `storyboard_image_jobs` | `shot_id?` | Polls image jobs. |
| `storyboard_image_candidate` | `job_id`, `index?` | Returns one output image of a job, so you can look at it before applying. |
| `storyboard_apply_image` | `job_id`, `index?` | Makes that output the board image. |
| `storyboard_generate_video` | `shot_id`, `prompt?`, `negative_prompt?`, `seconds?`, `end_shot_id?` | **Comfy Cloud credits.** Starts a Wan 2.2 i2v take, or a first+last-frame take when `end_shot_id` is given. |
| `storyboard_video_takes` | `shot_id?` | Polls video takes; without `shot_id`, polls every board. |
| `storyboard_render_sequence` | `route_id?`, `shot_ids?`, `takes?` (`{shot_id: take_id}`) | Renders the chosen takes, in board order, into one MP4 under `Exports/`. |
| `storyboard_list_generation_requests` | `shot_id?`, `destination?`, `status?` | Lists the generation-handoff queue (Codex). |
| `storyboard_get_generation_request` | `request_id` | Returns one handoff package. |
| `storyboard_submit_generation_result` | `request_id`, `artifact_paths`, `summary?` | Uploads generated images as the result of a handoff. |

Board fields:

- Text fields: `title`, `description`, `dialogue`, `action_note`, `camera_note`, `character_note`, `lighting_note`, `transition_note`, `scene`, `status`.
- `duration_seconds` and `tags`.
- Prompt fields: `prompt` sets the board's manual image prompt, and an empty string returns the board to its automatic prompt. Also `prompt_extra` and `negative_prompt`.
- `shot_design`: a partial object that is merged into the board's shot design. For example, `camera_movement` and `subject_movement` feed the video prompt.

The tool-to-endpoint mapping is the `ROUTES` table at the top of `mcp_server.py`.
