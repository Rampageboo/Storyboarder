import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  ArrowBendDownRight, CaretRight, ChatCircle, FilmStrip, GitBranch, PencilSimple, Play, Plus,
  SkipBack, SkipForward, X,
} from '@phosphor-icons/react'
import { useProject } from '../state/useProject'
import type { Shot } from '../types'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { statusStyle } from '../utils/status'
import { shotDisplayVersion, shotHasBoardBackground, shotHasCodexLayer, shotShouldOverlayPreview } from '../utils/shotPreview'
import { AdvancedPanel } from './AdvancedPanel'
import { BoardGrid } from './BoardGrid'
import { BoardStrip } from './BoardStrip'
import { BulkBoardActions } from './BulkBoardActions'
import { CanvasBoard } from './CanvasBoard'
import { NeighborContext } from './NeighborContext'
import { ShotInspector } from './ShotInspector'
import { ShotThumb } from './ShotThumb'
import { StoryMap } from './StoryMap'
import { AnimaticPlayer } from './AnimaticPlayer'
import { PanelResizeHandle } from './PanelResizeHandle'
import './StoryWorkspace.css'

type StoryView = 'map' | 'draw' | 'play' | 'all'
type RouteDialog = 'branch' | 'rename' | 'join'

function duration(shot: Shot): number {
  const seconds = Number(shot.duration_seconds)
  return Number.isFinite(seconds) && seconds > 0 ? seconds : 3
}

function clock(seconds: number): string {
  const tenths = Math.max(0, Math.round(seconds * 10))
  const whole = Math.floor(tenths / 10)
  return Math.floor(whole / 60) + ':' + String(whole % 60).padStart(2, '0') + '.' + (tenths % 10)
}

function BoardVisual({ shot, epoch, index = 0 }: { shot: Shot; epoch: number; index?: number }) {
  return <ShotThumb shotId={shot.shot_id} version={shotDisplayVersion(shot, epoch, index)}
    hasImage={shotShouldOverlayPreview(shot)} hasBg={shotHasBoardBackground(shot)} hasCodex={shotHasCodexLayer(shot)} />
}

function RouteEditor({
  mode, routeName, fromTitle, availableShots, busy, onClose, onSubmit,
}: {
  mode: RouteDialog
  routeName: string
  fromTitle: string
  availableShots: Shot[]
  busy: boolean
  onClose: () => void
  onSubmit: (value: string) => Promise<void>
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [value, setValue] = useState(mode === 'rename' ? routeName : mode === 'join' ? availableShots[0]?.shot_id ?? '' : '')
  const [error, setError] = useState('')
  const title = mode === 'branch' ? 'Create a story branch' : mode === 'rename' ? 'Rename route' : 'Join an existing board'
  useEffect(() => {
    const dialog = dialogRef.current
    dialog?.showModal()
    return () => dialog?.close()
  }, [])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !value.trim()) return
    setError('')
    try { await onSubmit(value.trim()) } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The route could not be saved. Please try again.')
    }
  }
  return (
    <dialog ref={dialogRef} className="story-route-dialog" aria-labelledby="story-route-dialog-title"
      onCancel={event => { event.preventDefault(); if (!busy) onClose() }}>
      <form onSubmit={event => { void submit(event) }}>
        <div className="story-dialog-heading"><h2 id="story-route-dialog-title">{title}</h2>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close dialog"><X size={18} /></button></div>
        {mode === 'branch' ? <p>Share the current route up to <strong>{fromTitle || 'its beginning'}</strong>, then develop a different continuation. Shared boards remain the same board on every route.</p> : null}
        {mode === 'join' ? <p>Append a shared board after the end of <strong>{routeName}</strong>. This creates a join without copying the board or replacing existing route content.</p> : null}
        <label htmlFor="story-route-value">{mode === 'join' ? 'Board to join' : 'Route name'}</label>
        {mode === 'join' ? <select id="story-route-value" autoFocus value={value} onChange={event => setValue(event.target.value)} disabled={busy}>
          {availableShots.map(shot => <option key={shot.shot_id} value={shot.shot_id}>{shotDisplayLabel(shot)}</option>)}
        </select> : <input id="story-route-value" autoFocus required maxLength={120} value={value}
          placeholder="e.g. Through the station" onChange={event => setValue(event.target.value)} disabled={busy} />}
        {mode === 'join' ? <small>The joined board becomes this route’s ending. You can append more boards afterwards. A join that creates a cycle will be rejected.</small> : null}
        {error ? <p className="story-dialog-error" role="alert">{error}</p> : null}
        <div className="story-dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="primary" disabled={busy || !value.trim()}>{busy ? 'Saving…' : mode === 'branch' ? 'Create branch' : mode === 'join' ? 'Join board' : 'Save name'}</button>
        </div>
      </form>
    </dialog>
  )
}

const VIEW_LABELS: { view: StoryView; label: string; title: string }[] = [
  { view: 'draw', label: 'Board', title: 'Edit the selected board' },
  { view: 'play', label: 'Play', title: 'Play the current route as an animatic' },
  { view: 'map', label: 'Map', title: 'Story map: routes, branches and joins' },
  { view: 'all', label: 'All', title: 'Every board in the project, with bulk tools' },
]

interface OutlineGroup { key: string; label: string; shots: { shot: Shot; index: number }[] }

function outlineGroups(shots: Shot[]): OutlineGroup[] {
  const groups: OutlineGroup[] = []
  shots.forEach((shot, index) => {
    const label = shot.scene?.trim() || 'No scene'
    const last = groups[groups.length - 1]
    if (last && last.label === label) last.shots.push({ shot, index })
    else groups.push({ key: `${groups.length}:${label}`, label, shots: [{ shot, index }] })
  })
  return groups
}

function StoryNavigator({
  shots, selectedShotId, disabled, onChoose, onOpenMap, routeList,
}: {
  shots: Shot[]
  selectedShotId: string | null
  disabled: boolean
  onChoose: (shotId: string) => void
  onOpenMap: () => void
  routeList: ReactNode
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())
  const groups = useMemo(() => outlineGroups(shots), [shots])
  const reviewCount = shots.filter(shot => String(shot.status).toLowerCase() === 'review').length
  const openNotes = shots.reduce((sum, shot) => sum + (shot.comments ?? []).filter(comment => !comment.resolved).length, 0)
  const toggle = (key: string) => setCollapsed(current => {
    const next = new Set(current)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })

  return (
    <aside className="story-nav" aria-label="Story navigator">
      {routeList}
      <div className="story-nav-heading">
        <span className="section-label">Outline</span>
        <button type="button" className="ghost story-nav-link" onClick={onOpenMap}>Story map</button>
      </div>
      <div className="story-outline">
        {groups.map(group => {
          const open = !collapsed.has(group.key)
          return (
            <div key={group.key} className="story-outline-group">
              <button type="button" className="story-nav-row is-group" aria-expanded={open} onClick={() => toggle(group.key)}>
                <CaretRight size={12} weight="bold" className="story-outline-caret" />
                <span className="story-nav-row-label">{group.label}</span>
                <span className="story-nav-count">{group.shots.length}</span>
              </button>
              {open ? group.shots.map(({ shot, index }) => (
                <button type="button" key={shot.shot_id + ':' + index}
                  className={'story-nav-row is-shot' + (shot.shot_id === selectedShotId ? ' is-active' : '')}
                  aria-current={shot.shot_id === selectedShotId ? 'true' : undefined}
                  disabled={disabled} onClick={() => onChoose(shot.shot_id)} title={shotDisplayLabel(shot)}>
                  <span className="story-nav-num">{String(index + 1).padStart(2, '0')}</span>
                  <span className="story-nav-row-label">{shotDisplayLabel(shot)}</span>
                  <span className="status-dot" style={statusStyle(shot.status)} title={String(shot.status || 'Draft')} />
                </button>
              )) : null}
            </div>
          )
        })}
        {!shots.length ? <p className="story-empty-note">No boards on this route yet.</p> : null}
      </div>
      {reviewCount || openNotes ? (
        <div className="story-nav-footer">
          {reviewCount ? <span className="status-chip" style={statusStyle('Review')}><span className="status-dot" />Review {reviewCount}</span> : null}
          {openNotes ? <span className="story-nav-notes"><ChatCircle size={13} />{openNotes} open note{openNotes === 1 ? '' : 's'}</span> : null}
        </div>
      ) : null}
    </aside>
  )
}

export function StoryWorkspace({ active = true }: { active?: boolean }) {
  const {
    project, storyGraph, activeRouteShots, selectedShotId, visualEpoch, projectActionBusy,
    drawingActive, reportError, selectStoryShot, setActiveStoryRoute,
    createStoryBranch, updateStoryGraph, addShotAfterSelection,
  } = useProject()
  const [view, setView] = useState<StoryView>('draw')
  const [allView, setAllView] = useState<'grid' | 'strip'>('grid')
  const [dialog, setDialog] = useState<RouteDialog | null>(null)
  const [localBusy, setLocalBusy] = useState(false)
  const actionRef = useRef(false)
  const [dragShotId, setDragShotId] = useState('')
  const stripRef = useRef<HTMLDivElement>(null)
  const projectKey = (project?.project_json_path ?? '') + ':' + (project?.project_path ?? '')
  const activeRoute = storyGraph?.routes.find(route => route.id === storyGraph.active_route_id)
  const routeKey = activeRoute?.id ?? ''
  const selectedIndex = activeRouteShots.findIndex(shot => shot.shot_id === selectedShotId)
  const selectedShot = project?.shots.find(shot => shot.shot_id === selectedShotId)
  const [previousProject, setPreviousProject] = useState(projectKey)
  if (previousProject !== projectKey) {
    setPreviousProject(projectKey)
    setDialog(null)
    setView('draw')
  }
  const disabled = projectActionBusy || localBusy || drawingActive
  const totalDuration = useMemo(() => activeRouteShots.reduce((sum, shot) => sum + duration(shot), 0), [activeRouteShots])
  const selectedStart = useMemo(() => activeRouteShots.slice(0, Math.max(0, selectedIndex)).reduce((sum, shot) => sum + duration(shot), 0),
    [activeRouteShots, selectedIndex])
  const availableJoins = useMemo(() => {
    const existing = new Set(activeRoute?.shot_ids ?? [])
    return project?.shots.filter(shot => !existing.has(shot.shot_id)) ?? []
  }, [project?.shots, activeRoute])

  const runAction = useCallback(async (action: () => Promise<void>): Promise<boolean> => {
    if (actionRef.current || projectActionBusy || drawingActive) return false
    actionRef.current = true
    setLocalBusy(true)
    try { await action(); return true } catch (error) { reportError(error); return false } finally {
      actionRef.current = false
      setLocalBusy(false)
    }
  }, [drawingActive, projectActionBusy, reportError])

  const chooseShot = useCallback((shotId: string, openDrawing = false) => {
    void runAction(async () => {
      await selectStoryShot(shotId)
      if (openDrawing) setView('draw')
    })
  }, [runAction, selectStoryShot])

  const changeView = (next: StoryView) => {
    if (drawingActive && next !== 'draw') return
    if (view === 'all' && next !== 'all' && selectedShotId && selectedIndex < 0) {
      void runAction(async () => {
        await selectStoryShot(selectedShotId)
        setView(next)
      })
      return
    }
    setView(next)
  }

  useEffect(() => {
    const element = stripRef.current?.querySelector<HTMLElement>('[aria-current="step"]')
    if (!element || !stripRef.current) return
    const parent = stripRef.current
    const left = element.offsetLeft
    if (left < parent.scrollLeft) parent.scrollLeft = left - 16
    else if (left + element.offsetWidth > parent.scrollLeft + parent.clientWidth) parent.scrollLeft = left + element.offsetWidth - parent.clientWidth + 16
  }, [selectedShotId, routeKey])

  useEffect(() => {
    const strip = stripRef.current
    if (!strip || !active || view === 'all') return
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY) || strip.scrollWidth <= strip.clientWidth) return
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? strip.clientWidth : 1
      event.preventDefault()
      strip.scrollLeft += event.deltaY * unit
    }
    strip.addEventListener('wheel', onWheel, { passive: false })
    return () => strip.removeEventListener('wheel', onWheel)
  }, [active, view, projectKey])

  const submitDialog = async (value: string) => {
    if (!storyGraph || !activeRoute || actionRef.current || disabled) return
    actionRef.current = true
    setLocalBusy(true)
    try {
      if (dialog === 'branch') await createStoryBranch(value, selectedShotId ?? undefined)
      else if (dialog === 'rename') await updateStoryGraph({
        ...storyGraph, routes: storyGraph.routes.map(route => route.id === activeRoute.id ? { ...route, name: value } : route),
      })
      else if (dialog === 'join') await updateStoryGraph({
        ...storyGraph, routes: storyGraph.routes.map(route => route.id === activeRoute.id ? { ...route, shot_ids: [...route.shot_ids, value] } : route),
      })
      setDialog(null)
    } catch (error) { reportError(error); throw error } finally {
      actionRef.current = false
      setLocalBusy(false)
    }
  }

  const reorderRoute = (sourceId: string, targetId: string) => {
    if (!storyGraph || !activeRoute || sourceId === targetId) return
    const ids = activeRoute.shot_ids.filter(id => id !== sourceId)
    const index = ids.indexOf(targetId)
    if (index < 0 || !activeRoute.shot_ids.includes(sourceId)) return
    ids.splice(index, 0, sourceId)
    void runAction(() => updateStoryGraph({ ...storyGraph,
      routes: storyGraph.routes.map(route => route.id === activeRoute.id ? { ...route, shot_ids: ids } : route) }))
  }

  const moveSelectedLater = () => {
    if (!activeRoute || !storyGraph || !selectedShotId || selectedIndex < 0 || selectedIndex >= activeRouteShots.length - 1) return
    const ids = [...activeRoute.shot_ids]
    const next = ids[selectedIndex + 1]
    ids[selectedIndex + 1] = ids[selectedIndex]
    ids[selectedIndex] = next
    void runAction(() => updateStoryGraph({ ...storyGraph, routes: storyGraph.routes.map(route => route.id === routeKey ? { ...route, shot_ids: ids } : route) }))
  }

  if (!project) return null
  const canvasHidden = view !== 'draw' && !(view === 'all' && allView === 'strip')

  const viewSwitch = (
    <div className="seg-group" role="group" aria-label="Story workspace view">
      {VIEW_LABELS.map(item => (
        <button key={item.view} type="button" title={item.title} aria-pressed={view === item.view}
          disabled={drawingActive && item.view !== 'draw'} onClick={() => changeView(item.view)}>{item.label}</button>
      ))}
    </div>
  )

  const stageTitle = view === 'all' ? (
    <div className="stage-title"><strong>All boards</strong><span className="stage-meta">{project.shots.length} in project</span></div>
  ) : view === 'map' ? (
    <div className="stage-title"><strong>Story map</strong><span className="stage-meta">{storyGraph?.routes.length ?? 0} routes</span></div>
  ) : selectedShot ? (
    <div className="stage-title">
      {selectedShot.scene?.trim() && selectedShot.scene.trim() !== shotDisplayLabel(selectedShot) ? <span className="stage-crumb">{selectedShot.scene.trim()} /</span> : null}
      <strong>{selectedIndex >= 0 ? String(selectedIndex + 1).padStart(2, '0') + ' · ' : ''}{shotDisplayLabel(selectedShot)}</strong>
      <span className="status-chip" style={statusStyle(selectedShot.status)}><span className="status-dot" />{String(selectedShot.status || 'Draft')}</span>
    </div>
  ) : (
    <div className="stage-title"><strong>No board selected</strong></div>
  )

  const stageLead = <>{stageTitle}<div className="stage-spacer" />{viewSwitch}</>

  const routeList = (
    <>
      <div className="story-nav-heading">
        <span className="section-label">Routes</span>
        <div className="story-nav-heading-actions">
          <button type="button" className="ghost icon-btn" title="Branch a new route from the selected board" aria-label="Branch from the selected board"
            disabled={disabled || !activeRoute || !selectedShotId} onClick={() => setDialog('branch')}><GitBranch size={15} /></button>
          <button type="button" className="ghost icon-btn" title="Append an existing board to this route" aria-label="Join an existing board"
            disabled={disabled || !activeRoute || !availableJoins.length} onClick={() => setDialog('join')}><ArrowBendDownRight size={15} /></button>
          <button type="button" className="ghost icon-btn" title="Rename current route" aria-label="Rename current route"
            disabled={disabled || !activeRoute} onClick={() => setDialog('rename')}><PencilSimple size={15} /></button>
        </div>
      </div>
      <div className="story-routes">
        {storyGraph ? storyGraph.routes.map(route => (
          <button key={route.id} type="button"
            className={'story-nav-row is-route' + (route.id === routeKey ? ' is-active' : '')}
            aria-current={route.id === routeKey ? 'true' : undefined}
            disabled={disabled} onClick={() => { if (route.id !== routeKey) void runAction(() => setActiveStoryRoute(route.id)) }}>
            <GitBranch size={15} className="story-route-icon" />
            <span className="story-nav-row-label">{route.name}</span>
            <span className="story-nav-count">{route.shot_ids.length}</span>
          </button>
        )) : <p className="story-empty-note">Story structure is loading.</p>}
      </div>
    </>
  )

  return (
    <section className={'story-workspace' + (view === 'all' ? ' is-all-boards' : '')} data-story-view={view} aria-label="Story workspace">
      <StoryNavigator shots={activeRouteShots} selectedShotId={selectedShotId} disabled={disabled}
        onChoose={id => chooseShot(id)} onOpenMap={() => changeView('map')} routeList={routeList} />

      <main className="story-stage">
        {drawingActive ? <div className="story-drawing-guard notice is-warn" role="status">Save the drawing or close the editor before changing boards.</div> : null}
        {canvasHidden || !selectedShot || view === 'all' ? <div className="stage-toolbar">{stageLead}</div> : null}
        {view === 'all' ? <div className="story-global-actions">
          <BulkBoardActions />
          <div className="story-all-toggle"><span>Global order and bulk tools</span>
            <div className="seg-group">
              <button type="button" aria-pressed={allView === 'grid'} onClick={() => setAllView('grid')}>Grid</button>
              <button type="button" aria-pressed={allView === 'strip'} onClick={() => setAllView('strip')}>Strip</button>
            </div>
          </div>
        </div> : null}
        <div className="story-canvas-host" hidden={canvasHidden}>
          <CanvasBoard panelsInitiallyOpen={false} headerLead={view === 'all' ? undefined : stageLead} />
        </div>
        {view === 'map' ? <div className="story-map-host">{storyGraph ? <StoryMap graph={storyGraph} shots={project.shots}
          selectedShotId={selectedShotId} visualEpoch={visualEpoch} disabled={disabled}
          onSelect={id => chooseShot(id)} onOpen={id => chooseShot(id, true)}
          onUpdate={updateStoryGraph} onError={reportError} /> : <div className="story-empty-note">Story structure is loading.</div>}</div> : null}
        {view === 'play' ? <AnimaticPlayer key={projectKey + ':' + routeKey + ':' + activeRoute?.shot_ids.join('|')}
          shots={activeRouteShots} routeId={routeKey} selectedId={selectedShotId} active={active && !localBusy}
          onSelect={chooseShot} /> : null}
        {view === 'all' && allView === 'grid' ? <div className="story-grid-host"><BoardGrid /></div> : null}
        {view === 'all' && allView === 'strip' ? <div className="story-legacy-strip">
          <PanelResizeHandle panelKey="all-boards-strip" label="Resize Boards strip" edge="top" bounds=".story-stage"
            height={{ property: '--story-all-strip-height', min: 140, max: 600, fraction: 0.6 }} />
          <NeighborContext /><BoardStrip /></div> : null}
        {!project.shots.length ? <div className="story-empty-project">
          <FilmStrip size={30} /><h2>Start with your first board</h2><p>Draw a scene, then branch into other story directions.</p>
          <button type="button" className="primary" disabled={disabled} onClick={() => { void runAction(addShotAfterSelection) }}><Plus size={16} />Add first board</button>
        </div> : null}
      </main>

      <aside className="story-inspector" aria-label="Board inspector">
        {view === 'play' && selectedShot ? <p className="story-play-selection-note">Editing <strong>{shotDisplayLabel(selectedShot)}</strong> while the animatic plays.</p> : null}
        <ShotInspector advanced={<AdvancedPanel embedded />} />
        <PanelResizeHandle panelKey="story-inspector" label="Resize inspector" edge="left"
          host=".story-workspace" target=".story-inspector"
          width={{ property: '--story-inspector-width', min: 300, max: 640, fraction: 0.4 }} />
      </aside>

      <footer className="story-dock" hidden={view === 'all'} aria-label="Route timeline">
        <PanelResizeHandle panelKey="story-route-strip" label="Resize timeline" edge="top" host=".story-workspace" target=".story-dock"
          height={{ property: '--story-route-height', min: 132, max: 420, fraction: 0.45 }} />
        <div className="story-dock-bar">
          <button type="button" className="ghost icon-btn" aria-label="Previous board" title="Previous board (←)"
            disabled={disabled || selectedIndex <= 0} onClick={() => chooseShot(activeRouteShots[selectedIndex - 1].shot_id)}><SkipBack size={16} weight="fill" /></button>
          <button type="button" className={'icon-btn story-dock-play' + (view === 'play' ? ' is-on' : '')} aria-label={view === 'play' ? 'Back to board' : 'Play route'}
            title={view === 'play' ? 'Back to board editing' : 'Play this route'} disabled={drawingActive || !activeRouteShots.length}
            onClick={() => changeView(view === 'play' ? 'draw' : 'play')}><Play size={15} weight="fill" /></button>
          <button type="button" className="ghost icon-btn" aria-label="Next board" title="Next board (→)"
            disabled={disabled || selectedIndex < 0 || selectedIndex >= activeRouteShots.length - 1} onClick={() => chooseShot(activeRouteShots[selectedIndex + 1].shot_id)}><SkipForward size={16} weight="fill" /></button>
          <span className="story-dock-time">{clock(selectedStart)}</span>
          <span className="story-dock-total">/ {clock(totalDuration)}</span>
          <div className="stage-spacer" />
          <span className="story-dock-route">{activeRoute?.name ?? 'Route'} · {activeRouteShots.length} board{activeRouteShots.length === 1 ? '' : 's'}</span>
          <span className="story-dock-divider" aria-hidden="true" />
          <button type="button" className="ghost" disabled={disabled || selectedIndex <= 0}
            onClick={() => reorderRoute(selectedShotId!, activeRouteShots[selectedIndex - 1].shot_id)}>Earlier</button>
          <button type="button" className="ghost" disabled={disabled || selectedIndex < 0 || selectedIndex >= activeRouteShots.length - 1}
            onClick={moveSelectedLater}>Later</button>
          <button type="button" className="ghost" disabled={disabled || !activeRoute || !selectedShotId} onClick={() => setDialog('branch')}>
            <GitBranch size={15} />Branch here</button>
          <button type="button" disabled={disabled} title="Add a board after the selected board (N)" onClick={() => { void runAction(addShotAfterSelection) }}>
            <Plus size={15} />Board</button>
        </div>
        <div className="story-dock-progress" aria-hidden="true">
          <span style={{ width: totalDuration ? `${(selectedStart / totalDuration) * 100}%` : '0%' }} />
        </div>
        <div ref={stripRef} className="story-route-cards" aria-label="Boards in the current route">
          {activeRouteShots.map((shot, index) => <button type="button" key={shot.shot_id + ':' + index}
            className={shot.shot_id === selectedShotId ? 'story-route-card is-active' : 'story-route-card'}
            aria-current={shot.shot_id === selectedShotId ? 'step' : undefined}
            disabled={disabled} title={shotDisplayLabel(shot)} onClick={() => chooseShot(shot.shot_id)}
            onDoubleClick={() => chooseShot(shot.shot_id, true)}
            draggable={!disabled} onDragStart={event => { setDragShotId(shot.shot_id); event.dataTransfer.setData('text/plain', shot.shot_id) }}
            onDragEnd={() => setDragShotId('')} onDragOver={event => { if (dragShotId) event.preventDefault() }}
            onDrop={event => { event.preventDefault(); if (dragShotId) reorderRoute(dragShotId, shot.shot_id); setDragShotId('') }}>
            <span className="story-route-thumbnail"><BoardVisual shot={shot} epoch={visualEpoch} index={index} /><span className="story-route-duration">{Number(duration(shot).toFixed(3))}s</span></span>
            <span className="story-route-card-label"><b>{String(index + 1).padStart(2, '0')}</b><span>{shotDisplayLabel(shot)}</span>
              <i className="status-dot" style={statusStyle(shot.status)} /></span>
          </button>)}
          {!activeRouteShots.length ? <p className="story-empty-note">Add a board to begin this route.</p> : null}
        </div>
      </footer>
      {dialog && activeRoute ? <RouteEditor key={dialog + ':' + activeRoute.id} mode={dialog} routeName={activeRoute.name}
        fromTitle={selectedShot ? shotDisplayLabel(selectedShot) : ''} availableShots={availableJoins}
        busy={localBusy || projectActionBusy} onClose={() => setDialog(null)} onSubmit={submitDialog} /> : null}
    </section>
  )
}

