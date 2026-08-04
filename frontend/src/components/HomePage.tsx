import { useCallback, useEffect, useState } from 'react'
import { forgetRecent, listRecents } from '../api'
import type { RecentProject } from '../api/system'
import { useProject } from '../state/useProject'
import './HomePage.css'

const DEFAULT_CANVAS = { canvas_width: 1920, canvas_height: 1080 }

function formatModified(ms: number): string {
  if (!ms) return ''
  const date = new Date(ms)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function formatSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 100 * 1024 * 1024 ? 1 : 0)} MB`
}

function RecentCard({
  entry,
  disabled,
  onOpen,
  onForget,
}: {
  entry: RecentProject
  disabled: boolean
  onOpen: () => void
  onForget: () => void
}) {
  const boards = entry.shot_count === 1 ? '1 board' : `${entry.shot_count} boards`
  const meta = [entry.exists ? boards : 'Not found', formatSize(entry.size_bytes), formatModified(entry.modified_ms)]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className={`home-card${entry.exists ? '' : ' is-missing'}`}>
      <button
        type="button"
        className="home-card-open"
        onClick={onOpen}
        disabled={disabled || !entry.exists}
        title={entry.exists ? entry.path : `Missing: ${entry.path}`}
      >
        <span className="home-card-thumb">
          {entry.thumbnail ? (
            <img src={entry.thumbnail} alt="" loading="lazy" />
          ) : (
            <span className="home-card-thumb-empty" aria-hidden="true">
              {entry.kind === 'folder' ? '▤' : '▦'}
            </span>
          )}
          <span className="home-card-kind">{entry.kind === 'folder' ? 'FOLDER' : 'SBD'}</span>
        </span>
        <span className="home-card-name">{entry.name}</span>
        <span className="home-card-meta">{meta}</span>
        <span className="home-card-location">{entry.location}</span>
      </button>
      <button
        type="button"
        className="home-card-forget"
        onClick={onForget}
        disabled={disabled}
        aria-label={`Remove ${entry.name} from recent`}
        title="Remove from recent"
      >
        &times;
      </button>
    </div>
  )
}

/**
 * Landing screen. Startup no longer reopens the last document, so this is where
 * the app begins and where "Home" returns to after closing one.
 */
export function HomePage() {
  const { newProject, openProjectFromDialog, openProjectPath, projectActionBusy, reportError } = useProject()
  const [recents, setRecents] = useState<RecentProject[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const result = await listRecents()
      setRecents(result.recents)
    } catch {
      // A recents read failure must not block New/Open — leave the grid empty.
      setRecents([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleNew = useCallback(async () => {
    try {
      await newProject({ path: null, ...DEFAULT_CANVAS })
    } catch {
      // surfaced via the app error banner
    }
  }, [newProject])

  const handleOpen = useCallback(async () => {
    try {
      await openProjectFromDialog()
    } catch {
      // surfaced via the app error banner
    }
  }, [openProjectFromDialog])

  const handleOpenRecent = useCallback(
    async (entry: RecentProject) => {
      try {
        await openProjectPath(entry.open_path)
      } catch {
        // The document may have moved since it was listed; refresh so the card
        // updates to "Not found" instead of silently failing again.
        void refresh()
      }
    },
    [openProjectPath, refresh],
  )

  const handleForget = useCallback(
    async (entry: RecentProject) => {
      try {
        const result = await forgetRecent(entry.path)
        setRecents(result.recents)
      } catch (error) {
        reportError(error)
      }
    },
    [reportError],
  )

  return (
    <div className="home-page">
      <aside className="home-sidebar">
        <button type="button" className="home-action primary" onClick={() => void handleNew()} disabled={projectActionBusy}>
          New file
        </button>
        <button type="button" className="home-action" onClick={() => void handleOpen()} disabled={projectActionBusy}>
          Open
        </button>
        <div className="home-sidebar-note">
          <p>Each project is a portable folder with a lightweight .sbd document and editable assets.</p>
        </div>
      </aside>

      <section className="home-main">
        <h1 className="home-title">Welcome to Storyboarder</h1>
        <div className="home-recent-head">
          <h2>Recent</h2>
          {recents.length > 0 ? <span className="home-recent-count">{recents.length}</span> : null}
        </div>

        {loading ? (
          <p className="home-empty">Loading recent documents...</p>
        ) : recents.length === 0 ? (
          <p className="home-empty">No recent documents yet. Create one with New file, or open an existing .sbd.</p>
        ) : (
          <div className="home-grid">
            {recents.map((entry) => (
              <RecentCard
                key={entry.path}
                entry={entry}
                disabled={projectActionBusy}
                onOpen={() => void handleOpenRecent(entry)}
                onForget={() => void handleForget(entry)}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
