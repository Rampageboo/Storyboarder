import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { restoreRefApply, getProject, snapshotRefBoards, deleteRefSegment, updateSettings } from '../api'
import type { ProjectPayload } from '../types'
import type { ProjectLifecycle } from './projectLifecycle'
import type { ProjectHistory } from './projectHistory'
import { createReferenceCommands } from './referenceCommands'
import type { ReferenceApplyRecord } from './referenceCommands'

interface Options {
  lifecycle: ProjectLifecycle
  projectRef: RefObject<ProjectPayload | null>
  runExclusive: <T>(operation: () => Promise<T>) => Promise<T>
  accept: (payload: ProjectPayload, selected?: string | null) => boolean
  history: ProjectHistory
}
const api = { restoreRefApply, getProject, snapshotRefBoards, deleteRefSegment, updateSettings }

export function useReferenceSegments(options: Options) {
  const [segmentRange, setSegmentRange] = useState<{ anchorShotId: string | null; endShotId: string | null }>({ anchorShotId: null, endShotId: null })
  const [refApplyUndoToken, setRefApplyUndoToken] = useState<string | null>(null)
  const [activeAppliedSegmentId, setActiveAppliedSegmentId] = useState<string | null>(null)
  const [refSegmentInspectOpen, setRefSegmentInspectOpen] = useState(false)
  const latest = useRef({ ...options, activeAppliedSegmentId })
  useLayoutEffect(() => { latest.current = { ...options, activeAppliedSegmentId } })
  const setSegmentAnchor = useCallback((shotId: string | null) => setSegmentRange(range => ({ ...range, anchorShotId: shotId })), [])
  const setSegmentEnd = useCallback((shotId: string | null) => setSegmentRange(range => ({ ...range, endShotId: shotId })), [])
  const clearSegmentRange = useCallback(() => setSegmentRange({ anchorShotId: null, endShotId: null }), [])
  const clearActiveAppliedSegment = useCallback(() => {
    setActiveAppliedSegmentId(null)
    setRefSegmentInspectOpen(false)
  }, [])
  const closeRefSegmentInspect = useCallback(() => setRefSegmentInspectOpen(false), [])
  const openRefSegmentInspect = useCallback((segmentId: string) => {
    setActiveAppliedSegmentId(segmentId)
    setRefSegmentInspectOpen(true)
  }, [])
  const dismissRefSegmentUi = useCallback(() => {
    clearSegmentRange()
    clearActiveAppliedSegment()
  }, [clearSegmentRange, clearActiveAppliedSegment])
  const pickSegmentShot = useCallback((shotId: string) => {
    clearActiveAppliedSegment()
    setSegmentRange(range => !range.anchorShotId ? { anchorShotId: shotId, endShotId: null }
      : !range.endShotId ? { anchorShotId: range.anchorShotId, endShotId: shotId } : { anchorShotId: shotId, endShotId: null })
  }, [clearActiveAppliedSegment])
  const resetReferenceState = useCallback(() => {
    dismissRefSegmentUi()
    setRefApplyUndoToken(null)
  }, [dismissRefSegmentUi])
  const commands = useCallback(() => createReferenceCommands({ api,
    readProject: () => latest.current.projectRef.current,
    readActiveSegment: () => latest.current.activeAppliedSegmentId,
    dismiss: dismissRefSegmentUi,
    setUndoToken: setRefApplyUndoToken,
    runExclusive: operation => latest.current.runExclusive(operation),
    accept: (payload, selected) => latest.current.accept(payload, selected),
    history: latest.current.history,
  }), [dismissRefSegmentUi])
  // A bake response may outlive its originating document, including a reopen of the same path.
  const epoch = options.lifecycle.capture()
  const recordRefApply = useCallback((record: ReferenceApplyRecord) => {
    if (options.lifecycle.accepts(epoch)) commands().recordRefApply(record)
  }, [commands, epoch, options.lifecycle])
  const deleteRefSegmentUndoable = useCallback((id: string) => commands().deleteRefSegmentUndoable(id), [commands])
  const deleteActiveRefSegment = useCallback(() => commands().deleteActiveRefSegment(), [commands])
  const referenceState = useMemo(() => ({ segmentRange, setSegmentAnchor, setSegmentEnd, clearSegmentRange,
    activeAppliedSegmentId, setActiveAppliedSegmentId, clearActiveAppliedSegment, refSegmentInspectOpen,
    openRefSegmentInspect, closeRefSegmentInspect, dismissRefSegmentUi, pickSegmentShot, refApplyUndoToken,
    setRefApplyUndoToken, recordRefApply, deleteRefSegmentUndoable, deleteActiveRefSegment }),
  [segmentRange, setSegmentAnchor, setSegmentEnd, clearSegmentRange, activeAppliedSegmentId, clearActiveAppliedSegment,
    refSegmentInspectOpen, openRefSegmentInspect, closeRefSegmentInspect, dismissRefSegmentUi, pickSegmentShot,
    refApplyUndoToken, recordRefApply, deleteRefSegmentUndoable, deleteActiveRefSegment])
  return { resetReferenceState, referenceState }
}
