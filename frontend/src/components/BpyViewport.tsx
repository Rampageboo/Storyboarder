import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { createBpyCameraPath, getBpyViewportStatus, saveBpyScene, startBpyViewport } from '../api'
import './BpyViewport.css'

type Mode = 'orbit' | 'draw'
type CameraMode = 'orbit' | 'scene'

type ViewState = {
  yaw: number
  pitch: number
  distance: number
  target: [number, number, number]
}

const DEFAULT_VIEW: ViewState = {
  yaw: 0.6,
  pitch: 0.55,
  distance: 9,
  target: [0, 0, 0],
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function BpyViewport({
  active,
  disabled,
  canCapture,
  onCapture,
  onMessage,
  onError,
  onExternalOwnershipChange,
}: {
  active: boolean
  disabled: boolean
  canCapture: boolean
  onCapture: (image: Blob) => Promise<void>
  onMessage: (message: string) => void
  onError: (error: unknown) => void
  onExternalOwnershipChange?: (owned: boolean, connected: boolean) => void
}) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const viewRef = useRef<ViewState>({ ...DEFAULT_VIEW })
  const cameraModeRef = useRef<CameraMode>('orbit')
  const dragRef = useRef<{ pointerId: number; x: number; y: number } | null>(null)
  const drawRef = useRef<Array<{ x: number; y: number }>>([])
  const frameRequestRef = useRef(0)
  const externalOwnerRef = useRef(false)
  const [running, setRunning] = useState(false)
  const [starting, setStarting] = useState(false)
  const [externalOwned, setExternalOwned] = useState(false)
  const [externalConnected, setExternalConnected] = useState(false)
  const [externalCamera, setExternalCamera] = useState('')
  const [mode, setMode] = useState<Mode>('orbit')
  const [cameraMode, setCameraMode] = useState<CameraMode>('orbit')
  const [frameUrl, setFrameUrl] = useState('')
  const [duration, setDuration] = useState(120)
  const [target, setTarget] = useState<[number, number, number]>([0, 0, 0])

  const dimensions = useCallback((preview = false) => {
    const bounds = rootRef.current?.getBoundingClientRect()
    const width = Math.max(320, Math.round(bounds?.width || 960))
    const height = Math.max(180, Math.round(bounds?.height || 540))
    if (preview) return { width: Math.min(640, width), height: Math.min(360, height) }
    return { width: Math.min(1280, width), height: Math.min(720, height) }
  }, [])

  const buildFrameUrl = useCallback(
    (preview = false) => {
      const view = viewRef.current
      const size = dimensions(preview)
      const params = new URLSearchParams({
        width: String(size.width),
        height: String(size.height),
        yaw: String(view.yaw),
        pitch: String(view.pitch),
        distance: String(view.distance),
        target_x: String(view.target[0]),
        target_y: String(view.target[1]),
        target_z: String(view.target[2]),
        camera: cameraModeRef.current,
        t: String(Date.now()),
      })
      return `/api/project/bpy-viewport/frame?${params.toString()}`
    },
    [dimensions],
  )

  const requestFrame = useCallback(
    (preview = false) => {
      window.cancelAnimationFrame(frameRequestRef.current)
      frameRequestRef.current = window.requestAnimationFrame(() => {
        setFrameUrl(buildFrameUrl(preview))
      })
    },
    [buildFrameUrl],
  )

  const start = useCallback(async () => {
    if (starting || running || externalOwnerRef.current) return
    setStarting(true)
    try {
      await startBpyViewport()
      setRunning(true)
      onMessage('Built-in Blender is ready.')
      requestFrame()
    } catch (error) {
      onError(error)
    } finally {
      setStarting(false)
    }
  }, [onError, onMessage, requestFrame, running, starting])

  useEffect(() => {
    if (!active) return
    let cancelled = false
    let timer = 0

    const poll = async () => {
      try {
        const status = await getBpyViewportStatus()
        if (cancelled) return
        const owned = status.owner === 'external' || !!status.external_blender_owned
        const connected = !!status.external_blender_connected
        const wasOwned = externalOwnerRef.current
        externalOwnerRef.current = owned
        setExternalOwned(owned)
        setExternalConnected(connected)
        setExternalCamera(status.external_blender_camera || '')
        onExternalOwnershipChange?.(owned, connected)
        if (owned) {
          setRunning(false)
          setStarting(false)
        } else if (status.running) {
          setRunning(true)
        } else if (wasOwned) {
          onMessage('External Blender disconnected. Restarting the built-in viewport.')
        }
      } catch {
        // A transient status failure should not tear down the current viewport.
      } finally {
        if (!cancelled) timer = window.setTimeout(() => void poll(), 2000)
      }
    }

    void poll()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [active, onExternalOwnershipChange, onMessage])

  useEffect(() => {
    if (!active || running || starting || externalOwned) return
    const request = window.requestAnimationFrame(() => void start())
    return () => window.cancelAnimationFrame(request)
  }, [active, externalOwned, running, start, starting])

  useEffect(() => {
    cameraModeRef.current = cameraMode
    if (running) requestFrame()
  }, [cameraMode, requestFrame, running])

  useEffect(() => {
    viewRef.current.target = target
    if (running && cameraMode === 'orbit') requestFrame()
  }, [cameraMode, requestFrame, running, target])

  useEffect(() => {
    const canvas = canvasRef.current
    const root = rootRef.current
    if (!canvas || !root) return
    const resize = () => {
      const bounds = root.getBoundingClientRect()
      canvas.width = Math.max(1, Math.round(bounds.width))
      canvas.height = Math.max(1, Math.round(bounds.height))
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(root)
    return () => observer.disconnect()
  }, [])

  useEffect(
    () => () => {
      window.cancelAnimationFrame(frameRequestRef.current)
    },
    [],
  )

  const drawStroke = useCallback(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    context.clearRect(0, 0, canvas.width, canvas.height)
    const points = drawRef.current
    if (points.length < 2) return
    context.strokeStyle = '#36f269'
    context.lineWidth = 4
    context.lineJoin = 'round'
    context.lineCap = 'round'
    context.beginPath()
    context.moveTo(points[0].x, points[0].y)
    for (const point of points.slice(1)) context.lineTo(point.x, point.y)
    context.stroke()
  }, [])

  const localPoint = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return {
      x: clamp(event.clientX - bounds.left, 0, bounds.width),
      y: clamp(event.clientY - bounds.top, 0, bounds.height),
    }
  }

  const onPointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!running || disabled) return
    event.currentTarget.setPointerCapture(event.pointerId)
    const point = localPoint(event)
    if (mode === 'draw') {
      drawRef.current = [point]
      drawStroke()
      return
    }
    if (cameraModeRef.current !== 'orbit') {
      cameraModeRef.current = 'orbit'
      setCameraMode('orbit')
    }
    dragRef.current = { pointerId: event.pointerId, ...point }
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!running || disabled) return
    const point = localPoint(event)
    if (mode === 'draw' && event.currentTarget.hasPointerCapture(event.pointerId)) {
      const previous = drawRef.current.at(-1)
      if (!previous || Math.hypot(point.x - previous.x, point.y - previous.y) >= 5) {
        drawRef.current.push(point)
        drawStroke()
      }
      return
    }
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const view = viewRef.current
    view.yaw -= (point.x - drag.x) * 0.01
    view.pitch = clamp(view.pitch + (point.y - drag.y) * 0.01, -1.35, 1.35)
    drag.x = point.x
    drag.y = point.y
    requestFrame(true)
  }

  const finishDrawing = async (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    const points = drawRef.current
    drawRef.current = []
    canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height)
    if (points.length < 2 || !canvas) {
      onMessage('Draw a longer camera path.')
      return
    }
    const simplified = points.filter((_, index) => index === 0 || index === points.length - 1 || index % 2 === 0)
    try {
      const size = dimensions()
      const view = viewRef.current
      const result = await createBpyCameraPath({
        points: simplified.map((point) => [point.x / canvas.width, point.y / canvas.height]),
        width: size.width,
        height: size.height,
        yaw: view.yaw,
        pitch: view.pitch,
        distance: view.distance,
        target,
        duration_frames: duration,
      })
      setCameraMode('scene')
      cameraModeRef.current = 'scene'
      setMode('orbit')
      onMessage(`Created ${result.path} with ${result.camera} tracking ${result.target}.`)
      requestFrame()
    } catch (error) {
      onError(error)
    } finally {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId)
      }
    }
  }

  const onPointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (mode === 'draw') {
      void finishDrawing(event)
      return
    }
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    requestFrame()
  }

  const capture = async () => {
    if (!frameUrl) return
    try {
      const response = await fetch(buildFrameUrl())
      if (!response.ok) throw new Error(`Built-in Blender capture failed (${response.status}).`)
      await onCapture(await response.blob())
    } catch (error) {
      onError(error)
    }
  }

  const save = async () => {
    try {
      await saveBpyScene()
      onMessage('Saved the built-in Blender scene.')
    } catch (error) {
      onError(error)
    }
  }

  return (
    <div className="bpy-workspace">
      <div className="bpy-toolbar">
        {externalOwned ? (
          <span className={`bpy-external-status ${externalConnected ? 'is-connected' : ''}`}>
            {externalConnected ? 'External Blender connected' : 'Opening external Blender...'}
            {externalCamera ? ` - ${externalCamera}` : ''}
          </span>
        ) : null}
        <button type="button" className={mode === 'orbit' ? 'active' : ''} onClick={() => setMode('orbit')} disabled={!running || disabled}>
          Orbit
        </button>
        <button type="button" className={mode === 'draw' ? 'active' : ''} onClick={() => setMode('draw')} disabled={!running || disabled}>
          Draw camera path
        </button>
        <button type="button" className={cameraMode === 'scene' ? 'active' : ''} onClick={() => setCameraMode('scene')} disabled={!running || disabled}>
          Path camera
        </button>
        <label>
          Duration
          <input type="number" min={2} max={100000} value={duration} onChange={(event) => setDuration(clamp(Number(event.target.value) || 2, 2, 100000))} />
        </label>
        <span className="bpy-target-label">Target</span>
        {target.map((value, index) => (
          <input
            key={index}
            className="bpy-coordinate"
            type="number"
            step="0.1"
            aria-label={`Target ${'XYZ'[index]}`}
            value={value}
            onChange={(event) => {
              const next = [...target] as [number, number, number]
              next[index] = Number(event.target.value) || 0
              setTarget(next)
            }}
          />
        ))}
        <button type="button" onClick={() => void capture()} disabled={!running || !canCapture || disabled}>
          Capture to board
        </button>
        <button type="button" onClick={() => void save()} disabled={!running || disabled}>
          Save .blend
        </button>
        {!running && !externalOwned ? (
          <button type="button" onClick={() => void start()} disabled={starting || disabled}>
            {starting ? 'Starting Blender…' : 'Start built-in Blender'}
          </button>
        ) : null}
      </div>
      <div className={`bpy-viewport ${mode === 'draw' ? 'is-drawing' : ''}`} ref={rootRef}>
        {frameUrl && !externalOwned ? <img src={frameUrl} alt="Built-in Blender viewport" draggable={false} onError={() => setRunning(false)} /> : null}
        {!running ? (
          <div className="bpy-placeholder">
            {externalOwned
              ? externalConnected
                ? 'This scene is open in external Blender. Built-in editing is paused.'
                : 'Waiting for external Blender to connect...'
              : starting
                ? 'Starting built-in Blender…'
                : 'Built-in Blender is stopped.'}
          </div>
        ) : null}
        <canvas
          ref={canvasRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onWheel={(event) => {
            if (!running || disabled || mode !== 'orbit') return
            event.preventDefault()
            viewRef.current.distance = clamp(viewRef.current.distance * Math.exp(event.deltaY * 0.001), 0.25, 100000)
            requestFrame(true)
          }}
        />
      </div>
      <div className="bpy-help">
        Orbit by dragging and zoom with the wheel. Draw mode projects the green line onto the horizontal plane through the target.
      </div>
    </div>
  )
}
