import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { X } from '@phosphor-icons/react'
import { reportUiReady } from './api'
import { Topbar, type WorkspaceMode } from './components/Topbar'
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
import { LiveBridgeProvider } from './state/LiveBridgeContext'
import { useGlobalShortcuts } from './hooks/useGlobalShortcuts'
import { useAutosave } from './hooks/useAutosave'
import './App.css'

function AppInner() {
  const { lifecycle, project, initialLoading, lastError, clearError, reloadProject, closeProjectToHome, drawingActive, reportError, runProjectMutation } =
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

  const changeWorkspace = (mode: WorkspaceMode) => {
    if (mode === workspaceMode) return
    if (drawingActive) { reportError(new Error('Save or close the drawing editor before switching workspace.')); return }
    void runProjectMutation(async () => { setWorkspaceMode(mode) }).catch(reportError)
  }

  return (
    <div className="app-root" style={themeVars}>
      <Topbar
        workspaceMode={workspaceMode}
        onSetWorkspaceMode={changeWorkspace}
        refsOpen={refsOpen}
        onToggleRefs={() => setRefsOpen((v) => !v)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenExport={() => setExportOpen(true)}
        onGoHome={() => handleGoHome()}
      />
      {lastError ? (
        <div className="app-banner" role="alert">
          <span>{lastError}</span>
          <button type="button" className="ghost icon-btn" onClick={clearError} aria-label="Dismiss error">
            <X size={14} />
          </button>
        </div>
      ) : null}
      <div className="workspace-shell">
        <div className={`workspace workspace-${workspaceMode}`}>
          {initialLoading ? (
            <div className="loading-panel">Loading…</div>
          ) : !project ? (
            <HomePage />
          ) : (
            <>
              <ReferenceSidebar open={refsOpen} onOpenChange={setRefsOpen} />
              <div className="workspace-content workspace-content-board" hidden={workspaceMode !== 'board'}>
                <StoryWorkspace active={workspaceMode === 'board'} />
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
            </>
          )}
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
