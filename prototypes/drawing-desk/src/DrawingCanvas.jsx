import {
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import "./DrawingCanvas.css";

const WIDTH = 1672;
const HEIGHT = 941;
const EMPTY_STROKES = [];

function paintStroke(context, stroke) {
  if (!stroke.points.length) return;
  context.save();
  context.globalCompositeOperation =
    stroke.tool === "eraser" ? "destination-out" : "source-over";
  context.strokeStyle = stroke.color;
  context.fillStyle = stroke.color;
  context.lineWidth = stroke.width;
  context.lineCap = "round";
  context.lineJoin = "round";
  if (stroke.points.length === 1) {
    context.beginPath();
    context.arc(
      stroke.points[0].x,
      stroke.points[0].y,
      stroke.width / 2,
      0,
      Math.PI * 2,
    );
    context.fill();
  } else {
    context.beginPath();
    context.moveTo(stroke.points[0].x, stroke.points[0].y);
    for (const point of stroke.points.slice(1))
      context.lineTo(point.x, point.y);
    context.stroke();
  }
  context.restore();
}

function loadImage(source) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("画面未能加载，请检查图片后重试。"));
    image.src = source;
  });
}

function paintContainedImage(context, image) {
  const scale = Math.min(
    WIDTH / image.naturalWidth,
    HEIGHT / image.naturalHeight,
  );
  const width = image.naturalWidth * scale;
  const height = image.naturalHeight * scale;
  context.fillStyle = "#f5f3ec";
  context.fillRect(0, 0, WIDTH, HEIGHT);
  context.drawImage(
    image,
    (WIDTH - width) / 2,
    (HEIGHT - height) / 2,
    width,
    height,
  );
}

export default function DrawingCanvas({
  shot,
  strokes = EMPTY_STROKES,
  onStrokesChange,
  tool = "pen",
  color = "#292724",
  brushSize = 12,
  showSketch = true,
  generatedImage = null,
  showGenerated = true,
  zoom = 1,
  fit = "cover",
  canvasRef,
}) {
  const viewportRef = useRef(null);
  const backgroundRef = useRef(null);
  const inkRef = useRef(null);
  const activeRef = useRef(null);
  const readyRef = useRef(Promise.resolve());
  const generationRef = useRef(0);
  const [size, setSize] = useState({ width: 900, height: 506.5 });
  const [imageState, setImageState] = useState({ loading: false, error: "" });
  const scale = Number.isFinite(zoom) ? Math.max(0.25, Math.min(4, zoom)) : 1;

  function repaintInk(active = activeRef.current) {
    const context = inkRef.current?.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, WIDTH, HEIGHT);
    strokes.forEach((stroke) => paintStroke(context, stroke));
    if (active && active.shotId === shot.id)
      paintStroke(context, active.stroke);
  }

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const measure = () => {
      const availableWidth = Math.max(1, viewport.clientWidth);
      const availableHeight = Math.max(1, viewport.clientHeight);
      const width =
        fit === "contain"
          ? Math.min(availableWidth, (availableHeight * WIDTH) / HEIGHT)
          : Math.max(availableWidth, (availableHeight * WIDTH) / HEIGHT);
      setSize({ width, height: (width * HEIGHT) / WIDTH });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [fit]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    viewport.scrollLeft = Math.max(
      0,
      (viewport.scrollWidth - viewport.clientWidth) / 2,
    );
    viewport.scrollTop = Math.max(
      0,
      (viewport.scrollHeight - viewport.clientHeight) / 2,
    );
  }, [size.width, size.height, scale, fit]);

  useLayoutEffect(() => {
    // An in-progress gesture belongs to exactly one shot and one drawing tool.
    activeRef.current = null;
    repaintInk(null);
  }, [shot.id, tool, strokes]);

  useEffect(() => {
    const generation = ++generationRef.current;
    const context = backgroundRef.current.getContext("2d");
    context.fillStyle = "#f5f3ec";
    context.fillRect(0, 0, WIDTH, HEIGHT);
    const sources = [
      showSketch ? shot.image : null,
      showGenerated ? generatedImage : null,
    ].filter(Boolean);
    setImageState({ loading: sources.length > 0, error: "" });
    const loading = Promise.all(sources.map(loadImage)).then((images) => {
      if (generation !== generationRef.current) return;
      context.fillStyle = "#f5f3ec";
      context.fillRect(0, 0, WIDTH, HEIGHT);
      images.forEach((image) => paintContainedImage(context, image));
      setImageState({ loading: false, error: "" });
    });
    readyRef.current = loading;
    loading.catch((error) => {
      if (generation === generationRef.current)
        setImageState({ loading: false, error: error.message });
    });
    return () => {
      generationRef.current += 1;
    };
  }, [shot.id, shot.image, showSketch, generatedImage, showGenerated]);

  useImperativeHandle(canvasRef, () => ({
    async exportPng() {
      const generation = generationRef.current;
      await readyRef.current;
      if (generation !== generationRef.current)
        throw new Error("镜头已切换，请重新导出当前镜头。");
      const output = document.createElement("canvas");
      output.width = WIDTH;
      output.height = HEIGHT;
      const context = output.getContext("2d");
      context.drawImage(backgroundRef.current, 0, 0);
      context.drawImage(inkRef.current, 0, 0);
      return output.toDataURL("image/png");
    },
  }));

  function pointFromEvent(event) {
    const bounds = inkRef.current.getBoundingClientRect();
    return {
      x: Math.max(
        0,
        Math.min(WIDTH, ((event.clientX - bounds.left) * WIDTH) / bounds.width),
      ),
      y: Math.max(
        0,
        Math.min(
          HEIGHT,
          ((event.clientY - bounds.top) * HEIGHT) / bounds.height,
        ),
      ),
    };
  }

  function startStroke(event) {
    if (
      tool === "select" ||
      event.button !== 0 ||
      !event.isPrimary ||
      activeRef.current
    )
      return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    activeRef.current = {
      pointerId: event.pointerId,
      shotId: shot.id,
      stroke: {
        points: [pointFromEvent(event)],
        color,
        width: Math.max(1, brushSize),
        tool,
      },
    };
    repaintInk();
  }

  function moveStroke(event) {
    const active = activeRef.current;
    if (
      !active ||
      active.pointerId !== event.pointerId ||
      active.shotId !== shot.id
    )
      return;
    const events = event.nativeEvent.getCoalescedEvents?.() || [];
    for (const sample of events.length ? events : [event])
      active.stroke.points.push(pointFromEvent(sample));
    repaintInk();
  }

  function finishStroke(event) {
    const active = activeRef.current;
    if (!active || active.pointerId !== event.pointerId) return;
    activeRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
    if (active.shotId !== shot.id) return;
    active.stroke.points.push(pointFromEvent(event));
    onStrokesChange?.([...strokes, active.stroke]);
  }

  function cancelStroke(event) {
    if (activeRef.current?.pointerId !== event.pointerId) return;
    activeRef.current = null;
    repaintInk(null);
  }

  return (
    <div
      ref={viewportRef}
      className="drawing-canvas-viewport"
      tabIndex={0}
      aria-label="分镜画布，可滚动查看放大的画面"
    >
      <div
        className="drawing-canvas-stage"
        style={{ width: size.width * scale, height: size.height * scale }}
      >
        <canvas
          ref={backgroundRef}
          width={WIDTH}
          height={HEIGHT}
          className="drawing-canvas-background"
          aria-hidden="true"
        />
        <canvas
          ref={inkRef}
          width={WIDTH}
          height={HEIGHT}
          className={`drawing-canvas-ink drawing-canvas-ink--${tool}`}
          aria-label={`${shot.title}，${tool === "pen" ? "画笔" : tool === "eraser" ? "橡皮擦" : "浏览"}模式`}
          onPointerDown={startStroke}
          onPointerMove={moveStroke}
          onPointerUp={finishStroke}
          onPointerCancel={cancelStroke}
          onLostPointerCapture={cancelStroke}
        >
          当前镜头：{shot.title}。此区域支持鼠标或触控笔绘画。
        </canvas>
        {imageState.loading ? (
          <div className="drawing-canvas-notice" role="status">
            载入画面…
          </div>
        ) : null}
        {imageState.error ? (
          <div
            className="drawing-canvas-notice drawing-canvas-notice--error"
            role="alert"
          >
            {imageState.error}
          </div>
        ) : null}
      </div>
    </div>
  );
}
