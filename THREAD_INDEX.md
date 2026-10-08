# Thread Index

Reviewed from Codex chats on 2026-10-03. Status describes recorded chat work, not fresh runtime acceptance. Archived labels reflect confirmed archive actions.

| Chat | Purpose | Status | Key outcomes | Files / components | Related |
|---|---|---|---|---|---|
| [ARCH] Project State Boundaries (`01a0fd13-46dd-7341-b5d0-493117bb419e`) | 分阶段重构项目状态、保存与事务边界。 | Round 2 complete | 两轮均已整合；编辑命令/历史与场景服务归属明确，既有 lint 清零；后端 1327 通过/2 跳过，前端 38 通过，最终界面 19/19 通过。 | ProjectContext; mutation_executor; scene service adapters | 下方子代理记录及 docs/design/project-boundaries-round2-2026-10-03.md |
| [FEAT] Comic Animatic Tools (`01a0fa9f-60fa-76b1-824c-0fa66f3ef955`) | 处理“Comic Animatic Tools”相关的实现、调查或交付。 | Blocked | long scroll、spread、时间线和导出已实现，桌面宿主未验。 | Storyboarder | — |
| [FEAT] Embedded Drawing Editor (`01a04406-beec-7711-a575-23670672ac0b`) | 处理“Embedded Drawing Editor”相关的实现、调查或交付。 | Blocked | 嵌入式绘画已实现，真实笔压未验。 | Storyboarder | — |
| [FEAT] Branching Story Map (`019fa905-807b-7f40-b1de-ab9ceaa5f35c`) | 处理“Branching Story Map”相关的实现、调查或交付。 | Blocked | 分支地图、绘制和重启 QA 有结果，导出及桌面验证未完。 | Storyboarder | — |
| [FEAT] Shot Prompt Continuity (`019f5ae4-b2e3-7aa1-aef3-82d228ad055b`) | 完善镜头提示词与连续性编写。 | Resolved | 镜头提示词与连续性编写近期有实质工作。 | Storyboarder | — |
| 更新 Shot 展开与 Scene 继承 (archived) (`019f969d-699c-72d1-b6ba-e91c8b22c393`) | 处理“更新 Shot 展开与 Scene 继承”相关的实现、调查或交付。 | Resolved | Layers/Queue 持久开合与 BoardStrip 滚动修复已完成。 | Storyboarder; BoardStrip | — |
| Frontend-only task in a React + TypeScript app (cwd = repo root). Edit ONLY these two files: - … (archived) (`019f8df3-19ed-7113-8156-94e9f958cb25`) | 实现 BoardGrid 拖拽排序与定位。 | Resolved | BoardGrid 拖拽排序与选中项自动滚动已实现。 | Storyboarder; BoardGrid | — |
| Add Stable Diffusion workflow (archived) (`019f849e-956f-70d2-a59a-4b1fd00f770a`) | 处理“Add Stable Diffusion workflow”相关的实现、调查或交付。 | Resolved | Send to Codex 作为唯一生成入口且不自动运行的决策有用。 | Storyboarder | — |
| You are implementing a small, bounded, backward-compatible backend change in a Python project. … (archived) (`019f84b1-7c23-7831-beb6-bc97d6e6a8eb`) | 为生成服务加入 provider 字段。 | Resolved | 生成服务 provider 字段和 codex 默认值已加测试。 | Storyboarder | — |
| 确认拉取改动后是否需要构建 (archived) (`019f79c3-003c-7b11-8fcb-664bb6faa6ec`) | 处理 Storyboarder 浮动面板与 3D 资产快照。 | Superseded | 后续完成浮动 Layers/Queue 和 Scene3D 资产快照。 | Storyboarder; Scene3D | — |
| [OPS] UXP Plugin Packaging (`019f2d3f-beaa-7a90-a1af-1ef85648d79c`) | 处理“UXP Plugin Packaging”相关的实现、调查或交付。 | Blocked | 插件图标与 manifest 修好，实际 UXP Package 重试未完。 | Storyboarder | — |
| 优化加号图标与右键菜单 (archived) (`019eea59-42e3-7d83-87e6-ac0507060798`) | 处理“优化加号图标与右键菜单”相关的实现、调查或交付。 | Resolved | BoardStrip 居中与创建后几何问题已修并构建。 | Storyboarder; BoardStrip | — |
| 修复3D自由视角失效 (archived) (`019eea79-eef4-7ca1-9f41-e428d383a04c`) | 处理“修复3D自由视角失效”相关的实现、调查或交付。 | Resolved | Scene3D 自由视角被强制重置的问题已修。 | Storyboarder; Scene3D | — |
| Fix CODEX_TASK issues (archived) (`019ee93b-82ec-7891-adcf-6a4de3eae17e`) | 处理“Fix CODEX_TASK issues”相关的实现、调查或交付。 | Resolved | Photoshop 路径、Scene2D 恢复及预览生命周期已修。 | Storyboarder; Photoshop; Scene2D | — |
| Read CODEX_TASK.md (archived) (`019ee253-67ca-7620-b9ed-f006cd7427d2`) | 处理“Read CODEX_TASK.md”相关的实现、调查或交付。 | Resolved | Scene2D UUID 迁移带 journal/rollback 与恢复测试。 | Storyboarder; Scene2D | — |
| Redesign storyboard main layout (archived) (`019ee4d2-32e8-7900-b204-8923d3ace8d8`) | 处理“Redesign storyboard main layout”相关的实现、调查或交付。 | Superseded | 主界面布局和暗色画布改版完成，旧 CSS 覆盖已修。 | Storyboarder | — |
| 锁定依赖版本 (archived) (`019edf64-57c5-7083-893b-777c957a9c89`) | 处理“锁定依赖版本”相关的实现、调查或交付。 | Resolved | 桥接 runtime 状态与请求 schema 提取有测试结果。 | Storyboarder | — |
| [BUG] Photoshop Background Sync (`019edb8a-8e2e-76a3-bb19-4b996a8bc0d0`) | 处理“Photoshop Background Sync”相关的实现、调查或交付。 | Blocked | 背景持久化路径改了，Photoshop 重开人工验收未完。 | Storyboarder; Photoshop | — |
| 检查 merge 冲突 (archived) (`019edaf0-31f2-79a0-ae0d-38156ce1cfda`) | 处理“检查 merge 冲突”相关的实现、调查或交付。 | Resolved | 合并保留前端状态与 Photoshop bridge 合约，通过测试。 | Storyboarder; Photoshop | 019eda79-4b2c |
| Add plugin API endpoints (archived) (`019ed967-1c0b-7b00-a552-1aa7c43b7982`) | 处理“Add plugin API endpoints”相关的实现、调查或交付。 | Resolved | 桥接 API、schema 和 heartbeat 刷新有完整实现记录。 | Storyboarder | — |
| Integrate roadmap branches (archived) (`019eda79-4bc9-7e70-8769-80dd34d98214`) | 处理“Integrate roadmap branches”相关的实现、调查或交付。 | Resolved | 前端状态边界分支通过构建，后被合并。 | Storyboarder | — |
| Build storyboard MVP (archived) (`019eba59-abc5-7612-8545-4f8178613bac`) | 处理“Build storyboard MVP”相关的实现、调查或交付。 | Superseded | 早期 Python/UXP MVP 有历史价值，现已被后续版本替代。 | Storyboarder | — |

## Project boundary refactor sub-agents — 2026-10-03

These are bounded sub-agents of the Project State Boundaries chat, not separate user-owned chats. Shared contract and final evidence: `docs/design/project-boundaries-refactor-2026-10-03.md`. Isolation baseline: `74924258417086501f76b6971db03c98105db048` (working source snapshot; integration branch/index unchanged). Temporary worker worktrees are archived; task-only branches were removed after exact integration checks.

| Agent | Model / effort | Scope / components | Status | Integration |
|---|---|---|---|---|
| `/root/frontend` | GPT-6 Astra / high | Frontend project lifecycle, draft flushing, stale response acceptance | Complete | Integrated through `cb1d81d`; 18 frontend regressions pass; worktree archived |
| `/root/backend` | GPT-6 Astra / high | Explicit operation mutation policies and transaction execution | Complete | Integrated through `9441522`; 146 handlers inventoried; worktree archived |
| `/root/verifier` | GPT-6 Astra / high | Baseline and integrated backend/frontend/UI verification | Complete with recorded exceptions | Full backend 1277 pass/2 skip/1 known lease failure; fixture repaired and module 42 pass; frontend build and browser 9/9 pass; 8 pre-existing lint errors |
| `/root` | Current model | Reference metadata storage boundary, review and integration | Complete | Main checkout preserves prior work; docs/bundle integrated, index unchanged, no commit/push |

## Round 2 sub-agents — 2026-10-03

The same bounded sub-agents continued their established scopes. Contract and evidence: `docs/design/project-boundaries-round2-2026-10-03.md`. Both round-two worktrees are archived, and their temporary branches plus the isolation-baseline branch were removed after exact integration checks. First-round worktrees remain archived.

| Agent | Model / effort | Scope | Status |
|---|---|---|---|
| `/root/frontend` | GPT-6 Astra / high | Board/reference commands and shared reversible history | Complete; integrated `9ee0799`, 38 behavioral tests pass; worktree archived |
| `/root/backend` | GPT-6 Astra / high | Scene2D/Scene3D service ownership and upload helper boundary | Complete; integrated `2257226`, 244 targeted tests and full backend pass; worktree archived |
| `/root/verifier` | GPT-6 Astra / high | Baseline, full integrated gate and browser behavior | Complete; full gate exit 0 (1327 backend/2 skips, 38 frontend); final frontend gate and 19/19 browser checks pass |
| `/root` | Current model | Component/shortcut state repair, contracts, review and integration | Complete; original work preserved, final bundles integrated, main index unchanged, no commit/push |

## Route interaction and new SBD type — 2026-10-03

Bounded sub-agents in the current chat; no new user-owned chat. Root completed route-strip source edits before handing sole source-writer ownership to `new_sbd_type`; Verifier owns all executable checks and builds. Existing dirty work is preserved.

| Agent | Model / effort | Scope | Status |
|---|---|---|---|
| `/root` | Current model | Route wheel/resize repair, shared project-type contract and integration review | Complete; existing work preserved, no commit/push |
| `/root/new_sbd_type` | GPT-6 Astra / high | Video/Comic creation choice, persistence, initial workspace, right-inspector CSS and Layout 2 recents save repair | Complete; source reviewed and integrated |
| `/root/verifier` | Existing agent settings | Route/inspector gestures, creation cancellation/reopen and sequential checks/builds | Complete; 80 Python and 38 frontend tests pass, build/lint pass, browser checks pass; temporary services stopped |
