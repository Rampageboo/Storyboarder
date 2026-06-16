import { useCallback } from 'react'
import { useProject } from '../state/ProjectContext'
import type { ProjectPathRequest } from '../types'
import './Topbar.css'

export function Topbar() {
  const { project, newProject, openProject, saveProject, lastError, clearError } = useProject()

  const handleNew = useCallback(async () => {
    const body: ProjectPathRequest = {
      path: null,
      canvas_width: 1920,
      canvas_height: 1080,
    }
    await newProject(body)
  }, [newProject])

  const handleOpen = useCallback(async () => {
    const projectJsonPath = window.prompt(
      '请输入 project.json 的完整路径：\n例如 D:\\\\MyProject\\\\Storyboard_Project\\\\project.json',
    )
    if (!projectJsonPath) return
    await openProject({ project_json_path: projectJsonPath })
  }, [openProject])

  const handleSave = useCallback(async () => {
    await saveProject()
  }, [saveProject])

  const projectLabel = project ? `${project.name}${project.dirty ? ' *' : ''}` : 'No project open'

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
          <button type="button" onClick={handleSave} disabled={!project || !project.dirty}>
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

