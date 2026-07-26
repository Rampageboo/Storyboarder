import { useCallback, useEffect, useRef, useState } from 'react'
import {
  exportAnimatic,
  exportContactSheet,
  exportImageSequence,
  exportPdf,
  exportShotList,
  exportTiming,
  openExport,
  resolveBoardRange,
} from '../api'
import type { ExportResult, ExportScope, ExportType, PdfLayout, ResolvedRange } from '../api/export'
import { useProject } from '../state/useProject'
import './ExportModal.css'

interface ExportModalProps {
  open: boolean
  onClose: () => void
}

type RangeMode = 'all' | 'current' | 'custom'

const RANGE_DEBOUNCE_MS = 200

export function ExportModal({ open, onClose }: ExportModalProps) {
  const { project, selectedShotId, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [busy, setBusy] = useState<ExportType | ''>('')
  // Keeps the scope each file was written with, so Open still finds it after the
  // range moves.
  const [done, setDone] = useState<Partial<Record<ExportType, ExportScope>>>({})
  const [pdfLayout, setPdfLayout] = useState<PdfLayout>('one_per_page')
  const [fps, setFps] = useState(24)
  const [captions, setCaptions] = useState(false)
  const [rangeMode, setRangeMode] = useState<RangeMode>('all')
  const [customRange, setCustomRange] = useState('')
  const [resolved, setResolved] = useState<ResolvedRange | null>(null)

  const totalBoards = project?.shots.length ?? 0
  const selectedIndex = project ? project.shots.findIndex((shot) => shot.shot_id === selectedShotId) : -1
  const selectedBoard = selectedIndex >= 0 ? selectedIndex + 1 : 0

  // One spec drives every export below. Empty means the whole storyboard, so
  // "current board" is just the shorthand for its own number.
  const boards = rangeMode === 'custom' ? customRange : rangeMode === 'current' && selectedBoard ? String(selectedBoard) : ''
  const scope: ExportScope = boards ? { boards } : {}

  // Validate as the user types, on the backend's parser rather than a second
  // copy of the grammar here.
  const requestId = useRef(0)
  const customIsBlank = rangeMode === 'custom' && customRange.trim() === ''

  // A blank field means "not chosen yet", not "everything" — never resolve it,
  // or an empty Range would silently export the whole storyboard.
  const shouldResolve = open && rangeMode === 'custom' && !customIsBlank
  useEffect(() => {
    if (!shouldResolve) return
    const id = ++requestId.current
    const timer = window.setTimeout(() => {
      void resolveBoardRange(customRange)
        .then((result) => {
          if (id === requestId.current) setResolved(result)
        })
        .catch(() => {
          if (id === requestId.current) setResolved(null)
        })
    }, RANGE_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [shouldResolve, customRange])

  // Stale feedback is cleared where the change happens, not from an effect.
  const chooseRangeMode = useCallback((mode: RangeMode) => {
    requestId.current += 1
    setResolved(null)
    setRangeMode(mode)
  }, [])

  const editCustomRange = useCallback((value: string) => {
    requestId.current += 1
    setResolved(null)
    setCustomRange(value)
  }, [])

  const rangeInvalid = rangeMode === 'custom' && (customIsBlank || !resolved || !!resolved.error || resolved.count === 0)

  const run = useCallback(
    async (type: ExportType, usedScope: ExportScope, fn: () => Promise<ExportResult>) => {
      setBusy(type)
      try {
        await flushDirtyShots()
        await fn()
        setDone((prev) => ({ ...prev, [type]: usedScope }))
      } catch (error) {
        reportError(error)
      } finally {
        setBusy('')
      }
    },
    [flushDirtyShots, reportError],
  )

  const reveal = useCallback(
    async (type: ExportType, revealScope: ExportScope) => {
      try {
        await openExport(type, revealScope)
      } catch (error) {
        reportError(error)
      }
    },
    [reportError],
  )

  if (!open || !project) return null

  const disabled = busy !== '' || projectActionBusy || rangeInvalid
  const suffix = rangeMode === 'all' ? '' : rangeMode === 'current' ? `_board-${String(selectedBoard).padStart(3, '0')}` : resolved?.suffix ?? ''

  const openButton = (type: ExportType, label = 'Open') => {
    const usedScope = done[type]
    return usedScope ? (
      <button type="button" className="export-open" onClick={() => void reveal(type, usedScope)} disabled={disabled}>
        {label}
      </button>
    ) : null
  }

  return (
    <div className="export-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="export-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="export-modal-header">
          <div>
            <h2 id="export-modal-title">Export</h2>
            <p>Generate a video, printable pages, or data from this storyboard.</p>
          </div>
          <button type="button" className="export-modal-close" onClick={onClose} aria-label="Close export">
            x
          </button>
        </div>

        <div className="export-range">
          <div className="export-range-modes" role="radiogroup" aria-label="Export range">
            <button
              type="button"
              role="radio"
              aria-checked={rangeMode === 'all'}
              className={rangeMode === 'all' ? 'is-active' : ''}
              onClick={() => chooseRangeMode('all')}
              disabled={busy !== ''}
            >
              All boards
              <small>{totalBoards} total</small>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={rangeMode === 'current'}
              className={rangeMode === 'current' ? 'is-active' : ''}
              onClick={() => chooseRangeMode('current')}
              disabled={busy !== '' || !selectedBoard}
              title={selectedBoard ? `Export only board ${selectedBoard}` : 'Select a board first'}
            >
              Current board
              <small>{selectedBoard ? `Board ${selectedBoard}` : 'none selected'}</small>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={rangeMode === 'custom'}
              className={rangeMode === 'custom' ? 'is-active' : ''}
              onClick={() => chooseRangeMode('custom')}
              disabled={busy !== ''}
            >
              Range
              <small>e.g. 1-5, 8</small>
            </button>
          </div>

          {rangeMode === 'custom' ? (
            <div className="export-range-input">
              <label htmlFor="export-range-field">Boards</label>
              <input
                id="export-range-field"
                type="text"
                value={customRange}
                onChange={(event) => editCustomRange(event.target.value)}
                placeholder={totalBoards > 1 ? `1-${totalBoards}, or 1-3, 6` : '1'}
                spellCheck={false}
                autoComplete="off"
                disabled={busy !== ''}
                aria-invalid={!!resolved?.error}
                aria-describedby="export-range-status"
              />
              <span
                id="export-range-status"
                className={`export-range-status${resolved?.error ? ' is-error' : ''}`}
                role={resolved?.error ? 'alert' : undefined}
              >
                {resolved?.error || resolved?.label || 'Enter a board range'}
              </span>
            </div>
          ) : null}
        </div>

        <div className="export-modal-body">
          <section className="export-group">
            <h3>Video · Animatic</h3>
            <p>Each board plays for its shot duration, assembled into an .mp4.</p>
            <div className="export-options">
              <label>
                <span>Frame rate</span>
                <select value={fps} onChange={(event) => setFps(Number(event.target.value))} disabled={disabled}>
                  <option value={12}>12 fps</option>
                  <option value={24}>24 fps</option>
                  <option value={30}>30 fps</option>
                </select>
              </label>
              <label className="export-check">
                <input type="checkbox" checked={captions} onChange={(event) => setCaptions(event.target.checked)} disabled={disabled} />
                <span>Burn in captions (board # + title + dialogue)</span>
              </label>
            </div>
            <div className="export-actions">
              <button
                type="button"
                className="primary"
                onClick={() => void run('animatic', scope, () => exportAnimatic({ fps, captions, ...scope }))}
                disabled={disabled}
              >
                {busy === 'animatic' ? 'Rendering…' : 'Export .mp4'}
              </button>
              {openButton('animatic')}
            </div>
          </section>

          <section className="export-group">
            <h3>Print · PDF</h3>
            <div className="export-options">
              <label>
                <span>Layout</span>
                <select value={pdfLayout} onChange={(event) => setPdfLayout(event.target.value as PdfLayout)} disabled={disabled}>
                  <option value="one_per_page">Shot detail — one board per page</option>
                  <option value="two_per_page">Two boards per page</option>
                  <option value="thumbnails">Thumbnail grid (6 / page)</option>
                </select>
              </label>
            </div>
            <div className="export-actions">
              <button
                type="button"
                className="primary"
                onClick={() => void run('pdf', scope, () => exportPdf(pdfLayout, scope))}
                disabled={disabled}
              >
                {busy === 'pdf' ? 'Building…' : 'Export PDF'}
              </button>
              {openButton('pdf')}
            </div>
          </section>

          <section className="export-group">
            <h3>Images</h3>
            <div className="export-actions">
              <button
                type="button"
                onClick={() => void run('contact_sheet', scope, () => exportContactSheet(scope))}
                disabled={disabled}
              >
                {busy === 'contact_sheet' ? 'Building…' : 'Contact sheet (PNG)'}
              </button>
              {openButton('contact_sheet')}
              <button
                type="button"
                onClick={() => void run('image_sequence', scope, () => exportImageSequence(scope))}
                disabled={disabled}
              >
                {busy === 'image_sequence' ? 'Rendering…' : rangeMode === 'current' ? 'Board image (PNG)' : 'Image sequence'}
              </button>
              {openButton('image_sequence', 'Open folder')}
            </div>
          </section>

          <section className="export-group">
            <h3>Data</h3>
            <div className="export-actions">
              <button type="button" onClick={() => void run('shot_list', scope, () => exportShotList(scope))} disabled={disabled}>
                {busy === 'shot_list' ? 'Writing…' : 'Shot list (CSV)'}
              </button>
              {openButton('shot_list')}
              <button type="button" onClick={() => void run('timing', scope, () => exportTiming(scope))} disabled={disabled}>
                {busy === 'timing' ? 'Writing…' : 'Timing (JSON)'}
              </button>
              {openButton('timing')}
            </div>
          </section>
        </div>

        <div className="export-modal-footer">
          <span className="export-note">
            Files are written to the project&rsquo;s <code>exports/</code> folder
            {suffix ? <>, named <code>…{suffix}</code></> : null}.
          </span>
          <button type="button" onClick={onClose} disabled={busy !== ''}>
            Close
          </button>
        </div>
      </section>
    </div>
  )
}
