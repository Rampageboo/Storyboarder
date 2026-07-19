import { useCallback, useEffect, useState } from 'react'
import { preheatPhotoshop } from '../api'
import { useProject } from '../state/useProject'
import { bridgeStatusLabel, useBridgeStatus } from '../state/liveBridgeUtils'
import './Topbar.css'

const PREHEAT_COUNTDOWN_SECONDS = 10
let preheatSessionState: 'ready' | 'countdown' | 'cancelled' | 'attempted' = 'ready'

type WorkspaceMode = 'board' | 'scene2d' | 'scene3d'

const workspaceLabels: Record<WorkspaceMode, string> = {
  board: 'Board workspace',
  scene2d: 'Scene library',
  scene3d: 'Scene 3D workspace',
}

function shortShotId(shotId: string) {
  return shotId.length > 12 ? `${shotId.slice(0, 8)}...` : shotId
}

function latestPreviewExport(exports: Record<string, number> | undefined) {
  const entries = Object.entries(exports ?? {}).filter(([, value]) => Number.isFinite(value))
  if (!entries.length) return ''
  const [shotId, timestamp] = entries.reduce((latest, current) => (current[1] > latest[1] ? current : latest))
  return `${shortShotId(shotId)} ${new Date(timestamp * 1000).toLocaleTimeString()}`
}

function photoshopStatusTitle(label: string, selectedShotId: string, openShotIds: string[], lastExport: string) {
  const parts = [label]
  if (selectedShotId) parts.push(`Current: ${selectedShotId}`)
  if (openShotIds.length) parts.push(`Open tabs: ${openShotIds.join(', ')}`)
  if (lastExport) parts.push(`Last preview export: ${lastExport}`)
  return parts.join('\n')
}

export function Topbar({ workspaceMode }: { workspaceMode: WorkspaceMode }) {
  const { project, dirtyShotIds, initialLoading } = useProject()
  const bridgeStatus = useBridgeStatus()
  const [preheatState, setPreheatState] = useState<'idle' | 'countdown' | 'preheating'>('idle')
  const [preheatSeconds, setPreheatSeconds] = useState(PREHEAT_COUNTDOWN_SECONDS)

  const cancelPreheatCountdown = useCallback(() => {
    if (preheatSessionState !== 'countdown') return
    preheatSessionState = 'cancelled'
    setPreheatState('idle')
  }, [])

  const projectPreheatEnabled = Boolean(project?.settings?.preheat_photoshop_on_open)
  const projectSessionKey = project?.project_json_path ?? project?.project_path ?? ''
  const psAlreadyLinked = Boolean(bridgeStatus?.plugin_linked)

  useEffect(() => {
    if (initialLoading) return
    if (!projectPreheatEnabled) return
    if (!projectSessionKey) return
    if (preheatSessionState !== 'ready') return
    if (psAlreadyLinked) {
      // PS is already running and connected — no need to preheat.
      preheatSessionState = 'attempted'
      return
    }

    preheatSessionState = 'countdown'
    const kickoff = window.setTimeout(() => {
      setPreheatSeconds(PREHEAT_COUNTDOWN_SECONDS)
      setPreheatState('countdown')
    }, 0)

    let remaining = PREHEAT_COUNTDOWN_SECONDS
    const timer = window.setInterval(() => {
      remaining -= 1
      if (remaining > 0) {
        setPreheatSeconds(remaining)
        return
      }

      window.clearInterval(timer)
      if (preheatSessionState !== 'countdown') return
      preheatSessionState = 'attempted'
      setPreheatState('preheating')
      void preheatPhotoshop()
        .catch(() => {
          // Best-effort warmup; missing/unsupported Photoshop must not affect the app.
        })
        .finally(() => {
          setPreheatState('idle')
        })
    }, 1000)

    return () => {
      window.clearTimeout(kickoff)
      window.clearInterval(timer)
      if (preheatSessionState === 'countdown') {
        preheatSessionState = 'ready'
        window.setTimeout(() => setPreheatState('idle'), 0)
      }
    }
  }, [initialLoading, projectPreheatEnabled, projectSessionKey, psAlreadyLinked])

  const hasUnsaved = !!project && (project.dirty || dirtyShotIds.length > 0)
  const projectLabel = project ? `${project.name}${hasUnsaved ? ' *' : ''}` : 'Storyboarder'
  const shotCount = project?.shots.length ?? 0
  const subtitle = project
    ? `${shotCount} shot${shotCount === 1 ? '' : 's'}${hasUnsaved ? ' | unsaved changes' : ''}`
    : initialLoading
      ? 'Loading...'
      : 'Open or create a project'

  const psLabel = bridgeStatusLabel(bridgeStatus, !!project)
  const psSelectedShot = bridgeStatus?.plugin_selected_shot_id ?? ''
  const psOpenShots = bridgeStatus?.plugin_open_shot_ids ?? []
  const psLastExport = latestPreviewExport(bridgeStatus?.plugin_last_exported_preview)
  const psDetails = [
    psSelectedShot ? shortShotId(psSelectedShot) : '',
    psOpenShots.length ? `${psOpenShots.length} open` : '',
    psLastExport ? 'exported' : '',
  ].filter(Boolean)
  const psVisibleLabel = psDetails.length ? `${psLabel} | ${psDetails.join(' | ')}` : psLabel
  const preheatCountdownActive = preheatState === 'countdown'
  const preheatBusy = preheatState === 'preheating'
  const psDisplayLabel = preheatCountdownActive
    ? `Preheat PS in ${preheatSeconds}s`
    : preheatBusy
      ? 'Preheating Photoshop...'
      : psVisibleLabel
  const psStatusTitle = preheatCountdownActive
    ? 'Click to cancel Photoshop preheat for this app session.'
    : preheatBusy
      ? 'Launching Photoshop in the background.'
      : photoshopStatusTitle(psLabel, psSelectedShot, psOpenShots, psLastExport)

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="topbar-project-copy">
          <div className="topbar-title">{projectLabel}</div>
          <div className="topbar-subtitle">{subtitle}</div>
        </div>
      </div>

      <div className="topbar-center">
        <div className="topbar-context">{workspaceLabels[workspaceMode]}</div>
      </div>

      <div className="topbar-right">
        <button
          type="button"
          className={`topbar-ps-status ${bridgeStatus?.plugin_linked && !preheatCountdownActive && !preheatBusy ? 'is-linked' : ''} ${preheatCountdownActive ? 'is-preheat-countdown' : ''} ${preheatBusy ? 'is-preheating' : ''}`}
          title={psStatusTitle}
          onClick={preheatCountdownActive ? cancelPreheatCountdown : undefined}
          aria-label={preheatCountdownActive ? 'Cancel Photoshop preheat' : psDisplayLabel}
        >
          {psDisplayLabel}
        </button>
      </div>
    </header>
  )
}
