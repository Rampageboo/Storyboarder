import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
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

type RightPanel = 'scene2d' | 'scene3d' | null

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
        <p>Create a new storyboard project in a chosen folder, or open an existing project folder.</p>
        <div className="welcome-actions">
          <button type="button" className="primary" onClick={() => void handleNew()} disabled={projectActionBusy}>
            New project
          </button>
          <button type="button" onClick={() => void handleOpen()} disabled={projectActionBusy}>
            Open project folder
          </button>
        </div>
      </div>
    </div>
  )
}

function LeftRail({
  refsOpen,
  onToggleRefs,
  onOpenSettings,
}: {
  refsOpen: boolean
  onToggleRefs: () => void
  onOpenSettings: () => void
}) {
  return (
    <nav className="left-rail" aria-label="Workspace navigation">
      <div className="left-rail-brand" aria-label="Storyboarder">
        <span>SB</span>
      </div>
      <div className="left-rail-group">
        <button type="button" className="left-rail-item is-active" title="Board" aria-current="page">
          <span className="left-rail-icon">&#9638;</span>
          <span>Board</span>
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
    </nav>
  )
}

function RightRail({
  activePanel,
  onToggleScene2D,
  onToggleScene3D,
  onOpenSettings,
}: {
  activePanel: RightPanel
  onToggleScene2D: () => void
  onToggleScene3D: () => void
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
      <div className="right-rail-group">
        <button
          type="button"
          className={`right-rail-item ${activePanel === 'scene2d' ? 'is-active' : ''}`}
          onClick={onToggleScene2D}
          title="Scene 2D"
          aria-pressed={activePanel === 'scene2d'}
        >
          <span className="right-rail-icon">&#9636;</span>
          <span>2D</span>
        </button>
        <button
          type="button"
          className={`right-rail-item ${activePanel === 'scene3d' ? 'is-active' : ''}`}
          onClick={onToggleScene3D}
          title="Scene 3D"
          aria-pressed={activePanel === 'scene3d'}
        >
          <span className="right-rail-icon">&#11042;</span>
          <span>3D</span>
        </button>
      </div>

      <div className="right-rail-group right-rail-bottom">
        <button type="button" className="right-rail-item" disabled title="Upload is not wired yet">
          <span className="right-rail-icon">&#8679;</span>
          <span>Upload</span>
        </button>
        <button type="button" className="right-rail-item" disabled title="Share is not wired yet">
          <span className="right-rail-icon">&#8599;</span>
          <span>Share</span>
        </button>
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

function SidePanelDrawer({ activePanel, onClose }: { activePanel: RightPanel; onClose: () => void }) {
  if (!activePanel) return null

  return (
    <aside className="side-panel-drawer is-open" aria-label={activePanel === 'scene2d' ? 'Scene 2D panel' : 'Scene 3D panel'}>
      <div className="side-panel-drawer-head">
        <span>{activePanel === 'scene2d' ? 'Scene 2D' : 'Scene 3D'}</span>
        <button type="button" onClick={onClose} aria-label="Close panel">
          &times;
        </button>
      </div>
      <div className="side-panel-drawer-body">
        {activePanel === 'scene2d' ? <Scene2DPanel /> : <Scene3DPanel />}
      </div>
    </aside>
  )
}

function AppInner() {
  const { project, initialLoading, lastError, clearError, reloadProject } = useProject()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [refsOpen, setRefsOpen] = useState(false)
  const [rightPanel, setRightPanel] = useState<RightPanel>(null)
  useGlobalShortcuts()

  const themeVars: CSSProperties = {
    '--thumb-empty-bg': project?.settings?.canvas_background_color || undefined,
    '--canvas-empty-bg': project?.settings?.canvas_background_color || undefined,
  } as CSSProperties

  useEffect(() => {
    void reloadProject()
  }, [reloadProject])

  return (
    <div className="app-root" style={themeVars}>
      <Topbar />
      {lastError ? (
        <div className="app-banner" role="alert">
          <span>{lastError}</span>
          <button type="button" onClick={clearError} aria-label="Dismiss error">
            &times;
          </button>
        </div>
      ) : null}
      <div className="workspace-shell">
        {project ? (
          <LeftRail
            refsOpen={refsOpen}
            onToggleRefs={() => setRefsOpen((value) => !value)}
            onOpenSettings={() => setSettingsOpen(true)}
          />
        ) : null}
        <div className="workspace">
          {initialLoading ? (
            <div className="loading-panel">Loading project...</div>
          ) : !project ? (
            <WelcomePanel />
          ) : (
            <>
              <ReferenceSidebar open={refsOpen} onOpenChange={setRefsOpen} />
              <main className="main-center">
                <CanvasBoard />
                <NeighborContext />
                <BoardStrip />
              </main>
              <aside className="main-right">
                <ShotInspector />
                <AdvancedPanel />
              </aside>
              <RightRail
                activePanel={rightPanel}
                onToggleScene2D={() => setRightPanel((value) => (value === 'scene2d' ? null : 'scene2d'))}
                onToggleScene3D={() => setRightPanel((value) => (value === 'scene3d' ? null : 'scene3d'))}
                onOpenSettings={() => setSettingsOpen(true)}
              />
              <SidePanelDrawer activePanel={rightPanel} onClose={() => setRightPanel(null)} />
            </>
          )}
        </div>
      </div>
      <ReferenceAssignmentPopover />
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
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
