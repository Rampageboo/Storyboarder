import { useEffect } from 'react'
import { Topbar } from './components/Topbar'
import { ShotInspector } from './components/ShotInspector'
import { Timeline } from './components/Timeline'
import { CanvasBoard } from './components/CanvasBoard'
import { AdvancedPanel } from './components/AdvancedPanel'
import { ProjectProvider, useProject } from './state/ProjectContext'
import './App.css'

function AppInner() {
  const { reloadProject } = useProject()

  useEffect(() => {
    void reloadProject()
  }, [reloadProject])

  return (
    <div className="app-root">
      <Topbar />
      <div className="workspace">
        <aside className="sidebar">
          <Timeline />
        </aside>
        <main className="main">
          <div className="main-split">
            <CanvasBoard />
            <div className="main-right">
              <ShotInspector />
              <AdvancedPanel />
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ProjectProvider>
      <AppInner />
    </ProjectProvider>
  )
}
