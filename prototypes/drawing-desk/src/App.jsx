import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
} from "@xyflow/react";
import {
  FilmSlate,
  Graph,
  PencilSimple,
  Play,
  Pause,
  Cursor,
  Eraser,
  ArrowCounterClockwise,
  ArrowClockwise,
  Minus,
  Plus,
  DownloadSimple,
  Sparkle,
  UploadSimple,
  Eye,
  EyeSlash,
  Stack,
  X,
  ArrowRight,
  GitBranch,
  ImageSquare,
  Check,
  Info,
  SkipBack,
  SkipForward,
} from "@phosphor-icons/react";
import "@xyflow/react/dist/style.css";
import DrawingCanvas from "./DrawingCanvas.jsx";
import {
  INITIAL_SHOTS,
  INITIAL_EDGES,
  INITIAL_ROUTES,
  getRouteShots,
  addBranch,
} from "./story-model.js";

const emptyDrawing = { strokes: [], redo: [] };
function IconButton({ icon: Icon, label, active, ...props }) {
  return (
    <button
      type="button"
      className={"icon-button" + (active ? " active" : "")}
      aria-label={label}
      title={label}
      {...props}
    >
      <Icon size={20} />
    </button>
  );
}
function ShotNode({ data }) {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={"选择故事镜头 " + data.id + " " + data.title}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          data.onSelect(data.id);
        }
      }}
      className={
        "shot-node" +
        (data.active ? " selected" : "") +
        (data.onRoute ? " on-route" : "") +
        (["01", "02", "10"].includes(data.id) ? " shared" : "")
      }
    >
      <Handle type="target" position={Position.Top} />
      <img src={data.image} alt="" draggable="false" />
      <div>
        <span>{data.id}</span> {data.title}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
const nodeTypes = { shot: ShotNode };
const demoCandidates = [
  {
    id: "demo-dialogue",
    image: "/assets/dialogue.png",
    label: "站台对话 · 示例",
  },
  { id: "demo-train", image: "/assets/train.png", label: "车厢视角 · 示例" },
];
const initialPrompt =
  "两人在站台低声交谈，保持草图站位。黑白铅笔粗稿，突出人物的视线关系。";

export function App() {
  const [story, setStory] = useState({
    shots: INITIAL_SHOTS,
    edges: INITIAL_EDGES,
    routes: INITIAL_ROUTES,
  });
  const [routeId, setRouteId] = useState("main");
  const [selectedId, setSelectedId] = useState("06");
  const [mode, setMode] = useState("draw");
  const [tab, setTab] = useState("generate");
  const [tool, setTool] = useState("pen");
  const [brushSize, setBrushSize] = useState(12);
  const [color, setColor] = useState("#3b3936");
  const [zoom, setZoom] = useState(1);
  const [drawings, setDrawings] = useState({});
  const [settings, setSettings] = useState({});
  const [positions, setPositions] = useState({});
  const [playing, setPlaying] = useState(false);
  const [modal, setModal] = useState(null);
  const [branchTitle, setBranchTitle] = useState("");
  const [branchError, setBranchError] = useState("");
  const [notice, setNotice] = useState("");
  const canvasRef = useRef(null);
  const importRef = useRef(null);
  const importTargetRef = useRef(null);
  const modalRef = useRef(null);
  const modalTriggerRef = useRef(null);
  const flowRef = useRef(null);
  const graphContainerRef = useRef(null);
  const routeStripRef = useRef(null);
  const route =
    story.routes.find((item) => item.id === routeId) || story.routes[0];
  const routeShots = useMemo(
    () => getRouteShots(story.shots, route),
    [story.shots, route],
  );
  const shot =
    story.shots.find((item) => item.id === selectedId) || routeShots[0];
  const drawing = drawings[shot.id] || emptyDrawing;
  const config = settings[shot.id] || {};
  const prompt =
    config.prompt ??
    (shot.image === "/assets/dialogue.png"
      ? initialPrompt
      : shot.image === "/assets/train.png"
        ? "背包男子进入空旷的老式车厢，保留走廊透视和窗边光线。黑白铅笔分镜粗稿。"
        : "旧车站的大钟与末班站台，背包男子望向远方。黑白铅笔粗稿，建立场景空间。");
  const candidates = [...demoCandidates, ...(config.candidates || [])];
  const selectedIndex = routeShots.findIndex((item) => item.id === shot.id);
  const patchConfig = (update) =>
    setSettings((all) => ({
      ...all,
      [shot.id]: { ...all[shot.id], ...update },
    }));
  function openDialog(kind) {
    modalTriggerRef.current = document.activeElement;
    setPlaying(false);
    setModal(kind);
  }

  const chooseShot = useCallback(
    (id) => {
      setPlaying(false);
      setSelectedId(id);
      setZoom(1);
      setRouteId((current) => {
        const active = story.routes.find((item) => item.id === current);
        return active?.shotIds.includes(id)
          ? current
          : story.routes.find((item) => item.shotIds.includes(id))?.id ||
              current;
      });
    },
    [story.routes],
  );
  function chooseRoute(id) {
    setPlaying(false);
    setRouteId(id);
    const next = story.routes.find((item) => item.id === id);
    if (!next.shotIds.includes(selectedId)) setSelectedId(next.shotIds[0]);
  }
  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(() => {
      if (selectedIndex >= routeShots.length - 1) {
        setPlaying(false);
        return;
      }
      setSelectedId(routeShots[selectedIndex + 1].id);
    }, shot.duration * 1000);
    return () => window.clearTimeout(timer);
  }, [playing, selectedIndex, routeShots, shot.duration]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!modal) return;
    const previousFocus = modalTriggerRef.current;
    const focusables = () => [
      ...modalRef.current.querySelectorAll(
        'button:not(:disabled), input, select, textarea, [tabindex="0"]',
      ),
    ];
    if (!modalRef.current.contains(document.activeElement))
      focusables()[0]?.focus();
    const onKey = (event) => {
      if (event.key === "Escape") setModal(null);
      if (event.key !== "Tab") return;
      const elements = focusables();
      const first = elements[0],
        last = elements.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previousFocus?.focus();
    };
  }, [modal]);
  useEffect(() => {
    const strip = routeStripRef.current;
    const selected = strip?.querySelector('[aria-current="true"]');
    if (!selected) return;
    const bounds = selected.getBoundingClientRect(),
      parent = strip.getBoundingClientRect();
    if (bounds.left < parent.left)
      strip.scrollLeft += bounds.left - parent.left - 6;
    else if (bounds.right > parent.right)
      strip.scrollLeft += bounds.right - parent.right + 6;
  }, [selectedId, routeId]);
  useEffect(() => {
    const frame = requestAnimationFrame(() =>
      flowRef.current?.fitView({ padding: 0.04, duration: 200 }),
    );
    return () => cancelAnimationFrame(frame);
  }, [story.shots.length]);
  useEffect(() => {
    let frame;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() =>
        flowRef.current?.fitView({ padding: 0.04 }),
      );
    });
    observer.observe(graphContainerRef.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  const graphNodes = useMemo(
    () =>
      story.shots.map((item) => ({
        id: item.id,
        type: "shot",
        position: positions[item.id] || {
          x: item.x * 0.8 - (["01", "02", "10"].includes(item.id) ? 17.5 : 0),
          y: item.y,
        },
        data: {
          ...item,
          active: item.id === shot.id,
          onRoute: route.shotIds.includes(item.id),
          onSelect: chooseShot,
        },
      })),
    [story.shots, positions, shot.id, route.shotIds, chooseShot],
  );
  const graphEdges = useMemo(
    () =>
      story.edges.map((edge) => {
        const active = route.shotIds.some(
          (id, index) =>
            id === edge.source && route.shotIds[index + 1] === edge.target,
        );
        return {
          ...edge,
          type: "smoothstep",
          style: {
            stroke: active ? "#d6a84f" : "#626b76",
            strokeWidth: active ? 2.5 : 1.3,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: active ? "#d6a84f" : "#626b76",
          },
        };
      }),
    [story.edges, route.shotIds],
  );
  function commitStrokes(strokes) {
    setDrawings((all) => ({ ...all, [shot.id]: { strokes, redo: [] } }));
  }
  function undo() {
    setDrawings((all) => {
      const current = all[shot.id] || emptyDrawing;
      if (!current.strokes.length) return all;
      return {
        ...all,
        [shot.id]: {
          strokes: current.strokes.slice(0, -1),
          redo: [...current.redo, current.strokes.at(-1)],
        },
      };
    });
  }
  function redo() {
    setDrawings((all) => {
      const current = all[shot.id] || emptyDrawing;
      if (!current.redo.length) return all;
      return {
        ...all,
        [shot.id]: {
          strokes: [...current.strokes, current.redo.at(-1)],
          redo: current.redo.slice(0, -1),
        },
      };
    });
  }
  function startPlayback() {
    setZoom(1);
    setMode("play");
    if (!playing && selectedIndex === routeShots.length - 1)
      setSelectedId(routeShots[0].id);
    setPlaying((value) => !value);
  }
  function createBranch(event) {
    event.preventDefault();
    try {
      const next = addBranch(story, {
        fromId: shot.id,
        title: branchTitle,
        routeId,
      });
      setStory({ shots: next.shots, edges: next.edges, routes: next.routes });
      setSelectedId(next.shotId);
      setRouteId(next.routeId);
      setModal(null);
      setNotice("已从镜头 " + shot.id + " 创建独立分支；原路线保持不变。");
    } catch (error) {
      setBranchError(error.message);
    }
  }
  function beginImport() {
    importTargetRef.current = shot.id;
    setPlaying(false);
    importRef.current.click();
  }
  async function importCandidate(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (
      !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
      file.size > 15 * 1024 * 1024
    ) {
      setNotice("请选择 15 MB 以内的 PNG、JPEG 或 WebP 图片。");
      return;
    }
    const targetId = importTargetRef.current || shot.id;
    const reader = new FileReader();
    reader.onerror = () => setNotice("图片读取失败，请重新选择。");
    reader.onload = () => {
      const candidate = {
        id: crypto.randomUUID(),
        image: reader.result,
        label: file.name,
      };
      setSettings((all) => ({
        ...all,
        [targetId]: {
          ...all[targetId],
          candidates: [...(all[targetId]?.candidates || []), candidate],
        },
      }));
      setNotice("图片已加入镜头 " + targetId + " 的候选列表，尚未覆盖草图。");
    };
    reader.readAsDataURL(file);
  }
  async function exportFrame() {
    try {
      const url = await canvasRef.current.exportPng();
      const link = document.createElement("a");
      link.href = url;
      link.download = "storyboard-" + shot.id + ".png";
      link.click();
      setNotice("当前可见图层已导出为 PNG。");
    } catch {
      setNotice("画面尚未载入，暂时无法导出，请稍后重试。");
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <FilmSlate size={23} />
          <strong>Storyboarder</strong>
          <span className="project-name">· 末班列车</span>
        </div>
        <nav aria-label="工作区">
          {[
            ["map", Graph, "地图"],
            ["draw", PencilSimple, "绘画"],
            ["play", Play, "播放"],
          ].map(([id, Icon, label]) => (
            <button
              key={id}
              className={mode === id ? "selected" : ""}
              onClick={() => {
                setMode(id);
                if (id === "play") setZoom(1);
                setPlaying(false);
              }}
            >
              <Icon size={17} />
              {label}
            </button>
          ))}
        </nav>
        <span className="prototype-tag">
          <PencilSimple size={14} />
          交互原型 · 仅本次会话
        </span>
      </header>
      <main className={"workspace " + (mode === "map" ? "map-mode" : "")}>
        <aside className="graph-pane panel">
          <div className="panel-heading">
            <Graph size={19} />
            <h2>故事结构</h2>
            <span>{story.shots.length} 镜头</span>
          </div>
          <div className="graph-view" ref={graphContainerRef}>
            <ReactFlow
              key={mode === "map" ? "full" : "compact"}
              nodes={graphNodes}
              edges={graphEdges}
              nodeTypes={nodeTypes}
              onInit={(instance) => {
                flowRef.current = instance;
              }}
              onNodesChange={(changes) =>
                setPositions((all) => {
                  const moved = changes.filter(
                    (change) => change.type === "position" && change.position,
                  );
                  return moved.length
                    ? {
                        ...all,
                        ...Object.fromEntries(
                          moved.map((change) => [change.id, change.position]),
                        ),
                      }
                    : all;
                })
              }
              onNodeClick={(_, node) => chooseShot(node.id)}
              onNodeDragStop={(_, node) =>
                setPositions((all) => ({ ...all, [node.id]: node.position }))
              }
              nodesConnectable={false}
              nodesFocusable={false}
              deleteKeyCode={null}
              fitView
              fitViewOptions={{ padding: 0.04 }}
              minZoom={0.2}
              maxZoom={1.8}
              proOptions={{ hideAttribution: true }}
            >
              {mode === "map" && <Background color="#26303d" gap={24} />}
              {mode === "map" && <Controls showInteractive={false} />}
            </ReactFlow>
          </div>
          <div className="graph-footer">
            <span>分支独立 · 结尾汇合</span>
            <button
              onClick={() => {
                setBranchTitle("");
                setBranchError("");
                openDialog("branch");
              }}
            >
              <GitBranch size={16} />
              新建分支
            </button>
          </div>
        </aside>

        <section className="editor-pane panel" aria-label="分镜绘画工作区">
          <div className="editor-heading">
            <div>
              <span>{route.name}</span>
              <span className="slash">/</span>
              {shot.title}
              <span className="slash">/</span>
              <strong>镜头 {shot.id}</strong>
            </div>
            <div className="zoom-tools">
              <IconButton
                icon={Minus}
                label="缩小画布"
                disabled={zoom <= 0.5}
                onClick={() => setZoom((value) => Math.max(0.5, value - 0.25))}
              />
              <button
                className="zoom-value"
                onClick={() => setZoom(1)}
                title="重置缩放"
              >
                {Math.round(zoom * 100)}%
              </button>
              <IconButton
                icon={Plus}
                label="放大画布"
                disabled={zoom >= 2}
                onClick={() => setZoom((value) => Math.min(2, value + 0.25))}
              />
            </div>
          </div>
          {mode !== "play" ? (
            <div className="drawing-toolbar">
              <div className="tool-group">
                <IconButton
                  icon={Cursor}
                  label="选择工具"
                  active={tool === "select"}
                  onClick={() => setTool("select")}
                />
                <IconButton
                  icon={PencilSimple}
                  label="画笔"
                  active={tool === "pen"}
                  onClick={() => setTool("pen")}
                />
                <IconButton
                  icon={Eraser}
                  label="橡皮擦"
                  active={tool === "eraser"}
                  onClick={() => setTool("eraser")}
                />
              </div>
              <div className="tool-group brush-settings">
                <input
                  aria-label="画笔颜色"
                  type="color"
                  value={color}
                  onChange={(event) => setColor(event.target.value)}
                />
                <output>{brushSize} px</output>
                <input
                  aria-label="画笔大小"
                  type="range"
                  min="1"
                  max="40"
                  value={brushSize}
                  onChange={(event) => setBrushSize(Number(event.target.value))}
                />
              </div>
              <div className="tool-group">
                <IconButton
                  icon={ArrowCounterClockwise}
                  label="撤销笔迹"
                  disabled={!drawing.strokes.length}
                  onClick={undo}
                />
                <IconButton
                  icon={ArrowClockwise}
                  label="重做笔迹"
                  disabled={!drawing.redo.length}
                  onClick={redo}
                />
              </div>
              <IconButton
                icon={DownloadSimple}
                label="导出当前画面 PNG"
                onClick={exportFrame}
              />
            </div>
          ) : (
            <div className="playback-toolbar">
              <span>路线预览 / {route.name}</span>
              <span>
                {selectedIndex + 1} / {routeShots.length} 镜头 · 当前{" "}
                {shot.duration}s
              </span>
            </div>
          )}
          <div
            className={
              "canvas-stage " + (mode === "play" ? "playing-stage" : "")
            }
          >
            <DrawingCanvas
              shot={shot}
              strokes={drawing.strokes}
              onStrokesChange={commitStrokes}
              tool={mode === "play" ? "select" : tool}
              color={color}
              brushSize={brushSize}
              showSketch={config.showSketch !== false}
              generatedImage={config.generatedImage || null}
              showGenerated={config.showGenerated !== false}
              zoom={zoom}
              canvasRef={canvasRef}
              fit={mode === "play" ? "contain" : "cover"}
            />
          </div>
          <div className="canvas-status">
            <span>
              {mode === "play"
                ? "按当前路线播放，不按画布位置排序"
                : "草图与采纳图分层 · 切换镜头保留本次笔迹"}
            </span>
            <span>
              {drawing.strokes.length} 笔 · {shot.duration}s
            </span>
          </div>
        </section>

        <aside className="inspector-pane panel">
          <div className="inspector-tabs" role="tablist" aria-label="镜头属性">
            {[
              ["layers", "图层"],
              ["reference", "参考"],
              ["generate", "生成"],
            ].map(([id, label]) => (
              <button
                key={id}
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="inspector-content" role="tabpanel">
            {tab === "generate" && (
              <>
                <label className="field-label" htmlFor="prompt">
                  创意提示词
                </label>
                <textarea
                  id="prompt"
                  maxLength={600}
                  value={prompt}
                  onChange={(event) =>
                    patchConfig({ prompt: event.target.value })
                  }
                />
                <div className="char-count">{prompt.length} / 600</div>
                <h3>参考图</h3>
                <div className="reference-grid">
                  <figure>
                    <img src="/assets/dialogue.png" alt="人物站位参考" />
                    <figcaption>人物站位</figcaption>
                  </figure>
                  <figure>
                    <img src="/assets/station.png" alt="旧车站场景参考" />
                    <figcaption>站台</figcaption>
                  </figure>
                </div>
                <div className="slider-label">
                  <label htmlFor="adherence">草图遵循</label>
                  <Info size={14} />
                  <output>{(config.adherence ?? 0.8).toFixed(1)}</output>
                </div>
                <input
                  id="adherence"
                  className="adherence"
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={config.adherence ?? 0.8}
                  onChange={(event) =>
                    patchConfig({ adherence: Number(event.target.value) })
                  }
                />
                <button
                  className="primary generate-button"
                  onClick={() => openDialog("generate")}
                >
                  <Sparkle size={21} weight="fill" />
                  生成候选
                </button>
                <div className="connection-status">
                  <Info size={14} />
                  <span>ComfyUI · 未连接</span>
                  <button onClick={() => openDialog("generate")}>
                    接入说明
                  </button>
                </div>
                <div className="section-heading">
                  <h3>
                    候选图 <span>({candidates.length})</span>
                  </h3>
                  <button onClick={beginImport}>
                    <UploadSimple size={14} />
                    导入
                  </button>
                </div>
                <div className="candidate-list">
                  {candidates.map((candidate) => (
                    <article
                      className={
                        "candidate" +
                        (config.acceptedId === candidate.id ? " accepted" : "")
                      }
                      key={candidate.id}
                    >
                      <img src={candidate.image} alt={candidate.label} />
                      <div>
                        <span title={candidate.label}>{candidate.label}</span>
                        <button
                          onClick={() => {
                            patchConfig({
                              acceptedId: candidate.id,
                              generatedImage: candidate.image,
                              showGenerated: true,
                            });
                            setNotice("候选图已采纳到独立图层，原草图保留。");
                          }}
                        >
                          {config.acceptedId === candidate.id ? (
                            <>
                              <Check size={13} />
                              已采纳
                            </>
                          ) : (
                            "采纳到独立图层"
                          )}
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
                <p className="quiet-note">
                  示例图用于体验采纳流程，并非本次 AI 生成结果。
                </p>
              </>
            )}
            {tab === "layers" && (
              <>
                <div className="section-heading">
                  <h3>镜头 {shot.id} 的图层</h3>
                  <Stack size={19} />
                </div>
                <div className="layer-row">
                  <PencilSimple size={20} />
                  <div>
                    <strong>手绘笔迹</strong>
                    <span>{drawing.strokes.length} 笔 · 可单独撤销</span>
                  </div>
                  <Eye size={19} />
                </div>
                <div className="layer-row">
                  <ImageSquare size={20} />
                  <div>
                    <strong>采纳图层</strong>
                    <span>
                      {config.generatedImage
                        ? "候选图 · 不覆盖草图"
                        : "尚未采纳候选"}
                    </span>
                  </div>
                  <IconButton
                    icon={config.showGenerated === false ? EyeSlash : Eye}
                    label="切换采纳图层可见性"
                    disabled={!config.generatedImage}
                    onClick={() =>
                      patchConfig({
                        showGenerated: config.showGenerated === false,
                      })
                    }
                  />
                </div>
                <div className="layer-row">
                  <ImageSquare size={20} />
                  <div>
                    <strong>原始草图</strong>
                    <span>始终保留</span>
                  </div>
                  <IconButton
                    icon={config.showSketch === false ? EyeSlash : Eye}
                    label="切换草图可见性"
                    onClick={() =>
                      patchConfig({ showSketch: config.showSketch === false })
                    }
                  />
                </div>
                <p className="quiet-note">
                  图层设置、提示词和笔迹按镜头保存于本次会话。刷新页面会重置；需要保留的画面请先导出
                  PNG。
                </p>
              </>
            )}
            {tab === "reference" && (
              <>
                <h3>当前镜头参考</h3>
                <p className="quiet-note">
                  分支只表达故事走向，不自动建立生成依赖。
                </p>
                <figure className="large-reference">
                  <img
                    src="/assets/dialogue.png"
                    alt="主角与女子在站台对话的站位参考"
                  />
                  <figcaption>角色与站位 / 站台对话</figcaption>
                </figure>
                <figure className="large-reference">
                  <img
                    src="/assets/station.png"
                    alt="车站大钟与站台的空间参考"
                  />
                  <figcaption>场景 / 旧车站</figcaption>
                </figure>
                <p className="quiet-note">
                  正式接入时将明确选择跨镜头参考，避免汇合节点误用另一条分支的人物状态。
                </p>
              </>
            )}
          </div>
        </aside>
      </main>
      <footer className="route-panel panel">
        <div className="route-heading">
          <div>
            <span className="route-accent">当前路线</span>
            <select
              aria-label="当前路线"
              value={routeId}
              onChange={(event) => chooseRoute(event.target.value)}
            >
              {story.routes.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <span>
              {routeShots.length} 镜头 ·{" "}
              {routeShots.reduce((sum, item) => sum + item.duration, 0)}s
            </span>
          </div>
          <div className="route-controls">
            <IconButton
              icon={SkipBack}
              label="上一个镜头"
              disabled={selectedIndex <= 0}
              onClick={() => chooseShot(routeShots[selectedIndex - 1].id)}
            />
            <button className="play-route" onClick={startPlayback}>
              {playing ? (
                <Pause size={16} weight="fill" />
              ) : (
                <Play size={16} weight="fill" />
              )}
              {playing ? "暂停" : "播放路线"}
            </button>
            <IconButton
              icon={SkipForward}
              label="下一个镜头"
              disabled={selectedIndex >= routeShots.length - 1}
              onClick={() => chooseShot(routeShots[selectedIndex + 1].id)}
            />
          </div>
        </div>
        <div className="route-strip" ref={routeStripRef}>
          {routeShots.map((item, index) => (
            <div className="route-item-wrap" key={item.id}>
              <button
                className={
                  "route-card" + (item.id === shot.id ? " selected" : "")
                }
                aria-label={"选择镜头 " + item.id + " " + item.title}
                aria-current={item.id === shot.id ? "true" : undefined}
                onClick={() => chooseShot(item.id)}
              >
                <img
                  src={
                    settings[item.id]?.generatedImage &&
                    settings[item.id]?.showGenerated !== false
                      ? settings[item.id].generatedImage
                      : item.image
                  }
                  alt=""
                />
                <span>
                  <b>{item.id}</b> {item.title}
                </span>
              </button>
              {index < routeShots.length - 1 && (
                <ArrowRight className="route-arrow" size={24} />
              )}
            </div>
          ))}
        </div>
      </footer>
      <input
        hidden
        ref={importRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={importCandidate}
      />
      {notice && (
        <div className="toast" role="status">
          <Check size={18} />
          {notice}
          <button aria-label="关闭提示" onClick={() => setNotice("")}>
            <X size={14} />
          </button>
        </div>
      )}
      {modal && (
        <div
          className="modal-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget) setModal(null);
          }}
        >
          <section
            ref={modalRef}
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
          >
            <IconButton
              icon={X}
              label="关闭对话框"
              onClick={() => setModal(null)}
            />
            {modal === "branch" ? (
              <form onSubmit={createBranch}>
                <GitBranch size={28} className="gold" />
                <h2 id="dialog-title">从镜头 {shot.id} 新建分支</h2>
                <p>共享此前的镜头，从这里探索另一个走向。现有路线不受影响。</p>
                <label htmlFor="branch-title">新分支名称</label>
                <input
                  autoFocus
                  id="branch-title"
                  maxLength={40}
                  value={branchTitle}
                  onChange={(event) => setBranchTitle(event.target.value)}
                  placeholder="例如：错过末班车"
                  required
                />
                {branchError && <p role="alert">{branchError}</p>}
                <button type="submit" className="primary">
                  创建分支
                </button>
              </form>
            ) : (
              <>
                <Sparkle size={28} className="gold" />
                <h2 id="dialog-title">把草图交给 ComfyUI</h2>
                <p>这个原型尚未连接生成服务，不会发送图片或运行模型。</p>
                <div className="connection-steps">
                  <span>当前草图 + 明确选择的参考</span>
                  <ArrowRight size={18} />
                  <span>ComfyUI 工作流</span>
                  <ArrowRight size={18} />
                  <span>候选图 → 独立图层</span>
                </div>
                <p>
                  你可以先导入已有结果，体验候选比较与无损采纳。提示词和遵循度目前只保留在界面中。
                </p>
                <button
                  className="primary"
                  onClick={() => {
                    setModal(null);
                    beginImport();
                  }}
                >
                  <UploadSimple size={18} />
                  导入候选图
                </button>
                <button
                  className="secondary"
                  onClick={() => {
                    setModal(null);
                    setNotice("右侧已提供两张示例候选，可直接采纳体验图层。");
                  }}
                >
                  使用示例候选体验
                </button>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
