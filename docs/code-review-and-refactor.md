# 代码审查与重构记录

最后更新:2026-06-15
范围:`storyboard_tool/`(后端 Python + 前端 `web/static/`)及仓库卫生。
原则:受控重构,保持用户可见行为不变;高风险项先记录、不强行改。

---

## 0. 状态总览

| # | 问题 | 影响文件 | 风险 | 状态 |
|---|------|----------|------|------|
| P1 | `project_manager.py` 是"God object"(约 1649 行) | `storyboard_tool/project_manager.py` | 高 | ✅ 已修复 |
| P2 | API 层逻辑重复(REST 与内部 dispatch 两套) | `api.py` / `backend_service.py` | 高 | ◑ JSON/multipart 已委托;FileResponse 可选 |
| P3 | `apply_ref_segment_*` 三函数重复 | `reference_segments.py` | 中 | ◑ 部分修复 |
| P4 | 备份无上限/无清理,可能无限增长 | `backups.py` | 中 | ✅ 已修复 |
| P5 | 宽泛异常处理(裸 `except` / `except: pass`) | 多个后端文件 | 中 | ◑ 部分修复 |
| P6 | 版本控制卫生:`__pycache__`、`Sessions/*.json` 被跟踪 | 仓库根、`.gitignore` | 低 | ✅ 已修复 |
| P7 | `app.js` 过大(约 2000 行),职责混杂 | `web/static/app.js` | 中 | ◑ 部分修复 |
| P8 | 批注逻辑分散在 `app.js` 多处 | `web/static/app.js` | 低 | ✅ 已修复 |
| P9 | 前端隐式全局命名空间依赖(`globalThis`) | 全部 `web/static/*.js` | 中 | ⏳ 待修复 |
| P10 | 前端隐式脚本加载顺序 | `web/static/main.js` | 中 | ◑ 部分修复 |

图例:✅ 已修复 ◑ 部分修复 ⏳ 待修复

---

## 1. 后端问题与修复

### P1 — `project_manager.py` 是 God object ✅
**问题**:单文件约 1649 行,集中了项目读写、设置、画布、参考片段、Blender 集成、备份等几乎全部业务逻辑,难以维护、易冲突。

**修复方式**:按职责拆分为新模块,并用 **facade(门面)模式**在 `project_manager.py` 中重新导出所有被移动的公共函数,保持对外 API 完全兼容:

- `backups.py` — 备份创建
- `external_tools.py` — Blender 路径/场景、3D 场景导入、外部程序打开文件
- `canvas_settings.py` — 画布尺寸/颜色/显示相关设置
- `reference_segments.py` — 视频/3D/图片参考片段的归一化与应用

`project_manager.py` 从约 1649 行降到约 520 行,保留核心 `create_project` / `open_project` / `save_project`、分镜 CRUD 与底层 helper。新模块通过 `import project_manager as pm` 在**运行时**回调共享 helper,避免循环导入。

**验证**:编译检查、`tests.test_smoke` 通过、项目存取往返自测、各消费方(`api`/`backend_service`/`desktop`/`live_bridge`)导入正常。

### P2 — API 层逻辑重复 ◑
**问题**:`api.py`(REST 路由)与 `backend_service.py`(桌面 dispatch 的 `method_*`)实现了两套高度相似的业务逻辑,改一处容易漏改另一处。

**已做**:`api.py` 中绝大多数有对应 `method_*` 的路由已改为薄适配层,通过 `_svc().method_*()` 委托给 `backend_service.py` 作为**唯一业务实现**。

**Multipart 上传**(P2 收尾):REST 路由读取 `UploadFile` 字节后委托给 `method_*`;dispatch 路径接受 `(filename, bytes|list[int])`,与桌面 `upload_multipart` 的字节数组格式一致。共享 helper:`_normalize_upload_bytes` / `_upload_stream`。

| `method_*` | REST 路由 |
|------------|-----------|
| `upload_project_reference` | `POST /api/project/references` |
| `upload_reference_video` | `POST /api/project/reference-video` |
| `import_scene3d` | `POST /api/project/scene3d/import` |
| `import_shot_image` | `POST /api/shots/{id}/image` |
| `add_shot_reference_image` | `POST /api/shots/{id}/references` |
| `import_shot_source` | `POST /api/shots/{id}/source` |

**JSON 端点**(P2 第二轮):以下也已委托:

| `method_*` | REST 路由 |
|------------|-----------|
| `delete_project_reference` | `DELETE /api/project/references/{id}` |
| `open_blender_scene` | `POST /api/project/scene3d/open-blender` |
| `get_canvas_color` / `set_canvas_color` | `GET/POST /api/project/canvas-color` |
| `remove_shot_reference_image` | `DELETE /api/shots/{id}/references` |
| `set_shot_reference_image_paths` | `PUT /api/shots/{id}/references` |
| `create_shot_canvas` | `POST /api/shots/{id}/canvas` |
| `save_shot_drawing` | `POST /api/shots/{id}/drawing` |
| `sync_all_shots` | `POST /api/project/sync` |

**遗留**(仍保留在 `api.py`,因返回 `FileResponse` 或纯静态):

- 文件下载:export GET 路由、shot image/thumbnail/board-background、`/api/files`、`/api/project/scene3d/file`
- 插件心跳:`POST /api/bridge/plugin-heartbeat`(单行状态写入)
- 静态页面路由:`/`、`/ref-*`

> 桌面端 FormData 上传仍走 `bridge.upload_multipart` → REST(设计如此);`dispatch.js` 尚未为 multipart 注册映射(可选后续)。

### P3 — 参考片段应用函数重复 ◑
**问题**:`apply_ref_segment_to_boards` / `apply_ref_segment_3d_to_boards` / `apply_ref_segment_image_to_boards` 三者有相同的区间与时长校验骨架。

**已做**:抽出共享 helper `_segment_board_range` 与 `_segment_storyboard_duration`,媒体相关逻辑保持各自独立以不改变行为。

**遗留**:三函数主体仍有可进一步合并的骨架,留待下一轮。

### P4 — 备份无清理 ✅
**问题**:`_write_backup` 每次按时间戳复制 `project.json` 与 `shots.csv` 到 `backups/`,**没有数量/时间上限**,长期使用会无限增长。

**修复方式**:在 `backups.py` 增加 `_prune_old_backups`,默认保留最近 **50** 组时间戳备份(`MAX_BACKUP_SETS = 50`)。每次 `_write_backup` 写入后自动清理最旧备份。

**验证**:新增 `test_backup_retention_prunes_oldest_sets`。

### P5 — 宽泛异常处理 ◑
**问题**:多处使用裸 `except` 或 `except: pass`,会吞掉真实错误、增加排障难度。

**现状**:代码库中已无裸 `except:`;剩余 `except Exception: pass` 主要出现在桌面启动重试(`desktop.py`)与可选依赖回退(`video_utils.py`),属有意容错。

**已做**:`method_open_source` / `method_open_preview` 补齐与 REST 一致的 `HTTP 400` 错误包装。

**遗留**:其余容错点需逐处评估后再收窄。

### P6 — 版本控制卫生 ✅
**问题**:`storyboard_tool/__pycache__/*.pyc`、`Sessions/*.json` 等运行期产物曾被 git 跟踪。

**已做**:`.gitignore` 已覆盖 `__pycache__/`、`Sessions/`;已执行 `git rm --cached` 从索引移除 22 个文件(本地文件保留),并提交 commit `c73b785`。

---

## 2. 前端问题与修复

前端是一组**经典脚本(classic `<script>`)**,由 `web/static/main.js` 的 `APP_SCRIPTS` 按固定顺序动态注入。所有顶层 `function` / `const` 落在**同一个全局词法作用域**,彼此靠"全局可见 + 加载顺序"隐式调用。`core/bootstrap.js` 通过 `Object.assign(globalThis, { state, el, ... })` 桥接给唯一的 ES module `reference_model_preview.js`。

### P7 — `app.js` 过大 ◑
**问题**:约 2000 行,混合了状态、渲染、批注、Scene3D、对话框、同步轮询等职责。

**已做**:抽出批注子系统(见 P8),`app.js` 缩减约 240 行。

**遗留**:可继续拆分画布颜色、Scene3D 集成、时间线事件绑定、对话框/Toast 工具、设置 UI 等。

### P8 — 批注逻辑分散 ✅
**问题**:批注的几何、绘制、持久化、指针监听散落在 `app.js` 多处(约 938 / 1271 / 1350 / 1708–1902 行)。

**修复方式**:整体抽取到新文件 `web/static/annotations.js`,包含:
`annotationCache`、`layoutAnnotationCanvas`、`promptAnnotationText`、`loadAnnotations`、`saveAnnotations`、`updateAnnotationControls`、`resizeCanvas`、`drawAnnotations`、`drawAnnotation`、`drawArrowHead`、`imageDrawRect`、`pointerToNormalized`、`denormalize`、`syncAnnotationLayout`,以及 `pointerdown`/`pointermove`/`pointerup` 监听、`resize` 监听和 `ResizeObserver`。

**改动文件**:新增 `annotations.js`;`app.js` 移除上述代码;`main.js` 在 `APP_SCRIPTS` 中注册。

### P9 — 隐式全局命名空间依赖 ⏳
**问题**:函数/变量靠全局作用域互相调用,依赖关系不显式,仍重度依赖 `globalThis`。

**建议修复**:**真正消除需迁移到 ES module 的 `import`/`export`**,但会牵动数百处跨文件引用,且当前**无浏览器端自动化测试**可验证,风险高。建议分阶段:先把已抽出的叶子模块改为真正 `export`,再逐步让消费方改为 module。**本轮未做**。

### P10 — 隐式脚本加载顺序 ◑
**问题**:行为正确与否取决于 `APP_SCRIPTS` 顺序,但顺序约束此前无文档。

**已做**:将 `annotations.js` 放在 `bootstrap.js`/`api.js` 之后、`app.js` 之前,并在文件头注释中**写明该加载顺序约束的原因**:
- 须在 `bootstrap.js` 之后,顶层指针监听才能挂到已就绪的 `el.annotationCanvas`;
- 须在 `app.js` 之前,使其延迟启动渲染调用 `drawAnnotations` / 读取 `annotationCache`(`const`)时已定义,避免 ReferenceError / TDZ。

```
"animatic.js",
"annotations.js",   // 新增
"app.js",
```

**遗留**:整体仍是顺序链式注入,可考虑单一入口 module + 静态 `import` 图彻底取代。

---

## 3. 已运行的检查

- 后端:Python 编译检查;`python -m unittest tests.test_smoke` → **27/27 OK**;项目存取往返自测;消费方导入验证;lint 无错误。
- 前端:`node --check`(`annotations.js`/`app.js`/`main.js` 语法通过);`app.js` 无残留重复定义;同一套冒烟测试覆盖 `main.js`/`app.js`/`core/api.js` 的字符串断言;lint 无错误。

> 说明:当前缺少浏览器端自动化测试,前端行为一致性主要靠经典脚本作用域模型 + 加载顺序的静态推理保证。

---

## 4. 下一轮优先级建议

1. **P2 收尾 FileResponse 适配**(可选):为下载端点增加 `method_*` 返回路径/媒体类型,或保持 REST 层直出文件。
2. **P7 继续拆分 `app.js`**:画布颜色 / Scene3D / 时间线事件 / 设置 UI。
3. **P3 参考片段函数合并**:在行为测试保护下进一步合并三函数骨架。
4. **P9 ES module 迁移**:分阶段、配合浏览器端验证手段推进。
