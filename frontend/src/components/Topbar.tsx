import { useCallback } from 'react'
import { useProject } from '../state/useProject'
import { useBridgeStatus, bridgeStatusLabel } from '../state/liveBridgeUtils'
import type { ProjectPathRequest } from '../types'
import './Topbar.css'

function shortShotId(shotId: string) {
  return shotId.length > 12 ? `${shotId.slice(0, 8)}...` : shotId
}

function latestPreviewExport(exports: Record<string, number> | undefined) {
  const entries = Object.entries(exports ?? {}).filter(([, value]) => Number.isFinite(value))
  if (!entries.length) return ''
  const [shotId, timestamp] = entries.reduce((latest, current) => (current[1] > latest[1] ? current : latest))
  return `${shortShotId(shotId)} ${new Date(timestamp * 1000).toLocaleTimeString()}`
}

function photoshopStatusTitle(
  label: string,
  selectedShotId: string,
  openShotIds: string[],
  lastExport: string,
) {
  const parts = [label]
  if (selectedShotId) parts.push(`Current: ${selectedShotId}`)
  if (openShotIds.length) parts.push(`Open tabs: ${openShotIds.join(', ')}`)
  if (lastExport) parts.push(`Last preview export: ${lastExport}`)
  return parts.join('\n')
}

interface TopbarProps {
  onOpenSettings: () => void
}

export function Topbar({ onOpenSettings }: TopbarProps) {
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
  const psLabel = bridgeStatusLabel(bridgeStatus, !!project)
  const psSelectedShot = bridgeStatus?.plugin_selected_shot_id ?? ''
  const psOpenShots = bridgeStatus?.plugin_open_shot_ids ?? []
  const psLastExport = latestPreviewExport(bridgeStatus?.plugin_last_exported_preview)
  const psDetails = [
    psSelectedShot ? shortShotId(psSelectedShot) : '',
    psOpenShots.length ? `${psOpenShots.length} open` : '',
    psLastExport ? 'exported' : '',
  ].filter(Boolean)
  const psVisibleLabel = psDetails.length ? `${psLabel} · ${psDetails.join(' · ')}` : psLabel

  let subtitle = 'Open a project folder or create a new project folder.'
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
            Open Folder
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
        <button
          type="button"
          className="topbar-settings"
          onClick={onOpenSettings}
          disabled={!project || projectActionBusy || initialLoading}
          title="Settings"
          aria-label="Settings"
        >
          Settings
        </button>
        <span
          className={`topbar-ps-status ${bridgeStatus?.plugin_linked ? 'is-linked' : ''}`}
          title={photoshopStatusTitle(psLabel, psSelectedShot, psOpenShots, psLastExport)}
        >
          {psVisibleLabel}
        </span>
      </div>
    </header>
  )
}
