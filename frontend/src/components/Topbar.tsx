import { useCallback, useEffect, useState } from 'react'
import { CaretDown, DownloadSimple, GearSix, Images } from '@phosphor-icons/react'
import { preheatPhotoshop } from '../api'
import { useProject } from '../state/useProject'
import { useBridgeStatus } from '../state/liveBridgeUtils'
import { canConvertProjectToLayout2 } from '../projectCapabilities'
import { useDetailsMenu } from '../hooks/useDetailsMenu'
import './Topbar.css'

const PREHEAT_COUNTDOWN_SECONDS = 10
let preheatSessionState: 'ready' | 'countdown' | 'cancelled' | 'attempted' = 'ready'

export type WorkspaceMode = 'board' | 'comic' | 'scene2d' | 'scene3d'

const WORKSPACES: { mode: WorkspaceMode; label: string; title: string }[] = [
  { mode: 'board', label: 'Story', title: 'Boards, routes and animatic' },
  { mode: 'comic', label: 'Comic', title: 'Pages, spreads and long scrolls' },
  { mode: 'scene2d', label: 'Scenes', title: 'Scene library and perspectives' },
  { mode: 'scene3d', label: '3D', title: 'Blender scene and cameras' },
]

function shortShotId(shotId: string) {
  return shotId.length > 12 ? `${shotId.slice(0, 8)}…` : shotId
}

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 16 16"><rect x="2" y="3.5" width="5" height="9" rx="1" /><rect x="9" y="3.5" width="5" height="9" rx="1" /></svg>
    </span>
  )
}

function usePhotoshopPreheat() {
  const { project, initialLoading } = useProject()
  const bridgeStatus = useBridgeStatus()
  const [preheatState, setPreheatState] = useState<'idle' | 'countdown' | 'preheating'>('idle')
  const [preheatSeconds, setPreheatSeconds] = useState(PREHEAT_COUNTDOWN_SECONDS)

  const cancel = useCallback(() => {
    if (preheatSessionState !== 'countdown') return
    preheatSessionState = 'cancelled'
    setPreheatState('idle')
  }, [])

  const enabled = Boolean(project?.settings?.preheat_photoshop_on_open)
  const sessionKey = project?.project_json_path ?? project?.project_path ?? ''
  const linked = Boolean(bridgeStatus?.plugin_linked)

  useEffect(() => {
    if (initialLoading || !enabled || !sessionKey) return
    if (preheatSessionState !== 'ready') return
    if (linked) {
      // PS is already running and connected — no need to preheat.
      preheatSessionState = 'attempted'
      return
    }

    preheatSessionState = 'countdown'
    const kickoff = window.setTimeout(() => {
      setPreheatSeconds(PREHEAT_COUNTDOWN_SECONDS)
      setPreheatState('countdown')
    }, 0)

    let remaining = PREHEAT_COUNTDOWN_SECONDS
    const timer = window.setInterval(() => {
      remaining -= 1
      if (remaining > 0) {
        setPreheatSeconds(remaining)
        return
      }
      window.clearInterval(timer)
      if (preheatSessionState !== 'countdown') return
      preheatSessionState = 'attempted'
      setPreheatState('preheating')
      void preheatPhotoshop()
        .catch(() => {
          // Best-effort warmup; missing/unsupported Photoshop must not affect the app.
        })
        .finally(() => setPreheatState('idle'))
    }, 1000)

    return () => {
      window.clearTimeout(kickoff)
      window.clearInterval(timer)
      if (preheatSessionState === 'countdown') {
        preheatSessionState = 'ready'
        window.setTimeout(() => setPreheatState('idle'), 0)
      }
    }
  }, [initialLoading, enabled, sessionKey, linked])

  return { preheatState, preheatSeconds, cancel }
}

function PhotoshopStatus() {
  const { project } = useProject()
  const status = useBridgeStatus()
  const { preheatState, preheatSeconds, cancel } = usePhotoshopPreheat()
  const linked = Boolean(status?.plugin_linked)
  const selected = status?.plugin_selected_shot_id ?? ''
  const openShots = status?.plugin_open_shot_ids ?? []

  let label = 'Ps'
  let title = linked ? 'Photoshop connected' : 'Photoshop not connected'
  if (preheatState === 'countdown') {
    label = `Ps in ${preheatSeconds}s`
    title = 'Click to cancel the Photoshop preheat for this session.'
  } else if (preheatState === 'preheating') {
    label = 'Ps starting…'
    title = 'Launching Photoshop in the background.'
  } else if (linked) {
    const details = [selected ? `Current: ${selected}` : '', openShots.length ? `Open: ${openShots.map(shortShotId).join(', ')}` : '']
    title = [title, ...details.filter(Boolean)].join('\n')
  }
  if (!project) return null
  const state = preheatState !== 'idle' ? 'is-pending' : linked ? 'is-on' : 'is-off'
  return (
    <button
      type="button"
      className={`ghost topbar-bridge ${state}`}
      title={title}
      aria-label={preheatState === 'countdown' ? 'Cancel Photoshop preheat' : title}
      onClick={preheatState === 'countdown' ? cancel : undefined}
    >
      <span className="topbar-bridge-dot" aria-hidden="true" />
      {label}
      {linked && openShots.length ? <span className="topbar-bridge-count">{openShots.length}</span> : null}
    </button>
  )
}

function ProjectMenu({ onOpenSettings, onGoHome }: { onOpenSettings: () => void; onGoHome: () => void }) {
  const { project, newProject, openProjectFromDialog, saveProject, saveProjectAs, convertProject, dirtyShotIds, projectActionBusy, initialLoading } = useProject()
  const { ref, close } = useDetailsMenu()
  const busy = projectActionBusy || initialLoading
  const hasUnsaved = !!project && (project.dirty || dirtyShotIds.length > 0)
  const run = (action: () => Promise<unknown> | void) => {
    close()
    void Promise.resolve(action()).catch(() => { /* surfaced via the app error banner */ })
  }
  if (!project) return null
  return (
    <details className="menu topbar-project-menu" ref={ref}>
      <summary className="topbar-project-name" title={project.project_json_path || project.project_path}>
        <span>{project.name}</span>
        <CaretDown size={12} weight="bold" />
      </summary>
      <div className="menu-panel is-left" role="menu">
        <button type="button" role="menuitem" disabled={busy} onClick={() => run(onGoHome)}>Close to Home</button>
        <div className="menu-divider" />
        <button type="button" role="menuitem" disabled={busy} onClick={() => run(() => newProject({ path: null, canvas_width: 1920, canvas_height: 1080 }))}>
          New project…<span className="menu-hint">Ctrl N</span>
        </button>
        <button type="button" role="menuitem" disabled={busy} onClick={() => run(openProjectFromDialog)}>
          Open project…<span className="menu-hint">Ctrl O</span>
        </button>
        <div className="menu-divider" />
        <button type="button" role="menuitem" disabled={busy || !hasUnsaved} onClick={() => run(saveProject)}>
          Save<span className="menu-hint">Ctrl S</span>
        </button>
        <button type="button" role="menuitem" disabled={busy} onClick={() => run(saveProjectAs)}>Save as…</button>
        {canConvertProjectToLayout2(project) ? (
          <button type="button" role="menuitem" disabled={busy} onClick={() => run(convertProject)}>Convert to Layout 2…</button>
        ) : null}
        <div className="menu-divider" />
        <button type="button" role="menuitem" disabled={busy} onClick={() => run(onOpenSettings)}>Project settings…</button>
      </div>
    </details>
  )
}

function SaveState() {
  const { project, dirtyShotIds, savingShots, projectActionBusy } = useProject()
  if (!project) return null
  const saving = projectActionBusy || Object.values(savingShots).some(Boolean)
  const dirty = project.dirty || dirtyShotIds.length > 0
  const state = saving ? 'is-saving' : dirty ? 'is-dirty' : 'is-saved'
  const label = saving ? 'Saving…' : dirty ? 'Unsaved changes' : 'Saved'
  return (
    <span className={`topbar-save ${state}`} role="status">
      <span className="topbar-save-dot" aria-hidden="true" />
      {label}
    </span>
  )
}

export function Topbar({
  workspaceMode,
  onSetWorkspaceMode,
  refsOpen,
  onToggleRefs,
  onOpenSettings,
  onOpenExport,
  onGoHome,
}: {
  workspaceMode: WorkspaceMode
  onSetWorkspaceMode: (mode: WorkspaceMode) => void
  refsOpen: boolean
  onToggleRefs: () => void
  onOpenSettings: () => void
  onOpenExport: () => void
  onGoHome: () => void
}) {
  const { project, projectActionBusy, initialLoading } = useProject()
  const busy = projectActionBusy || initialLoading

  return (
    <header className="topbar">
      <div className="topbar-left">
        <BrandMark />
        {project ? (
          <>
            <ProjectMenu onOpenSettings={onOpenSettings} onGoHome={onGoHome} />
            <SaveState />
          </>
        ) : (
          <span className="topbar-app-name">Storyboarder</span>
        )}
      </div>

      {project ? (
        <nav className="topbar-center" aria-label="Workspace">
          <div className="seg-group">
            {WORKSPACES.map((item) => (
              <button
                key={item.mode}
                type="button"
                title={item.title}
                aria-current={workspaceMode === item.mode ? 'page' : undefined}
                onClick={() => onSetWorkspaceMode(item.mode)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>
      ) : <div className="topbar-center" />}

      <div className="topbar-right">
        <PhotoshopStatus />
        {project ? (
          <>
            <span className="topbar-divider" aria-hidden="true" />
            <button type="button" aria-pressed={refsOpen} aria-controls="ref-drawer-panel" onClick={onToggleRefs}
              className={refsOpen ? 'is-active' : undefined}>
              <Images size={16} />References
            </button>
            <button type="button" className="primary" disabled={busy} onClick={onOpenExport}>
              <DownloadSimple size={16} weight="bold" />Export
            </button>
            <button type="button" className="ghost icon-btn" aria-label="Project settings" title="Project settings" disabled={busy} onClick={onOpenSettings}>
              <GearSix size={17} />
            </button>
          </>
        ) : null}
      </div>
    </header>
  )
}
