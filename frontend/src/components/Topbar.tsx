import { useCallback, useEffect, useRef, useState } from 'react'
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
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [openMenu, setOpenMenu] = useState<'file' | 'view' | null>(null)

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

  const closeMenu = useCallback(() => {
    setOpenMenu(null)
  }, [])

  useEffect(() => {
    if (!openMenu) return
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
  }, [openMenu, closeMenu])

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
  const newDisabled = projectActionBusy || initialLoading
  const openDisabled = projectActionBusy || initialLoading
  const saveDisabled = !project || !hasUnsaved || projectActionBusy
  const settingsDisabled = !project || projectActionBusy || initialLoading

  const runMenuAction = useCallback((action: () => void) => {
    closeMenu()
    action()
  }, [closeMenu])

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
        <div className="topbar-menu" ref={menuRef}>
          <div className="topbar-menu-item">
            <button
              type="button"
              className="topbar-menu-label"
              aria-haspopup="menu"
              aria-expanded={openMenu === 'file'}
              onClick={() => setOpenMenu((value) => (value === 'file' ? null : 'file'))}
            >
              File
            </button>
            {openMenu === 'file' ? (
              <div className="topbar-dropdown" role="menu" aria-label="File">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(() => void handleNew())}
                  disabled={newDisabled}
                >
                  New Project
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(() => void handleOpen())}
                  disabled={openDisabled}
                >
                  Open Project Folder
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(() => void handleSave())}
                  disabled={saveDisabled}
                  title={hasUnsaved ? 'Save project and pending shot edits' : 'Nothing to save'}
                >
                  {projectActionBusy ? 'Saving…' : 'Save Project'}
                </button>
              </div>
            ) : null}
          </div>

          <div className="topbar-menu-item">
            <button
              type="button"
              className="topbar-menu-label"
              aria-haspopup="menu"
              aria-expanded={openMenu === 'view'}
              onClick={() => setOpenMenu((value) => (value === 'view' ? null : 'view'))}
            >
              View
            </button>
            {openMenu === 'view' ? (
              <div className="topbar-dropdown" role="menu" aria-label="View">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(onOpenSettings)}
                  disabled={settingsDisabled}
                >
                  Settings
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div className="topbar-center">
        <div className="topbar-title">{projectLabel}</div>
        <div className="topbar-subtitle">{subtitle}</div>
      </div>

      <div className="topbar-right">
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
