import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type PropsWithChildren,
  type SetStateAction,
} from 'react'
import { getMissingFiles, getProject } from '../api'
import { NewProjectDialog } from '../components/NewProjectDialog'
import {
  refreshPreviewAnalysis,
  updateAppSession,
} from '../api'
import type { MissingFileRow, ProjectPathRequest, ProjectPayload, ShotUpdate } from '../types'
import { ProjectContext } from './useProject'
import { useStoryGraph } from './useStoryGraph'
import { useProjectLifecycle } from './useProjectLifecycle'
import { useShotDrafts } from './useShotDrafts'
import { useProjectActions } from './useProjectActions'
import { useProjectHistory } from './useProjectHistory'
import { useBoardCommands } from './useBoardCommands'
import { useReferenceSegments } from './useReferenceSegments'
import { acceptsProjectPayload } from './projectResponses'
import type { ProjectLifecycle } from './projectLifecycle'
import type { StoryGraph } from '../types/storyGraph'
import type { Shot } from '../types'

export interface ProjectContextValue {
  /** Shared draft and response lifetime coordination for domain hooks. */
  lifecycle: ProjectLifecycle
  registerDraftFlusher: (flush: () => Promise<void>) => () => void
  runProjectMutation: <T>(operation: () => Promise<T>) => Promise<T>
  storyGraph: StoryGraph | null
  activeRouteShots: Shot[]
  updateStoryGraph: (graph: StoryGraph) => Promise<void>
  createStoryBranch: (title: string, fromShotId?: string) => Promise<void>
  setActiveStoryRoute: (routeId: string) => Promise<void>
  selectStoryShot: (shotId: string) => Promise<void>
  drawingActive: boolean
  setDrawingActive: (active: boolean) => void
  project: ProjectPayload | null
  selectedShotId: string | null
  selectedShotIds: string[]
  setSelectedShotId: (shotId: string | null) => void
  selectShot: (shotId: string, mode?: 'replace' | 'toggle' | 'range') => void
  clearShotSelection: () => void
  replaceProject: (payload: ProjectPayload, preferredShotId?: string | null) => void
  refreshProjectFromBridge: (pluginSelectedShotId?: string | null) => Promise<void>
  refreshProjectFromGeneration: () => Promise<void>
  setProject: Dispatch<SetStateAction<ProjectPayload | null>>
  reloadProject: () => Promise<void>
  newProject: (body?: ProjectPathRequest) => Promise<void>
  openProjectFromDialog: () => Promise<void>
  /** Open a document by path — the Home screen's recent cards. */
  openProjectPath: (path: string) => Promise<void>
  /** Save and close the open document, returning the app to Home. */
  closeProjectToHome: () => Promise<void>
  saveProject: () => Promise<void>
  saveProjectAs: () => Promise<void>
  convertProject: () => Promise<void>
  addShotAfterSelection: () => Promise<void>
  insertShotAtIndex: (index: number) => Promise<void>
  deleteSelectedShot: () => Promise<void>
  sendSelectedShotsToQueue: () => Promise<void>
  changeSelectedShotsScene: (sceneId: string, sceneName: string) => Promise<void>
  moveSelectedShot: (direction: 'up' | 'down') => Promise<void>
  reorderBoards: (orderedIds: string[], selectId?: string | null) => Promise<void>
  deleteActiveRefSegment: () => Promise<void>
  deleteRefSegmentUndoable: (segmentId: string) => Promise<void>
  recordRefApply: (opts: { label: string; undoToken: string; redo: () => Promise<ProjectPayload> }) => void
  undo: () => Promise<void>
  redo: () => Promise<void>
  canUndo: boolean
  canRedo: boolean
  undoLabel: string | null
  redoLabel: string | null
  syncSelectedShot: () => Promise<void>
  openSelectedShotSource: () => Promise<void>
  initialLoading: boolean
  projectActionBusy: boolean
  getDraft: (shotId: string) => ShotUpdate | undefined
  editShotField: <K extends keyof ShotUpdate>(shotId: string, key: K, value: ShotUpdate[K]) => void
  isShotDirty: (shotId: string) => boolean
  dirtyShotIds: string[]
  savingShots: Record<string, boolean>
  saveShot: (shotId: string) => Promise<void>
  flushDirtyShots: () => Promise<void>
  visualEpoch: number
  segmentRange: { anchorShotId: string | null; endShotId: string | null }
  setSegmentAnchor: (shotId: string | null) => void
  setSegmentEnd: (shotId: string | null) => void
  pickSegmentShot: (shotId: string) => void
  clearSegmentRange: () => void
  /** Selected persisted segment for inspect/edit (not the temporary dot draft). */
  activeAppliedSegmentId: string | null
  setActiveAppliedSegmentId: (segmentId: string | null) => void
  clearActiveAppliedSegment: () => void
  /** True when the assignment popover is open for inspect/edit of a persisted segment. */
  refSegmentInspectOpen: boolean
  openRefSegmentInspect: (segmentId: string) => void
  closeRefSegmentInspect: () => void
  dismissRefSegmentUi: () => void
  refApplyUndoToken: string | null
  setRefApplyUndoToken: (token: string | null) => void
  lastError: string | null
  clearError: () => void
  reportError: (error: unknown) => void
  missingFiles: MissingFileRow[] | null
  missingFilesLoading: boolean
  refreshMissingFiles: () => void
  refreshPreviewFields: () => Promise<void>
}

function preferredShotId(payload: ProjectPayload, wanted?: string | null): string | null {
  if (wanted && payload.shots.some((shot) => shot.shot_id === wanted)) return wanted
  return payload.shots[0]?.shot_id ?? null
}

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function mixHash(hash: number, value: unknown): number {
  return Math.imul(hash ^ hashString(String(value ?? '')), 16777619) >>> 0
}

function projectVisualEpoch(payload: ProjectPayload | null): number {
  if (!payload) return 0
  let hash = payload.dirty ? 17 : 0
  hash = (hash * 31 + payload.shots.length) >>> 0
  for (const shot of payload.shots) {
    hash = mixHash(hash, shot.shot_id)
    hash = mixHash(hash, shot.preview_disk_mtime)
    hash = mixHash(hash, shot.thumbnail_disk_mtime)
    hash = mixHash(hash, shot.board_background_disk_mtime)
    hash = mixHash(hash, shot.codex_layer_disk_mtime)
    hash = mixHash(hash, shot.image_path)
    hash = mixHash(hash, shot.preview_image_path)
    hash = mixHash(hash, shot.source_file_path)
    hash = mixHash(hash, shot.has_board_background ? '1' : '0')
    hash = mixHash(hash, shot.has_codex_layer ? '1' : '0')
  }
  hash = mixHash(hash, JSON.stringify(payload.settings?.ref_segments ?? []))
  return hash
}

export function ProjectProvider({ children }: PropsWithChildren) {
  const { lifecycle, project, projectRef, setProject, commitProject, beginProject,
    drawingActive, drawingActiveRef, setDrawingActive, projectActionBusy, runProjectTransition,
    lastError, setLastError, reportError, clearError } = useProjectLifecycle()
  const { resetDrafts, getDraft, isShotDirty, dirtyShotIds, savingShots, editShotField, saveShot } =
    useShotDrafts(lifecycle, projectRef, commitProject, reportError)
  const registerDraftFlusher = lifecycle.register
  const flushDirtyShots = lifecycle.flush
  const [shotSelection, setShotSelection] = useState<{
    primary: string | null
    ids: string[]
    anchor: string | null
  }>({ primary: null, ids: [], anchor: null })
  const selectedShotId = shotSelection.primary
  const selectedShotIds = shotSelection.ids
  const [missingFiles, setMissingFiles] = useState<MissingFileRow[] | null>(null)
  const [missingFilesLoading, setMissingFilesLoading] = useState(false)
  const missingFilesInFlightRef = useRef<number | null>(null)

  const setSelectedShotId = useCallback((shotId: string | null) => {
    if (drawingActiveRef.current) return
    setShotSelection({
      primary: shotId,
      ids: shotId ? [shotId] : [],
      anchor: shotId,
    })
  }, [drawingActiveRef])

  const selectShot = useCallback((shotId: string, mode: 'replace' | 'toggle' | 'range' = 'replace') => {
    if (drawingActiveRef.current) return
    setShotSelection((current) => {
      const shots = projectRef.current?.shots ?? []
      const order = shots.map((shot) => shot.shot_id)
      if (!order.includes(shotId)) return current
      if (mode === 'replace') {
        return { primary: shotId, ids: [shotId], anchor: shotId }
      }
      if (mode === 'range') {
        const anchor = current.anchor && order.includes(current.anchor) ? current.anchor : current.primary ?? shotId
        const from = order.indexOf(anchor)
        const to = order.indexOf(shotId)
        const ids = order.slice(Math.min(from, to), Math.max(from, to) + 1)
        return { primary: shotId, ids, anchor }
      }
      const selected = new Set(current.ids)
      if (selected.has(shotId)) selected.delete(shotId)
      else selected.add(shotId)
      const ids = order.filter((id) => selected.has(id))
      const primary = selected.has(shotId) ? shotId : ids.includes(current.primary ?? '') ? current.primary : ids[0] ?? null
      return { primary, ids, anchor: shotId }
    })
  }, [drawingActiveRef, projectRef])

  const clearShotSelection = useCallback(() => {
    setShotSelection((current) => current.primary
      ? { primary: current.primary, ids: [current.primary], anchor: current.primary }
      : current)
  }, [])

  const replaceProject = useCallback((payload: ProjectPayload, selected?: string | null) => {
    if (!acceptsProjectPayload(lifecycle, lifecycle.capture(), projectRef.current, payload)) return false
    commitProject(payload)
    setLastError(null)
    setShotSelection((current) => {
      if (selected !== undefined) {
        const preferred = preferredShotId(payload, selected)
        return { primary: preferred, ids: preferred ? [preferred] : [], anchor: preferred }
      }
      const validIds = new Set(payload.shots.map((shot) => shot.shot_id))
      const ids = current.ids.filter((id) => validIds.has(id))
      const primary = current.primary && validIds.has(current.primary)
        ? current.primary
        : ids[0] ?? payload.shots[0]?.shot_id ?? null
      return {
        primary,
        ids: ids.length > 0 ? ids : primary ? [primary] : [],
        anchor: current.anchor && validIds.has(current.anchor) ? current.anchor : primary,
      }
    })
    return true
  }, [commitProject, setLastError, lifecycle, projectRef])

  const { history, clearHistory, historyState } = useProjectHistory(lifecycle, runProjectTransition, replaceProject, reportError)
  const boardCommands = useBoardCommands({ projectRef, selectedShotId, selectedShotIds,
    runExclusive: runProjectTransition, accept: replaceProject, history })
  const { resetReferenceState, referenceState } = useReferenceSegments({ lifecycle, projectRef,
    runExclusive: runProjectTransition, accept: replaceProject, history })

  const visualEpoch = useMemo(() => projectVisualEpoch(project), [project])

  useEffect(() => {
    if (!project?.project_json_path || !selectedShotId) return
    void updateAppSession({
      last_project_json_path: project.project_json_path,
      selected_shot_id: selectedShotId,
      recent_projects: [project.project_path, ...(project.settings.recent_projects ?? [])],
    }).catch(() => {})
  }, [project?.project_json_path, project?.project_path, project?.settings.recent_projects, selectedShotId])

  const resetEditState = useCallback(() => {
    resetDrafts()
    resetReferenceState()
    clearHistory()
    setMissingFiles(null)
  }, [resetDrafts, resetReferenceState, clearHistory])

  const refreshMissingFiles = useCallback(() => {
    if (!projectRef.current) return
    const epoch = lifecycle.capture()
    if (missingFilesInFlightRef.current === epoch) return
    missingFilesInFlightRef.current = epoch
    setMissingFilesLoading(true)
    getMissingFiles()
      .then((payload) => {
        if (lifecycle.accepts(epoch)) setMissingFiles(payload.missing_files ?? [])
      })
      .catch(() => {
        // Silently ignore: missing-file errors must never break the UI
      })
      .finally(() => {
        if (missingFilesInFlightRef.current === epoch) {
          missingFilesInFlightRef.current = null
          setMissingFilesLoading(false)
        }
      })
  }, [lifecycle, projectRef])

  const projectEpoch = lifecycle.capture()
  const projectPath = project?.project_json_path
  // Defer missing-files scan until after first paint so it never blocks initial loading.
  useEffect(() => {
    if (!projectPath) return
    const hasIdleCallback = typeof window !== 'undefined' && 'requestIdleCallback' in window
    let id: number
    if (hasIdleCallback) {
      id = (window as Window & typeof globalThis).requestIdleCallback(refreshMissingFiles)
    } else {
      id = window.setTimeout(refreshMissingFiles, 500)
    }
    return () => {
      if (hasIdleCallback) {
        (window as Window & typeof globalThis).cancelIdleCallback(id)
      } else {
        clearTimeout(id)
      }
    }
  }, [projectPath, projectEpoch, refreshMissingFiles])

  // Narrow project refresh: merge only preview-analysis fields from the server
  // without touching undo/redo history, selected shot, or unsaved drafts.
  const refreshPreviewFields = useCallback(async () => {
    if (!projectRef.current) return
    const ticket = lifecycle.captureRead()
    const payload = await getProject()
    if (!lifecycle.acceptsRead(ticket)) return
    const shotMap = new Map(payload.shots.map((s) => [s.shot_id, s]))
    commitProject((prev) => {
      if (!prev) return payload
      return {
        ...prev,
        shots: prev.shots.map((s) => {
          const fresh = shotMap.get(s.shot_id)
          if (!fresh) return s
          return {
            ...s,
            has_artwork_preview: fresh.has_artwork_preview,
            preview_has_transparency: fresh.preview_has_transparency,
            preview_analysis_state: fresh.preview_analysis_state,
            preview_disk_mtime: fresh.preview_disk_mtime,
          }
        }),
      }
    })
  }, [commitProject, lifecycle, projectRef])

  const openPayload = useCallback(
    (payload: ProjectPayload, selected?: string | null) => {
      resetEditState()
      beginProject(payload)
      setLastError(null)
      const preferred = preferredShotId(payload, selected)
      setShotSelection({ primary: preferred, ids: preferred ? [preferred] : [], anchor: preferred })
    },
    [resetEditState, beginProject, setLastError],
  )

  const refreshProjectFromBridge = useCallback(
    async (pluginSelectedShotId?: string | null) => {
      const ticket = lifecycle.captureRead()
      const payload = await getProject()
      if (!lifecycle.acceptsRead(ticket)) return
      const pluginSelectionValid = !!pluginSelectedShotId && payload.shots.some((shot) => shot.shot_id === pluginSelectedShotId)
      // A plugin-driven refresh means boards/metadata changed outside our control;
      // discard history so undo/redo can never replay against a stale world.
      if (replaceProject(payload, pluginSelectionValid ? pluginSelectedShotId : undefined)) clearHistory()
    },
    [replaceProject, lifecycle, clearHistory],
  )

  const refreshProjectFromGeneration = useCallback(async () => {
    // A result is a background update, not a navigation request. Keep the board
    // the artist is currently viewing even when Codex finished another shot.
    const ticket = lifecycle.captureRead()
    const payload = await getProject()
    if (lifecycle.acceptsRead(ticket)) replaceProject(payload)
  }, [replaceProject, lifecycle])

  const { initialLoading, reloadProject, newProjectAction, newProjectType, finishNewProjectChoice, openProjectFromDialog, openProjectPath, closeProjectToHome,
    saveProjectAction, saveProjectAsAction, convertProjectAction } = useProjectActions({
    lifecycle, runProjectTransition, flushDirtyShots, openPayload, resetEditState, beginProject, commitProject,
    setSelectedShotId, selectedShotId, setLastError,
  })

  const requestedAnalysisSignaturesRef = useRef(new Set<string>())
  const previewAnalysisSignature = project
    ? [
        project.project_path,
        ...project.shots
          .filter((shot) => shot.preview_analysis_state === 'provisional')
          .map((shot) => `${shot.shot_id}:${shot.preview_disk_mtime ?? 0}:${shot.preview_analysis_state}`)
          .sort(),
      ].join('|')
    : ''

  // Trigger preview analysis for each new provisional-preview signature.
  // The signature changes when Photoshop exports a preview and the backend
  // reports a new preview_disk_mtime, but completed/cached states stop repeats.
  useEffect(() => {
    if (initialLoading) return
    if (!project || !previewAnalysisSignature || !project.shots.some((shot) => shot.preview_analysis_state === 'provisional')) return
    if (requestedAnalysisSignaturesRef.current.has(previewAnalysisSignature)) return
    requestedAnalysisSignaturesRef.current.add(previewAnalysisSignature)
    const doAnalysis = () => { void refreshPreviewAnalysis().catch(() => {}) }
    const hasIdleCallback = typeof window !== 'undefined' && 'requestIdleCallback' in window
    if (hasIdleCallback) {
      const id = (window as Window & typeof globalThis).requestIdleCallback(doAnalysis)
      return () => (window as Window & typeof globalThis).cancelIdleCallback(id)
    }
    const id = window.setTimeout(doAnalysis, 500)
    return () => clearTimeout(id)
  }, [initialLoading, project, previewAnalysisSignature])

  const story = useStoryGraph({ project, selectedShotId, drawingActive, flushDirtyShots, replaceProject, setSelectedShotId, runExclusive: runProjectTransition, clearHistory })

  const responseEpoch = lifecycle.capture()
  const acceptProject = useCallback((payload: ProjectPayload, selected?: string | null) => {
    if (acceptsProjectPayload(lifecycle, responseEpoch, projectRef.current, payload)) {
      replaceProject(payload, selected)
    }
  }, [lifecycle, responseEpoch, projectRef, replaceProject])
  const value = useMemo<ProjectContextValue>(
    () => ({
      lifecycle,
      registerDraftFlusher,
      runProjectMutation: runProjectTransition,
      ...story,
      drawingActive,
      setDrawingActive,
      project,
      selectedShotId,
      selectedShotIds,
      setSelectedShotId,
      selectShot,
      clearShotSelection,
      replaceProject: acceptProject,
      refreshProjectFromBridge,
      refreshProjectFromGeneration,
      setProject,
      reloadProject,
      newProject: newProjectAction,
      openProjectFromDialog,
      openProjectPath,
      closeProjectToHome,
      saveProject: saveProjectAction,
      saveProjectAs: saveProjectAsAction,
      convertProject: convertProjectAction,
      initialLoading,
      projectActionBusy,
      getDraft,
      editShotField,
      isShotDirty,
      dirtyShotIds,
      savingShots,
      saveShot,
      flushDirtyShots,
      visualEpoch,
      lastError,
      clearError,
      reportError,
      missingFiles,
      missingFilesLoading,
      refreshMissingFiles,
      refreshPreviewFields,
      ...boardCommands,
      ...referenceState,
      ...historyState,
    }),
    [lifecycle, setProject, acceptProject, boardCommands, referenceState, historyState, registerDraftFlusher,
      runProjectTransition, story, drawingActive, setDrawingActive, project, selectedShotId, selectedShotIds,
      setSelectedShotId, selectShot, clearShotSelection, refreshProjectFromBridge, refreshProjectFromGeneration,
      reloadProject, newProjectAction, openProjectFromDialog, openProjectPath, closeProjectToHome,
      saveProjectAction, saveProjectAsAction, convertProjectAction, initialLoading, projectActionBusy,
      getDraft, editShotField, isShotDirty, dirtyShotIds, savingShots, saveShot, flushDirtyShots, visualEpoch,
      lastError, clearError, reportError, missingFiles, missingFilesLoading, refreshMissingFiles, refreshPreviewFields],
  )

  return <ProjectContext.Provider value={value}>
    {children}
    {newProjectType !== null ? <NewProjectDialog initialType={newProjectType} onChoose={finishNewProjectChoice} /> : null}
  </ProjectContext.Provider>
}
