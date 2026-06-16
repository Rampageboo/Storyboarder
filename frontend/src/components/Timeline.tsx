import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { addShot, deleteShot, moveShotDown, moveShotUp } from '../api'
import { useProject } from '../state/ProjectContext'
import './Timeline.css'

const TIMELINE_LAYOUT = {
  gap: 6,
  insertWidth: 22,
  thumbHeight: 56,
  minShotWidth: 56,
  maxShotWidth: 200,
  bufferPx: 360,
}

type TimelineItem =
  | { type: 'shot'; shotId: string; index: number; left: number; width: number }
  | { type: 'insert'; afterShotId: string; left: number; width: number }

function timelineBoardWidth(canvasWidth = 1920, canvasHeight = 1080) {
  const canvasW = Math.max(1, Number(canvasWidth) || 1920)
  const canvasH = Math.max(1, Number(canvasHeight) || 1080)
  const width = Math.round(TIMELINE_LAYOUT.thumbHeight * (canvasW / canvasH))
  return Math.min(TIMELINE_LAYOUT.maxShotWidth, Math.max(TIMELINE_LAYOUT.minShotWidth, width))
}

function buildTimelineLayout(shotIds: string[], canvasWidth: number, canvasHeight: number) {
  const items: TimelineItem[] = []
  let left = 0
  const width = timelineBoardWidth(canvasWidth, canvasHeight)
  for (let index = 0; index < shotIds.length; index += 1) {
    const shotId = shotIds[index]
    items.push({ type: 'shot', shotId, index, left, width })
    left += width + TIMELINE_LAYOUT.gap
    items.push({ type: 'insert', afterShotId: shotId, left, width: TIMELINE_LAYOUT.insertWidth })
    left += TIMELINE_LAYOUT.insertWidth + TIMELINE_LAYOUT.gap
  }
  return { items, totalWidth: Math.max(0, left - TIMELINE_LAYOUT.gap) }
}

function computeVisibleTimelineItems(layout: TimelineItem[], scrollLeft: number, viewportWidth: number, activeShotId = '') {
  const buffer = TIMELINE_LAYOUT.bufferPx
  const viewStart = Math.max(0, scrollLeft - buffer)
  const viewEnd = scrollLeft + Math.max(viewportWidth, 320) + buffer
  const inView = (item: TimelineItem) => item.left + item.width >= viewStart && item.left <= viewEnd
  const visible = new Map<string, TimelineItem>()
  for (const item of layout) {
    if (inView(item)) visible.set(`${item.type}:${item.left}`, item)
  }
  if (activeShotId) {
    const activeIndex = layout.findIndex((item) => item.type === 'shot' && item.shotId === activeShotId)
    if (activeIndex >= 0) {
      for (let index = Math.max(0, activeIndex - 2); index <= Math.min(layout.length - 1, activeIndex + 2); index += 1) {
        const item = layout[index]
        visible.set(`${item.type}:${item.left}`, item)
      }
    }
  }
  return [...visible.values()].sort((a, b) => a.left - b.left)
}

export function Timeline() {
  const { project, selectedShotId, setSelectedShotId, setProject, flushDirtyShots } = useProject()
  const [busy, setBusy] = useState(false)
  const stripRef = useRef<HTMLDivElement | null>(null)
  const [scrollLeft, setScrollLeft] = useState(0)
  const [viewportWidth, setViewportWidth] = useState(0)

  const shots = project?.shots || []
  const selectedIndex = useMemo(() => shots.findIndex((s) => s.shot_id === selectedShotId), [shots, selectedShotId])
  const shotIdToTitle = useMemo(() => new Map(shots.map((s) => [s.shot_id, s.title || s.shot_id])), [shots])

  const layout = useMemo(() => {
    const canvasW = Number(project?.settings?.canvas_width || 1920)
    const canvasH = Number(project?.settings?.canvas_height || 1080)
    return buildTimelineLayout(
      shots.map((s) => s.shot_id),
      canvasW,
      canvasH,
    )
  }, [shots, project?.settings?.canvas_width, project?.settings?.canvas_height])

  const visibleItems = useMemo(
    () => computeVisibleTimelineItems(layout.items, scrollLeft, viewportWidth, selectedShotId || ''),
    [layout.items, scrollLeft, viewportWidth, selectedShotId],
  )

  useEffect(() => {
    const el = stripRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setViewportWidth(el.clientWidth || 0)
    })
    ro.observe(el)
    setViewportWidth(el.clientWidth || 0)
    return () => ro.disconnect()
  }, [])

  const handleAdd = useCallback(async () => {
    if (!project) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const afterId = selectedShotId || undefined
      const payload = await addShot(afterId ? { after_shot_id: afterId } : {})
      setProject(payload)
      const nextId = payload.shots[Math.min(Math.max(selectedIndex + 1, 0), payload.shots.length - 1)]?.shot_id
      if (nextId) setSelectedShotId(nextId)
    } catch {
      // Aborted (flush failure already surfaced) or structural op failed; leave state unchanged.
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, selectedIndex, setProject, setSelectedShotId, flushDirtyShots])

  const handleInsertAfter = useCallback(
    async (afterShotId: string) => {
      if (!project) return
      setBusy(true)
      try {
        await flushDirtyShots()
        const payload = await addShot({ after_shot_id: afterShotId })
        setProject(payload)
        const idx = payload.shots.findIndex((s) => s.shot_id === afterShotId)
        const nextId = payload.shots[Math.min(idx + 1, payload.shots.length - 1)]?.shot_id
        if (nextId) setSelectedShotId(nextId)
      } catch {
        // Aborted (flush failure already surfaced) or structural op failed; leave state unchanged.
      } finally {
        setBusy(false)
      }
    },
    [project, setProject, setSelectedShotId, flushDirtyShots],
  )

  const handleDelete = useCallback(async () => {
    if (!project || !selectedShotId) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await deleteShot(selectedShotId)
      setProject(payload)
      const nextIndex = Math.min(selectedIndex, payload.shots.length - 1)
      const nextId = payload.shots[nextIndex]?.shot_id ?? null
      setSelectedShotId(nextId)
    } catch {
      // Aborted (flush failure already surfaced) or structural op failed; leave state unchanged.
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, selectedIndex, setProject, setSelectedShotId, flushDirtyShots])

  const handleMoveUp = useCallback(async () => {
    if (!project || !selectedShotId) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await moveShotUp(selectedShotId)
      setProject(payload)
      setSelectedShotId(selectedShotId)
    } catch {
      // Aborted (flush failure already surfaced) or structural op failed; leave state unchanged.
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, setProject, setSelectedShotId, flushDirtyShots])

  const handleMoveDown = useCallback(async () => {
    if (!project || !selectedShotId) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await moveShotDown(selectedShotId)
      setProject(payload)
      setSelectedShotId(selectedShotId)
    } catch {
      // Aborted (flush failure already surfaced) or structural op failed; leave state unchanged.
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, setProject, setSelectedShotId, flushDirtyShots])

  return (
    <div className="timeline">
      <div className="timeline-header">
        <div className="timeline-title">Timeline</div>
        <div className="timeline-actions">
          <button type="button" onClick={handleAdd} disabled={!project || busy}>
            + Add
          </button>
          <button type="button" onClick={handleDelete} disabled={!project || !selectedShotId || busy}>
            Delete
          </button>
          <button
            type="button"
            onClick={handleMoveUp}
            disabled={!project || !selectedShotId || selectedIndex <= 0 || busy}
            title="Move up"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={handleMoveDown}
            disabled={!project || !selectedShotId || selectedIndex < 0 || selectedIndex >= shots.length - 1 || busy}
            title="Move down"
          >
            ↓
          </button>
        </div>
      </div>

      <div
        ref={stripRef}
        className="timeline-strip"
        onScroll={(e) => setScrollLeft((e.target as HTMLDivElement).scrollLeft)}
      >
        <div className="timeline-track" style={{ width: layout.totalWidth }}>
          {visibleItems.map((item) => {
            if (item.type === 'insert') {
              return (
                <button
                  key={`insert:${item.left}`}
                  type="button"
                  className="timeline-insert"
                  style={{ left: item.left, width: item.width }}
                  disabled={!project || busy}
                  title="Insert shot here"
                  onClick={() => void handleInsertAfter(item.afterShotId)}
                >
                  +
                </button>
              )
            }

            const title = shotIdToTitle.get(item.shotId) || item.shotId
            const isSelected = selectedShotId === item.shotId
            return (
              <button
                key={`shot:${item.shotId}:${item.left}`}
                type="button"
                className={`timeline-shot ${isSelected ? 'is-selected' : ''}`}
                style={{ left: item.left, width: item.width }}
                onClick={() => setSelectedShotId(item.shotId)}
              >
                <div className="timeline-shot-title">{title}</div>
                <div className="timeline-shot-sub">#{item.index + 1}</div>
              </button>
            )
          })}
          {!project ? <div className="timeline-empty">No project open</div> : null}
        </div>
      </div>
    </div>
  )
}

