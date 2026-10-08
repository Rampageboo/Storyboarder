import { useCallback, useEffect, useRef, useState } from 'react'
import type { Canvas as FabricCanvas, FabricObject } from 'fabric'
import { loadShotDrawingProject } from '../api'

type DrawingTool = 'select' | 'pen' | 'eraser' | 'hand'
type FabricModule = typeof import('fabric')
type EditorObject = FabricObject & { storyboardId?: string; storyboardName?: string; storyboardLocked?: boolean }

interface FullDrawingEditorProps {
  shotId: string
  width: number
  height: number
  artworkImage: string
  boardBackgroundImage: string
  codexImage: string
  canvasColor: string
  disabled: boolean
  onCancel: () => void
  onError: (error: unknown) => void
  onSave: (imageData: string, editorData: string) => Promise<boolean>
}

interface DrawingLayer { id: string; name: string; visible: boolean; locked: boolean; kind: string }

interface NativeDrawingDocument {
  info: { format: 'storyboarder-fabric'; version: 1; width: number; height: number }
  layers: Array<{ id: string; name: string; visible: boolean }>
  canvas: Record<string, unknown>
}

const SERIALIZED_PROPERTIES = ['storyboardId', 'storyboardName', 'storyboardLocked']

function setObjectLocked(object: EditorObject, locked: boolean) {
  object.storyboardLocked = locked
  object.set({ selectable: !locked, evented: !locked })
}

function finishTextEditing(canvas: FabricCanvas) {
  const active = canvas.getActiveObject()
  if (active && 'exitEditing' in active && typeof active.exitEditing === 'function') active.exitEditing()
}

function isNativeDrawingDocument(value: unknown): value is NativeDrawingDocument {
  if (!value || typeof value !== 'object') return false
  const document = value as Partial<NativeDrawingDocument>
  return document.info?.format === 'storyboarder-fabric'
    && document.info.version === 1
    && Boolean(document.canvas && typeof document.canvas === 'object')
}

function makeObjectId(): string {
  return `drawing-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function layerName(object: EditorObject, fallbackIndex: number): string {
  if (object.storyboardName) return object.storyboardName
  if (object.type === 'image') return 'Artwork'
  if (object.type === 'rect') return 'Artwork base'
  return `Drawing ${fallbackIndex + 1}`
}

function imageBlobDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') resolve(reader.result)
      else reject(new Error('The artwork image could not be embedded in the drawing.'))
    }
    reader.onerror = () => reject(reader.error ?? new Error('The artwork image could not be read.'))
    reader.onabort = () => reject(new Error('Reading the artwork image was cancelled.'))
    reader.readAsDataURL(blob)
  })
}

export function FullDrawingEditor({
  shotId, width, height, artworkImage, boardBackgroundImage, codexImage, canvasColor,
  disabled, onCancel, onError, onSave,
}: FullDrawingEditorProps) {
  const canvasElementRef = useRef<HTMLCanvasElement | null>(null)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<FabricCanvas | null>(null)
  const fabricRef = useRef<FabricModule | null>(null)
  const brushFactoryRef = useRef<typeof import('./freehandBrush').createFreehandBrush | null>(null)
  const brushStyleRef = useRef({ marker: false, pressure: true, stabilize: 35 })
  const toolRef = useRef<DrawingTool>('pen')
  const colorRef = useRef('#292724')
  const brushSizeRef = useRef(8)
  const opacityRef = useRef(100)
  const operationBusyRef = useRef(false)
  const blockedRef = useRef(true)
  const panRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const hydratingRef = useRef(false)
  const undoRef = useRef<string[]>([])
  const redoRef = useRef<string[]>([])
  const saveRef = useRef<() => void>(() => undefined)
  const resetRef = useRef<() => Promise<void>>(async () => undefined)
  const strokeCountRef = useRef(0)
  const [tool, setTool] = useState<DrawingTool>('pen')
  const [color, setColor] = useState('#292724')
  const [brushSize, setBrushSize] = useState(8)
  const [opacity, setOpacity] = useState(100)
  const [brushStyle, setBrushStyle] = useState<'ink' | 'marker'>('ink')
  const [pressure, setPressure] = useState(true)
  const [stabilize, setStabilize] = useState(35)
  const [fillShapes, setFillShapes] = useState(false)
  const [layersOpen, setLayersOpen] = useState(true)
  const [renameId, setRenameId] = useState('')
  const [renameValue, setRenameValue] = useState('')
  const [zoom, setZoom] = useState(1)
  const [viewportSize, setViewportSize] = useState({ width: 1, height: 1 })
  const [layers, setLayers] = useState<DrawingLayer[]>([])
  const [activeLayerId, setActiveLayerId] = useState('')
  const [ready, setReady] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [historyBusy, setHistoryBusy] = useState(false)
  const [canUndo, setCanUndo] = useState(false)
  const [canRedo, setCanRedo] = useState(false)
  const [loadingLabel, setLoadingLabel] = useState('Loading drawing engine...')

  const updateLayers = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const objects = canvas.getObjects() as EditorObject[]
    setLayers(objects.map((object, index) => ({
      id: object.storyboardId || '',
      name: layerName(object, index),
      visible: object.visible !== false,
      locked: object.storyboardLocked === true,
      kind: object.globalCompositeOperation === 'destination-out' ? 'Eraser'
        : object.type === 'image' ? 'Image'
        : object.type === 'rect' ? 'Rectangle'
        : object.type === 'ellipse' ? 'Ellipse'
        : object.type === 'line' ? 'Line'
        : object.type === 'i-text' || object.type === 'textbox' ? 'Text' : 'Stroke',
    })).reverse())
  }, [])

  const serializeCanvas = useCallback((): string => {
    const canvas = canvasRef.current
    return canvas ? JSON.stringify(canvas.toObject(SERIALIZED_PROPERTIES)) : ''
  }, [])

  const updateHistoryControls = useCallback(() => {
    setCanUndo(undoRef.current.length > 1)
    setCanRedo(redoRef.current.length > 0)
  }, [])

  const commitHistory = useCallback(() => {
    if (hydratingRef.current) return
    const snapshot = serializeCanvas()
    if (!snapshot || undoRef.current.at(-1) === snapshot) return
    undoRef.current.push(snapshot)
    if (undoRef.current.length > 80) undoRef.current.shift()
    redoRef.current = []
    setDirty(true)
    updateLayers()
    updateHistoryControls()
  }, [serializeCanvas, updateHistoryControls, updateLayers])

  const applyTool = useCallback((nextTool: DrawingTool, nextColor = colorRef.current, nextSize = brushSizeRef.current) => {
    toolRef.current = nextTool
    setTool(nextTool)
    const canvas = canvasRef.current
    const fabric = fabricRef.current
    if (!canvas || !fabric) return
    const previousBrush = canvas.freeDrawingBrush
    if (previousBrush && 'finish' in previousBrush && typeof previousBrush.finish === 'function') previousBrush.finish()
    finishTextEditing(canvas)
    if (nextTool !== 'select') canvas.discardActiveObject()
    canvas.isDrawingMode = nextTool === 'pen' || nextTool === 'eraser'
    canvas.selection = nextTool === 'select'
    canvas.skipTargetFind = nextTool !== 'select'
    canvas.defaultCursor = nextTool === 'hand' ? 'grab' : nextTool === 'select' ? 'default' : 'crosshair'
    if (canvas.isDrawingMode) {
      if (brushFactoryRef.current) canvas.freeDrawingBrush = brushFactoryRef.current(fabric, canvas, {
        ...brushStyleRef.current, color: nextColor, size: nextSize,
        opacity: opacityRef.current, eraser: nextTool === 'eraser',
      })
    }
    canvas.requestRenderAll()
  }, [])

  useEffect(() => {
    colorRef.current = color
    brushSizeRef.current = brushSize
    opacityRef.current = opacity
    brushStyleRef.current = { marker: brushStyle === 'marker', pressure, stabilize }
    applyTool(toolRef.current, color, brushSize)
  }, [applyTool, brushSize, color, opacity, brushStyle, pressure, stabilize])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const observer = new ResizeObserver(() => {
      setViewportSize({ width: Math.max(1, viewport.clientWidth - 24), height: Math.max(1, viewport.clientHeight - 24) })
      canvasRef.current?.calcOffset()
    })
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    let canvas: FabricCanvas | null = null
    const artworkLoad = new AbortController()

    async function addCurrentArtwork(fabric: FabricModule, target: FabricCanvas) {
      let artwork: FabricObject | null = null
      if (artworkImage) {
        // The preview URL is overwritten by Save drawing. Embed its original bytes
        // so restoring editable layers never reloads a resized, already-composited preview.
        const response = await fetch(artworkImage, { signal: artworkLoad.signal })
        if (!response.ok) throw new Error('The artwork image could not be loaded (HTTP ' + response.status + ').')
        const immutableSource = await imageBlobDataUrl(await response.blob())
        if (cancelled) return
        const image = await fabric.FabricImage.fromURL(immutableSource, { signal: artworkLoad.signal })
        image.set({ originX: 'left', originY: 'top', left: 0, top: 0, scaleX: width / Math.max(1, image.width), scaleY: height / Math.max(1, image.height) })
        Object.assign(image, { storyboardId: makeObjectId(), storyboardName: 'Artwork' })
        setObjectLocked(image, true)
        artwork = image
      } else if (!boardBackgroundImage && !codexImage) {
        const base = new fabric.Rect({ originX: 'left', originY: 'top', left: 0, top: 0, width, height, fill: canvasColor })
        Object.assign(base, { storyboardId: makeObjectId(), storyboardName: 'Artwork base' })
        setObjectLocked(base, true)
        artwork = base
      }
      if (cancelled) return
      target.clear()
      if (artwork) target.add(artwork)
      target.discardActiveObject()
      target.requestRenderAll()
    }

    async function initialize() {
      if (!canvasElementRef.current) return
      try {
        const [fabric, brushModule] = await Promise.all([import('fabric'), import('./freehandBrush')])
        if (cancelled || !canvasElementRef.current) return
        fabricRef.current = fabric
        brushFactoryRef.current = brushModule.createFreehandBrush
        canvas = new fabric.Canvas(canvasElementRef.current, {
          width, height, backgroundColor: 'transparent', preserveObjectStacking: true, selection: false, enablePointerEvents: true,
        })
        canvasRef.current = canvas
        canvas.upperCanvasEl.addEventListener('pointercancel', (event) => {
          const brush = canvas!.freeDrawingBrush
          if (brush && 'cancel' in brush && typeof brush.cancel === 'function') brush.cancel()
          canvas!._onMouseUp(event)
        })
        hydratingRef.current = true
        setLoadingLabel('Restoring editable drawing...')
        const saved = await loadShotDrawingProject(shotId)
        if (cancelled) return
        let restored = false
        if (saved.editor_data) {
          try {
            const document = JSON.parse(saved.editor_data) as unknown
            if (isNativeDrawingDocument(document)) {
              await canvas.loadFromJSON(document.canvas)
              restored = true
            }
          } catch { restored = false }
        }
        if (!restored) await addCurrentArtwork(fabric, canvas)
        if (cancelled) return
        ;(canvas.getObjects() as EditorObject[]).forEach((object, index) => {
          if (!object.storyboardId) object.storyboardId = makeObjectId()
          if (!object.storyboardName) object.storyboardName = layerName(object, index)
          setObjectLocked(object, object.storyboardLocked ?? ['Artwork', 'Artwork base'].includes(object.storyboardName))
        })
        strokeCountRef.current = canvas.getObjects().length
        hydratingRef.current = false
        undoRef.current = [serializeCanvas()]
        redoRef.current = []
        updateLayers()
        updateHistoryControls()

        canvas.on('path:created', ({ path }) => {
          const object = path as EditorObject
          const erasing = object.globalCompositeOperation === 'destination-out'
          strokeCountRef.current += 1
          Object.assign(object, {
            storyboardId: makeObjectId(),
            storyboardName: `${erasing ? 'Eraser' : 'Drawing'} ${strokeCountRef.current}`,
          })
          canvas!.requestRenderAll()
          commitHistory()
        })
        canvas.on('object:modified', commitHistory)
        canvas.on('text:editing:exited', commitHistory)
        canvas.on('selection:created', ({ selected }) => setActiveLayerId((selected?.[0] as EditorObject)?.storyboardId || ''))
        canvas.on('selection:updated', ({ selected }) => setActiveLayerId((selected?.[0] as EditorObject)?.storyboardId || ''))
        canvas.on('selection:cleared', () => setActiveLayerId(''))

        resetRef.current = async () => {
          if (operationBusyRef.current) return
          operationBusyRef.current = true
          finishTextEditing(canvas!)
          hydratingRef.current = true
          setHistoryBusy(true)
          try {
            await addCurrentArtwork(fabric, canvas!)
            if (cancelled) return
            hydratingRef.current = false
            commitHistory()
            applyTool('pen')
          } finally {
            hydratingRef.current = false
            operationBusyRef.current = false
            if (!cancelled) setHistoryBusy(false)
          }
        }
        setReady(true)
        applyTool('pen')
      } catch (error) {
        if (cancelled) return
        hydratingRef.current = false
        onError(error)
        setLoadingLabel('Drawing editor could not be initialized.')
      }
    }

    void initialize()
    return () => {
      cancelled = true
      artworkLoad.abort()
      const brush = canvas?.freeDrawingBrush
      if (brush && 'cancel' in brush && typeof brush.cancel === 'function') brush.cancel()
      canvasRef.current = null
      fabricRef.current = null
      brushFactoryRef.current = null
      void canvas?.dispose()
    }
  }, [applyTool, artworkImage, boardBackgroundImage, canvasColor, codexImage, commitHistory, height, onError, serializeCanvas, shotId, updateHistoryControls, updateLayers, width])

  const restoreSnapshot = useCallback(async (snapshot: string) => {
    const canvas = canvasRef.current
    if (!canvas) return
    operationBusyRef.current = true
    setHistoryBusy(true)
    hydratingRef.current = true
    try {
      await canvas.loadFromJSON(JSON.parse(snapshot))
      canvas.discardActiveObject()
      canvas.requestRenderAll()
      setDirty(true)
      updateLayers()
      updateHistoryControls()
      applyTool(toolRef.current)
    } catch (error) { onError(error) }
    finally { hydratingRef.current = false; operationBusyRef.current = false; setHistoryBusy(false) }
  }, [applyTool, onError, updateHistoryControls, updateLayers])

  const undo = useCallback(() => {
    if (undoRef.current.length <= 1 || blockedRef.current || operationBusyRef.current) return
    finishTextEditing(canvasRef.current!)
    const current = undoRef.current.pop()
    if (current) redoRef.current.push(current)
    const previous = undoRef.current.at(-1)
    updateHistoryControls()
    if (previous) void restoreSnapshot(previous)
  }, [restoreSnapshot, updateHistoryControls])

  const redo = useCallback(() => {
    if (!redoRef.current.length || blockedRef.current || operationBusyRef.current) return
    const next = redoRef.current.pop()
    if (!next) return
    undoRef.current.push(next)
    updateHistoryControls()
    void restoreSnapshot(next)
  }, [restoreSnapshot, updateHistoryControls])

  const findObject = useCallback((id: string): EditorObject | undefined => (
    (canvasRef.current?.getObjects() as EditorObject[] | undefined)?.find((object) => object.storyboardId === id)
  ), [])

  const selectLayer = (id: string) => {
    const canvas = canvasRef.current; const object = findObject(id)
    if (!canvas || !object || object.visible === false) return
    applyTool('select')
    canvas.discardActiveObject()
    if (!object.storyboardLocked) canvas.setActiveObject(object)
    setActiveLayerId(id)
    canvas.requestRenderAll()
  }

  const toggleLayer = (id: string) => {
    const canvas = canvasRef.current; const object = findObject(id)
    if (!canvas || !object) return
    object.set('visible', object.visible === false)
    if (!object.visible) canvas.discardActiveObject()
    canvas.requestRenderAll(); commitHistory()
  }

  const renameLayer = (id: string) => {
    const object = findObject(id)
    if (!object) return
    setRenameId(id)
    setRenameValue(layerName(object, 0))
  }

  const finishRename = () => {
    const object = findObject(renameId)
    const name = renameValue.trim()
    if (object && name && name !== object.storyboardName) {
      object.storyboardName = name
      commitHistory()
    }
    setRenameId('')
  }

  const toggleLock = (id: string) => {
    const canvas = canvasRef.current
    const object = findObject(id)
    if (!canvas || !object) return
    finishTextEditing(canvas)
    canvas.discardActiveObject()
    setObjectLocked(object, !object.storyboardLocked)
    setActiveLayerId(id)
    commitHistory()
    canvas.requestRenderAll()
  }

  const moveLayer = (id: string, direction: 'up' | 'down') => {
    const canvas = canvasRef.current; const object = findObject(id)
    if (!canvas || !object) return
    const objects = canvas.getObjects(); const index = objects.indexOf(object)
    const next = direction === 'up' ? index + 1 : index - 1
    if (next < 0 || next >= objects.length) return
    canvas.moveObjectTo(object, next); canvas.requestRenderAll(); commitHistory()
  }

  const deleteLayer = useCallback((id = activeLayerId) => {
    const canvas = canvasRef.current
    if (!canvas || blockedRef.current || operationBusyRef.current) return
    const selected = canvas.getActiveObjects() as EditorObject[]
    const object = findObject(id)
    const targets = selected.length > 1 && id === activeLayerId ? selected : object ? [object] : []
    const removable = targets.filter((item) => !item.storyboardLocked)
    if (!removable.length) return
    finishTextEditing(canvas)
    canvas.discardActiveObject()
    canvas.remove(...removable)
    setActiveLayerId('')
    canvas.requestRenderAll()
    commitHistory()
  }, [activeLayerId, commitHistory, findObject])

  const duplicateSelection = useCallback(async () => {
    const canvas = canvasRef.current
    const object = findObject(activeLayerId)
    if (!canvas || !object || object.storyboardLocked || blockedRef.current || operationBusyRef.current) return
    finishTextEditing(canvas)
    operationBusyRef.current = true
    setHistoryBusy(true)
    try {
      canvas.discardActiveObject()
      const copy = await object.clone(SERIALIZED_PROPERTIES) as EditorObject
      if (canvasRef.current !== canvas) return
      copy.set({ left: object.left + 24, top: object.top + 24 })
      Object.assign(copy, { storyboardId: makeObjectId(), storyboardName: `${layerName(object, 0)} copy` })
      canvas.add(copy)
      applyTool('select')
      canvas.setActiveObject(copy)
      copy.setCoords()
      canvas.requestRenderAll()
      commitHistory()
    } catch (error) { onError(error) }
    finally { operationBusyRef.current = false; setHistoryBusy(false) }
  }, [activeLayerId, applyTool, commitHistory, findObject, onError])

  const addShape = (kind: 'rectangle' | 'ellipse' | 'line' | 'text') => {
    const canvas = canvasRef.current
    const fabric = fabricRef.current
    if (!canvas || !fabric || blockedRef.current) return
    finishTextEditing(canvas)
    const size = Math.min(width, height) * 0.25
    const options = {
      left: width / 2, top: height / 2, originX: 'center' as const, originY: 'center' as const,
      stroke: color, strokeWidth: brushSize, fill: fillShapes ? color : 'transparent', opacity: opacity / 100,
    }
    const object = kind === 'rectangle' ? new fabric.Rect({ ...options, width: size * 1.5, height: size })
      : kind === 'ellipse' ? new fabric.Ellipse({ ...options, rx: size * 0.75, ry: size * 0.5 })
      : kind === 'line' ? new fabric.Line([0, 0, size * 1.5, 0], options)
      : new fabric.IText('Text', { ...options, fill: color, strokeWidth: 0, fontSize: Math.max(24, size * 0.4), fontFamily: 'sans-serif' })
    strokeCountRef.current += 1
    Object.assign(object, { storyboardId: makeObjectId(), storyboardName: `${kind[0].toUpperCase()}${kind.slice(1)} ${strokeCountRef.current}` })
    applyTool('select')
    canvas.add(object)
    canvas.setActiveObject(object)
    commitHistory()
    canvas.requestRenderAll()
    if (kind === 'text' && object instanceof fabric.IText) {
      object.enterEditing()
      object.selectAll()
    }
  }

  const changeOpacity = (value: number) => {
    setOpacity(value)
    opacityRef.current = value
    const object = findObject(activeLayerId)
    if (tool === 'select' && object && !object.storyboardLocked && object.globalCompositeOperation !== 'destination-out') {
      object.set('opacity', value / 100)
      canvasRef.current?.requestRenderAll()
      commitHistory()
    }
  }

  const cancel = useCallback(() => {
    if (dirty && !window.confirm('Discard the unsaved drawing changes?')) return
    onCancel()
  }, [dirty, onCancel])

  const save = useCallback(async () => {
    const canvas = canvasRef.current
    if (!canvas || !ready || saving || disabled || operationBusyRef.current) return
    const brush = canvas.freeDrawingBrush
    if (brush && 'finish' in brush && typeof brush.finish === 'function') brush.finish()
    finishTextEditing(canvas)
    operationBusyRef.current = true
    setSaving(true)
    try {
      canvas.discardActiveObject(); canvas.requestRenderAll()
      const objects = canvas.getObjects() as EditorObject[]
      const document: NativeDrawingDocument = {
        info: { format: 'storyboarder-fabric', version: 1, width, height },
        layers: objects.map((object, index) => ({ id: object.storyboardId || '', name: layerName(object, index), visible: object.visible !== false })),
        canvas: canvas.toObject(SERIALIZED_PROPERTIES) as Record<string, unknown>,
      }
      const imageData = canvas.toDataURL({ format: 'png', multiplier: 1, enableRetinaScaling: false })
      if (await onSave(imageData, JSON.stringify(document))) setDirty(false)
    } catch (error) { onError(error) }
    finally { operationBusyRef.current = false; setSaving(false) }
  }, [disabled, height, onError, onSave, ready, saving, width])

  useEffect(() => { saveRef.current = () => { void save() } }, [save])

  useEffect(() => {
    document.body.classList.add('storyboard-drawing-active')
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const key = event.key.toLowerCase()
      const mod = event.ctrlKey || event.metaKey
      if (mod && key === 's') { event.preventDefault(); saveRef.current(); return }
      const active = canvasRef.current?.getActiveObject()
      if (target?.closest('input, textarea, select, [contenteditable="true"]') || (active && 'isEditing' in active && active.isEditing)) return
      if (blockedRef.current) return
      if (mod && key === 'z') { event.preventDefault(); if (event.shiftKey) redo(); else undo() }
      else if (mod && key === 'y') { event.preventDefault(); redo() }
      else if (mod && key === 'd') { event.preventDefault(); void duplicateSelection() }
      else if (mod || event.altKey) return
      else if ((event.key === 'Delete' || event.key === 'Backspace') && activeLayerId) { event.preventDefault(); deleteLayer() }
      else if (key === 'v') applyTool('select')
      else if (key === 'b') applyTool('pen')
      else if (key === 'e') applyTool('eraser')
      else if (key === 'h') applyTool('hand')
      else if (key === '[' || key === ']') { event.preventDefault(); setBrushSize((size) => Math.max(1, Math.min(80, size + (key === '[' ? -1 : 1)))) }
      else if (key === 'escape') { canvasRef.current?.discardActiveObject(); canvasRef.current?.requestRenderAll(); setActiveLayerId('') }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => { document.body.classList.remove('storyboard-drawing-active'); window.removeEventListener('keydown', handleKeyDown) }
  }, [activeLayerId, applyTool, deleteLayer, duplicateSelection, redo, undo])

  useEffect(() => {
    if (!dirty) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [dirty])

  const reset = () => {
    if (!window.confirm('Replace the editable layers with the current storyboard shot?')) return
    void resetRef.current().catch(onError)
  }

  const controlsDisabled = disabled || saving || historyBusy || !ready
  useEffect(() => {
    blockedRef.current = controlsDisabled
    const canvas = canvasRef.current
    if (!canvas) return
    if (controlsDisabled) {
      canvas.isDrawingMode = false
      canvas.selection = false
      canvas.skipTargetFind = true
    } else applyTool(toolRef.current)
  }, [applyTool, controlsDisabled])

  const activeLayer = layers.find((layer) => layer.id === activeLayerId)
  const fitScale = Math.min(viewportSize.width / width, viewportSize.height / height)
  const stageWidth = Math.max(1, width * fitScale * zoom)
  const stageHeight = Math.max(1, height * fitScale * zoom)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const diameter = Math.max(3, Math.min(120, brushSize * stageWidth / width))
    const size = Math.ceil(diameter + 6)
    const center = size / 2
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}"><circle cx="${center}" cy="${center}" r="${diameter / 2}" fill="none" stroke="white" stroke-width="3"/><circle cx="${center}" cy="${center}" r="${diameter / 2}" fill="none" stroke="black" stroke-width="1"/></svg>`
    canvas.freeDrawingCursor = `url("data:image/svg+xml,${encodeURIComponent(svg)}") ${Math.floor(center)} ${Math.floor(center)}, crosshair`
  }, [brushSize, ready, stageWidth, width])

  return (
    <div className="full-drawing-editor">
      <div className="native-drawing-toolbar" aria-label="Drawing tools">
        <div className="native-drawing-tool-group" role="group" aria-label="Tools">
          <button type="button" className={tool === 'select' ? 'is-active' : ''} onClick={() => applyTool('select')} disabled={controlsDisabled} title="Select and transform (V)">Select</button>
          <button type="button" className={tool === 'pen' ? 'is-active' : ''} onClick={() => applyTool('pen')} disabled={controlsDisabled} title="Pen (B)">Pen</button>
          <button type="button" className={tool === 'eraser' ? 'is-active' : ''} onClick={() => applyTool('eraser')} disabled={controlsDisabled} title="Eraser (E)">Eraser</button>
          <button type="button" className={tool === 'hand' ? 'is-active' : ''} onClick={() => applyTool('hand')} disabled={controlsDisabled} title="Pan canvas (H)">Hand</button>
        </div>
        <label className="native-drawing-color" title="Stroke color">Color<input type="color" value={color} onChange={(event) => setColor(event.target.value)} disabled={controlsDisabled} /></label>
        <label className="native-drawing-size">Size<input type="range" min="1" max="80" value={brushSize} onChange={(event) => setBrushSize(Number(event.target.value))} disabled={controlsDisabled} /><span>{brushSize}px</span></label>
        <div className="native-drawing-history" role="group" aria-label="History">
          <button type="button" onClick={undo} disabled={controlsDisabled || !canUndo}>Undo</button>
          <button type="button" onClick={redo} disabled={controlsDisabled || !canRedo}>Redo</button>
        </div>
        <div className="full-drawing-toolbar-spacer" />
        <button type="button" onClick={reset} disabled={controlsDisabled}>Reset</button>
        <button type="button" onClick={cancel} disabled={saving || historyBusy || disabled}>Cancel</button>
        <button type="button" className="primary" onClick={() => void save()} disabled={controlsDisabled}>{saving ? 'Saving...' : 'Save drawing'}</button>
      </div>
      <div className="native-drawing-toolbar native-drawing-options" aria-label="Drawing options">
        <div className="native-drawing-tool-group" role="group" aria-label="Add shapes">
          <button type="button" onClick={() => addShape('rectangle')} disabled={controlsDisabled} title="Add rectangle">▭ Rectangle</button>
          <button type="button" onClick={() => addShape('ellipse')} disabled={controlsDisabled} title="Add ellipse">◯ Ellipse</button>
          <button type="button" onClick={() => addShape('line')} disabled={controlsDisabled} title="Add line">╱ Line</button>
          <button type="button" onClick={() => addShape('text')} disabled={controlsDisabled} title="Add text; double-click to edit">T Text</button>
        </div>
        <label className="native-drawing-fill"><input type="checkbox" checked={fillShapes} onChange={(event) => setFillShapes(event.target.checked)} disabled={controlsDisabled} />Fill</label>
        <label className="native-drawing-opacity">Opacity<input type="range" min="1" max="100" value={opacity} onChange={(event) => changeOpacity(Number(event.target.value))} disabled={controlsDisabled || (tool === 'select' && !!activeLayer?.locked)} /><span>{opacity}%</span></label>
        <button type="button" onClick={() => void duplicateSelection()} disabled={controlsDisabled || !activeLayer || activeLayer.locked} title="Duplicate selected object (Ctrl+D)">Duplicate</button>
        <div className="full-drawing-toolbar-spacer" />
        <div className="native-drawing-tool-group" role="group" aria-label="Canvas zoom">
          <button type="button" aria-label="Zoom out" onClick={() => setZoom((value) => Math.max(0.5, value / 1.25))} disabled={controlsDisabled || zoom <= 0.5}>−</button>
          <span className="native-drawing-zoom" title="Zoom relative to fit">{Math.round(zoom * 100)}%</span>
          <button type="button" aria-label="Zoom in" onClick={() => setZoom((value) => Math.min(4, value * 1.25))} disabled={controlsDisabled || zoom >= 4}>+</button>
          <button type="button" onClick={() => { setZoom(1); viewportRef.current?.scrollTo(0, 0) }} disabled={controlsDisabled}>Fit</button>
        </div>
        <button type="button" aria-pressed={layersOpen} onClick={() => setLayersOpen((value) => !value)}>Layers</button>
      </div>
      <div className="native-drawing-toolbar native-drawing-brush-options" aria-label="Brush settings">
        <div className="native-drawing-tool-group" role="group" aria-label="Brush style">
          <button type="button" className={brushStyle === 'ink' && tool === 'pen' ? 'is-active' : ''} disabled={controlsDisabled} onClick={() => { setBrushStyle('ink'); setBrushSize(8); setOpacity(100); applyTool('pen') }}>Ink</button>
          <button type="button" className={brushStyle === 'marker' && tool === 'pen' ? 'is-active' : ''} disabled={controlsDisabled} onClick={() => { setBrushStyle('marker'); setBrushSize(28); setOpacity(35); applyTool('pen') }}>Marker</button>
        </div>
        <label className="native-drawing-fill" title="Pen pressure for a stylus; speed-based width variation for a mouse"><input type="checkbox" checked={pressure} onChange={(event) => setPressure(event.target.checked)} disabled={controlsDisabled || brushStyle === 'marker'} />Pressure</label>
        <label className="native-drawing-stabilize">Stabilize<input type="range" min="0" max="100" value={stabilize} onChange={(event) => setStabilize(Number(event.target.value))} disabled={controlsDisabled} /><span>{stabilize}%</span></label>
        <span className="native-drawing-brush-hint">Shift: straight stroke · [ ]: size</span>
      </div>
      <div className="native-drawing-workspace">
        <div
          ref={viewportRef}
          className={`native-drawing-stage-wrap${tool === 'hand' ? ' is-hand' : ''}`}
          onPointerDownCapture={(event) => {
            if (tool !== 'hand' || controlsDisabled || event.button !== 0) return
            event.preventDefault()
            event.stopPropagation()
            const viewport = event.currentTarget
            viewport.setPointerCapture(event.pointerId)
            panRef.current = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop }
          }}
          onPointerMove={(event) => {
            const pan = panRef.current
            if (!pan) return
            event.currentTarget.scrollLeft = pan.left + pan.x - event.clientX
            event.currentTarget.scrollTop = pan.top + pan.y - event.clientY
          }}
          onPointerUp={(event) => { panRef.current = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId) }}
          onPointerCancel={() => { panRef.current = null }}
        >
          {!ready ? <div className="full-drawing-loading">{loadingLabel}</div> : null}
          <div className="native-drawing-stage-position" style={{ width: stageWidth + 24, height: stageHeight + 24 }}>
          <div className="native-drawing-stage" style={{ width: stageWidth, height: stageHeight, backgroundColor: boardBackgroundImage || codexImage ? undefined : canvasColor }}>
            {boardBackgroundImage ? <img className="native-drawing-reference" src={boardBackgroundImage} alt="" draggable={false} /> : null}
            {codexImage ? <img className="native-drawing-reference native-drawing-reference-codex" src={codexImage} alt="" draggable={false} /> : null}
            <canvas ref={canvasElementRef} aria-label="Editable storyboard drawing canvas" />
          </div>
          </div>
        </div>
        {layersOpen ? <aside className="native-drawing-layers" aria-label="Drawing layers">
          <div className="native-drawing-layers-heading"><strong>Layers</strong><span>{layers.length}</span></div>
          <div className="native-drawing-layer-list">
            {layers.length ? layers.map((layer, index) => (
              <div key={layer.id || `${layer.name}-${index}`} className={`native-drawing-layer${activeLayerId === layer.id ? ' is-active' : ''}`}>
                <button type="button" className="native-layer-visible" onClick={() => toggleLayer(layer.id)} title={layer.visible ? 'Hide layer' : 'Show layer'} aria-label={`${layer.visible ? 'Hide' : 'Show'} ${layer.name}`} disabled={controlsDisabled}>{layer.visible ? '●' : '○'}</button>
                {renameId === layer.id ? <input className="native-layer-rename" aria-label="Layer name" autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} onBlur={finishRename} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); finishRename() } else if (event.key === 'Escape') setRenameId('') }} /> : <button type="button" className="native-layer-name" onClick={() => selectLayer(layer.id)} onDoubleClick={() => renameLayer(layer.id)} title="Select; double-click to rename" disabled={controlsDisabled || !layer.visible}><span>{layer.name}</span><small>{layer.kind}</small></button>}
                <button type="button" className="native-layer-lock" onClick={() => toggleLock(layer.id)} aria-label={`${layer.locked ? 'Unlock' : 'Lock'} ${layer.name}`} title={layer.locked ? 'Unlock layer' : 'Lock layer'} disabled={controlsDisabled}>{layer.locked ? '▣' : '▢'}</button>
                <button type="button" onClick={() => moveLayer(layer.id, 'up')} title="Move layer up" disabled={controlsDisabled || index === 0}>↑</button>
                <button type="button" onClick={() => moveLayer(layer.id, 'down')} title="Move layer down" disabled={controlsDisabled || index === layers.length - 1}>↓</button>
                <button type="button" className="native-layer-delete" onClick={() => deleteLayer(layer.id)} aria-label={`Delete ${layer.name}`} title={layer.locked ? 'Unlock before deleting' : 'Delete layer'} disabled={controlsDisabled || layer.locked}>×</button>
              </div>
            )) : <div className="native-drawing-layers-empty">Draw a stroke to create a layer.</div>}
          </div>
          <div className="native-drawing-shortcuts"><span className={dirty ? 'is-dirty' : ''}>{dirty ? 'Unsaved drawing' : 'Drawing saved'} · {width}×{height}</span><br />V Select · B Pen · E Eraser · H Hand<br />[ ] Brush size · Ctrl+D Duplicate<br />Ctrl+Z/Y History · Del Remove</div>
        </aside> : null}
      </div>
    </div>
  )
}
