import { useCallback, useEffect, type CSSProperties } from 'react'
import { Topbar } from './components/Topbar'
import { ShotInspector } from './components/ShotInspector'
import { BoardStrip } from './components/BoardStrip'
import { CanvasBoard } from './components/CanvasBoard'
import { ReferencePanel } from './components/ReferencePanel'
import { ReferenceSidebar } from './components/ReferenceSidebar'
import { ReferenceAssignmentPopover } from './components/ReferenceAssignmentPopover'
import { Scene3DPanel } from './components/Scene3DPanel'
import { NeighborContext } from './components/NeighborContext'
import { AdvancedPanel } from './components/AdvancedPanel'
import { ProjectProvider, useProject } from './state/ProjectContext'
import { LiveBridgeProvider } from './state/LiveBridgeContext'
import { useGlobalShortcuts } from './hooks/useGlobalShortcuts'
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

function AppInner() {
  const { project, initialLoading, lastError, clearError, reloadProject } = useProject()
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
            ×
          </button>
        </div>
      ) : null}
      <div className="workspace">
        {initialLoading ? (
          <div className="loading-panel">Loading project…</div>
        ) : !project ? (
          <WelcomePanel />
        ) : (
          <>
            <ReferenceSidebar />
            <main className="main-center">
              <CanvasBoard />
              <NeighborContext />
              <BoardStrip />
            </main>
            <aside className="main-right">
              <ShotInspector />
              <ReferencePanel />
              <Scene3DPanel />
              <AdvancedPanel />
            </aside>
          </>
        )}
      </div>
      <ReferenceAssignmentPopover />
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
