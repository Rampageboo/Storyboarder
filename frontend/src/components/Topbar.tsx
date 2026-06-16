import { useCallback } from 'react'
import { browseProjectJson } from '../api'
import { useProject } from '../state/ProjectContext'
import type { ProjectPathRequest } from '../types'
import './Topbar.css'

export function Topbar() {
  const { project, newProject, openProject, saveProject, flushDirtyShots, dirtyShotIds, lastError, clearError } =
    useProject()

  const handleNew = useCallback(async () => {
    const body: ProjectPathRequest = {
      path: null,
      canvas_width: 1920,
      canvas_height: 1080,
    }
    try {
      await newProject(body)
    } catch {
      // Flush/create failed — error already surfaced via lastError; keep current state.
    }
  }, [newProject])

  const handleOpen = useCallback(async () => {
    // Flush unsaved edits before discarding the current project. Abort if it fails.
    try {
      await flushDirtyShots()
    } catch {
      return
    }
    let result
    try {
      result = await browseProjectJson()
    } catch (error) {
      window.alert(error instanceof Error ? error.message : String(error))
      return
    }
    if (result.cancelled || !result.path) return
    try {
      await openProject({ project_json_path: result.path })
    } catch {
      // error already surfaced via lastError
    }
  }, [flushDirtyShots, openProject])

  const handleSave = useCallback(async () => {
    try {
      await saveProject()
    } catch {
      // error already surfaced via lastError
    }
  }, [saveProject])

  const hasUnsaved = !!project && (project.dirty || dirtyShotIds.length > 0)
  const projectLabel = project ? `${project.name}${hasUnsaved ? ' *' : ''}` : 'No project open'

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="topbar-group">
          <button type="button" onClick={handleNew}>
            New
          </button>
          <button type="button" onClick={handleOpen}>
            Open
          </button>
          <button type="button" onClick={handleSave} disabled={!project || !hasUnsaved}>
            Save
          </button>
        </div>
      </div>
      <div className="topbar-center">
        <div className="topbar-title">{projectLabel}</div>
        {lastError ? (
          <div className="topbar-error" role="alert">
            <span>{lastError}</span>
            <button type="button" className="topbar-error-close" onClick={clearError} aria-label="Close">
              ×
            </button>
          </div>
        ) : (
          <div className="topbar-subtitle">Open or create a project to begin.</div>
        )}
      </div>
      <div className="topbar-right" />
    </header>
  )
}
