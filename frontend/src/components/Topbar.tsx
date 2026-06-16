import { useCallback } from 'react'
import { useProject } from '../state/ProjectContext'
import { useBridgeStatus, bridgeStatusLabel } from '../state/LiveBridgeContext'
import type { ProjectPathRequest } from '../types'
import './Topbar.css'

export function Topbar() {
  const {
    project,
    newProject,
    openProjectFromDialog,
    saveProject,
    dirtyShotIds,
    projectActionBusy,
    initialLoading,
  } = useProject()
  const bridgeStatus = useBridgeStatus()

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

  const hasUnsaved = !!project && (project.dirty || dirtyShotIds.length > 0)
  const projectLabel = project ? `${project.name}${hasUnsaved ? ' *' : ''}` : 'No project open'

  let subtitle = 'Open or create a project to begin.'
  if (initialLoading) {
    subtitle = 'Loading…'
  } else if (project) {
    const dirtyNote = hasUnsaved ? ' · unsaved changes' : ''
    const shotNote = `${project.shots.length} shot${project.shots.length === 1 ? '' : 's'}`
    subtitle = `${shotNote}${dirtyNote}`
    if (dirtyShotIds.length > 0) {
      subtitle += ` · ${dirtyShotIds.length} shot edit${dirtyShotIds.length === 1 ? '' : 's'} pending`
    }
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="topbar-group">
          <button type="button" onClick={() => void handleNew()} disabled={projectActionBusy || initialLoading}>
            New
          </button>
          <button type="button" onClick={() => void handleOpen()} disabled={projectActionBusy || initialLoading}>
            Open
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!project || !hasUnsaved || projectActionBusy}
            title={hasUnsaved ? 'Save project and pending shot edits' : 'Nothing to save'}
          >
            {projectActionBusy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
      <div className="topbar-center">
        <div className="topbar-title">{projectLabel}</div>
        <div className="topbar-subtitle">{subtitle}</div>
      </div>
      <div className="topbar-right">
        <span
          className={`topbar-ps-status ${bridgeStatus?.plugin_linked ? 'is-linked' : ''}`}
          title={bridgeStatusLabel(bridgeStatus, !!project)}
        >
          {bridgeStatusLabel(bridgeStatus, !!project)}
        </span>
      </div>
    </header>
  )
}
