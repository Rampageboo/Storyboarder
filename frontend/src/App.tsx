import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { reportUiReady } from './api'
import { Topbar } from './components/Topbar'
import { HomePage } from './components/HomePage'
import { StoryWorkspace } from './components/StoryWorkspace'
import { ComicWorkspace } from './components/ComicWorkspace'
import { ReferenceSidebar } from './components/ReferenceSidebar'
import { ReferenceAssignmentPopover } from './components/ReferenceAssignmentPopover'
import { Scene2DPanel } from './components/Scene2DPanel'
import { Scene3DPanel } from './components/Scene3DPanel'
import { SettingsModal } from './components/SettingsModal'
import { ExportModal } from './components/ExportModal'
import { ProjectProvider } from './state/ProjectContext'
import { useProject } from './state/useProject'
import { canConvertProjectToLayout2 } from './projectCapabilities'
import { LiveBridgeProvider } from './state/LiveBridgeContext'
import { useGlobalShortcuts } from './hooks/useGlobalShortcuts'
import { useAutosave } from './hooks/useAutosave'
import type { ProjectPathRequest } from './types'
import './App.css'

type WorkspaceMode = 'board' | 'comic' | 'scene2d' | 'scene3d'

function LeftRail({
  showNav,
  workspaceMode,
  refsOpen,
  onToggleRefs,
  onSetWorkspaceMode,
  onOpenSettings,
  onGoHome,
  homeBusy,
}: {
  showNav: boolean
  workspaceMode: WorkspaceMode
  refsOpen: boolean
  onToggleRefs: () => void
  onSetWorkspaceMode: (mode: WorkspaceMode) => void
  onOpenSettings: () => void
  onGoHome: () => void
  homeBusy: boolean
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
              className="left-rail-item"
              onClick={onGoHome}
              disabled={homeBusy}
              title="Save and close this document, back to Home"
            >
              <span className="left-rail-icon">&#8962;</span>
              <span>Home</span>
            </button>
          </div>
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
            <button type="button" className={`left-rail-item ${workspaceMode === 'comic' ? 'is-active' : ''}`}
              onClick={() => onSetWorkspaceMode('comic')} title="Comic pages, spreads and long scrolls"
              aria-current={workspaceMode === 'comic' ? 'page' : undefined} aria-pressed={workspaceMode === 'comic'}>
              <span className="left-rail-icon">&#9707;</span><span>Comic</span>
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

function BoardWorkspace({ active }: { active: boolean }) {
  return <StoryWorkspace active={active} />
}

function RightRail({
  onOpenSettings,
  onOpenExport,
}: {
  onOpenSettings: () => void
  onOpenExport: () => void
}) {
  const { project, newProject, openProjectFromDialog, saveProject, saveProjectAs, convertProject, dirtyShotIds, projectActionBusy, initialLoading } =
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

  const handleSaveAs = useCallback(async () => {
    try {
      await saveProjectAs()
    } catch {
      // error surfaced via banner
    }
  }, [saveProjectAs])

  const handleConvert = useCallback(async () => {
    try {
      await convertProject()
    } catch {
      // error surfaced via banner
    }
  }, [convertProject])

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
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(() => void handleSaveAs())}
                disabled={!project || projectActionBusy || initialLoading}
              >
                Save Project As…
              </button>
              {canConvertProjectToLayout2(project) ? (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(() => void handleConvert())}
                  disabled={projectActionBusy || initialLoading}
                >
                  Convert to Layout 2...
                </button>
              ) : null}
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(onOpenExport)}
                disabled={!project || projectActionBusy || initialLoading}
              >
                Export…
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
  const { lifecycle, project, initialLoading, lastError, clearError, reloadProject, closeProjectToHome, projectActionBusy, drawingActive, reportError, runProjectMutation } =
    useProject()
  const workspaceKey = project ? `${lifecycle.capture()}:${project.project_json_path}:${project.project_path}` : ''
  const [workspace, setWorkspace] = useState<{ key: string; mode: WorkspaceMode }>({ key: '', mode: 'board' })
  const workspaceMode = workspace.key === workspaceKey ? workspace.mode : project?.settings.project_type === 'comic' ? 'comic' : 'board'
  const setWorkspaceMode = (mode: WorkspaceMode) => setWorkspace({ key: workspaceKey, mode })
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [refsOpen, setRefsOpen] = useState(false)
  const uiReadyReportedRef = useRef(false)
  useGlobalShortcuts()
  useAutosave()

  const themeVars: CSSProperties = {
    '--thumb-empty-bg': project?.settings?.canvas_background_color || undefined,
    '--canvas-empty-bg': project?.settings?.canvas_background_color || undefined,
  } as CSSProperties

  // Home always saves on the way out, so there is nothing to confirm here.
  const handleGoHome = useCallback(async () => {
    try {
      await closeProjectToHome()
    } catch {
      // error surfaced via banner
    }
  }, [closeProjectToHome])

  useEffect(() => {
    void reloadProject()
  }, [reloadProject])

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
      <div className={`left-rail-dock${project ? ' is-auto-hide' : ''}`}>
        <LeftRail
          showNav={!!project}
          workspaceMode={workspaceMode}
          refsOpen={refsOpen}
          onToggleRefs={() => setRefsOpen((v) => !v)}
          onSetWorkspaceMode={mode => {
            if (drawingActive && mode !== workspaceMode) { reportError(new Error('请先保存或关闭绘画编辑器，再切换工作区。')); return }
            void runProjectMutation(async () => { setWorkspaceMode(mode) }).catch(reportError)
          }}
          onOpenSettings={() => setSettingsOpen(true)}
          onGoHome={() => void handleGoHome()}
          homeBusy={projectActionBusy}
        />
      </div>
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
          <div className={`workspace workspace-${workspaceMode}`}>
            {initialLoading ? (
              <div className="loading-panel">Loading...</div>
            ) : !project ? (
              <HomePage />
            ) : (
              <>
                <ReferenceSidebar open={refsOpen} onOpenChange={setRefsOpen} />
                <div className="workspace-content workspace-content-board" hidden={workspaceMode !== 'board'}>
                  <BoardWorkspace active={workspaceMode === 'board'} />
                </div>
                <div className="workspace-content workspace-content-comic" hidden={workspaceMode !== 'comic'}>
                  <ComicWorkspace key={workspaceKey} active={workspaceMode === 'comic'} />
                </div>
                <div className="workspace-content workspace-content-scene" hidden={workspaceMode !== 'scene2d'}>
                  <Scene2DPanel key={workspaceKey} active={workspaceMode === 'scene2d'} />
                </div>
                <div className="workspace-content workspace-content-scene" hidden={workspaceMode !== 'scene3d'}>
                  <Scene3DPanel active={workspaceMode === 'scene3d'} />
                </div>
                <div className="right-rail-dock">
                  <button
                    type="button"
                    className="right-rail-handle"
                    aria-label="Show More tools"
                    title="Hover at the right edge to show More tools"
                  />
                  <RightRail
                    onOpenSettings={() => setSettingsOpen(true)}
                    onOpenExport={() => setExportOpen(true)}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      </div>
      <ReferenceAssignmentPopover />
      {settingsOpen ? <SettingsModal open onClose={() => setSettingsOpen(false)} /> : null}
      {exportOpen ? <ExportModal open onClose={() => setExportOpen(false)} /> : null}
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
