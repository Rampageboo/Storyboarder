# 修复计划 — 逐条执行的 Loop Prompts

> 面向**本地自用**(通过 `Storyboarder.vbs` 启动桌面窗口)的修复清单。
> 不涉及打包/发布。按顺序逐条执行,**每条做完先验证、再提交,然后才做下一条**。

## 怎么用这份文档

1. 复制下面某个 Prompt 的整段文字,贴给 Claude Code 执行。
2. 等它改完,按该 Prompt 的「验收」跑测试 / 启动确认。
3. 没问题就用该 Prompt 的「提交信息」提交。
4. 再做下一条。**不要一次性把所有 Prompt 一起丢进去。**

优先级:**Prompt 1 现在就做**(零风险、收益最大)。Prompt 2–4 顺手做。Prompt 5 属于"以后想加功能再说"的可选重构。

---

## 通用规则(每条 Prompt 都默认遵守 —— 也写进每个 Prompt 里了)

- **不要改生成产物**:`storyboard_tool/web/dist/**`、`storyboard_tool/web/static/runtime/scene3d_workspace.js`、`storyboard_tool/web/static/vendor/**`。
- **不要动 Photoshop 桥接契约**:`/api/plugin/*`、`/api/bridge/*` 的字段名、心跳文件名、超时常量(见 `docs/current_architecture.md` 第 13 节)。这块历史上出过"图层重置/死循环"的 bug,非本计划范围不要碰。
- **每条改动都要能跑通现有测试**:`.venv\Scripts\python.exe -m pytest tests/ -q`。
- **行为尽量保持不变**:这些是稳定性/可维护性修复,不是功能改动。
- 改完**只提交本条相关的文件**,提交信息用每条给的那句。

---

## Prompt 1 — 锁定依赖版本(现在就做)

**解决:** 依赖全是 `>=`,且 `run-silent.bat` 在 `.venv` 损坏时会删库重建并安装"当时最新版",可能某天静默把 pywebview / psd-tools / opencv 升级到不兼容版本,导致桌面窗口打不开,而 `pythonw` 无控制台、报错只进 `logs\desktop.log`,极难排查。

复制以下整段给 Claude Code:

> 任务:把这个项目的 Python 依赖锁定到我当前 `.venv` 里已验证可用的精确版本,这样 venv 即使被重建也不会升级到未知版本。
>
> 步骤:
> 1. 运行 `.venv\Scripts\python.exe -m pip freeze` 把当前已安装的精确版本写入仓库根目录的新文件 `requirements.lock.txt`(用 `==` 固定版本)。在文件顶部加一行注释说明:这是从已验证 venv 冻结出来的锁定版本,运行时安装应优先用它;`requirements.txt` 保留为人类可读的顶层依赖清单。
> 2. 修改 `run-silent.bat` 和 `run.bat`:把安装命令从 `pip install -r requirements.txt` 改为 `pip install -r requirements.lock.txt`(如果 `requirements.lock.txt` 不存在则回退到 `requirements.txt`)。其余逻辑不变。
> 3. 在 `requirements.txt` 顶部加一行注释,指向 `requirements.lock.txt` 说明二者关系。
>
> 禁止:不要改任何 `.py` 源码;不要改生成产物(`web/dist`、`scene3d_workspace.js`、`web/static/vendor`);不要新增第三方依赖。
>
> 验收:`requirements.lock.txt` 存在且全部是 `==` 精确版本;两个 `.bat` 都引用它;`.venv\Scripts\python.exe -m pytest tests/ -q` 全绿。
>
> 提交信息:`build: pin runtime dependencies via requirements.lock.txt`

---

## Prompt 2 — 清理 `desktop.py` 重复函数并加固 asyncio 补丁

**解决:** `desktop.py` 里 `_ignore_connection_reset` 重复定义了两份(约第 59 行的嵌套版本 + 约第 101 行的模块级版本);并且启动时给 CPython 私有类 `asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost` 打了猴补丁,Python 升级后这个私有实现可能消失,会让启动**静默失败**。

复制以下整段给 Claude Code:

> 任务:清理 `storyboard_tool/desktop.py` 的重复代码,并让 asyncio 私有补丁在失效时"响亮地"降级而不是静默炸掉。行为对正常情况必须完全不变。
>
> 步骤:
> 1. `desktop.py` 里有两份内容相同的 `_ignore_connection_reset`:一份嵌套在 `_configure_windows_asyncio_noise` 内、一份是模块级。保留模块级那份,删掉嵌套那份,并让 `_configure_windows_asyncio_noise` 直接引用模块级函数。
> 2. 给那段替换 `_ProactorBasePipeTransport._call_connection_lost` 的猴补丁包一层防御:用 `getattr` 确认目标属性存在再打补丁;如果不存在(未来 Python 版本移除/改名),用 `logging` 记一条 warning 然后**跳过补丁继续启动**,绝不让 `AttributeError` 冒泡导致启动失败。
> 3. 不改变 Windows 上正常压制 ConnectionReset/10053/10054 噪音的现有行为。
>
> 禁止:不要改窗口创建、端口解析、桥接逻辑;不要改生成产物。
>
> 验收:`.venv\Scripts\python.exe -m pytest tests/test_internal_desktop_server.py tests/test_smoke.py -q` 全绿;`desktop.py` 里 `_ignore_connection_reset` 只剩一份定义。
>
> 提交信息:`refactor(desktop): dedupe connection-reset handler and harden asyncio patch`

---

## Prompt 3 — 让"意外错误"返回 500 并记录堆栈,而不是一律压成 400

**解决:** `backend_service.py` 里大量 `except Exception` 把所有异常(包括程序 bug、磁盘满、权限错误)都返回成 HTTP 400 + 原始报错字符串(`errors.py` 的 `app_error` 默认 `status=400`)。结果:真正的服务器故障被伪装成"客户端输入错误",且自用时你分不清是输入问题还是程序坏了,真堆栈只在日志里。

复制以下整段给 Claude Code:

> 任务:在 FastAPI 后端区分"预期错误"和"意外错误"。预期错误(输入/找不到文件)继续返回 4xx;意外错误返回 500 并把完整 traceback 记入日志。保持现有的结构化错误码与前端 `payload.detail` 兼容。
>
> 步骤:
> 1. 在 `storyboard_tool/api.py` 的 `create_app` 里新增一个全局异常处理器:捕获未被处理的 `Exception`(非 `HTTPException`),用 `logger.exception(...)` 记录完整堆栈,返回 `JSONResponse(status_code=500, content={"detail": "Internal error. See logs/desktop.log.", "code": "INTERNAL_ERROR"})`。保留现有的 `HTTPException` 处理器不变。
> 2. 在 `storyboard_tool/errors.py` 的 `AppErrorCode` 里增加 `INTERNAL_ERROR = "INTERNAL_ERROR"`。
> 3. 审查 `storyboard_tool/backend_service.py` 中所有 `except Exception as exc:` 后直接 `raise HTTPException(400, ...)` 或 `raise app_error(..., REF_APPLY_FAILED/INVALID_REQUEST, ...)` 的地方:把它们改成**只捕获预期类型**(`ValueError`、`FileNotFoundError`,必要时 `KeyError`)→ 返回 400;其余异常**不再捕获**,让它们冒泡到第 1 步的全局 500 处理器。已经写明 `# noqa: BLE001` 且有意保留宽捕获的(如 `method_recover_shot_source` 的 PSD 重建)保持原样,但确保它们 `logger.exception` 了。
> 4. 不改变正常成功路径的返回结构。
>
> 禁止:不要改生成产物;不要动桥接字段名;不要改前端读取 `payload.detail` 的契约。
>
> 验收:`.venv\Scripts\python.exe -m pytest tests/test_api_errors.py tests/test_error_handling.py tests/test_regression.py -q` 全绿。如果有测试断言"某个意外错误返回 400",评估它是否本来就该是 500,并在提交说明里注明改动原因。
>
> 提交信息:`fix(errors): return 500 with logged traceback for unexpected failures`

---

## Prompt 4 — 修正 `method_update_settings` 会"静默丢设置"的分支

**解决:** `backend_service.py` 的 `method_update_settings` 结尾是 `if canvas_background_color … elif scene3d … else: save_settings`。同一次请求里**同时**带画布颜色和 `scene3d` 时,`scene3d` 的保存会被 `elif` 吃掉、悄悄不生效。

复制以下整段给 Claude Code:

> 任务:修正 `storyboard_tool/backend_service.py` 里 `method_update_settings` 末尾的 `if/elif/else` 分支,使每个被传入的设置项都独立持久化,不会因为另一个设置项的存在而被跳过。
>
> 步骤:
> 1. 定位 `method_update_settings` 结尾处对 `canvas_background_color`、`scene3d` 以及默认 `save_settings()/write_bridge_file()` 的互斥 `if/elif/else`。
> 2. 改成:`canvas_background_color`、`scene3d` 各自用独立的 `if`(而非 `elif`)处理;最后**无条件**做一次统一的持久化(确保 `save_settings` 与 `write_bridge_file` 该调用的都调用,且不重复多余写盘)。验证同时传 `canvas_background_color` + `scene3d` 时两者都被保存。
> 3. 保持其它设置项(photoshop_path、reference_* 等)分支逻辑不变。
>
> 禁止:不要改 Pydantic 请求模型 `SettingsUpdateRequest` 的字段;不要改生成产物。
>
> 验收:`.venv\Scripts\python.exe -m pytest tests/ -q` 全绿。并新增/补充一个测试:一次 PATCH 同时带 `canvas_background_color` 和 `scene3d`,断言两者都被写入 settings。
>
> 提交信息:`fix(settings): persist canvas color and scene3d together instead of dropping one`

---

## Prompt 5(可选,以后要扩展参考功能时再做)— 合并四个重复的 apply 函数

**解决:** `reference_segments.py` 里 `apply_ref_segment_to_boards / _3d_to_boards / apply_model_captures_to_boards / apply_ref_segment_image_to_boards` 四个函数(约 879–1313 行)复制了同一套"快照 → 遍历板块 → 合成背景 → 盖 provenance → 持久化 → 返回 undo token"骨架,改一处要四处同步改。

复制以下整段给 Claude Code:

> 任务:在 `storyboard_tool/reference_segments.py` 中,把四个 `apply_ref_segment_*` / `apply_model_captures_to_boards` 共有的流程抽成**一个**模板函数,差异部分(如何为单个板块生成背景图)用一个回调/策略参数注入。这是纯行为保持的重构,**输出与副作用必须逐字节等价**。
>
> 步骤:
> 1. 先读懂四个函数,列出它们的公共骨架(板块范围解析、`snapshot_boards_for_undo`、循环、`_stamp_ref_segment_provenance`、`_persist_ref_segment_apply`、返回结构)与各自的差异(视频抽帧 / 3D 合成 / 已渲染 PNG / 图片平铺)。
> 2. 抽出一个内部模板函数承载公共骨架,把"为某板块产出背景源"的部分作为参数传入。四个公开函数改为薄包装,保持各自的函数签名和返回字段**完全不变**(对应的 `backend_service.method_apply_*` 和路由不需要改)。
> 3. 不改返回 dict 的键、不改 undo token 行为、不改 provenance 字段。
>
> 禁止:不要改公开函数签名;不要改 `project_manager` 的 re-export 列表;不要动桥接;不要改生成产物。
>
> 验收:`.venv\Scripts\python.exe -m pytest tests/test_reference_segments.py tests/test_asset_lifecycle.py tests/test_regression.py -q` 全绿。手动确认四种 apply(视频/3D/模型截图/图片)各自仍返回原有字段。
>
> 提交信息:`refactor(reference_segments): unify four apply flows behind one template`

---

## 全部做完后的总验证

1. 跑全量测试:`.venv\Scripts\python.exe -m pytest tests/ -q`
2. 双击 `Storyboarder.vbs`,确认桌面窗口正常打开(不是浏览器),能新建/打开项目、选板块、在 Photoshop 里存盘后预览能同步。
3. 看一眼 `logs\desktop.log` 末尾,确认启动期间没有新的异常堆栈。
4. 故意制造一次后端意外错误(可选),确认现在返回的是 500 且日志里有完整 traceback(验证 Prompt 3 生效)。
