import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { Topbar } from './components/Topbar'
import { ShotInspector } from './components/ShotInspector'
import { BoardStrip } from './components/BoardStrip'
import { CanvasBoard } from './components/CanvasBoard'
import { ReferenceSidebar } from './components/ReferenceSidebar'
import { ReferenceAssignmentPopover } from './components/ReferenceAssignmentPopover'
import { Scene2DPanel, type Scene2DPanelHandle } from './components/Scene2DPanel'
import { Scene3DPanel, type Scene3DPanelHandle } from './components/Scene3DPanel'
import { NeighborContext } from './components/NeighborContext'
import { AdvancedPanel } from './components/AdvancedPanel'
import { SettingsModal } from './components/SettingsModal'
import { ProjectProvider } from './state/ProjectContext'
import { useProject } from './state/useProject'
import { LiveBridgeProvider } from './state/LiveBridgeContext'
import { useGlobalShortcuts } from './hooks/useGlobalShortcuts'
import type { ProjectPathRequest } from './types'
import './App.css'

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
  showNav,
  refsOpen,
  onToggleRefs,
  onOpen2D,
  onOpen3D,
  onOpenSettings,
}: {
  showNav: boolean
  refsOpen: boolean
  onToggleRefs: () => void
  onOpen2D: () => void
  onOpen3D: () => void
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
            <button type="button" className="left-rail-item is-active" title="Board" aria-current="page">
              <span className="left-rail-icon">&#9638;</span>
              <span>Board</span>
            </button>
            <button type="button" className="left-rail-item" onClick={onOpen2D} title="Scene 2D">
              <span className="left-rail-icon">&#9636;</span>
              <span>2D</span>
            </button>
            <button type="button" className="left-rail-item" onClick={onOpen3D} title="Scene 3D">
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

function AppInner() {
  const { project, initialLoading, lastError, clearError, reloadProject } = useProject()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [refsOpen, setRefsOpen] = useState(false)
  const scene2dRef = useRef<Scene2DPanelHandle>(null)
  const scene3dRef = useRef<Scene3DPanelHandle>(null)
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
      <LeftRail
        showNav={!!project}
        refsOpen={refsOpen}
        onToggleRefs={() => setRefsOpen((v) => !v)}
        onOpen2D={() => scene2dRef.current?.openWorkspace()}
        onOpen3D={() => scene3dRef.current?.openWorkspace()}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <div className="app-main">
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
                <RightRail onOpenSettings={() => setSettingsOpen(true)} />
                <Scene2DPanel ref={scene2dRef} />
                <Scene3DPanel ref={scene3dRef} />
              </>
            )}
          </div>
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
