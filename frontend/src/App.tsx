import { useCallback, useEffect } from 'react'
import { Topbar } from './components/Topbar'
import { ShotInspector } from './components/ShotInspector'
import { Timeline } from './components/Timeline'
import { CanvasBoard } from './components/CanvasBoard'
import { BoardOverview } from './components/BoardOverview'
import { ReferencePanel } from './components/ReferencePanel'
import { AdvancedPanel } from './components/AdvancedPanel'
import { ProjectProvider, useProject } from './state/ProjectContext'
import { LiveBridgeProvider } from './state/LiveBridgeContext'
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
        <aside className="sidebar">
          <Timeline />
        </aside>
        {initialLoading ? (
          <div className="loading-panel">Loading project…</div>
        ) : !project ? (
          <WelcomePanel />
        ) : (
          <>
            <main className="main-center">
              <CanvasBoard />
              <BoardOverview />
            </main>
            <aside className="main-right">
              <ShotInspector />
              <ReferencePanel />
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
