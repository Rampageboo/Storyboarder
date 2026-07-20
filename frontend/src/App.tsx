import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { reportUiReady } from './api'
import { Topbar } from './components/Topbar'
import { ShotInspector } from './components/ShotInspector'
import { BoardStrip } from './components/BoardStrip'
import { CanvasBoard } from './components/CanvasBoard'
import { ReferenceSidebar } from './components/ReferenceSidebar'
import { ReferenceAssignmentPopover } from './components/ReferenceAssignmentPopover'
import { Scene2DPanel } from './components/Scene2DPanel'
import { Scene3DPanel } from './components/Scene3DPanel'
import { NeighborContext } from './components/NeighborContext'
import { AdvancedPanel } from './components/AdvancedPanel'
import { SettingsModal } from './components/SettingsModal'
import { ProjectProvider } from './state/ProjectContext'
import { useProject } from './state/useProject'
import { LiveBridgeProvider } from './state/LiveBridgeContext'
import { useGlobalShortcuts } from './hooks/useGlobalShortcuts'
import type { ProjectPathRequest } from './types'
import './App.css'

type WorkspaceMode = 'board' | 'scene2d' | 'scene3d'

function WelcomePanel() {
  const { newProject, openProjectFromDialog, projectActionBusy } = useProject()

  const handleNew = useCallback(async () => {
    try {
      await newProject({ path: null, canvas_width: 1920, canvas_height: 1080 })
    } catch {
      // error surfaced via banner
    }
  }, [newProject])

  const handleOpen = useCallback(async () => {
    try {
      await openProjectFromDialog()
    } catch {
      // error surfaced via banner
    }
  }, [openProjectFromDialog])

  return (
    <div className="welcome-panel">
      <div className="welcome-card">
        <h2>No project open</h2>
        <p>Create or open a local Storyboarder document. Scenes, shots, and artwork stay together in one .sbd file.</p>
        <div className="welcome-actions">
          <button type="button" className="primary" onClick={() => void handleNew()} disabled={projectActionBusy}>
            New project
          </button>
          <button type="button" onClick={() => void handleOpen()} disabled={projectActionBusy}>
            Open document
          </button>
        </div>
      </div>
    </div>
  )
}

function LeftRail({
  showNav,
  workspaceMode,
  refsOpen,
  onToggleRefs,
  onSetWorkspaceMode,
  onOpenSettings,
}: {
  showNav: boolean
  workspaceMode: WorkspaceMode
  refsOpen: boolean
  onToggleRefs: () => void
  onSetWorkspaceMode: (mode: WorkspaceMode) => void
  onOpenSettings: () => void
}) {
  return (
    <nav className="left-rail" aria-label="Workspace navigation">
      <div className="left-rail-logo">
        <img src="/react/icon.png" width="46" height="46" alt="" style={{ borderRadius: 11, display: 'block' }} />
      </div>
      {showNav ? (
        <>
          <div className="left-rail-group">
            <button
              type="button"
              className={`left-rail-item ${workspaceMode === 'board' ? 'is-active' : ''}`}
              onClick={() => onSetWorkspaceMode('board')}
              title="Board"
              aria-current={workspaceMode === 'board' ? 'page' : undefined}
              aria-pressed={workspaceMode === 'board'}
            >
              <span className="left-rail-icon">&#9638;</span>
              <span>Board</span>
            </button>
            <button
              type="button"
              className={`left-rail-item ${workspaceMode === 'scene2d' ? 'is-active' : ''}`}
              onClick={() => onSetWorkspaceMode('scene2d')}
              title="Scenes"
              aria-current={workspaceMode === 'scene2d' ? 'page' : undefined}
              aria-pressed={workspaceMode === 'scene2d'}
            >
              <span className="left-rail-icon">&#9636;</span>
              <span>Scenes</span>
            </button>
            <button
              type="button"
              className={`left-rail-item ${workspaceMode === 'scene3d' ? 'is-active' : ''}`}
              onClick={() => onSetWorkspaceMode('scene3d')}
              title="Scene 3D"
              aria-current={workspaceMode === 'scene3d' ? 'page' : undefined}
              aria-pressed={workspaceMode === 'scene3d'}
            >
              <span className="left-rail-icon">&#11042;</span>
              <span>3D</span>
            </button>
            <button
              type="button"
              className={`left-rail-item ${refsOpen ? 'is-active' : ''}`}
              onClick={onToggleRefs}
              title="References"
              aria-expanded={refsOpen}
              aria-controls="ref-drawer-panel"
            >
              <span className="left-rail-icon">&#9671;</span>
              <span>Refs</span>
            </button>
          </div>
          <div className="left-rail-group left-rail-bottom">
            <button type="button" className="left-rail-item" onClick={onOpenSettings} title="Settings">
              <span className="left-rail-icon">&#9881;</span>
              <span>Settings</span>
            </button>
          </div>
        </>
      ) : null}
    </nav>
  )
}

function BoardWorkspace({
  inspectorCollapsed,
  onToggleInspector,
}: {
  inspectorCollapsed: boolean
  onToggleInspector: () => void
}) {
  return (
    <>
      <main className="main-center">
        <CanvasBoard />
        <NeighborContext />
        <BoardStrip />
      </main>
      <aside className={`main-right${inspectorCollapsed ? ' is-collapsed' : ''}`}>
        <button
          type="button"
          className="inspector-size-toggle"
          onClick={onToggleInspector}
          aria-label={inspectorCollapsed ? 'Show shot details' : 'Hide shot details'}
          aria-pressed={!inspectorCollapsed}
          title={inspectorCollapsed ? 'Show shot details' : 'Hide shot details to expand the canvas'}
        >
          <span aria-hidden="true">{inspectorCollapsed ? '\u2039' : '\u203a'}</span>
        </button>
        {!inspectorCollapsed ? (
          <>
            <ShotInspector />
            <AdvancedPanel />
          </>
        ) : null}
      </aside>
    </>
  )
}

function RightRail({
  onOpenSettings,
}: {
  onOpenSettings: () => void
}) {
  const { project, newProject, openProjectFromDialog, saveProject, dirtyShotIds, projectActionBusy, initialLoading } =
    useProject()
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const hasUnsaved = !!project && (project.dirty || dirtyShotIds.length > 0)

  const handleNew = useCallback(async () => {
    const body: ProjectPathRequest = {
      path: null,
      canvas_width: 1920,
      canvas_height: 1080,
    }
    try {
      await newProject(body)
    } catch {
      // error surfaced via banner
    }
  }, [newProject])

  const handleOpen = useCallback(async () => {
    try {
      await openProjectFromDialog()
    } catch {
      // error surfaced via banner
    }
  }, [openProjectFromDialog])

  const handleSave = useCallback(async () => {
    try {
      await saveProject()
    } catch {
      // error surfaced via banner
    }
  }, [saveProject])

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  const runMenuAction = useCallback(
    (action: () => void) => {
      closeMenu()
      action()
    },
    [closeMenu],
  )

  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) closeMenu()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen, closeMenu])

  return (
    <nav className="right-rail" aria-label="Workspace tools">
      <div className="right-rail-group right-rail-bottom">
        <div className="right-rail-menu" ref={menuRef}>
          <button
            type="button"
            className={`right-rail-item ${menuOpen ? 'is-active' : ''}`}
            onClick={() => setMenuOpen((value) => !value)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title="More"
          >
            <span className="right-rail-icon">&#8942;</span>
            <span>More</span>
          </button>
          {menuOpen ? (
            <div className="right-rail-dropdown" role="menu" aria-label="More actions">
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(() => void handleNew())}
                disabled={projectActionBusy || initialLoading}
              >
                New Project
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(() => void handleOpen())}
                disabled={projectActionBusy || initialLoading}
              >
                Open Project Folder
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(() => void handleSave())}
                disabled={!project || !hasUnsaved || projectActionBusy}
              >
                {projectActionBusy ? 'Saving...' : 'Save Project'}
              </button>
              <div className="right-rail-menu-divider" />
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(onOpenSettings)}
                disabled={!project || projectActionBusy || initialLoading}
              >
                Settings
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </nav>
  )
}

function AppInner() {
  const { project, initialLoading, lastError, clearError, reloadProject } = useProject()
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('board')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [refsOpen, setRefsOpen] = useState(false)
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false)
  const uiReadyReportedRef = useRef(false)
  useGlobalShortcuts()

  const themeVars: CSSProperties = {
    '--thumb-empty-bg': project?.settings?.canvas_background_color || undefined,
    '--canvas-empty-bg': project?.settings?.canvas_background_color || undefined,
  } as CSSProperties

  useEffect(() => {
    void reloadProject()
  }, [reloadProject])

  useEffect(() => {
    setWorkspaceMode('board')
  }, [project?.project_json_path, project?.project_path])

  // Report UI-ready after Welcome or Board UI paints (double rAF = 2 frames).
  // This lets the native splash window close at the right moment.
  useEffect(() => {
    if (initialLoading) return
    if (uiReadyReportedRef.current) return
    uiReadyReportedRef.current = true
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        void reportUiReady().catch(() => {})
      })
    })
  }, [initialLoading])

  return (
    <div className="app-root" style={themeVars}>
      <LeftRail
        showNav={!!project}
        workspaceMode={workspaceMode}
        refsOpen={refsOpen}
        onToggleRefs={() => setRefsOpen((v) => !v)}
        onSetWorkspaceMode={setWorkspaceMode}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <div className="app-main">
        <Topbar workspaceMode={workspaceMode} />
        {lastError ? (
          <div className="app-banner" role="alert">
            <span>{lastError}</span>
            <button type="button" onClick={clearError} aria-label="Dismiss error">
              &times;
            </button>
          </div>
        ) : null}
        <div className="workspace-shell">
          <div className={`workspace workspace-${workspaceMode}${inspectorCollapsed ? ' is-inspector-collapsed' : ''}`}>
            {initialLoading ? (
              <div className="loading-panel">Loading project...</div>
            ) : !project ? (
              <WelcomePanel />
            ) : (
              <>
                <ReferenceSidebar open={refsOpen} onOpenChange={setRefsOpen} />
                <div className={`workspace-content workspace-content-board${inspectorCollapsed ? ' is-inspector-collapsed' : ''}`} hidden={workspaceMode !== 'board'}>
                  <BoardWorkspace
                    inspectorCollapsed={inspectorCollapsed}
                    onToggleInspector={() => setInspectorCollapsed((value) => !value)}
                  />
                </div>
                <div className="workspace-content workspace-content-scene" hidden={workspaceMode !== 'scene2d'}>
                  <Scene2DPanel active={workspaceMode === 'scene2d'} />
                </div>
                <div className="workspace-content workspace-content-scene" hidden={workspaceMode !== 'scene3d'}>
                  <Scene3DPanel active={workspaceMode === 'scene3d'} />
                </div>
                <RightRail onOpenSettings={() => setSettingsOpen(true)} />
              </>
            )}
          </div>
        </div>
      </div>
      <ReferenceAssignmentPopover />
      {settingsOpen ? <SettingsModal open onClose={() => setSettingsOpen(false)} /> : null}
    </div>
  )
}

export default function App() {
  return (
    <ProjectProvider>
      <LiveBridgeProvider>
        <AppInner />
      </LiveBridgeProvider>
    </ProjectProvider>
  )
}
