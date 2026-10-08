import { useEffect, useMemo, useRef, useState, type PointerEvent, type CSSProperties } from 'react'
import {
  ArrowClockwise, ArrowCounterClockwise, BoundingBox, CaretDown, ChatCircleText, Crop, Cursor, DownloadSimple, FrameCorners, GridFour,
  Knife, Polygon,
} from '@phosphor-icons/react'
import { addShot, duplicateShot } from '../api'
import { useDetailsMenu } from '../hooks/useDetailsMenu'
import { exportComic, openComicExport, previewComicPrompt, type ComicExportScope } from '../api/comic'
import { useProject } from '../state/useProject'
import { useComicDocument } from '../state/useComicDocument'
import type { ComicLettering, ComicMode, ComicPage, ComicPanel } from '../types/comic'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { shotDisplayVersion, shotHasBoardBackground, shotHasCodexLayer, shotShouldOverlayPreview } from '../utils/shotPreview'
import { ShotThumb } from './ShotThumb'
import { ShotInspector } from './ShotInspector'
import { CanvasBoard } from './CanvasBoard'
import { ComicLayoutPreview } from './ComicLayoutPreview'
import { alignPanels, comicGridSize, knifeSplit, panelClip, panelPoints, validPolygon, shiftScrollSpace, resizePanel, snapCoordinate, splitPanel, type Alignment, type PanelRect, type Point, type ResizeHandle } from '../utils/comicLayout'
import { letteringOverflows } from '../utils/comicLettering'
import { ComicLetteringVisual } from './ComicLetteringVisual'
import { PanelResizeHandle } from './PanelResizeHandle'
import './ComicWorkspace.css'

const modes: Record<ComicMode, string> = { page: 'Page', spread: 'Spread', scroll: 'Long scroll' }
const id = () => crypto.randomUUID()
const resizeHandles: ResizeHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']

function NumberField({ label, value, min = 0, max = 32000, disabled, onChange }: {
  label: string; value: number; min?: number; max?: number; disabled: boolean; onChange: (value: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  return <label>{label}<input type="number" min={min} max={max} step={1} value={editing ? text : value} disabled={disabled}
    title={`${min}–${max}; Enter or leave the field to apply`}
    onFocus={() => { setText(String(value)); setEditing(true) }} onChange={event => setText(event.currentTarget.value)}
    onBlur={event => {
      const next = event.currentTarget.valueAsNumber
      setEditing(false)
      if (Number.isInteger(next) && next >= min && next <= max && next !== value) onChange(next)
    }} onKeyDown={event => {
      if (event.key === 'Enter') event.currentTarget.blur()
      if (event.key === 'Escape') { event.currentTarget.value = String(value); event.currentTarget.blur() }
    }} /></label>
}

export function ComicWorkspace({ active }: { active: boolean }) {
  const { project, selectedShotId, setSelectedShotId, setProject, flushDirtyShots, reportError,
    projectActionBusy, drawingActive, visualEpoch, getDraft, editShotField, runProjectMutation } = useProject()
  const [gestureActive, setGestureActive] = useState(false)
  const { ref: exportMenuRef, close: closeExportMenu } = useDetailsMenu()
  const comic = useComicDocument(gestureActive)
  const document = comic.document
  const [chapterId, setChapterId] = useState('')
  const [pageId, setPageId] = useState('')
  const readingSurfaceRef = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<'layout' | 'artwork' | 'read'>('layout')
  const [inspector, setInspector] = useState<'page' | 'panel' | 'lettering' | 'ai'>('page')
  const [tool, setTool] = useState<'move' | 'draw' | 'shape' | 'knife' | 'crop'>('move')
  const [letteringId, setLetteringId] = useState('')
  const [letteringPreview, setLetteringPreview] = useState<(PanelRect & { id: string }) | null>(null)
  const letteringDrag = useRef<{ origin: ComicLettering; x: number; y: number; scale: number; resize: boolean; preview?: PanelRect } | null>(null)
  const [knifeLine, setKnifeLine] = useState<[Point, Point] | null>(null)
  const knifeOrigin = useRef<Point | null>(null)
  const knifeEnd = useRef<Point | null>(null)
  const [scrollSpacing, setScrollSpacing] = useState(160)
  const [guides, setGuides] = useState(true)
  const [selection, setSelection] = useState<string[]>([])
  const [groupPreview, setGroupPreview] = useState<ComicPanel[]>([])
  const [readerWidth, setReaderWidth] = useState(960)
  const [snap, setSnap] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [newRect, setNewRect] = useState<PanelRect | null>(null)
  const newRectRef = useRef<PanelRect | null>(null)
  const drawingRect = useRef<{ x: number; y: number } | null>(null)
  const [boardId, setBoardId] = useState('')
  const [adding, setAdding] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [message, setMessage] = useState('')
  const [lastExport, setLastExport] = useState<ComicExportScope | null>(null)
  const [promptPreview, setPromptPreview] = useState<{ shotId: string; text: string } | null>(null)
  const [dragPreview, setDragPreview] = useState<(ComicPanel) | null>(null)
  const drag = useRef<{ id: string; clientX: number; clientY: number; origin: ComicPanel; scale: number; handle?: ResizeHandle; vertex?: number; group?: ComicPanel[]; groupPreview?: ComicPanel[] } | null>(null)
  const dragPreviewRef = useRef<ComicPanel | null>(null)
  const chapter = document.chapters.find(chapter => chapter.id === chapterId) ?? document.chapters[0]
  const pages = document.pages.filter(page => page.chapter_id === chapter?.id)
  const page = pages.find(page => page.id === pageId) ?? pages[0]
  useEffect(() => {
    if (readingSurfaceRef.current) {
      readingSurfaceRef.current.scrollTop = 0
      readingSurfaceRef.current.scrollLeft = 0
    }
  }, [page?.id, view])
  const panel = page?.panels.find(panel => panel.shot_id === selectedShotId)
  const shotsById = useMemo(() => new Map(project?.shots.map(shot => [shot.shot_id, shot]) ?? []), [project?.shots])
  const lettering = page?.lettering?.find(item => item.id === letteringId)
  const selectedPanels = page?.panels.filter(item => selection.length ? selection.includes(item.id) : item.id === panel?.id) ?? []
  const selectedPanelIds = new Set(selectedPanels.map(item => item.id))
  const groupPositions = new Map(groupPreview.map(item => [item.id, item]))
  const shot = project?.shots.find(shot => shot.shot_id === panel?.shot_id)
  const promptConfig = shot ? getDraft(shot.shot_id)?.prompt_config ?? shot.prompt_config : null
  const placed = new Set(document.pages.flatMap(page => page.panels.map(panel => panel.shot_id)))
  const boards = project?.shots.filter(shot => !placed.has(shot.shot_id)) ?? []
  const selectedBoard = boards.find(shot => shot.shot_id === boardId) ?? boards[0]
  const nextPlacement = (() => {
    if (!page) return null
    const gap = page.gutter
    const width = page.mode !== 'scroll' ? Math.floor((page.width - gap * 3) / 2) : page.width - gap * 2
    const height = Math.min(Math.floor(width * 0.65), page.height - gap * 2)
    const bottom = page.panels.reduce((bottom, panel) => Math.max(bottom, panel.y + panel.height), 0)
    const column = page.panels.length % 2
    const x = page.mode === 'scroll' ? gap : gap + ((document.reading_direction === 'rtl' ? 1 - column : column) * (width + gap))
    const y = page.mode === 'scroll' && bottom ? bottom + gap : page.mode === 'scroll' ? gap : gap + Math.floor(page.panels.length / 2) * (height + gap)
    if (width < 16 || height < 16 || (page.mode !== 'scroll' && y + height > page.height) || y + height + gap > 32000 || page.width * Math.max(page.height, y + height + gap) > 64000000) return null
    return { x, y, width, height }
  })()
  const disabled = adding || exporting || projectActionBusy || drawingActive
  const changePage = (change: (page: ComicPage) => void) => comic.edit(document => {
    const target = document.pages.find(candidate => candidate.id === page?.id)
    if (target) change(target)
    return document
  })
  const changePanel = (change: (panel: ComicPanel) => void) => changePage(page => {
    const target = page.panels.find(candidate => candidate.id === panel?.id)
    if (target) change(target)
  })
  const movePanel = (delta: number) => changePage(page => {
    const index = page.panels.findIndex(candidate => candidate.id === panel?.id)
    if (index < 0 || index + delta < 0 || index + delta >= page.panels.length) return
    const [item] = page.panels.splice(index, 1)
    page.panels.splice(index + delta, 0, item)
  })
  const removePanel = () => changePage(page => {
    const removed = new Set(selectedPanels.filter(item => !item.locked).map(item => item.id))
    page.panels = page.panels.filter(candidate => !removed.has(candidate.id))
  })
  const alignSelection = (operation: Alignment) => changePage(page => {
    const next = new Map(alignPanels(selectedPanels, operation).map(item => [item.id, item]))
    page.panels = page.panels.map(item => next.get(item.id) ?? item)
  })
  const changeLettering = (change: (item: ComicLettering) => void) => changePage(page => {
    const target = page.lettering?.find(candidate => candidate.id === letteringId)
    if (target) change(target)
  })
  const cancelGesture = () => {
    drawingRect.current = null; newRectRef.current = null; setNewRect(null)
    drag.current = null; dragPreviewRef.current = null; setDragPreview(null); setGroupPreview([])
    letteringDrag.current = null; setLetteringPreview(null)
    knifeOrigin.current = null; knifeEnd.current = null; setKnifeLine(null); setGestureActive(false)
  }
  // Comic shortcuts operate on placements. Board deletion remains in the Board workspace.
  useEffect(() => {
    if (!active) return
    const onKey = (event: KeyboardEvent) => {
      if (disabled || view !== 'layout' || (event.target instanceof HTMLElement &&
          (event.target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)))) return
      if (gestureActive && event.key !== 'Escape') return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' && page) {
        event.preventDefault(); setSelection(page.panels.map(item => item.id)); setLetteringId(''); return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault(); if (event.shiftKey) comic.redo(); else comic.undo()
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') { event.preventDefault(); comic.redo() }
      else if (event.key === 'Delete' && lettering) { event.preventDefault(); changePage(page => { page.lettering = page.lettering?.filter(item => item.id !== lettering.id) }) }
      else if (event.key === 'Delete' && panel) { event.preventDefault(); removePanel() }
      else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        const index = page?.panels.findIndex(candidate => candidate.id === panel?.id) ?? -1
        const next = page?.panels[index + (event.key === 'ArrowLeft' ? -1 : 1)]
        if (next) { event.preventDefault(); setSelectedShotId(next.shot_id) }
      } else if (event.key === 'Escape') {
        setTool('move'); cancelGesture()
      } else if (!event.ctrlKey && !event.metaKey && !event.altKey) {
        if (event.key.toLowerCase() === 'r') setTool('draw')
        else if (event.key.toLowerCase() === 'v') setTool('move')
        else if (event.key.toLowerCase() === 'k') { setTool('knife'); setLetteringId(''); setInspector('panel') }
        else if (event.key.toLowerCase() === 'c') { setTool('crop'); setLetteringId(''); setInspector('panel') }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
  if (!project) return null

  const addPage = (mode: ComicMode) => {
    const chapterKey = chapter?.id ?? id()
    const pageKey = id()
    comic.edit(document => {
      if (!document.chapters.length) document.chapters.push({ id: chapterKey, title: 'Chapter 1', prompt: '' })
      document.pages.push({ id: pageKey, chapter_id: chapterKey, title: `${modes[mode]} ${pages.length + 1}`,
        mode, width: mode === 'spread' ? 2400 : mode === 'scroll' ? 800 : 1200,
        height: mode === 'scroll' ? 6000 : 1800, gutter: 32, prompt: '', panels: [] })
      return document
    })
    setSelection([]); setLetteringId(''); setChapterId(chapterKey); setPageId(pageKey); setView('layout'); setInspector('page'); setTool('move')
  }
  const placeBoard = (shotId: string, placement: PanelRect | null = nextPlacement) => {
    if (!page || !placement) {
      reportError(new Error('There is no room for this panel. Reduce the gutter or add another scroll section.')); return
    }
    const { x, y, width, height } = placement
    changePage(page => {
      if (page.mode === 'scroll' && placement === nextPlacement) page.height = Math.max(page.height, y + height + page.gutter)
      page.panels.push({ id: id(), shot_id: shotId, x, y, width, height, fit: 'contain', border: 2 })
    })
    setSelectedShotId(shotId)
    setSelection([])
    setLetteringId('')
    setInspector('panel')
  }
  const newPanel = async (placement: PanelRect | null = nextPlacement) => {
    if (!placement) return
    setAdding(true)
    try {
      await runProjectMutation(async () => {
        await flushDirtyShots()
        const payload = await addShot({})
        const added = payload.shots.find(shot => !project.shots.some(old => old.shot_id === shot.shot_id))
        setProject(current => current?.project_json_path === payload.project_json_path ? payload : current)
        if (added) placeBoard(added.shot_id, placement)
        await comic.flush()
      })
    } catch (error) { reportError(error) } finally { setAdding(false) }
  }
  const splitSelected = async (axis: 'horizontal' | 'vertical', cut?: [Point, Point]) => {
    if (!page || !panel || panel.locked) return
    const shapeCut: [Point, Point] | undefined = panel.points ? axis === 'horizontal' ?
      [[panel.x - 1, panel.y + panel.height / 2], [panel.x + panel.width + 1, panel.y + panel.height / 2]] :
      [[panel.x + panel.width / 2, panel.y - 1], [panel.x + panel.width / 2, panel.y + panel.height + 1]] : undefined
    const line = cut ?? shapeCut
    const halves = line ? knifeSplit(panel, line[0], line[1], page.gutter) : splitPanel(panel, axis, page.gutter, document.reading_direction)
    if (!halves) return
    if (line) halves.sort((a, b) => cut || axis === 'horizontal' ? (a.y + a.height / 2) - (b.y + b.height / 2) :
      ((a.x + a.width / 2) - (b.x + b.width / 2)) * (document.reading_direction === 'rtl' ? -1 : 1))
    const targetId = panel.id
    setAdding(true)
    try {
      await runProjectMutation(async () => {
        await flushDirtyShots()
        const payload = await addShot({})
        const added = payload.shots.find(shot => !project.shots.some(old => old.shot_id === shot.shot_id))
        setProject(current => current?.project_json_path === payload.project_json_path ? payload : current)
        if (added) changePage(page => {
          const index = page.panels.findIndex(panel => panel.id === targetId)
          if (index < 0) return
          const source = page.panels[index]
          page.panels.splice(index, 1, { ...source, points: null, ...halves[0] },
            { ...source, points: null, ...halves[1], id: id(), shot_id: added.shot_id })
        })
        setSelection([])
        await comic.flush()
      })
    } catch (error) { reportError(error) } finally { setAdding(false) }
  }
  const duplicatePanel = async () => {
    if (!page || !panel) return
    setAdding(true)
    try {
      await runProjectMutation(async () => {
        await flushDirtyShots()
        const payload = await duplicateShot(panel.shot_id)
        const added = payload.shots.find(shot => !project.shots.some(old => old.shot_id === shot.shot_id))
        setProject(current => current?.project_json_path === payload.project_json_path ? payload : current)
        if (added) {
          const placementKey = id()
          changePage(page => page.panels.push({ ...panel, id: placementKey, shot_id: added.shot_id,
            x: Math.min(page.width - panel.width, panel.x + comicGridSize), y: Math.min(page.height - panel.height, panel.y + comicGridSize) }))
          setSelection([placementKey])
          setSelectedShotId(added.shot_id)
        }
        await comic.flush()
      })
    } catch (error) { reportError(error) } finally { setAdding(false) }
  }
  const exportPage = async (wholeChapter = false, format?: ComicExportScope['format']) => {
    if (!page || !chapter) return
    setExporting(true); setMessage('')
    try {
      await flushDirtyShots()
      const scope: ComicExportScope = { project_path: project.project_json_path,
        ...(format ? { format } : {}),
        ...(wholeChapter ? { chapter_id: chapter.id } : { page_id: page.id }) }
      const result = await exportComic(scope)
      setLastExport(scope)
      setMessage(`Saved ${format?.toUpperCase() ?? (wholeChapter ? 'chapter ZIP' : 'full-size PNG')}: ${result.path}`)
    } catch (error) { reportError(error) } finally { setExporting(false) }
  }
  const startDrag = (event: PointerEvent<HTMLElement>, target: ComicPanel, currentPage: ComicPage, handle?: ResizeHandle, vertex?: number) => {
    if (disabled || view !== 'layout' || target.locked || tool === 'knife' || tool === 'draw' || event.button !== 0) return
    event.preventDefault(); event.stopPropagation()
    if (event.shiftKey || event.ctrlKey || event.metaKey) {
      setSelection(previous => {
        const initial = previous.length ? previous : panel ? [panel.id] : []
        return initial.includes(target.id) ? initial.filter(key => key !== target.id) : [...initial, target.id]
      })
      setSelectedShotId(target.shot_id); setLetteringId(''); setInspector('panel'); return
    }
    dragPreviewRef.current = null
    setSelectedShotId(target.shot_id)
    setLetteringId('')
    setInspector('panel')
    const surface = event.currentTarget.closest('.comic-sheet')
    if (!surface) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setGestureActive(true)
    const group = tool === 'move' && !handle && selectedPanels.some(item => item.id === target.id) ? selectedPanels.filter(item => !item.locked) : [target]
    if (!selectedPanels.some(item => item.id === target.id)) setSelection([target.id])
    drag.current = { id: target.id, clientX: event.clientX, clientY: event.clientY,
      origin: structuredClone(target),
      scale: surface.getBoundingClientRect().width / currentPage.width, handle, vertex, group }
  }
  const dragMove = (event: PointerEvent<HTMLElement>, target: ComicPanel, currentPage: ComicPage) => {
    if (!drag.current || drag.current.id !== target.id) return
    const origin = drag.current
    const rawDx = (event.clientX - origin.clientX) / origin.scale
    const rawDy = (event.clientY - origin.clientY) / origin.scale
    const dx = snapCoordinate(origin.origin.x + (origin.handle?.includes('e') ? origin.origin.width : 0) + rawDx, snap) -
      (origin.origin.x + (origin.handle?.includes('e') ? origin.origin.width : 0))
    const dy = snapCoordinate(origin.origin.y + (origin.handle?.includes('s') ? origin.origin.height : 0) + rawDy, snap) -
      (origin.origin.y + (origin.handle?.includes('s') ? origin.origin.height : 0))
    if (tool === 'crop') {
      dragPreviewRef.current = { ...origin.origin,
        image_x: Math.max(-2, Math.min(2, (origin.origin.image_x ?? 0) + rawDx / target.width)),
        image_y: Math.max(-2, Math.min(2, (origin.origin.image_y ?? 0) + rawDy / target.height)) }
      setDragPreview(dragPreviewRef.current); return
    }
    if (origin.vertex !== undefined) {
      const points = panelPoints(origin.origin).map(point => [...point] as Point)
      const original = points[origin.vertex]
      points[origin.vertex] = [Math.max(0, Math.min(1, original[0] + rawDx / target.width)), Math.max(0, Math.min(1, original[1] + rawDy / target.height))]
      if (validPolygon(points)) { dragPreviewRef.current = { ...origin.origin, points }; setDragPreview(dragPreviewRef.current) }
      return
    }
    if (!origin.handle && origin.group && origin.group.length > 1) {
      const moveX = Math.max(-Math.min(...origin.group.map(p => p.x)), Math.min(currentPage.width - Math.max(...origin.group.map(p => p.x + p.width)), dx))
      const moveY = Math.max(-Math.min(...origin.group.map(p => p.y)), Math.min(currentPage.height - Math.max(...origin.group.map(p => p.y + p.height)), dy))
      origin.groupPreview = origin.group.map(p => ({ ...p, x: p.x + moveX, y: p.y + moveY }))
      setGroupPreview(origin.groupPreview)
      dragPreviewRef.current = origin.groupPreview.find(p => p.id === target.id) ?? null; setDragPreview(dragPreviewRef.current); return
    }
    const rect = origin.handle ? resizePanel(origin.origin, origin.handle, dx, dy, currentPage) : { ...origin.origin,
      x: Math.round(Math.max(0, Math.min(currentPage.width - target.width, origin.origin.x + dx))),
      y: Math.round(Math.max(0, Math.min(currentPage.height - target.height, origin.origin.y + dy))) }
    dragPreviewRef.current = { ...origin.origin, ...rect }
    setDragPreview(dragPreviewRef.current)
  }
  const finishDrag = (event: PointerEvent<HTMLElement>, target: ComicPanel) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    const group = drag.current?.groupPreview
    drag.current = null
    setGestureActive(false)
    const position = dragPreviewRef.current
    if (position?.id === target.id) {
      changePage(page => {
        const moved = page.panels.find(panel => panel.id === target.id)
        if (moved) Object.assign(moved, position)
        if (group) for (const next of group) { const item = page.panels.find(item => item.id === next.id); if (item) Object.assign(item, next) }
      })
    }
    dragPreviewRef.current = null; setDragPreview(null); setGroupPreview([])
  }
  const canvasPoint = (event: PointerEvent<HTMLDivElement>, current: ComicPage) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return { x: Math.max(0, Math.min(current.width, snapCoordinate((event.clientX - bounds.left) * current.width / bounds.width, snap))),
      y: Math.max(0, Math.min(current.height, snapCoordinate((event.clientY - bounds.top) * current.height / bounds.height, snap))) }
  }
  const startRectangle = (event: PointerEvent<HTMLDivElement>, current: ComicPage) => {
    if (disabled || view !== 'layout' || (tool !== 'draw' && tool !== 'knife') || event.button !== 0) return
    if (tool === 'knife' && (!panel || panel.locked)) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    setGestureActive(true)
    const point = canvasPoint(event, current)
    if (tool === 'knife') {
      knifeOrigin.current = [point.x, point.y]; knifeEnd.current = knifeOrigin.current; setKnifeLine([knifeOrigin.current, knifeOrigin.current]); return
    }
    drawingRect.current = point
    newRectRef.current = null; setNewRect(null)
  }
  const moveRectangle = (event: PointerEvent<HTMLDivElement>, current: ComicPage) => {
    if (knifeOrigin.current) {
      const point = canvasPoint(event, current)
      knifeEnd.current = [point.x, point.y]; setKnifeLine([knifeOrigin.current, knifeEnd.current]); return
    }
    if (!drawingRect.current) return
    const origin = drawingRect.current, point = canvasPoint(event, current)
    newRectRef.current = { x: Math.min(origin.x, point.x), y: Math.min(origin.y, point.y),
      width: Math.abs(point.x - origin.x), height: Math.abs(point.y - origin.y) }
    setNewRect(newRectRef.current)
  }
  const finishRectangle = (event: PointerEvent<HTMLDivElement>) => {
    if (knifeOrigin.current && knifeEnd.current) {
      const cut: [Point, Point] = [knifeOrigin.current, knifeEnd.current]
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
      cancelGesture()
      if (panel && page && knifeSplit(panel, cut[0], cut[1], page.gutter)) void splitSelected('horizontal', cut)
      else setMessage('Drag a line across the selected panel. Both resulting pieces need enough space for the gutter.')
      return
    }
    if (!drawingRect.current) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    const rect = newRectRef.current
    drawingRect.current = null; newRectRef.current = null; setNewRect(null)
    setGestureActive(false)
    if (rect && rect.width >= 16 && rect.height >= 16) { setTool('move'); void newPanel(rect) }
  }
  const addLettering = (kind: ComicLettering['kind']) => {
    if (!page) return
    const key = id(), width = Math.min(300, page.width), height = Math.min(180, page.height)
    changePage(current => {
      current.lettering ??= []
      current.lettering.push({ id: key, kind, text: shot?.dialogue || (kind === 'caption' ? 'Caption' : 'Dialogue'),
        x: Math.min(page.width - width, panel?.x ?? 32), y: Math.min(page.height - height, panel?.y ?? 32),
        width, height, font_size: 32, vertical: false, color: '#161616', fill: '#ffffff', border: 2, tail: .25 })
    })
    setLetteringId(key); setInspector('lettering'); setTool('move'); setView('layout')
  }
  const startLetteringDrag = (event: PointerEvent<HTMLElement>, item: ComicLettering, current: ComicPage, resize = false) => {
    if (disabled || view !== 'layout' || tool !== 'move' || event.button !== 0) return
    event.preventDefault(); event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId)
    const sheet = event.currentTarget.closest('.comic-sheet')!
    setLetteringId(item.id); setInspector('lettering'); setGestureActive(true)
    letteringDrag.current = { origin: item, x: event.clientX, y: event.clientY,
      scale: sheet.getBoundingClientRect().width / current.width, resize }
  }
  const moveLettering = (event: PointerEvent<HTMLElement>, current: ComicPage) => {
    const gesture = letteringDrag.current
    if (!gesture) return
    const dx = (event.clientX - gesture.x) / gesture.scale, dy = (event.clientY - gesture.y) / gesture.scale
    const origin = gesture.origin
    const rect = gesture.resize ? resizePanel(origin, 'se', dx, dy, current) : { ...origin,
      x: Math.max(0, Math.min(current.width - origin.width, snapCoordinate(origin.x + dx, snap))),
      y: Math.max(0, Math.min(current.height - origin.height, snapCoordinate(origin.y + dy, snap))) }
    gesture.preview = rect; setLetteringPreview({ id: origin.id, ...rect })
  }
  const finishLettering = (event: PointerEvent<HTMLElement>) => {
    const gesture = letteringDrag.current
    if (!gesture) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (gesture.preview) changePage(page => {
      const item = page.lettering?.find(item => item.id === gesture.origin.id)
      if (item) Object.assign(item, { x: gesture.preview!.x, y: gesture.preview!.y, width: gesture.preview!.width, height: gesture.preview!.height })
    })
    letteringDrag.current = null; setLetteringPreview(null); setGestureActive(false)
  }
  const renderPage = (current: ComicPage) => <div key={current.id} className={`comic-sheet comic-${current.mode}`}
    data-tool={view === 'layout' ? tool : 'read'} aria-label={`${current.title}, ${modes[current.mode]}`}
    onPointerDown={event => startRectangle(event, current)} onPointerMove={event => moveRectangle(event, current)}
    onPointerUp={finishRectangle} onPointerCancel={cancelGesture}
    style={{ aspectRatio: `${current.width} / ${current.height}`, background: current.background ?? '#fff' }}>
    {snap && view === 'layout' ? <div className="comic-grid" aria-hidden="true" style={{ backgroundSize: `${100 * comicGridSize / current.width}cqw ${100 * comicGridSize / current.width}cqw` }} /> : null}
    {guides && view === 'layout' ? <div className="comic-safe-guide" aria-label="Safe margin guide" style={{
      inset: `${100 * (current.safe_margin ?? 32) / current.height}% ${100 * (current.safe_margin ?? 32) / current.width}%` }} /> : null}
    {current.mode === 'spread' && guides && view !== 'read' ? <div className="comic-spine" aria-label="Binding gutter"
      style={{ width: `${100 * current.gutter / current.width}%` }} /> : null}
    {current.panels.map((item, index) => {
      const shot = shotsById.get(item.shot_id)
      const position = dragPreview?.id === item.id ? dragPreview : groupPositions.get(item.id) ?? item
      if (!shot) return null
      return <div key={item.id} className={`comic-panel-frame ${selectedPanelIds.has(item.id) ? 'is-selected' : ''}`}
        style={{ left: `${100 * position.x / current.width}%`, top: `${100 * position.y / current.height}%`,
          width: `${100 * position.width / current.width}%`, height: `${100 * position.height / current.height}%` }}>
        <button type="button" className="comic-panel"
        aria-label={`Panel ${index + 1}: ${shotDisplayLabel(shot)}`} aria-pressed={selectedShotId === item.shot_id}
        onClick={event => { if (!drawingActive && !gestureActive && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
          setPageId(current.id); setSelectedShotId(item.shot_id); setLetteringId(''); setInspector('panel')
          if (!selectedPanelIds.has(item.id)) setSelection([item.id])
        } }}
        onDoubleClick={() => { if (!disabled && view === 'layout' && !item.locked) setTool('crop') }}
        onPointerDown={event => startDrag(event, item, current)} onPointerMove={event => dragMove(event, item, current)}
        onPointerUp={event => finishDrag(event, item)} onPointerCancel={() => { drag.current = null; dragPreviewRef.current = null; setDragPreview(null); setGestureActive(false) }}
        data-locked={item.locked ? 'true' : 'false'}
        style={{ '--comic-fit': item.fit, clipPath: panelClip(position) } as CSSProperties}>
        <div className="comic-image" style={{ transform: `translate(${(position.image_x ?? 0) * 100}%, ${(position.image_y ?? 0) * 100}%) scale(${position.image_scale ?? 1})` }}>
          <ShotThumb shotId={item.shot_id} version={shotDisplayVersion(shot, visualEpoch, index)} hasImage={shotShouldOverlayPreview(shot)}
            hasBg={shotHasBoardBackground(shot)} hasCodex={shotHasCodexLayer(shot)} fullResolution />
        </div>
        <svg className="comic-panel-border" viewBox={`0 0 ${position.width} ${position.height}`} preserveAspectRatio="none" aria-hidden="true">
          <polygon points={panelPoints(position).map(([x, y]) => `${x * position.width},${y * position.height}`).join(' ')} fill="none" stroke="#161616" strokeWidth={item.border * 2} />
        </svg>
        {view !== 'read' ? <span className="comic-panel-label">{item.locked ? '🔒 ' : ''}{index + 1} · {shotDisplayLabel(shot)}</span> : null}
        </button>
        {view === 'layout' && tool === 'move' && selectedShotId === item.shot_id && !disabled && !item.locked ? resizeHandles.map(handle =>
          <button key={handle} type="button" className={`comic-resize comic-resize-${handle}`}
            aria-label={`Resize panel ${index + 1} ${handle}`} title="Drag to resize; use Panel fields for exact dimensions"
            onPointerDown={event => startDrag(event, item, current, handle)}
            onPointerMove={event => dragMove(event, item, current)} onPointerUp={event => finishDrag(event, item)}
            onPointerCancel={cancelGesture} />) : null}
        {view === 'layout' && tool === 'shape' && selectedShotId === item.shot_id && !disabled && !item.locked ? panelPoints(position).map(([x, y], vertex) =>
          <button type="button" key={vertex} className="comic-resize comic-vertex" aria-label={`Edit panel vertex ${vertex + 1}`}
            style={{ left: `${x * 100}%`, top: `${y * 100}%` }} onPointerDown={event => startDrag(event, item, current, undefined, vertex)}
            onPointerMove={event => dragMove(event, item, current)} onPointerUp={event => finishDrag(event, item)} onPointerCancel={cancelGesture} />) : null}
      </div>
    })}
    {(current.lettering ?? []).map(item => {
      const position = letteringPreview?.id === item.id ? { ...item, ...letteringPreview } : item
      return <div key={item.id} className={`comic-lettering ${view === 'layout' && letteringId === item.id ? 'is-selected' : ''}`}
        style={{ left: `${position.x * 100 / current.width}%`, top: `${position.y * 100 / current.height}%`,
          width: `${position.width * 100 / current.width}%`, height: `${position.height * 100 / current.height}%` }}>
        <button type="button" className="comic-lettering-content" aria-label={`Lettering: ${item.text}`}
          onClick={() => { if (view !== 'read' && !disabled) { setLetteringId(item.id); setInspector('lettering') } }}
          onPointerDown={event => startLetteringDrag(event, item, current)} onPointerMove={event => moveLettering(event, current)}
          onPointerUp={finishLettering} onPointerCancel={cancelGesture}><ComicLetteringVisual item={position} /></button>
        {view === 'layout' && tool === 'move' && letteringId === item.id && !disabled ? <button type="button" className="comic-resize comic-resize-se"
          aria-label="Resize lettering" onPointerDown={event => startLetteringDrag(event, item, current, true)}
          onPointerMove={event => moveLettering(event, current)} onPointerUp={finishLettering} onPointerCancel={cancelGesture} /> : null}
      </div>
    })}
    {knifeLine && view === 'layout' ? <svg className="comic-knife-line" viewBox={`0 0 ${current.width} ${current.height}`} aria-hidden="true">
      <line x1={knifeLine[0][0]} y1={knifeLine[0][1]} x2={knifeLine[1][0]} y2={knifeLine[1][1]} stroke="var(--color-accent)" strokeWidth={3} vectorEffect="non-scaling-stroke" />
    </svg> : null}
    {newRect && view === 'layout' ? <div className="comic-new-rect" style={{ left: `${100 * newRect.x / current.width}%`,
      top: `${100 * newRect.y / current.height}%`, width: `${100 * newRect.width / current.width}%`, height: `${100 * newRect.height / current.height}%` }}>
      <span>{newRect.width} × {newRect.height}px</span></div> : null}
  </div>

  return <section className="comic-workspace" data-comic-active={active ? 'true' : 'false'} aria-label="Comic workspace">
    <header className="comic-toolbar stage-toolbar">
      <div className="stage-title"><strong>{page?.title || chapter?.title || 'Comic'}</strong>
        {page ? <span className="stage-meta">{page.width} × {page.height} · {page.panels.length} panel{page.panels.length === 1 ? '' : 's'}</span> : null}</div>
      <span className="comic-save-state" role="status">{comic.busy ? 'Saving…' : comic.dirty ? 'Unsaved layout' : 'Layout saved'}</span>
      <div className="seg-group" role="group" aria-label="Comic view">
        {(['layout', 'artwork', 'read'] as const).map(mode => <button key={mode} type="button" aria-pressed={view === mode}
          disabled={drawingActive || adding} onClick={() => { void flushDirtyShots().then(() => {
            cancelGesture(); setView(mode); if (mode === 'artwork') setInspector('panel')
          }).catch(reportError) }}>
          {mode === 'layout' ? 'Layout' : mode === 'artwork' ? 'Artwork' : 'Read'}</button>)}
      </div>
      <span className="stage-divider" aria-hidden="true" />
      <button type="button" className="ghost icon-btn" title="Undo" aria-label="Undo" onClick={comic.undo} disabled={disabled || comic.busy || !comic.canUndo}><ArrowCounterClockwise size={16} /></button>
      <button type="button" className="ghost icon-btn" title="Redo" aria-label="Redo" onClick={comic.redo} disabled={disabled || comic.busy || !comic.canRedo}><ArrowClockwise size={16} /></button>
      <button type="button" className="ghost" onClick={() => { void flushDirtyShots().catch(reportError) }} disabled={disabled}>Save layout</button>
      <details className="menu" ref={exportMenuRef}>
        <summary className={'comic-export-trigger' + (disabled || !page ? ' is-disabled' : '')} aria-label="Export this comic">
          <DownloadSimple size={16} />Export<CaretDown size={12} weight="bold" />
        </summary>
        <div className="menu-panel" role="menu">
          <button type="button" role="menuitem" onClick={() => { closeExportMenu(); void exportPage() }} disabled={disabled || !page}>This page as PNG</button>
          <div className="menu-divider" />
          <button type="button" role="menuitem" onClick={() => { closeExportMenu(); void exportPage(true) }} disabled={disabled || !page}>Chapter as ZIP of PNGs</button>
          <button type="button" role="menuitem" onClick={() => { closeExportMenu(); void exportPage(true, 'pdf') }} disabled={disabled || !page}>Chapter as PDF</button>
          <button type="button" role="menuitem" onClick={() => { closeExportMenu(); void exportPage(true, 'cbz') }} disabled={disabled || !page}>Chapter as CBZ</button>
        </div>
      </details>
    </header>
    <aside className="comic-structure">
      <div className="comic-heading"><strong>Chapters & pages</strong><button type="button" disabled={disabled} onClick={() => {
        const key = id()
        comic.edit(document => { document.chapters.push({ id: key, title: `Chapter ${document.chapters.length + 1}`, prompt: '' }); return document })
        setChapterId(key); setPageId('')
      }}>+ Chapter</button></div>
      <label>Chapter<select aria-label="Chapter" value={chapter?.id ?? ''} disabled={disabled} onChange={event => {
        cancelGesture(); setSelection([]); setLetteringId(''); setChapterId(event.target.value); setPageId('')
      }}>{document.chapters.map(chapter => <option key={chapter.id} value={chapter.id}>{chapter.title || 'Untitled chapter'}</option>)}</select></label>
      {chapter ? <label>Chapter title<input value={chapter.title} maxLength={120} disabled={disabled} onChange={event => comic.edit(document => {
        const target = document.chapters.find(item => item.id === chapter.id)
        if (target) target.title = event.target.value
        return document
      })} /></label> : null}
      <div className="comic-add-pages">{(Object.keys(modes) as ComicMode[]).map(mode => <button type="button" key={mode}
        disabled={disabled} onClick={() => addPage(mode)}>+ {modes[mode]}</button>)}</div>
      <ol className="comic-page-list">{pages.map((item, index) => <li key={item.id}><button type="button" disabled={disabled}
        className={page?.id === item.id ? 'is-active' : ''} onClick={() => { cancelGesture(); setSelection([]); setLetteringId(''); setPageId(item.id); setView('layout'); setInspector('page'); setTool('move') }}>
        <span>{String(index + 1).padStart(2, '0')}</span><span>{item.title || 'Untitled page'}<small>{modes[item.mode]} · {item.panels.length} panels</small></span>
        <ComicLayoutPreview width={item.width} height={item.height} panels={item.panels} spread={item.mode === 'spread'} />
      </button></li>)}</ol>
      <label>Reading direction<select value={document.reading_direction} disabled={disabled} onChange={event => comic.edit(document => {
        document.reading_direction = event.target.value as 'ltr' | 'rtl'; return document
      })}><option value="ltr">Left to right</option><option value="rtl">Right to left</option></select></label>
      <details><summary>Shared AI prompt</summary>
        <label>Comic style<textarea value={document.style_prompt} disabled={disabled} maxLength={20000}
          placeholder="Line art, palette, rendering style…" onChange={event => comic.edit(document => {
            document.style_prompt = event.target.value; return document
          })} /></label>
        {chapter ? <label>Chapter prompt<textarea value={chapter.prompt} disabled={disabled} maxLength={20000}
          placeholder="Story context and continuity for this chapter…" onChange={event => comic.edit(document => {
            const target = document.chapters.find(item => item.id === chapter.id)
            if (target) target.prompt = event.target.value
            return document
          })} /></label> : null}
        <p className="comic-hint">Style → chapter → page → panel prompt. Numbered panel order is explicit; changing direction does not reorder your panels.</p>
      </details>
      {comic.dirty ? <button type="button" disabled={comic.busy} onClick={() => { void comic.reload().catch(reportError) }}>Discard draft & reload saved layout</button> : null}
    </aside>
    <PanelResizeHandle panelKey="comic-structure" label="Resize Comic pages" edge="right" className="comic-structure-resize"
      host=".comic-workspace" target=".comic-structure" width={{ property: '--comic-structure-width', min: 150, max: 500, fraction: 0.28 }} />
    <main className="comic-center">
      {message ? <div className="comic-message" role="status">{message}
        {lastExport ? <button type="button" onClick={() => { void openComicExport(lastExport).catch(reportError) }}>Open export</button> : null}</div> : null}
      {page && view === 'layout' ? <div className="comic-tools" role="group" aria-label="Panel design tools">
        <div className="seg-group comic-tool-group">
          <button type="button" className="icon-btn" aria-pressed={tool === 'move'} aria-label="Select, move and resize"
            disabled={disabled} title="Select, move and resize (V)" onClick={() => setTool('move')}><Cursor size={16} /></button>
          <button type="button" className="icon-btn" aria-pressed={tool === 'draw'} aria-label="Draw panel"
            disabled={disabled} title="Draw a rectangular panel (R)" onClick={() => setTool('draw')}><BoundingBox size={16} /></button>
          {(['shape', 'knife', 'crop'] as const).map(next => {
            const label = next === 'shape' ? 'Edit vertices' : next === 'knife' ? 'Knife (K)' : 'Crop / pan artwork (C)'
            const Icon = next === 'shape' ? Polygon : next === 'knife' ? Knife : Crop
            return <button type="button" key={next} className="icon-btn" aria-pressed={tool === next} aria-label={label} title={label}
              disabled={disabled || !panel || panel.locked} onClick={() => { setLetteringId(''); setInspector('panel'); setTool(next) }}><Icon size={16} /></button>
          })}
        </div>
        <button type="button" className="ghost" disabled={disabled} onClick={() => addLettering('speech')}><ChatCircleText size={16} />Dialogue</button>
        <span className="stage-divider" aria-hidden="true" />
        <button type="button" className="ghost" aria-pressed={snap} disabled={disabled} title="Snap to grid"
          onClick={() => setSnap(value => !value)}><GridFour size={16} />Snap {comicGridSize}</button>
        <button type="button" className="ghost" aria-pressed={guides} title="Safe-area and binding guides" onClick={() => setGuides(value => !value)}><FrameCorners size={16} />Guides</button>
        <button type="button" className="ghost" disabled={disabled || !page.panels.length} onClick={() => { setSelection(page.panels.map(item => item.id)); setLetteringId(''); setInspector('panel') }}>Select all</button>
        <label>Zoom<select aria-label="Canvas zoom" value={zoom} onChange={event => setZoom(Number(event.target.value))}>
          <option value={.75}>75% of fit</option><option value={1}>Fit</option><option value={1.5}>150% of fit</option><option value={2}>200% of fit</option>
        </select></label>
      </div> : null}
      {page && view === 'read' ? <div className="comic-tools"><label>Reader width<select aria-label="Comic reader width" value={readerWidth} onChange={event => setReaderWidth(Number(event.target.value))}>
        <option value={360}>Phone · 360px</option><option value={640}>Tablet · 640px</option><option value={960}>Desktop · 960px</option></select></label></div> : null}
      {!page ? <div className="comic-empty"><h2>Plan a comic chapter</h2><p>Add a page, double-page spread, or long scroll section.</p>
        <p>Draw your panel boundaries, place artwork and arrange dialogue.</p></div> : view === 'artwork' ?
        panel ? <CanvasBoard panelsInitiallyOpen={false} panelSize={{ width: panel.width, height: panel.height }} /> :
          <div className="comic-empty"><p>Select a panel in reading order to edit its artwork.</p></div> :
        <div ref={readingSurfaceRef} className={`comic-reading-surface ${view === 'read' ? 'is-reading' : ''}`}>
          {(view === 'read' ? pages : [page]).map(item => <div key={item.id} className="comic-page-host"
            style={view === 'layout' ? { width: `${zoom * 100}%`, maxWidth: `${960 * zoom}px` } : { maxWidth: `${readerWidth}px` }}>
            {view !== 'read' ? <div className="comic-page-caption">{item.title} · {item.width} × {item.height}px
              <span>{document.reading_direction === 'rtl' ? '← Right to left' : 'Left to right →'}</span></div> : null}
            {renderPage(item)}
            {view === 'layout' ? <footer className="comic-canvas-footer"><span>{tool === 'draw' ? 'Drag to draw a panel · Esc to select' :
              tool === 'knife' ? 'Drag a cut across the selected panel · Esc to cancel' : tool === 'shape' ? 'Drag a vertex to reshape the panel' :
              tool === 'crop' ? 'Drag artwork inside the fixed panel · Adjust zoom in Panel' : `${item.panels.length} panels · Drag to move · Handles to resize`}</span>
              <span>{dragPreview ? `${dragPreview.width} × ${dragPreview.height}px` : `${item.width} × ${item.height}px`}</span></footer> : null}
          </div>)}
        </div>}
    </main>
    <PanelResizeHandle panelKey="comic-properties" label="Resize Comic properties" edge="left" className="comic-properties-resize"
      host=".comic-workspace" target=".comic-properties" width={{ property: '--comic-properties-width', min: 240, max: 650, fraction: 0.4 }} />
    <PanelResizeHandle panelKey="comic-properties" label="Resize Comic properties height" edge="top" className="comic-properties-height-resize"
      host=".comic-workspace" target=".comic-properties" height={{ property: '--comic-properties-height', min: 160, max: 520, fraction: 0.55 }} />
    <aside className="comic-properties">
      {page ? <>
        <div className="comic-inspector-tabs tab-row" role="tablist" aria-label="Comic inspector">
          {(['page', 'panel', 'lettering', 'ai'] as const).map(tab => <button key={tab} type="button" role="tab"
            aria-selected={inspector === tab} aria-controls={`comic-inspector-${tab}`} id={`comic-tab-${tab}`}
            className={inspector === tab ? 'is-active' : ''} disabled={drawingActive || (tab === 'ai' && !panel)}
            onClick={() => setInspector(tab)}>{tab === 'ai' ? 'AI' : tab === 'page' ? 'Page' : tab === 'lettering' ? 'Lettering' : 'Panel'}</button>)}
        </div>
        {inspector === 'page' ? <div role="tabpanel" id="comic-inspector-page" aria-labelledby="comic-tab-page">
        <div className="comic-heading"><strong>{modes[page.mode]} layout</strong></div>
        <label>Page title<input value={page.title} disabled={disabled} maxLength={120} onChange={event => changePage(page => { page.title = event.target.value })} /></label>
        <div className="comic-field-row">
          <NumberField label="Width (px)" value={page.width} min={Math.max(64, page.gutter + 1, ...[...page.panels, ...(page.lettering ?? [])].map(item => item.x + item.width))}
            max={Math.min(8192, Math.floor(64000000 / page.height))} disabled={disabled} onChange={width => changePage(page => { page.width = width })} />
          <NumberField label="Height (px)" value={page.height} min={Math.max(64, ...[...page.panels, ...(page.lettering ?? [])].map(item => item.y + item.height))}
            max={Math.min(32000, Math.floor(64000000 / page.width))} disabled={disabled} onChange={height => changePage(page => { page.height = height })} />
        </div>
        <NumberField label={page.mode === 'spread' ? 'Binding / panel gutter (px)' : 'Panel spacing (px)'} value={page.gutter} max={Math.min(512, page.width - 1)}
          disabled={disabled} onChange={gutter => changePage(page => { page.gutter = gutter })} />
        <label>Canvas type<select value={page.mode} disabled={disabled} onChange={event => changePage(page => { page.mode = event.target.value as ComicMode })}>
          {(Object.keys(modes) as ComicMode[]).map(mode => <option key={mode} value={mode}>{modes[mode]}</option>)}</select></label>
        <div className="comic-field-row"><NumberField label="Safe margin (px)" value={page.safe_margin ?? 32}
          max={Math.min(512, Math.floor(Math.min(page.width, page.height) / 2))} disabled={disabled} onChange={value => changePage(page => { page.safe_margin = value })} />
          <label>Paper<input type="color" value={page.background ?? '#ffffff'} disabled={disabled} onChange={event => changePage(page => { page.background = event.target.value })} /></label></div>
        {page.mode === 'scroll' ? <><div className="comic-heading"><strong>Scroll pacing</strong></div>
          <NumberField label="Breathing room (px)" value={scrollSpacing} min={16} max={2000} disabled={disabled} onChange={setScrollSpacing} />
          <div className="comic-field-row">{[1, -1].map(sign => <button key={sign} type="button" disabled={disabled || !panel || !shiftScrollSpace(page, panel.y + panel.height, sign * scrollSpacing)}
            onClick={() => { if (panel) { const changed = shiftScrollSpace(page, panel.y + panel.height, sign * scrollSpacing); if (changed) changePage(page => Object.assign(page, changed)) } }}>
            {sign > 0 ? 'Insert space below panel' : 'Remove space below panel'}</button>)}</div></> : null}
        <details><summary>Page prompt</summary><label>Page instructions<textarea value={page.prompt} maxLength={20000} disabled={disabled} onChange={event => changePage(page => { page.prompt = event.target.value })} /></label></details>
        <div className="comic-heading"><strong>Design on the canvas</strong></div>
        <p className="comic-hint">Draw each panel directly, then move, resize or split it. Pages start blank so you control the composition and pacing.</p>
        <button type="button" disabled={disabled} onClick={() => { setTool('draw'); setView('layout') }}>Draw a panel</button>
        <div className="comic-heading"><strong>Page actions</strong></div>
        <div className="comic-field-row"><button type="button" disabled={disabled || pages[0]?.id === page.id} onClick={() => comic.edit(document => {
          const index = document.pages.findIndex(item => item.id === page.id)
          const previous = document.pages.findIndex(item => item.id === pages[pages.findIndex(item => item.id === page.id) - 1]?.id)
          if (previous >= 0) [document.pages[index], document.pages[previous]] = [document.pages[previous], document.pages[index]]
          return document
        })}>Move page earlier</button>
          <button type="button" disabled={disabled} onClick={() => comic.edit(document => { document.pages = document.pages.filter(item => item.id !== page.id); return document })}>Remove page</button></div>
        <button type="button" disabled={disabled} onClick={() => setInspector('panel')}>Manage panels</button>
        <button type="button" disabled={disabled || pages.at(-1)?.id === page.id} onClick={() => comic.edit(document => {
          const index = document.pages.findIndex(item => item.id === page.id)
          const next = document.pages.findIndex(item => item.id === pages[pages.findIndex(item => item.id === page.id) + 1]?.id)
          if (next >= 0) [document.pages[index], document.pages[next]] = [document.pages[next], document.pages[index]]
          return document
        })}>Move page later</button>
        <label>Move to chapter<select value={page.chapter_id} disabled={disabled} onChange={event => {
          const chapterKey = event.target.value; changePage(page => { page.chapter_id = chapterKey }); setChapterId(chapterKey)
        }}>{document.chapters.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        </div> : inspector === 'lettering' ? <div role="tabpanel" id="comic-inspector-lettering" aria-labelledby="comic-tab-lettering">
          <div className="comic-heading"><strong>Dialogue & captions</strong></div>
          <div className="comic-field-row">{(['speech', 'caption', 'text'] as const).map(kind => <button type="button" key={kind} disabled={disabled} onClick={() => addLettering(kind)}>
            + {kind === 'speech' ? 'Bubble' : kind === 'caption' ? 'Caption' : 'Text'}</button>)}</div>
          <ol className="comic-panel-list">{page.lettering?.map((item, i) => <li key={item.id}><button type="button" className={letteringId === item.id ? 'is-active' : ''}
            onClick={() => setLetteringId(item.id)}>{i + 1}. {item.text || 'Empty text'}</button></li>)}</ol>
          {lettering ? <>
            <label>Text<textarea value={lettering.text} maxLength={2000} disabled={disabled} onChange={event => changeLettering(item => { item.text = event.target.value })} /></label>
            <label>Shape<select value={lettering.kind} disabled={disabled} onChange={event => changeLettering(item => { item.kind = event.target.value as ComicLettering['kind'] })}>
              <option value="speech">Speech bubble</option><option value="caption">Caption box</option><option value="text">Plain text / SFX</option></select></label>
            <div className="comic-field-row"><NumberField label="Lettering X" value={lettering.x} max={page.width - lettering.width} disabled={disabled} onChange={x => changeLettering(item => { item.x = x })} />
              <NumberField label="Lettering Y" value={lettering.y} max={page.height - lettering.height} disabled={disabled} onChange={y => changeLettering(item => { item.y = y })} /></div>
            <div className="comic-field-row"><NumberField label="Lettering width" value={lettering.width} min={16} max={page.width - lettering.x} disabled={disabled} onChange={width => changeLettering(item => { item.width = width })} />
              <NumberField label="Lettering height" value={lettering.height} min={16} max={page.height - lettering.y} disabled={disabled} onChange={height => changeLettering(item => { item.height = height })} /></div>
            <div className="comic-field-row"><NumberField label="Font size" value={lettering.font_size} min={8} max={160} disabled={disabled} onChange={size => changeLettering(item => { item.font_size = size })} />
              <NumberField label="Outline width" value={lettering.border} max={12} disabled={disabled} onChange={border => changeLettering(item => { item.border = border })} /></div>
            <label>Writing<select value={lettering.vertical ? 'vertical' : 'horizontal'} disabled={disabled} onChange={event => changeLettering(item => { item.vertical = event.target.value === 'vertical' })}>
              <option value="horizontal">Horizontal</option><option value="vertical">Vertical · right to left</option></select></label>
            <div className="comic-field-row"><label>Ink<input type="color" value={lettering.color} disabled={disabled} onChange={event => changeLettering(item => { item.color = event.target.value })} /></label>
              <label>Fill<input type="color" value={lettering.fill} disabled={disabled} onChange={event => changeLettering(item => { item.fill = event.target.value })} /></label></div>
            {lettering.kind === 'speech' ? <NumberField label="Tail position (%)" value={Math.round(lettering.tail * 100)} max={100} disabled={disabled} onChange={value => changeLettering(item => { item.tail = value / 100 })} /> : null}
            {letteringOverflows(lettering) ? <p role="status" className="comic-overflow-warning">Text exceeds this box. Increase the size or reduce the font before exporting.</p> : null}
            <div className="comic-field-row"><button type="button" disabled={disabled} onClick={() => changePage(page => {
              page.lettering!.push({ ...lettering, id: id(), x: Math.min(page.width - lettering.width, lettering.x + 24), y: Math.min(page.height - lettering.height, lettering.y + 24) })
            })}>Duplicate text</button><button type="button" disabled={disabled} onClick={() => changePage(page => { page.lettering = page.lettering?.filter(item => item.id !== lettering.id) })}>Remove text</button></div>
          </> : <p className="comic-hint">Add a bubble, caption or free text. Drag and resize it on the page. Lettering stays editable and exports with the artwork.</p>}
        </div> : <div role="tabpanel" id={`comic-inspector-${inspector}`} aria-labelledby={`comic-tab-${inspector}`}>
        <div className="comic-heading"><strong>{inspector === 'ai' ? 'Panel AI prompt' : 'Panels · reading order'}</strong>
          <span className="comic-hint">{page.panels.length} panels</span></div>
        {inspector === 'panel' ? <>
        {selectedPanels.length > 1 ? <><div className="comic-heading"><strong>{selectedPanels.length} selected</strong></div>
          <div className="comic-alignment-tools">{(['left', 'center-x', 'right', 'top', 'center-y', 'bottom', 'distribute-x', 'distribute-y'] as Alignment[]).map(operation =>
            <button type="button" key={operation} disabled={disabled || selectedPanels.filter(item => !item.locked).length < (operation.startsWith('distribute') ? 3 : 2)}
              onClick={() => alignSelection(operation)}>{operation.replace('center-x', 'Center H').replace('center-y', 'Center V').replace('distribute-x', 'Space H').replace('distribute-y', 'Space V')}</button>)}</div>
          <button type="button" disabled={disabled} onClick={() => changePage(page => {
            const lock = !selectedPanels.every(item => item.locked)
            for (const item of page.panels) if (selectedPanels.some(p => p.id === item.id)) item.locked = lock
          })}>{selectedPanels.every(item => item.locked) ? 'Unlock selection' : 'Lock selection'}</button>
          <p className="comic-hint">Shift/Ctrl click to select panels. Drag together, align or distribute. Locked panels keep their positions.</p></> : null}
        <div className="comic-add-panel"><select aria-label="Board to place" value={selectedBoard?.shot_id ?? ''} disabled={disabled}
          onChange={event => setBoardId(event.target.value)}>{boards.map(shot => <option key={shot.shot_id} value={shot.shot_id}>{shotDisplayLabel(shot)}</option>)}</select>
          <button type="button" disabled={disabled || !selectedBoard || !nextPlacement} onClick={() => selectedBoard && placeBoard(selectedBoard.shot_id)}>Place board</button>
          <button type="button" disabled={disabled || !nextPlacement} onClick={() => { void newPanel() }}>+ New panel</button></div>
        {!nextPlacement ? <p className="comic-hint">No room for another panel. Increase page height, reduce spacing, or add a page.</p> : null}
        </> : null}
        <ol className="comic-panel-list">{page.panels.map((item, index) => <li key={item.id}><button type="button" disabled={disabled}
          className={item.shot_id === selectedShotId ? 'is-active' : ''} onClick={() => { setSelection([item.id]); setLetteringId(''); setSelectedShotId(item.shot_id) }}>
          {index + 1}. {shotDisplayLabel(shotsById.get(item.shot_id) ?? { shot_id: item.shot_id, title: '', scene: '', sequence: '' })}
        </button></li>)}</ol>
        {panel ? <>
          <div className="comic-selected-panel"><strong>Panel {page.panels.findIndex(item => item.id === panel.id) + 1}</strong>
            <span>{shot ? shotDisplayLabel(shot) : ''}</span></div>
          {inspector === 'panel' ? <>
          <button type="button" disabled={disabled} aria-pressed={panel.locked ?? false} onClick={() => changePanel(panel => { panel.locked = !panel.locked })}>
            {panel.locked ? 'Unlock panel' : 'Lock panel'}</button>
          <fieldset className="comic-panel-edit-fields" disabled={disabled || panel.locked}>
          <div className="comic-field-row"><NumberField label="X" value={panel.x} max={page.width - panel.width} disabled={disabled} onChange={x => changePanel(panel => { panel.x = x })} />
            <NumberField label="Y" value={panel.y} max={page.height - panel.height} disabled={disabled} onChange={y => changePanel(panel => { panel.y = y })} /></div>
          <div className="comic-field-row"><NumberField label="Panel width" value={panel.width} min={16} max={page.width - panel.x} disabled={disabled} onChange={width => changePanel(panel => { panel.width = width })} />
            <NumberField label="Panel height" value={panel.height} min={16} max={page.height - panel.y} disabled={disabled} onChange={height => changePanel(panel => { panel.height = height })} /></div>
          <div className="comic-field-row"><label>Artwork fit<select value={panel.fit} disabled={disabled} onChange={event => changePanel(panel => { panel.fit = event.target.value as 'contain' | 'cover' })}>
            <option value="contain">Contain · keep whole image</option><option value="cover">Cover · crop to panel</option></select></label>
            <NumberField label="Border (px)" value={panel.border} max={32} disabled={disabled} onChange={border => changePanel(panel => { panel.border = border })} /></div>
          <div className="comic-field-row"><NumberField label="Artwork zoom (%)" value={Math.round((panel.image_scale ?? 1) * 100)} min={25} max={800} disabled={disabled} onChange={value => changePanel(panel => { panel.image_scale = value / 100 })} />
            <button type="button" disabled={disabled} onClick={() => changePanel(panel => { panel.image_x = 0; panel.image_y = 0; panel.image_scale = 1 })}>Reset crop</button></div>
          <div className="comic-field-row"><NumberField label="Artwork X (%)" value={Math.round((panel.image_x ?? 0) * 100)} min={-200} max={200} disabled={disabled} onChange={value => changePanel(panel => { panel.image_x = value / 100 })} />
            <NumberField label="Artwork Y (%)" value={Math.round((panel.image_y ?? 0) * 100)} min={-200} max={200} disabled={disabled} onChange={value => changePanel(panel => { panel.image_y = value / 100 })} /></div>
          <button type="button" disabled={disabled} onClick={() => changePanel(panel => { panel.points = null })}>Reset rectangular boundary</button>
          <div className="comic-field-row"><button type="button" disabled={disabled || !splitPanel(panel, 'horizontal', page.gutter, document.reading_direction)}
            onClick={() => { void splitSelected('horizontal') }}>Split horizontal</button>
            <button type="button" disabled={disabled || !splitPanel(panel, 'vertical', page.gutter, document.reading_direction)}
              onClick={() => { void splitSelected('vertical') }}>Split vertical</button></div>
          <button type="button" disabled={disabled} onClick={() => { void duplicatePanel() }}>Duplicate panel & board</button>
          <p className="comic-hint">Split keeps the original board in the first half and creates a blank board for the second. The page spacing controls the gap.</p>
          <div className="comic-field-row"><button type="button" disabled={disabled || panel.id === page.panels[0]?.id} onClick={() => movePanel(-1)}>Read earlier</button>
            <button type="button" disabled={disabled || panel.id === page.panels.at(-1)?.id} onClick={() => movePanel(1)}>Read later</button>
            <button type="button" disabled={disabled} onClick={removePanel}>Unplace</button></div>
          </fieldset>
          <p className="comic-hint">Drag to position; use the eight handles to resize. Unplacing keeps artwork and prompts in Boards. Spread panels may cross the binding guide.</p>
          <div className="comic-field-row"><button type="button" disabled={disabled} onClick={() => {
            void flushDirtyShots().then(() => { setView('artwork'); setInspector('panel') }).catch(reportError)
          }}>Edit artwork</button><button type="button" onClick={() => setInspector('ai')}>Panel prompt</button></div>
          <div className="comic-heading"><strong>Panel details & continuity</strong></div>
          <ShotInspector />
          </> : <>
          {shot && promptConfig ? <>
            <label>Prompt mode<select value={promptConfig.mode} disabled={disabled} onChange={event => {
              editShotField(shot.shot_id, 'prompt_config', { ...promptConfig, mode: event.target.value as 'auto' | 'manual' })
              setPromptPreview(null)
            }}><option value="auto">Auto · from panel details</option><option value="manual">Manual · write panel instructions</option></select></label>
            {promptConfig.mode === 'manual' ? <label>Panel prompt<textarea value={promptConfig.manual_prompt} disabled={disabled}
              placeholder="Describe this panel’s subjects, action and composition…" onChange={event => {
                editShotField(shot.shot_id, 'prompt_config', { ...promptConfig, manual_prompt: event.target.value }); setPromptPreview(null)
              }} /></label> : null}
            <label>Extra instructions<textarea value={promptConfig.prompt_extra} disabled={disabled} onChange={event => {
              editShotField(shot.shot_id, 'prompt_config', { ...promptConfig, prompt_extra: event.target.value }); setPromptPreview(null)
            }} /></label>
            <label>Negative prompt<textarea value={promptConfig.negative_prompt} disabled={disabled} onChange={event => {
              editShotField(shot.shot_id, 'prompt_config', { ...promptConfig, negative_prompt: event.target.value }); setPromptPreview(null)
            }} /></label>
            <NumberField label="Variants" value={promptConfig.variant_count} min={1} max={8} disabled={disabled} onChange={variant_count => {
              editShotField(shot.shot_id, 'prompt_config', { ...promptConfig, variant_count }); setPromptPreview(null)
            }} />
            <button type="button" disabled={disabled} onClick={() => {
              void flushDirtyShots().then(() => previewComicPrompt(shot.shot_id)).then(request => {
                setPromptPreview({ shotId: shot.shot_id, text: request.prompt.compiled_prompt + '\n\nNEGATIVE: ' + request.prompt.negative_prompt })
              }).catch(reportError)
            }}>Preview compiled prompt</button>
            {promptPreview?.shotId === shot.shot_id ? <label>Last saved prompt preview<textarea readOnly value={promptPreview.text} className="comic-prompt-preview" /></label> : null}
            <p className="comic-hint">Generation uses this panel’s {panel.width} × {panel.height}px. Open Artwork for drawing, reference layers, queue, and results.</p>
          </> : null}
          </>}
        </> : <p className="comic-hint">Select a panel to edit geometry, dialogue, prompt, references, and continuity.</p>}
        </div>}
      </> : null}
    </aside>
  </section>
}
