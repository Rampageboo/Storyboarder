import { useCallback, useState } from 'react'
import {
  exportAnimatic,
  exportContactSheet,
  exportImageSequence,
  exportPdf,
  exportShotList,
  exportTiming,
  openExport,
} from '../api'
import type { ExportResult, ExportType, PdfLayout } from '../api/export'
import { useProject } from '../state/useProject'
import './ExportModal.css'

interface ExportModalProps {
  open: boolean
  onClose: () => void
}

export function ExportModal({ open, onClose }: ExportModalProps) {
  const { project, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [busy, setBusy] = useState<ExportType | ''>('')
  const [done, setDone] = useState<Partial<Record<ExportType, string>>>({})
  const [pdfLayout, setPdfLayout] = useState<PdfLayout>('one_per_page')
  const [fps, setFps] = useState(24)
  const [captions, setCaptions] = useState(false)

  const run = useCallback(
    async (type: ExportType, fn: () => Promise<ExportResult>) => {
      setBusy(type)
      try {
        await flushDirtyShots()
        const result = await fn()
        setDone((prev) => ({ ...prev, [type]: result.path }))
      } catch (error) {
        reportError(error)
      } finally {
        setBusy('')
      }
    },
    [flushDirtyShots, reportError],
  )

  const reveal = useCallback(
    async (type: ExportType) => {
      try {
        await openExport(type)
      } catch (error) {
        reportError(error)
      }
    },
    [reportError],
  )

  if (!open || !project) return null

  const disabled = busy !== '' || projectActionBusy

  const openButton = (type: ExportType, label = 'Open') =>
    done[type] ? (
      <button type="button" className="export-open" onClick={() => void reveal(type)} disabled={disabled}>
        {label}
      </button>
    ) : null

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
                onClick={() => void run('animatic', () => exportAnimatic({ fps, captions }))}
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
              <button type="button" className="primary" onClick={() => void run('pdf', () => exportPdf(pdfLayout))} disabled={disabled}>
                {busy === 'pdf' ? 'Building…' : 'Export PDF'}
              </button>
              {openButton('pdf')}
            </div>
          </section>

          <section className="export-group">
            <h3>Images</h3>
            <div className="export-actions">
              <button type="button" onClick={() => void run('contact_sheet', exportContactSheet)} disabled={disabled}>
                {busy === 'contact_sheet' ? 'Building…' : 'Contact sheet (PNG)'}
              </button>
              {openButton('contact_sheet')}
              <button type="button" onClick={() => void run('image_sequence', exportImageSequence)} disabled={disabled}>
                {busy === 'image_sequence' ? 'Rendering…' : 'Image sequence'}
              </button>
              {openButton('image_sequence', 'Open folder')}
            </div>
          </section>

          <section className="export-group">
            <h3>Data</h3>
            <div className="export-actions">
              <button type="button" onClick={() => void run('shot_list', exportShotList)} disabled={disabled}>
                {busy === 'shot_list' ? 'Writing…' : 'Shot list (CSV)'}
              </button>
              {openButton('shot_list')}
              <button type="button" onClick={() => void run('timing', exportTiming)} disabled={disabled}>
                {busy === 'timing' ? 'Writing…' : 'Timing (JSON)'}
              </button>
              {openButton('timing')}
            </div>
          </section>
        </div>

        <div className="export-modal-footer">
          <span className="export-note">Files are written to the project&rsquo;s <code>exports/</code> folder.</span>
          <button type="button" onClick={onClose} disabled={busy !== ''}>
            Close
          </button>
        </div>
      </section>
    </div>
  )
}
