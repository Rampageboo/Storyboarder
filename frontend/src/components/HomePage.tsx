import { useCallback, useEffect, useState } from 'react'
import { BookOpen, FilmSlate, FilmStrip, FolderOpen, MagnifyingGlass, WarningCircle, X } from '@phosphor-icons/react'
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
  const meta = [boards, formatSize(entry.size_bytes), formatModified(entry.modified_ms)].filter(Boolean).join(' · ')

  if (!entry.exists) {
    return (
      <div className="home-card is-missing">
        <div className="home-card-thumb is-missing">
          <WarningCircle size={22} />
          <span>Not found</span>
        </div>
        <div className="home-card-body">
          <span className="home-card-name">{entry.name}</span>
          <span className="home-card-location" title={entry.path}>{entry.location}</span>
          <div className="home-card-actions">
            <button type="button" className="ghost" onClick={onForget} disabled={disabled}>Remove from recent</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="home-card">
      <button type="button" className="home-card-open" onClick={onOpen} disabled={disabled} title={entry.path}>
        <span className="home-card-thumb">
          {entry.thumbnail ? <img src={entry.thumbnail} alt="" loading="lazy" /> : <FilmSlate size={26} className="home-card-thumb-empty" />}
        </span>
        <span className="home-card-body">
          <span className="home-card-title-row">
            <span className="home-card-name">{entry.name}</span>
            <span className="home-card-kind">{entry.kind === 'folder' ? 'FOLDER' : 'SBD'}</span>
          </span>
          <span className="home-card-meta">{meta}</span>
          <span className="home-card-location">{entry.location}</span>
        </span>
      </button>
      <button
        type="button"
        className="ghost icon-btn home-card-forget"
        onClick={onForget}
        disabled={disabled}
        aria-label={`Remove ${entry.name} from recent`}
        title="Remove from recent"
      >
        <X size={14} />
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
  const [filter, setFilter] = useState('')

  const refresh = useCallback(() => listRecents()
    .then(result => setRecents(result.recents))
    // A recents read failure must not block New/Open — leave the grid empty.
    .catch(() => setRecents([]))
    .finally(() => setLoading(false)), [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleNew = useCallback(async (projectType: 'video' | 'comic') => {
    try {
      await newProject({ path: null, ...DEFAULT_CANVAS, project_type: projectType })
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

  const visible = filter.trim()
    ? recents.filter((entry) => `${entry.name} ${entry.location}`.toLowerCase().includes(filter.trim().toLowerCase()))
    : recents

  return (
    <div className="home-page">
      <aside className="home-sidebar">
        <div>
          <h1 className="home-title">Start a project</h1>
          <p className="home-lede">A project is a portable folder: one .sbd document plus the PSDs, previews and references it links.</p>
        </div>
        <div className="home-actions">
          <button type="button" className="home-action is-primary" onClick={() => void handleNew('video')} disabled={projectActionBusy}>
            <FilmStrip size={20} />
            <span><strong>New storyboard</strong><small>Boards, routes and animatic</small></span>
            <span className="kbd">Ctrl N</span>
          </button>
          <button type="button" className="home-action" onClick={() => void handleNew('comic')} disabled={projectActionBusy}>
            <BookOpen size={20} />
            <span><strong>New comic</strong><small>Chapters, pages and long scrolls</small></span>
          </button>
          <button type="button" className="home-action" onClick={() => void handleOpen()} disabled={projectActionBusy}>
            <FolderOpen size={20} />
            <span><strong>Open project…</strong><small>.sbd file or project folder</small></span>
            <span className="kbd">Ctrl O</span>
          </button>
        </div>
      </aside>

      <section className="home-main" aria-labelledby="home-recent-title">
        <div className="home-recent-head">
          <h2 id="home-recent-title">Recent</h2>
          {recents.length > 0 ? <span className="home-recent-count">{recents.length}</span> : null}
          {recents.length > 3 ? (
            <label className="home-filter">
              <MagnifyingGlass size={15} />
              <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter projects" aria-label="Filter recent projects" />
            </label>
          ) : null}
        </div>

        {loading ? (
          <p className="home-empty">Loading recent projects…</p>
        ) : recents.length === 0 ? (
          <div className="home-empty-state">
            <FilmSlate size={30} />
            <p>No recent projects yet.</p>
            <p className="home-empty">Create a storyboard or comic, or open an existing .sbd.</p>
          </div>
        ) : (
          <div className="home-grid">
            {visible.map((entry) => (
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
