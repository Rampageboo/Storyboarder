# 代码审查与重构记录

最后更新:2026-06-15(路线图 5.0–5.3 已落地)
范围:`storyboard_tool/`(后端 Python + 前端 `web/static/`)及仓库卫生。
原则:受控重构,保持用户可见行为不变;高风险项先记录、不强行改。

---

## 0. 状态总览

| # | 问题 | 影响文件 | 风险 | 状态 |
|---|------|----------|------|------|
| P1 | `project_manager.py` 是"God object"(约 1649 行) | `storyboard_tool/project_manager.py` | 高 | ✅ 已修复 |
| P2 | API 层逻辑重复(REST 与内部 dispatch 两套) | `api.py` / `backend_service.py` | 高 | ✅ 已修复 |
| P3 | `apply_ref_segment_*` 三函数重复 | `reference_segments.py` | 中 | ✅ 已修复 |
| P4 | 备份无上限/无清理,可能无限增长 | `backups.py` | 中 | ✅ 已修复 |
| P5 | 宽泛异常处理(裸 `except` / `except: pass`) | 多个后端文件 | 中 | ◑ 部分修复 |
| P6 | 版本控制卫生:`__pycache__`、`Sessions/*.json` 被跟踪 | 仓库根、`.gitignore` | 低 | ✅ 已修复 |
| P7 | `app.js` 过大(约 2000 行),职责混杂 | `web/static/app.js` | 中 | ◑ 部分修复 |
| P8 | 批注逻辑分散在 `app.js` 多处 | `web/static/app.js` | 低 | ✅ 已修复 |
| P9 | 前端隐式全局命名空间依赖(`globalThis`) | 全部 `web/static/*.js` | 中 | ◑ 部分修复 |
| P10 | 前端隐式脚本加载顺序 | `web/static/main.js` | 中 | ◑ 部分修复 |

图例:✅ 已修复 ◑ 部分修复 ⏳ 待修复

---

## 1. 后端问题与修复

(与此前相同,P1–P6 均已记录,此处从略。详见 git 历史 `84396d0` 及之前提交。)

---

## 2. 前端问题与修复

前端由 **`app/bootstrap_module.js`(ES module)** 桥接 Layer2 核心与叶子模块到 `globalThis`,再由 `main.js` 的 `APP_SCRIPTS` 按序注入经典脚本。`main.js` 在 `__bootstrapModuleReady` 之前不加载任何经典脚本。

### P7 — `app.js` 过大 ◑
**问题**:约 2000 行,混合了状态、渲染、批注、Scene3D、对话框、同步轮询等职责。

**已做**:

- P8:`annotations.js`
- `core/canvas_size.js`、`dialogs.js`、`canvas_color.js`、`scene3d_app.js`
- `sync_polling.js` — 后台同步轮询、live-bridge 心跳、bridge 状态轮询
- `exports_ui.js` — PDF/导出触发、打开预览/源文件、relink preview

`app.js` 已降至约 **950 行**;设置对话框(Blender/Photoshop)与渲染核心仍保留。

### P8 — 批注逻辑分散 ✅
整体抽取到 `annotations.js`。

### P9 — 隐式全局命名空间依赖 ◑
**已做**:

- **Layer1**(叶子):`dialogs.js`、`canvas_color.js`、`scene3d_app.js` → `export` + 动态 `import`(在 `el` 就绪后)
- **Layer2**(核心):`core/utils.js`、`core/state.js`、`core/dom.js` → `export`;`bootstrap_module.js` 内 `buildEl()` 并 `Object.assign(globalThis, ...)`
- 已删除经典 `core/bootstrap.js`(逻辑合并进 `bootstrap_module.js`)
- `index.html` import map 含 `@core/*` 与 `@app/*`

**遗留**:Layer3(`core/api.js`、`core/dispatch.js`、`core/settings.js` 等)仍待迁移。

### P10 — 隐式脚本加载顺序 ◑
**当前加载模型**:

1. `bootstrap_module.js`(module, top-level await) → 设置 `__bootstrapModuleReady`
2. `main.js` 轮询就绪后注入 `APP_SCRIPTS` 全链

**当前 `APP_SCRIPTS` 顺序**:

```
core/canvas_size.js → theme → dispatch → api → exports_ui.js → … → sync_polling.js → annotations.js → app.js → settings → …
```

**遗留**:终局为单一 `app/main_module.js` 静态 import 图(见 5.5)。

---

## 3. 已运行的检查

- 后端:`python -m unittest tests.test_smoke` → **30/30 OK**
- 浏览器(需 dev 依赖):`pip install -r requirements-dev.txt && playwright install chromium` → `tests.test_browser_startup` → **2/2 OK**
- 合计 discover `tests/test_*.py` → **32/32 OK**
- 前端:`node --check`;字符串 smoke 覆盖 `main.js` / `bootstrap_module.js` / `index.html` import map

---

## 4. 下一轮优先级建议

1. **P7 继续拆分 `app.js`**:Blender/Photoshop 设置对话框 → `external_tools_ui.js`;渲染/inspector 可逐步抽出。
2. **P9 Layer3**:`core/api.js`、`core/dispatch.js` module 化(已有 Playwright smoke 护航)。
3. **P5 异常处理收窄**:逐处评估 `except Exception`。
4. **P10 单一 module 入口**:`app/main_module.js` 替代 `APP_SCRIPTS` 循环。

---

## 5. 后续路线图(续写 · 2026-06-15)

### 5.0 浏览器 smoke ✅

- 新增 [`requirements-dev.txt`](requirements-dev.txt)(`playwright>=1.40`)
- 新增 [`tests/test_browser_startup.py`](tests/test_browser_startup.py):启动 uvicorn → 打开 `/` → 断言 overlay 完成、`__bootstrapModuleReady`、关键全局函数、REST 新建项目
- 未安装 playwright 时自动 skip,不影响 CI 最小路径

### 5.1 P9 Layer2 ✅

| 目标 | 状态 |
|------|------|
| `core/utils.js` | ✅ `export function` |
| `core/state.js` | ✅ `export const state/dialogState/...` |
| `core/dom.js` | ✅ `export function buildEl`;`el` 在 bootstrap 内实例化 |
| `core/bootstrap.js` | ✅ 已删除,合并进 `bootstrap_module.js` |

`bootstrap_module.js` 使用 **top-level await + 动态 import**,确保 `el` 就绪后再加载 `dialogs`/`canvas_color`/`scene3d_app`(修复并行加载竞态)。

### 5.2 P9 Layer3 — API 与分发层(下一步)

- `core/api.js`、`core/dispatch.js` 改为 `export`
- 迁移后跑 `test_browser_startup`

### 5.3 P7 剩余拆分

| 模块 | 状态 |
|------|------|
| `sync_polling.js` | ✅ |
| `exports_ui.js` | ✅ |
| `external_tools_ui.js`(Blender/PS 设置对话框) | ⏳ 下一步 |

### 5.4 P5 异常收尾 ⏳

### 5.5 单一 module 入口(P10 收口) ⏳

### 推荐执行顺序(更新后)

1. ~~5.0 浏览器 smoke~~ ✅
2. ~~5.3 sync_polling + exports_ui~~ ✅
3. ~~5.1 Layer2~~ ✅
4. **5.2 Layer3 api/dispatch** + **5.3 external_tools_ui**
5. **5.5 单一入口** + **5.4 异常收尾**
