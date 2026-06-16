import { useCallback, useEffect } from 'react'
import { Topbar } from './components/Topbar'
import { ShotInspector } from './components/ShotInspector'
import { BoardStrip } from './components/BoardStrip'
import { CanvasBoard } from './components/CanvasBoard'
import { ReferencePanel } from './components/ReferencePanel'
import { ReferenceSidebar } from './components/ReferenceSidebar'
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
        <p>Create a new storyboard project or open an existing project.json file.</p>
        <div className="welcome-actions">
          <button type="button" className="primary" onClick={() => void handleNew()} disabled={projectActionBusy}>
            New project
          </button>
          <button type="button" onClick={() => void handleOpen()} disabled={projectActionBusy}>
            Open project
          </button>
        </div>
      </div>
    </div>
  )
}

function AppInner() {
  const { project, initialLoading, lastError, clearError, reloadProject } = useProject()
  useGlobalShortcuts()

  useEffect(() => {
    void reloadProject()
  }, [reloadProject])

  return (
    <div className="app-root">
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
