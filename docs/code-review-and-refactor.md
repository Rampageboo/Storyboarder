# 代码审查与重构记录

最后更新:2026-06-15(Layer3 / P10 / P5 续推已落地)
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
| P10 | 前端隐式脚本加载顺序 | `web/static/app/main_module.js` | 中 | ✅ 已修复 |

图例:✅ 已修复 ◑ 部分修复 ⏳ 待修复

---

## 1. 后端问题与修复

(与此前相同,P1–P6 均已记录,此处从略。详见 git 历史 `84396d0` 及之前提交。)

**P5 本轮收尾**(`971746e`):

- `desktop.py`:Windows 任务栏 API 与启动轮询保留宽泛捕获,加 `# intentional` 注释
- `bridge.py`:webview 窗口复用/创建收窄为 `RuntimeError`/`AttributeError` + `logger.warning`;JSON 解析收窄为 `json.JSONDecodeError`/`ValueError`
- `live_bridge.py`:`is_storyboard_server` 网络/JSON 错误收窄
- `video_utils.py`:`ImportError` 分支补注释(回退 ffmpeg)

**未改**:`backend_service.py` 中 `except Exception → HTTPException`(业务包装,非吞异常)。

---

## 2. 前端问题与修复

前端由 **`app/main_module.js`(单一 ES module 入口)** 加载:

1. `init_globals.js` — Layer2(`utils`/`state`/`dom`)、Layer3(`api`/`dispatch`)、叶子模块(`dialogs`/`canvas_color`/`scene3d_app`)桥接到 `globalThis`
2. `main_module.js` — 按原 `APP_SCRIPTS` 顺序 **顺序注入经典脚本**,再处理启动 overlay

已删除:`main.js`、`bootstrap_module.js`、`__bootstrapModuleReady` 门控。

### P7 — `app.js` 过大 ◑
**问题**:约 2000 行,混合了状态、渲染、批注、Scene3D、对话框、同步轮询等职责。

**已做**:

- P8:`annotations.js`
- `core/canvas_size.js`、`dialogs.js`、`canvas_color.js`、`scene3d_app.js`
- `sync_polling.js` — 后台同步轮询、live-bridge 心跳、bridge 状态轮询
- `exports_ui.js` — PDF/导出触发、打开预览/源文件、relink preview
- **`external_tools_ui.js`** — Blender/Photoshop 桥接、在 Blender 中打开、`renderBlenderMenuStatus`

`app.js` 已降至约 **750 行**;渲染/inspector 核心仍保留。

### P8 — 批注逻辑分散 ✅
整体抽取到 `annotations.js`。

### P9 — 隐式全局命名空间依赖 ◑
**已做**:

- **Layer1**(叶子):`dialogs.js`、`canvas_color.js`、`scene3d_app.js` → `export` + `init_globals.js` 内动态 `import`(在 `el` 就绪后)
- **Layer2**(核心):`core/utils.js`、`core/state.js`、`core/dom.js` → `export`;`init_globals.js` 内 `buildEl()` 并 `Object.assign(globalThis, ...)`
- **Layer3**:`core/api.js`、`core/dispatch.js` → `export`;`apiDispatch` 经 `globalThis.showToast` 破环
- 已删除经典 `core/bootstrap.js`
- `index.html` import map 含 `@core/*` 与 `@app/*`

**遗留**:其余 `APP_SCRIPTS` 仍为经典脚本(由 `main_module.js` 顺序加载);`core/settings.js` 等可继续 Layer3 化。

### P10 — 隐式脚本加载顺序 ✅
**当前加载模型**:

1. `index.html` 仅 `<script type="module" src="/static/app/main_module.js">`
2. `init_globals.js` 建立 `globalThis` 桥接
3. `main_module.js` 内 `APP_SCRIPTS` 数组 + `loadClassicScript` 保持原顺序

**`APP_SCRIPTS` 顺序**(与旧 `main.js` 一致):

```
core/canvas_size.js → theme → toolbar_menus → exports_ui.js → status → undo
→ ref_segment → reference_* → timeline → virtual_timeline → animatic
→ sync_polling → external_tools_ui.js → annotations.js → app.js → settings → hints → drop
```

**说明**:经典脚本链暂保留全局作用域语义;终局可将各文件改为 `export` + 静态 import(需梳理跨文件标识符)。

---

## 3. 已运行的检查

- 后端:`python -m unittest tests.test_smoke` → **30/30 OK**
- 浏览器(需 dev 依赖):`pip install -r requirements-dev.txt && playwright install chromium` → `tests.test_browser_startup` → **2/2 OK**
- 合计 discover `tests/test_*.py` → **32/32 OK**
- 前端:`node --check`;字符串 smoke 覆盖 `main_module.js` / `init_globals.js` / `index.html` import map

---

## 4. 下一轮优先级建议

1. **P9 Layer3 续**:`core/settings.js`、`core/status.js` 等迁入 module + 减少 `globalThis` 桥接
2. **P7 继续拆分 `app.js`**:渲染/inspector 核心逐步抽出
3. **P5 异常处理**:`backend_service` 以外剩余宽泛 `except Exception` 逐处评估
4. **P10 静态 import 图**:将 `APP_SCRIPTS` 经典链改为 ES module 静态 import(需处理模块间全局标识符)

---

## 5. 后续路线图(续写 · 2026-06-15)

### 5.0 浏览器 smoke ✅

- 新增 [`requirements-dev.txt`](requirements-dev.txt)(`playwright>=1.40`)
- 新增 [`tests/test_browser_startup.py`](tests/test_browser_startup.py):启动 uvicorn → 打开 `/` → 断言 overlay 完成、关键全局函数、REST 新建项目
- 未安装 playwright 时自动 skip,不影响 CI 最小路径

### 5.1 P9 Layer2 ✅

| 目标 | 状态 |
|------|------|
| `core/utils.js` | ✅ `export function` |
| `core/state.js` | ✅ `export const state/dialogState/...` |
| `core/dom.js` | ✅ `export function buildEl`;`el` 在 bootstrap 内实例化 |
| `core/bootstrap.js` | ✅ 已删除,合并进 `init_globals.js` |

`init_globals.js` 使用 **top-level await + 动态 import**,确保 `el` 就绪后再加载 `dialogs`/`canvas_color`/`scene3d_app`。

### 5.2 P9 Layer3 — API 与分发层 ✅

- `core/api.js`、`core/dispatch.js` 改为 `export`,由 `init_globals.js` 桥接
- `test_browser_startup` 门禁通过

### 5.3 P7 剩余拆分 ✅

| 模块 | 状态 |
|------|------|
| `sync_polling.js` | ✅ |
| `exports_ui.js` | ✅ |
| `external_tools_ui.js`(Blender/PS 桥接 UI) | ✅ |

### 5.4 P5 异常收尾 ◑

本轮已处理 `desktop`/`bridge`/`live_bridge`/`video_utils`;其余后端文件待续。

### 5.5 单一 module 入口(P10 收口) ✅

- `app/main_module.js` + `app/init_globals.js` 替代双脚本加载
- `index.html` 单 module 入口;删除 `main.js` 与 `bootstrap_module.js`

### 推荐执行顺序(更新后)

1. ~~5.0 浏览器 smoke~~ ✅
2. ~~5.3 sync_polling + exports_ui + external_tools_ui~~ ✅
3. ~~5.1 Layer2~~ ✅
4. ~~5.2 Layer3 api/dispatch~~ ✅
5. ~~5.5 单一入口~~ ✅
6. ~~5.4 异常收尾(本轮)~~ ◑
7. **Layer3 续(settings 等)** + **app.js 渲染核心拆分** + **APP_SCRIPTS 静态 import 化**
