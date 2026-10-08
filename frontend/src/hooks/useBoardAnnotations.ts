import { useCallback, useEffect, useRef, useState } from 'react'
import { getAnnotations, saveAnnotations } from '../api'

export type AnnotationPoint = { x: number; y: number }
/** Stored shape: {type, start:{x,y}, end:{x,y}, text?, color?}, coordinates normalised to the board. */
export type Annotation = Record<string, unknown> & {
  type?: string
  start?: AnnotationPoint
  end?: AnnotationPoint
  text?: string
  color?: string
}

/** Load and save one board's annotations; stale responses for other boards are ignored. */
export function useBoardAnnotations(shotId: string | null, onError: (error: unknown) => void) {
  const [items, setItems] = useState<Annotation[]>([])
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const requestRef = useRef(0)

  useEffect(() => {
    if (!shotId) return
    const request = ++requestRef.current
    getAnnotations(shotId)
      .then((result) => {
        if (request !== requestRef.current) return
        const raw = (result as { annotations?: unknown }).annotations
        setItems(Array.isArray(raw) ? (raw as Annotation[]) : [])
        setLoadedFor(shotId)
      })
      .catch((error) => {
        if (request !== requestRef.current) return
        setItems([])
        setLoadedFor(shotId)
        onError(error)
      })
  }, [shotId, onError])

  const persist = useCallback(async (next: Annotation[]) => {
    if (!shotId) return
    setItems(next)
    try {
      const saved = await saveAnnotations(shotId, { annotations: next })
      if (Array.isArray(saved.annotations)) setItems(saved.annotations as Annotation[])
    } catch (error) {
      onError(error)
    }
  }, [onError, shotId])

  return { items: loadedFor === shotId ? items : [], ready: loadedFor === shotId, persist }
}
