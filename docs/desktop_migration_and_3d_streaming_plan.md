# 桌面化 & 三维流式渲染 规划文档

> 状态:探索 / 已有可运行 spike。
> 关联分支:`spike/bpy-solid-viewport`。
> 最后更新:2026-06-24。

本文档汇总两件相关的事:
1. **前端桌面化** —— 是否、以及如何把当前 pywebview + React 的壳换成更"原生"的桌面 UI(Qt / WPF / WinUI 3 / Flutter / Tauri)。
2. **三维层去 Three.js 化** —— 把三维渲染从前端 Three.js 搬到后端 Blender(`bpy`),让前端退化成"收帧 + 发指令"的薄客户端,从而让前端框架**可随意替换**。

这两件事在结论上是耦合的:**前端桌面化的主要成本不在 UI,而在三维层。** 谁先解决三维层,谁就解锁了前端的自由替换。

---

## 1. 现状架构

```
pywebview (原生窗口壳)
  └── 加载 http://127.0.0.1:XXXX
       ├── FastAPI (Python) — /api/* 路由、全部业务逻辑
       └── React 19 + Vite — UI,编译产物由 FastAPI 托管
           └── 三维视口:原生 Three.js(从 /static/vendor/three/ 动态加载)
```

- 不是 Electron:没有内置 Chromium、没有 Node IPC,只是系统 WebView 套壳。
- **前后端早已是 HTTP 边界**(FastAPI ↔ React 用本地 HTTP 通信)。这是后续一切的关键前提。

### 三维层规模(实测)

| 维度 | 数值 |
|------|------|
| 三维 TS 代码总量 | **~4790 行**,核心 `workspaceEditor.ts` 1440 行 |
| 渲染栈 | 纯原生 Three.js(非 React-Three-Fiber) |
| 用到的能力 | GLB 加载、`OrbitControls`、`TransformControls`(三轴 gizmo)、`AnimationMixer`、`Raycaster` 拾取、基本体、`RoomEnvironment`/PMREM、tone mapping、截图捕获 |
| 实时交互 | OrbitControls(带阻尼惯性)、TransformControls 拖拽(`objectChange` 高频)、G/R/S 快捷键 —— **本质是在用 Three.js 复刻 Blender** |

### Blender 现有集成(`external_tools.py`)

- 每个项目有 `scene3d/scene.blend`(从 `assets/scene_template.blend` 拷贝)。
- "Open Blender" = `subprocess.Popen([blender.exe, scene.blend])`,**弹出独立桌面 Blender 窗口**。
- 工具本体**从不读 `.blend`**;Three.js 视口读的是 `scene3d/scene.glb`。
- 数据流是**手动断开**的:在 Blender 改 → **手动导出 GLB** → 导回工具 → Three.js 显示。

---

## 2. 前端桌面化选型

### 2.1 候选对比

| 框架 | 语言 | 与现有 Python 后端 | 三维 | 适用判断 |
|------|------|------------------|------|---------|
| **Tauri**(已有 `src-tauri/` 脚手架) | Rust 壳 + 保留 Web 前端 | 零改动(仍是 HTTP) | 保留 Three.js | **最轻**。只想换个现代壳、不碰三维,首选 |
| **Qt / PySide6** | Python | 不换语言,直接绑定 | 可嵌 OpenGL widget 替代 Three.js | 后端已是 Python,最自然;UI 写起来比 React 笨,样式靠 QSS |
| **WPF / WinUI 3** | C# / XAML | **后端需 IPC 桥接**(见 2.2) | 需 C# 原生重建(OpenTK/DirectX) | 只做 Windows、要微软现代原生 UI 时 |
| **Flutter Desktop** | Dart | FFI / 子进程桥接 | UI 全自绘,三维需另接 | 重视像素级 UI 定制;桌面生态较小 |

### 2.2 WPF / WinUI 3 桌面化:不需要"重写后端"

一个常见误解是"换 C# 前端 = Python 后端要全部重写"。**对本项目不成立**,因为 FastAPI 这个 HTTP 边界已经是现成的桥:

```
┌─────────────────┐         ┌──────────────────┐
│  WinUI 3 / WPF  │ ◄─HTTP─► │  FastAPI (不动)   │
│   (C# 前端)      │  本地    │  业务逻辑 (不动)   │
└─────────────────┘         └──────────────────┘
```

C# 侧用 `HttpClient` 调 `http://127.0.0.1:XXXX/api/*`,和现在 React 用 `fetch` **完全一样**。后端一行不用动。

桥接方式(从推荐到不推荐):
1. **本地 HTTP / WebSocket** —— 你已经在用,换前端几乎无痛。**首选**。
2. **子进程 + stdin/stdout (JSON-RPC)** —— 想打包成单一应用、不占端口时更干净。
3. **COM / pythonnet 进程内** —— 仅当需要零序列化高频调用 / 共享大块内存时;复杂度爆炸,绝大多数情况是过度工程。**不推荐**。

### 2.3 桌面化的真实成本表

| 层 | 现在 | 换 WinUI 后 | 改动量 |
|----|------|------------|--------|
| 业务逻辑 | FastAPI | FastAPI(不动) | ≈ 0 |
| 通信 | 本地 HTTP | 本地 HTTP(不动) | ≈ 0 |
| UI | React 19 | WinUI 3 (XAML/C#) | 全部重写(中等) |
| 窗口壳 | pywebview | WinUI 自带 | 替换 |
| **三维渲染** | **Three.js** | **C# 原生 (OpenTK/DX)** | **全部重写(主战场,~70% 精力)** |

**结论:桌面化的瓶颈是三维层。** Three.js 替你包好的 `TransformControls`(三轴 gizmo)、`OrbitControls`、`GLTFLoader`、IBL 环境光,在原生 C# 里都没有现成对应物,要从零重建——这才是数周工作量的来源,而不是 UI。

> 这就引出核心策略:**先把三维层从前端剥离(搬到后端 Blender),桌面化才会变成纯粹的"换皮"。** 见第 3 节。

---

## 3. 三维层去 Three.js 化 —— "内嵌 Blender"

"内嵌 Blender"有四个层次,难度天差地别:

| 路线 | 做法 | 评价 |
|------|------|------|
| A | OS 层把 Blender GUI reparent 成子窗口 | ❌ Blender 非为嵌入设计,极脆弱,别走 |
| B | `blender --background --python` 当无头渲染/计算后端 | ✅ 契合现有架构 |
| **C** | **`pip install bpy`,进程内读 `.blend` 直接渲染** | ⭐ 删掉手动 GLB 搬运,见下 |
| — | 真·视口视频流(`draw_view3d` 流) | ⚠️ headless 受限,见第 4 节 |

### 3.1 路线 C:让工具第一次"读懂 .blend"

`bpy` 现在可 `pip install` 为 Python 模块,后端进程内直接 `import bpy`、打开 `.blend`、渲染——**不需要桌面 Blender、不需要弹窗**。

| | 现在 | 路线 C |
|--|------|--------|
| 视口数据源 | GLB(从 Blender 手动导出的二手货) | **直接读 `.blend` 一手数据** |
| 改完场景 | 手动导出 GLB → 导入 😩 | 无,后端直接渲 `.blend` |
| 画质 | GLB 转换有损 | `.blend` 原貌 |
| 前端职责 | 渲染三维(4800 行 Three.js) | 收帧 + 发相机/变换指令(薄客户端) |

**一旦三维渲染搬到后端,前端用 React / WinUI / Tauri / 任何框架都无所谓**——前端不再渲染三维,只显示后端推来的帧、把鼠标操作发回去。第 2 节的"桌面化诅咒"由此解除。

---

## 4. 视频流 vs 渐进式帧流 —— 两个正交的轴

"把三维搬后端"之后,怎么把画面送到前端?这里有两个**互相独立**的轴,早期讨论容易混淆:

```
轴1:帧从哪来(渲染源)          轴2:帧怎么送(传输/编码)
─────────────────────         ─────────────────────────
render.render  (✅ headless)    离散帧 / MJPEG·WebSocket  → 渐进式帧流
draw_view3d    (❌ headless)    编码视频流 / H.264·WebRTC → 视口视频流
```

| 方案 | 渲染源 | 传输 | 类型 | 复杂度 |
|------|--------|------|------|--------|
| **方案1(起步选定)** | `render.render`(Workbench/solid) | 离散帧 + 交互降分辨率 | **渐进式帧流** | 低,纯 bpy 模块即可 |
| 方案2(重新可行) | `draw_view3d` | H.264 / WebRTC 连续编码 | **视口视频流** | 中–高,主要是编码/传输管线 |

> **重要更正(2026-06-24,经 review 修复 spike bug 后):** 两个渲染源在 pip bpy 模块下**都可用**。
> 早先"`draw_view3d` headless 不可用"的结论是 spike 的 free-before-read bug 造成的假象,**已作废**。
> 实测 `draw_view3d` 在 pip bpy(background=True 但 windows=1)下真渲出 solid 视口,p50 **0.6ms**
> (比 `render.render` 的 ~25ms 快约 40 倍),有存证 PNG(网格+坐标轴+实心方块)。

### 延迟预算(本地回环,非云游戏)

本项目全程在同一台机器(pywebview/Tauri),两段网络 ≈ 0ms。motion-to-photon 各环节(需分开记账,勿混为一谈):

| 环节 | 估时 | 备注 |
|------|------|------|
| 输入转发 | ~1ms | localhost |
| 渲染源 | `render.render` ~25ms / `draw_view3d` ~0.6ms | GPU 渲染时间,**不含**下面几项 |
| GPU 读回 + JPEG 编码 | 待测 | 现 worker 走临时文件,生产应走内存 |
| HTTP / 解码 / present | ~5–10ms | 浏览器侧 |
| **motion-to-photon 合计** | **待端到端实测** | worker `/frame`(render.render)实测 ~20ms@640×360 / ~53ms@1280×720,已含编码+写盘+HTTP |

**渲染源不再是选型瓶颈。** 方案1 vs 方案2 的真正区别在**传输轴**(离散帧 vs 视频编码),不在渲染源可行性:
- **方案1(起步):** `render.render` + 离散帧/WebSocket,简单,够"摆位/构图";骨架已实现。
- **更快的中间档:** 把渲染源换成 `draw_view3d`(0.6ms),传输仍走离散帧——近实时且无需视频 codec。**推荐作为方案1 的下一步优化**。
- **方案2(若需极致丝滑):** `draw_view3d` + H.264/WebRTC 连续编码;现在渲染源已证实可行,门槛降到编码/传输管线本身。

---

## 5. Spike 验证结论

脚本:`spikes/bpy_solid_viewport_spike.py`(隔离 venv 运行,见第 6 节)。
环境:**pip bpy 5.0.1 / Python 3.11 / Windows + GPU / 1280×720**。结果是**单环境**的,见下方"待验证"。

| 测试 | 渲染源 | 结果 | 数字 |
|------|--------|------|------|
| **A** | `bpy.ops.render.render`(Workbench=solid) | ✅ 可用 | p50 **22~32ms**(~30–45fps),真出 PNG。**仅渲染时间,不含编码/写盘/HTTP** |
| **B** | `gpu.GPUOffScreen` + `draw_view3d`(真视口) | ✅ 可用(更正后) | p50 **~0.6ms**(~1500fps),存证 PNG 为真几何(网格+轴+方块) |

**结论(更正):**
- 两个渲染源在 pip bpy 下**都可行**;`draw_view3d` 远快于 `render.render`。
- 方案1 立即可走;方案2 不再被渲染源卡住,门槛降到编码/传输。

**⚠️ 待验证(本结果仅覆盖"pip bpy + 本机 GPU"一档):**
spike 的 Test B 现在跨环境探测,但只在以下其一跑过。`draw_view3d` 依赖 GL 上下文,
不同环境可能不同,部署前应分别验证:

| 环境 | 是否已验 | 备注 |
|------|---------|------|
| 1. pip bpy 完全 headless | ✅ 本机通过 | background=True 但 windows=1,意外地有 GL 上下文 |
| 2. `blender --background <file>` | ⬜ 未验 | 传统无头,可能无 window |
| 3. 正常 Blender 可见窗口 | ⬜ 未验 | 预期可用 |
| 4. 隐藏窗口 / EGL | ⬜ 未验 | 服务器部署形态 |

> **教训:** 早先"Test B headless 失败"是 spike 自身 bug(先 `offscreen.free()` 再 `texture_color.read()`,
> 读已释放 buffer 的报错被误当成 GL 无效证据)。修复读取顺序 + 存证 PNG 肉眼核验后结论反转。
> 任何"不可用"的负面结论,都应先排除测试代码自身错误,并跨多环境复现。

---

## 6. 硬约束:bpy 必须隔离

`bpy` 钉死 `numpy<2`;本项目的 `opencv-python` 要 `numpy>=2`。**两者永不能共存。**

- ❌ 绝不可 `pip install bpy` 进全局 / 项目环境(会静默降级 numpy、搞坏 opencv)。
- ✅ bpy 永远待在独立 venv:`spikes/.venv-bpy`,由 `spikes/run.ps1` / `run.sh` 自动provision。
- ✅ 渲染服务因此**必须是独立进程**,不能 import 进主 FastAPI app。

> 历史事故:首次验证时误装 bpy 进全局,把 numpy 降到 1.26.4,已修复(恢复 numpy 2.2.6 + 隔离 venv)。

---

## 7. 方案1 最小骨架(已落地、已验证)

目录:`spikes/render_server/`(分支 `spike/bpy-solid-viewport`,commit `114d81c`)。

```
spikes/render_server/
├── worker.py     # 独立 bpy 进程:启动时加载 .blend 常驻 → 按相机参数渲 solid JPEG
├── index.html    # 拖拽 orbit demo:拖动低分辨率、松手出全质量(渐进式)
└── run.ps1/.sh   # 在隔离 venv 里启动
```

**设计要点**(都被 numpy 约束逼出来):
- **独立进程**,HTTP 通信,不碰主环境。
- **单线程 HTTP**(`BaseHTTPServer`):bpy 非线程安全,渲染必须串行。
- **常驻 + 预热**:启动开一次 `.blend`、暖一帧,把 ~500ms 冷启动一次性消化。

**接口:**
- `GET /` — 拖拽 orbit demo 页
- `GET /frame?w=&h=&yaw=&pitch=&dist=` — 一张 solid JPEG;`X-Render-ms` 头带渲染耗时
- `GET /healthz` — 就绪探针

**实测(本地回环,`/frame` 端到端含编码+写盘+HTTP):** 交互帧 ~20ms @640×360 · 全质量帧 ~53ms @1280×720,返回真 solid 图。
(注:此处渲染源是 `render.render`;换成 `draw_view3d` 渲染部分可降到 ~0.6ms,瓶颈转为读回+编码。)

**运行:**
```powershell
./spikes/render_server/run.ps1            # → http://127.0.0.1:8765
./spikes/render_server/run.ps1 你的.blend  # 换真实场景
```

---

## 8. 路线图

### 阶段 0 — 验证(✅ 已完成)
- [x] spike 确认 `render.render` solid headless 可行 + 测速
- [x] 修复 numpy 污染 + 隔离 venv
- [x] 方案1 最小骨架(worker + 拖拽 demo),端到端验证

### 阶段 1 — 把骨架做实
- [ ] **渲染源升级:worker 从 `render.render` 换成 `draw_view3d`**(~25ms → ~0.6ms,需在 worker 进程内拿到 VIEW_3D region;pip bpy 已证实有窗口)
- [ ] 渲染源去磁盘往返:GPU 读回内存 buffer,不写临时 JPEG
- [ ] WebSocket 推帧替代每帧一个 HTTP 请求(拖拽更顺)
- [ ] 主 FastAPI app 负责拉起 / 管理 / 代理这个 worker 子进程
- [ ] 拿**真实角色 `.blend`** 压测(`--inject-demo` 仅用于空场景):确认重场景下渲染源仍快
- [ ] **跨 4 环境复验 `draw_view3d`**(见第 5 节表):确认部署形态下 GL 上下文可用

### 阶段 2 — 把主编辑器搬过来(真正工作量)
- [ ] 后端重建 gizmo / 拾取语义:translate / rotate / scale + Raycaster 拾取
- [ ] 相机 orbit 已通;补齐 focus、frame-selected、键位
- [ ] reference 3D 截图改走后端渲染(天然契合,见下)
- [ ] 前端三维层从 4800 行 Three.js 退化为帧视口 + 指令发送

### 阶段 3 — 前端桌面化(此时才低成本)
- [ ] 三维层已剥离,前端可自由选型:Tauri(最轻)/ PySide6 / WinUI 3
- [ ] 若选 WinUI 3:C# 前端 `HttpClient` 接 FastAPI,UI 用 XAML 重写

### 可选 / 暂缓
- [ ] 方案2 视口视频流(`draw_view3d` + H.264/WebRTC 连续编码)——渲染源已证实可行,仅当离散帧的拖拽手感确实不够时再上编码管线

---

## 9. 各功能受方案1 影响评估

| 功能 | 用三维的方式 | 受方案1 影响 |
|------|------------|-------------|
| **reference 3D 截图** | 摆角度→截静态图(`data_url` POST 后端落盘) | ✅ **受益**:本就是"摆好再截",天然适合服务端渲染;白赚画质,前端瘦身。后端 `applyRefSegment3d` 已有 `camera_name`/`captures` 字段,接口几乎不用改 |
| **scene3D 主编辑器** | 实时拖 gizmo / orbit | ⚠️ **最受考验**:实时拖拽吃延迟,是方案1 的难点(靠交互降分辨率缓解) |
| **GLB 预览缩略图** | 渲一张小图 | ✅ 受益,同 reference |

---

## 10. 决策记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-06-24 | 三维层走**路线 C**(后端 bpy 读 `.blend` 渲染) | 删掉手动 GLB 搬运,解锁前端自由替换 |
| 2026-06-24 | 传输**起步走方案1 渐进式帧流** | solid + render.render 够快够简单,骨架已落地 |
| 2026-06-24 | bpy 永久隔离在独立 venv | 与 opencv 的 numpy 需求硬冲突 |
| 2026-06-24 | 桌面化(WinUI 等)**排在三维剥离之后** | 桌面化瓶颈是三维层,先剥离才低成本 |
| 2026-06-24 | ~~方案2 暂缓因 `draw_view3d` headless 不可用~~ **作废** | 经 review 发现是 spike bug;`draw_view3d` 在 pip bpy 下可用且快 40×,方案2 重新可行,渲染源升级提上日程 |

---

## 附:关键文件索引

- 现有 Blender 集成:`storyboard_tool/external_tools.py`
- 现有三维前端:`frontend/src/scene3d/`(核心 `workspace/workspaceEditor.ts`)
- reference 后端:`storyboard_tool/reference_segments.py` · 前端 `frontend/src/components/Reference*.tsx`
- spike 渲染验证:`spikes/bpy_solid_viewport_spike.py`
- 方案1 骨架:`spikes/render_server/`
- Tauri 脚手架:`frontend/src-tauri/`
