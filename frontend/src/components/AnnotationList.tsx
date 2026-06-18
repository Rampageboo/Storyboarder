import { useCallback, useState } from 'react'
import { getAnnotations, saveAnnotations } from '../api'
import { useProject } from '../state/useProject'
import './AnnotationList.css'

// Annotations are stored as a list of objects. Text labels carry a `text` field plus normalized
// start/end coords (the legacy canvas overlay requires start/end). We edit text items and preserve
// any other item shapes (boxes, arrows, …) untouched so the legacy frontend still renders them.
type Annotation = Record<string, unknown> & {
  type?: string
  text?: string
}

function isTextAnnotation(item: Annotation) {
  return typeof item.text === 'string' || item.type === 'text'
}

type Placement = 'top-left' | 'center' | 'bottom-left'

// Normalized (0..1) anchor points for new text labels. start === end (a point label);
// the legacy canvas overlay reads `start` for fillText, so this stays drawing-compatible.
const PLACEMENTS: Record<Placement, { x: number; y: number }> = {
  'top-left': { x: 0.08, y: 0.1 },
  center: { x: 0.5, y: 0.5 },
  'bottom-left': { x: 0.08, y: 0.9 },
}

export function AnnotationList({ shotId }: { shotId: string | null }) {
  const { reportError } = useProject()
  const [items, setItems] = useState<Annotation[]>([])
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [newText, setNewText] = useState('')
  const [placement, setPlacement] = useState<Placement>('top-left')

  const load = useCallback(async () => {
    if (!shotId) return
    setBusy(true)
    try {
      const res = await getAnnotations(shotId)
      const raw = (res as { annotations?: unknown }).annotations
      setItems(Array.isArray(raw) ? (raw as Annotation[]) : [])
      setLoaded(true)
      setDirty(false)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [shotId, reportError])

  const persist = useCallback(
    async (next: Annotation[]) => {
      if (!shotId) return
      setBusy(true)
      try {
        const saved = await saveAnnotations(shotId, { annotations: next })
        setItems(Array.isArray(saved.annotations) ? (saved.annotations as Annotation[]) : next)
        setDirty(false)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [shotId, reportError],
  )

  const addText = () => {
    const text = newText.trim()
    if (!text) return
    const pos = PLACEMENTS[placement]
    setNewText('')
    void persist([...items, { type: 'text', text, start: { ...pos }, end: { ...pos } }])
  }

  const editText = (index: number, text: string) => {
    setItems((prev) => prev.map((it, i) => (i === index ? { ...it, text } : it)))
    setDirty(true)
  }

  const removeItem = (index: number) => {
    void persist(items.filter((_, i) => i !== index))
  }

  if (!shotId) return <div className="annot-empty">Select a shot.</div>

  return (
    <div className="annot">
      <div className="annot-actions">
        <button type="button" onClick={() => void load()} disabled={busy}>
          {loaded ? 'Reload' : 'Load'}
        </button>
        <button type="button" onClick={() => void persist(items)} disabled={busy || !loaded || !dirty}>
          Save
        </button>
      </div>

      {!loaded ? (
        <div className="annot-empty">Click Load to fetch annotations.</div>
      ) : (
        <>
          <ul className="annot-list">
            {items.length === 0 ? <li className="annot-empty">No annotations yet.</li> : null}
            {items.map((it, i) => (
              <li className="annot-item" key={i}>
                {isTextAnnotation(it) ? (
                  <input
                    className="annot-input"
                    value={String(it.text ?? '')}
                    onChange={(e) => editText(i, e.target.value)}
                    placeholder="Annotation text"
                  />
                ) : (
                  <span className="annot-shape">{String(it.type ?? 'annotation')} (non-text)</span>
                )}
                <button
                  type="button"
                  className="annot-remove"
                  onClick={() => removeItem(i)}
                  disabled={busy}
                  aria-label="Delete annotation"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>

          <div className="annot-add">
            <input
              className="annot-input"
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') addText()
              }}
              placeholder="New text annotation"
            />
            <select
              className="annot-select"
              value={placement}
              onChange={(e) => setPlacement(e.target.value as Placement)}
              title="Where to place the new text label on the frame"
            >
              <option value="top-left">Top-left</option>
              <option value="center">Center</option>
              <option value="bottom-left">Bottom-left</option>
            </select>
            <button type="button" onClick={addText} disabled={busy || !newText.trim()}>
              Add
            </button>
          </div>
        </>
      )}
    </div>
  )
}
