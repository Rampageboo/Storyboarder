import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ArrowBendDownRight, ArrowsOut, FilmStrip, GitBranch, MapTrifold, PencilSimple, Play, Plus, Rows, X } from '@phosphor-icons/react'
import { useProject } from '../state/useProject'
import type { Shot } from '../types'
import { shotDisplayLabel } from '../utils/shotDisplay'
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
  const rounded = Math.max(0, Math.round(seconds))
  return Math.floor(rounded / 60) + ':' + String(rounded % 60).padStart(2, '0')
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
          <button type="submit" className="story-primary" disabled={busy || !value.trim()}>{busy ? 'Saving…' : mode === 'branch' ? 'Create branch' : mode === 'join' ? 'Join board' : 'Save name'}</button>
        </div>
      </form>
    </dialog>
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
    if (drawingActive && (next === 'all' || next === 'play')) return
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
    if (left < parent.scrollLeft) parent.scrollLeft = left
    else if (left + element.offsetWidth > parent.scrollLeft + parent.clientWidth) parent.scrollLeft = left + element.offsetWidth - parent.clientWidth
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

  if (!project) return null
  const canvasHidden = view === 'map' || view === 'play' || (view === 'all' && allView === 'grid')

  return (
    <section className={'story-workspace' + (view === 'all' ? ' is-all-boards' : '')} data-story-view={view} aria-label="Story workspace">
      <header className="story-workspace-header">
        <div className="story-workspace-brand"><FilmStrip size={19} /><span>Story workspace</span><span className="story-header-divider" />{activeRoute?.name ?? 'Story structure'}</div>
        <nav className="story-view-tabs" aria-label="Story workspace view">
          <button type="button" className={view === 'map' ? 'is-active' : ''} aria-pressed={view === 'map'} onClick={() => changeView('map')}><MapTrifold size={17} />Map</button>
          <button type="button" className={view === 'draw' ? 'is-active' : ''} aria-pressed={view === 'draw'} onClick={() => changeView('draw')}><PencilSimple size={17} />Draw</button>
          <button type="button" className={view === 'play' ? 'is-active' : ''} aria-pressed={view === 'play'} disabled={drawingActive} onClick={() => changeView('play')}><Play size={17} />Play</button>
          <button type="button" className={view === 'all' ? 'is-active' : ''} aria-pressed={view === 'all'} disabled={drawingActive} onClick={() => changeView('all')}><Rows size={17} />All boards</button>
        </nav>
      </header>
      {drawingActive ? <div className="story-drawing-guard" role="status">Save drawing or close editor before changing shots. <button type="button" onClick={() => changeView('draw')}>Return to drawing</button></div> : null}
      <aside className="story-structure-panel" hidden={view === 'all'}>
        <div className="story-panel-heading"><GitBranch size={17} /><strong>Story structure</strong>
          <button type="button" title="Expand story map" aria-label="Expand story map" onClick={() => changeView('map')}><ArrowsOut size={15} /></button></div>
        <div className="story-route-controls">
          <label htmlFor="story-active-route">Current route</label>
          <select id="story-active-route" value={routeKey} disabled={disabled || !storyGraph}
            onChange={event => { const id = event.target.value; void runAction(() => setActiveStoryRoute(id)) }}>
            {storyGraph?.routes.map(route => <option key={route.id} value={route.id}>{route.name}</option>)}
          </select>
          <div className="story-route-actions">
            <button type="button" title="Branch from the selected board" disabled={disabled || !activeRoute || !selectedShotId}
              onClick={() => { setDialog('branch') }}><GitBranch size={15} />Branch</button>
            <button type="button" title="Append an existing board to this route" disabled={disabled || !activeRoute || !availableJoins.length}
              onClick={() => { setDialog('join') }}><ArrowBendDownRight size={15} />Join</button>
            <button type="button" title="Rename current route" aria-label="Rename current route" disabled={disabled || !activeRoute}
              onClick={() => { setDialog('rename') }}><PencilSimple size={15} /></button>
          </div>
        </div>
        <div className="story-mini-map">{storyGraph ? <StoryMap graph={storyGraph} shots={project.shots}
          selectedShotId={selectedShotId} visualEpoch={visualEpoch} disabled={disabled} compact
          onSelect={id => chooseShot(id)} onOpen={id => chooseShot(id, true)}
          onUpdate={updateStoryGraph} onError={reportError} /> : <p className="story-empty-note">Story structure is loading.</p>}</div>
        <div className="story-map-legend"><i />Current route<span>● Shared board</span></div>
      </aside>
      <PanelResizeHandle panelKey="story-structure" label="Resize Story structure" edge="right"
        className="story-structure-resize" hidden={view === 'all'} host=".story-workspace" target=".story-structure-panel"
        width={{ property: '--story-structure-width', min: 140, max: 520, fraction: 0.3 }} />
      <main className="story-center">
        {view === 'all' ? <div className="story-global-actions">
          <BulkBoardActions />
          <div className="story-all-toggle"><strong>All {project.shots.length} boards</strong><span>Global order and bulk tools</span>
            <button type="button" aria-pressed={allView === 'grid'} onClick={() => setAllView('grid')}>Grid</button>
            <button type="button" aria-pressed={allView === 'strip'} onClick={() => setAllView('strip')}>Strip</button>
          </div>
        </div> : null}
        <div className="story-canvas-host" hidden={canvasHidden}><CanvasBoard panelsInitiallyOpen={false} /></div>
        {view === 'map' ? <div className="story-map-host">{storyGraph ? <StoryMap graph={storyGraph} shots={project.shots}
          selectedShotId={selectedShotId} visualEpoch={visualEpoch} disabled={disabled}
          onSelect={id => chooseShot(id)} onOpen={id => chooseShot(id, true)}
          onUpdate={updateStoryGraph} onError={reportError} /> : <div className="story-empty-note">Story structure is loading.</div>}</div> : null}
        {view === 'play' ? <AnimaticPlayer key={projectKey + ':' + routeKey + ':' + activeRoute?.shot_ids.join('|')}
          shots={activeRouteShots} routeId={routeKey} selectedId={selectedShotId} active={active && !localBusy}
          onSelect={chooseShot} /> : null}
        {view === 'all' && allView === 'grid' ? <div className="story-grid-host"><BoardGrid /></div> : null}
        {view === 'all' && allView === 'strip' ? <div className="story-legacy-strip">
          <PanelResizeHandle panelKey="all-boards-strip" label="Resize Boards strip" edge="top" bounds=".story-center"
            height={{ property: '--story-all-strip-height', min: 140, max: 600, fraction: 0.6 }} />
          <NeighborContext /><BoardStrip /></div> : null}
        {!project.shots.length ? <div className="story-empty-project">
          <FilmStrip size={30} /><h2>Start with your first board</h2><p>Draw a scene, then branch into other story directions.</p>
          <button type="button" className="story-primary" disabled={disabled} onClick={() => { void runAction(addShotAfterSelection) }}><Plus size={16} />Add first board</button>
        </div> : null}
      </main>
      <aside className="main-right story-inspector">
        <div className="story-panel-heading"><PencilSimple size={16} /><strong>{view === 'play' ? 'Selected board details' : 'Shot details'}</strong></div>
        {view === 'play' && selectedShot ? <p className="story-play-selection-note">Editing <strong>{shotDisplayLabel(selectedShot)}</strong>.
          Use <strong>Edit board</strong> beside the playhead to edit the previewed board.</p> : null}
        <ShotInspector /><AdvancedPanel />
      </aside>
      <PanelResizeHandle panelKey="story-inspector" label="Resize Shot details" edge="left"
        className="story-inspector-resize" host=".story-workspace" target=".story-inspector"
        width={{ property: '--story-inspector-width', min: 230, max: 680, fraction: 0.4 }} />
      <footer className="story-route-strip" hidden={view === 'all'}>
        <PanelResizeHandle panelKey="story-route-strip" label="Resize Route boards" edge="top" host=".story-workspace" target=".story-route-strip"
          height={{ property: '--story-route-height', min: 105, max: 460, fraction: 0.45 }} />
        <div className="story-route-strip-heading"><div><GitBranch size={15} /><strong>{activeRoute?.name ?? 'Current route'}</strong>
          <span>{activeRouteShots.length} boards · {clock(totalDuration)}</span></div>
          <div className="story-route-reorder">
            <button type="button" disabled={disabled || selectedIndex <= 0} onClick={() => reorderRoute(selectedShotId!, activeRouteShots[selectedIndex - 1].shot_id)}>Earlier</button>
            <button type="button" disabled={disabled || selectedIndex < 0 || selectedIndex >= activeRouteShots.length - 1} onClick={() => {
              if (!activeRoute || !storyGraph || !selectedShotId) return
              const ids = [...activeRoute.shot_ids]; [ids[selectedIndex], ids[selectedIndex + 1]] = [ids[selectedIndex + 1], ids[selectedIndex]]
              void runAction(() => updateStoryGraph({ ...storyGraph, routes: storyGraph.routes.map(route => route.id === routeKey ? { ...route, shot_ids: ids } : route) }))
            }}>Later</button>
          </div>
          <button type="button" disabled={disabled} title="Add a board after the selected board" onClick={() => { void runAction(addShotAfterSelection) }}><Plus size={15} />Add board</button></div>
        <div ref={stripRef} className="story-route-cards" aria-label="Boards in the current route">
          {activeRouteShots.map((shot, index) => <button type="button" key={shot.shot_id}
            className={shot.shot_id === selectedShotId ? 'story-route-card is-active' : 'story-route-card'}
            aria-current={shot.shot_id === selectedShotId ? 'step' : undefined}
            disabled={disabled} title={shotDisplayLabel(shot)} onClick={() => chooseShot(shot.shot_id)}
            draggable={!disabled} onDragStart={event => { setDragShotId(shot.shot_id); event.dataTransfer.setData('text/plain', shot.shot_id) }}
            onDragEnd={() => setDragShotId('')} onDragOver={event => { if (dragShotId) event.preventDefault() }}
            onDrop={event => { event.preventDefault(); if (dragShotId) reorderRoute(dragShotId, shot.shot_id); setDragShotId('') }}>
            <span className="story-route-thumbnail"><BoardVisual shot={shot} epoch={visualEpoch} index={index} /><span className="story-route-duration">{Number(duration(shot).toFixed(3))}s</span></span>
            <span className="story-route-card-label"><b>{String(index + 1).padStart(2, '0')}</b><span>{shotDisplayLabel(shot)}</span></span>
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
