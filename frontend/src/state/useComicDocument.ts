import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { updateComic } from '../api/comic'
import { getProject } from '../api'
import { emptyComic, type ComicDocument } from '../types/comic'
import { useProject } from './useProject'
import { DraftBuffer } from './projectLifecycle'
import { mergeComicResponse, reloadComicDraft } from './projectResponses'

export function useComicDocument(autoSavePaused = false) {
  const { project, setProject, lifecycle, registerDraftFlusher, reportError } = useProject()
  const stored = project?.comic_document ?? emptyComic()
  const path = project?.project_json_path ?? ''
  const [draft, setDraft] = useState<ComicDocument | null>(null)
  const [busy, setBusy] = useState(false)
  const [saveFailed, setSaveFailed] = useState(false)
  const [history, setHistory] = useState<ComicDocument[]>([])
  const [future, setFuture] = useState<ComicDocument[]>([])
  const latest = useRef({ stored, path, project })
  useLayoutEffect(() => { latest.current = { stored, path, project } })
  const [buffer] = useState(() => new DraftBuffer<ComicDocument>(async snapshot => {
    const epoch = lifecycle.capture()
    const projectPath = path
    return lifecycle.write(async () => {
      const payload = await updateComic(snapshot, projectPath)
      const saved = payload.comic_document ?? snapshot
      if (lifecycle.accepts(epoch)) {
        // Merge Comic and its generation freshness side effect, retaining unrelated Shot edits.
        setProject(current => current ? mergeComicResponse(current, { ...payload, comic_document: saved }) : current)
      }
      return saved
    })
  }, (value, saving) => { setDraft(value); setBusy(saving) },
  (newer, saved) => ({ ...newer, revision: saved.revision })))
  const flush = useCallback(async () => {
    try { await buffer.flush(); setSaveFailed(false) }
    catch (error) { setSaveFailed(true); throw error }
  }, [buffer])
  useLayoutEffect(() => registerDraftFlusher(flush), [flush, registerDraftFlusher])
  useEffect(() => {
    if (!draft || busy || saveFailed || autoSavePaused) return
    const timer = window.setTimeout(() => { void flush().catch(reportError) }, 600)
    return () => window.clearTimeout(timer)
  }, [draft, busy, saveFailed, autoSavePaused, flush, reportError])
  const apply = useCallback((next: ComicDocument) => {
    if (!lifecycle.editable) { reportError(new Error('Wait for the current project action before editing.')); return }
    lifecycle.edited()
    setSaveFailed(false)
    buffer.edit(next)
    setProject(current => current ? { ...current, dirty: true } : current)
  }, [setProject, lifecycle, buffer, reportError])
  const edit = (change: (document: ComicDocument) => ComicDocument) => {
    if (!lifecycle.editable) return
    const current = buffer.current ?? latest.current.stored
    setHistory(previous => [...previous.slice(-39), current])
    setFuture([])
    apply(change(structuredClone(current)))
  }
  const undo = () => {
    if (busy || !history.length || !lifecycle.editable) return
    const current = buffer.current ?? latest.current.stored
    setFuture(previous => [...previous, current])
    apply({ ...history[history.length - 1], revision: current.revision })
    setHistory(previous => previous.slice(0, -1))
  }
  const redo = () => {
    if (busy || !future.length || !lifecycle.editable) return
    const current = buffer.current ?? latest.current.stored
    setHistory(previous => [...previous, current])
    apply({ ...future[future.length - 1], revision: current.revision })
    setFuture(previous => previous.slice(0, -1))
  }
  const reload = async () => {
    setBusy(true)
    setSaveFailed(true) // Pause the debounce while explicitly discarding a failed draft.
    try {
      const reloaded = await reloadComicDraft(buffer, lifecycle, () => latest.current.project, getProject,
        payload => setProject(current => current ? mergeComicResponse(current, payload) : current))
      if (!reloaded) return
      setHistory([]); setFuture([])
      setSaveFailed(false)
    } finally { setBusy(false) }
  }
  return { document: draft ?? stored, dirty: !!draft, busy, edit, flush, undo, redo, reload,
    canUndo: !!history.length, canRedo: !!future.length }
}
