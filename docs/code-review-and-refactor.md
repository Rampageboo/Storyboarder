# 代码审查与重构记录

最后更新:2026-06-15
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

### P1 — `project_manager.py` 是 God object ✅
**问题**:单文件约 1649 行,集中了项目读写、设置、画布、参考片段、Blender 集成、备份等几乎全部业务逻辑,难以维护、易冲突。

**修复方式**:按职责拆分为新模块,并用 **facade(门面)模式**在 `project_manager.py` 中重新导出所有被移动的公共函数,保持对外 API 完全兼容:

- `backups.py` — 备份创建
- `external_tools.py` — Blender 路径/场景、3D 场景导入、外部程序打开文件
- `canvas_settings.py` — 画布尺寸/颜色/显示相关设置
- `reference_segments.py` — 视频/3D/图片参考片段的归一化与应用

`project_manager.py` 从约 1649 行降到约 520 行,保留核心 `create_project` / `open_project` / `save_project`、分镜 CRUD 与底层 helper。新模块通过 `import project_manager as pm` 在**运行时**回调共享 helper,避免循环导入。

**验证**:编译检查、`tests.test_smoke` 通过、项目存取往返自测、各消费方(`api`/`backend_service`/`desktop`/`live_bridge`)导入正常。

### P2 — API 层逻辑重复 ✅
**问题**:`api.py`(REST 路由)与 `backend_service.py`(桌面 dispatch 的 `method_*`)实现了两套高度相似的业务逻辑,改一处容易漏改另一处。

**已做**:`api.py` 中绝大多数有对应 `method_*` 的路由已改为薄适配层,通过 `_svc().method_*()` 委托给 `backend_service.py` 作为**唯一业务实现**。

**Multipart 上传**:REST 路由读取 `UploadFile` 字节后委托给 `method_*`;dispatch 路径接受 `(filename, bytes|list[int])`,与桌面 `upload_multipart` 的字节数组格式一致。共享 helper:`_normalize_upload_bytes` / `_upload_stream`。

**JSON 端点**:项目生命周期、shots CRUD、comments、annotations、exports POST、settings、ref-segment apply、canvas-color、drawing、sync 等均已委托。

**FileResponse 下载**(P2 收尾):`backend_service` 新增 `method_get_*` / `method_download_*` 返回 `{path, media_type, filename}` 元数据;`api.py` 通过 `_file_response_from_meta()` 薄包装为 `FileResponse`,保留路径越界检查语义。

| `method_*` | REST 路由 |
|------------|-----------|
| `get_scene3d_file` | `GET /api/project/scene3d/file` |
| `get_shot_image` / `get_shot_thumbnail` / `get_shot_board_background` | 对应 shot GET |
| `get_project_file` | `GET /api/files` |
| `download_shot_list` / `download_timing` / `download_contact_sheet` / `download_pdf` | 对应 export GET |

**仍保留在 `api.py`**(非业务 JSON):

- 插件心跳:`POST /api/bridge/plugin-heartbeat`
- 静态页面路由:`/`、`/ref-*`

### P3 — 参考片段应用函数重复 ✅
**问题**:`apply_ref_segment_to_boards` / `apply_ref_segment_3d_to_boards` / `apply_ref_segment_image_to_boards` 三者有相同的路径校验与持久化骨架。

**已做**:

- 共享 helper `_segment_board_range`、`_segment_storyboard_duration`(此前已有)
- 新增 `_validate_segment_reference(project, seg, expected_type)` — 统一 video/model/image 路径存在性与 project root 校验
- 新增 `_persist_ref_segment_apply(...)` — 合并三函数末尾相同的 `ref_segment_apply` / `ref_segments` / `active_ref_segment_id` 写入与 `save_settings` / `save_shots_csv`
- 三函数各自保留 per-shot board loop(视频抽帧 / 3D 相机+预览 / 静态图 fit)

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

前端是一组**经典脚本(classic `<script>`)**,由 `web/static/main.js` 的 `APP_SCRIPTS` 按固定顺序动态注入;部分叶子模块已迁移为 ES module,由 `app/bootstrap_module.js` 并行加载并桥接到 `globalThis`。`core/bootstrap.js` 通过 `Object.assign(globalThis, { state, el, ... })` 桥接核心状态。

### P7 — `app.js` 过大 ◑
**问题**:约 2000 行,混合了状态、渲染、批注、Scene3D、对话框、同步轮询等职责。

**已做**:

- P8:抽出 `annotations.js`
- 新增 `core/canvas_size.js` — 画布尺寸预设、新建项目对话框、设置面板控件
- 新增 `dialogs.js` — `showDialog`、项目新建/打开、browse
- 新增 `canvas_color.js` — 画布颜色对话框与 `createCanvasForShot`
- 新增 `scene3d_app.js` — 3D 场景模态、Blender 导入、capture、reload

`app.js` 显著瘦身;同步/bridge 轮询仍与 app 生命周期耦合,留待下一轮。

### P8 — 批注逻辑分散 ✅
**问题**:批注的几何、绘制、持久化、指针监听散落在 `app.js` 多处。

**修复方式**:整体抽取到 `web/static/annotations.js`;`main.js` 在 `app.js` 之前注册。

### P9 — 隐式全局命名空间依赖 ◑
**问题**:函数/变量靠全局作用域互相调用,依赖关系不显式。

**已做(4a+4b 启动)**:

- `dialogs.js`、`canvas_color.js`、`scene3d_app.js` 改为 `export function ...`
- `index.html` 扩展 `<script type="importmap">`(`@app/dialogs` 等)
- 新增 `app/bootstrap_module.js`:按序 `import` 上述模块并 `Object.assign(globalThis, ...)`
- `main.js` 通过 `MODULE_GATE_SCRIPTS` 在加载 `core/canvas_size.js` 与 `app.js` 前等待 `__bootstrapModuleReady`

**遗留**:Layer2+(`core/api`、`dispatch`、`settings`、timeline 等)仍待迁移;建议配合 Playwright 或最小浏览器 smoke 后再大规模推进。

### P10 — 隐式脚本加载顺序 ◑
**问题**:行为正确与否取决于 `APP_SCRIPTS` 顺序,但顺序约束此前无文档。

**已做**:各抽出文件头注释写明 `APP_SCRIPTS` 顺序约束;`bootstrap_module` 与经典加载链并行,门控脚本在模块就绪后继续。

**当前关键顺序**:

```
core/utils.js
(core/canvas_size.js — 门控,需 module bootstrap)
...
annotations.js
app.js — 门控
```

**遗留**:整体仍是顺序链式注入 + 模块门控;长期目标为单一 module 入口 + 静态 `import` 图。

---

## 3. 已运行的检查

- 后端:Python 编译检查;`python -m unittest tests.test_smoke` → **29/29 OK**;项目存取往返自测;消费方导入验证。
- 前端:`node --check` 语法通过;冒烟测试覆盖 `main.js`/`app.js`/`bootstrap_module.js`/`index.html` import map 字符串断言。

> 说明:当前缺少浏览器端自动化测试,前端行为一致性主要靠经典脚本作用域模型 + 加载顺序的静态推理保证。

---

## 4. 下一轮优先级建议

1. **P7 继续拆分 `app.js`**:同步/bridge 轮询、设置对话框(Blender/Photoshop)、导出与文件操作。
2. **P9 ES module 迁移 Layer2+**:`core/state`、`dom`、`api`、`dispatch` — 配合浏览器端 smoke。
3. **P5 异常处理收窄**:逐处评估 `except Exception` 容错点。
4. **P10 单一 module 入口**:逐步用 `bootstrap_module.js` 替代 `APP_SCRIPTS` 循环。
