import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { bootstrapApp, browseProjectJson, browseProjectSave, closeProject, convertProject,
  createProject, openProject, saveProject, saveProjectAs } from '../api'
import type { ProjectPathRequest, ProjectPayload } from '../types'
import type { ProjectLifecycle } from './projectLifecycle'

interface Options {
  lifecycle: ProjectLifecycle
  runProjectTransition: <T>(operation: () => Promise<T>) => Promise<T>
  flushDirtyShots: () => Promise<void>
  openPayload: (payload: ProjectPayload, selected?: string | null) => void
  resetEditState: () => void
  beginProject: (payload: ProjectPayload | null) => void
  commitProject: Dispatch<SetStateAction<ProjectPayload | null>>
  setSelectedShotId: (id: string | null) => void
  selectedShotId: string | null
  setLastError: Dispatch<SetStateAction<string | null>>
}

export function useProjectActions({ lifecycle, runProjectTransition, flushDirtyShots, openPayload, resetEditState,
  beginProject, commitProject, setSelectedShotId, selectedShotId, setLastError }: Options) {
  type ProjectType = NonNullable<ProjectPathRequest['project_type']>
  const [newProjectType, setNewProjectType] = useState<ProjectType | null>(null)
  const typeChoiceRef = useRef<((choice: ProjectType | null) => void) | null>(null)
  const finishNewProjectChoice = useCallback((choice: ProjectType | null) => {
    const resolve = typeChoiceRef.current
    typeChoiceRef.current = null
    setNewProjectType(null)
    resolve?.(choice)
  }, [])
  useEffect(() => () => {
    typeChoiceRef.current?.(null)
    typeChoiceRef.current = null
  }, [])
  const [initialLoading, setInitialLoading] = useState(true)
  const reloadProject = useCallback(async () => {
    setInitialLoading(true)
    const epoch = lifecycle.capture()
    try {
      const bootstrap = await bootstrapApp()
      if (!lifecycle.accepts(epoch)) return
      if (bootstrap.project) {
        const selected = bootstrap.session.selected_shot_id
        openPayload(bootstrap.project, typeof selected === 'string' ? selected : null)
      } else {
        resetEditState()
        beginProject(null)
        setSelectedShotId(null)
        setLastError(null)
      }
      if (bootstrap.warning) console.warn('[bootstrap]', bootstrap.warning)
    } catch (error) {
      if (!lifecycle.accepts(epoch)) return
      setLastError(error instanceof Error ? error.message : String(error))
    } finally {
      setInitialLoading(false)
    }
  }, [openPayload, resetEditState, setSelectedShotId, lifecycle, beginProject, setLastError])

  // A native picker may stay open while edits arrive. Seal only when it returns,
  // then drain once more before saving or changing the backend's active document.
  const settleDocument = useCallback(async () => {
    lifecycle.seal()
    await flushDirtyShots()
  }, [lifecycle, flushDirtyShots])

  const newProjectAction = useCallback(async (body: ProjectPathRequest = {}) => {
    if (typeChoiceRef.current || lifecycle.busy) return
    // Ask before entering the transition lane: even its initial draft flush must
    // wait for Create, so cancelling this prompt leaves the current document alone.
    const projectType = await new Promise<ProjectType | null>((resolve) => {
      typeChoiceRef.current = resolve
      setNewProjectType(body.project_type ?? 'video')
    })
    if (!projectType) return
    await runProjectTransition(async () => {
      let next = { ...body, project_type: projectType }
      if (!next.path) {
        const result = await browseProjectSave()
        if (result.cancelled || !result.path) return
        next = { ...next, path: result.path }
      }
      await settleDocument()
      openPayload(await createProject(next))
    })
  }, [lifecycle, runProjectTransition, settleDocument, openPayload])

  const openProjectFromDialog = useCallback(async () => runProjectTransition(async () => {
    const result = await browseProjectJson()
    if (result.cancelled || !result.path) return
    await settleDocument()
    openPayload(await openProject({ project_json_path: result.path }))
  }), [runProjectTransition, settleDocument, openPayload])

  const openProjectPath = useCallback(async (path: string) => runProjectTransition(async () => {
    await settleDocument()
    openPayload(await openProject({ project_json_path: path }))
  }), [runProjectTransition, settleDocument, openPayload])

  const closeProjectToHome = useCallback(async () => runProjectTransition(async () => {
    await settleDocument()
    await closeProject()
    resetEditState()
    beginProject(null)
    setSelectedShotId(null)
    setLastError(null)
  }), [runProjectTransition, settleDocument, resetEditState, beginProject, setSelectedShotId, setLastError])

  const saveProjectAction = useCallback(async () => runProjectTransition(async () => {
    await settleDocument()
    commitProject(await saveProject())
    setLastError(null)
  }), [runProjectTransition, settleDocument, commitProject, setLastError])

  const saveProjectAsAction = useCallback(async () => runProjectTransition(async () => {
    const result = await browseProjectSave()
    if (result.cancelled || !result.path) return
    await settleDocument()
    beginProject(await saveProjectAs({ path: result.path }))
    setLastError(null)
  }), [runProjectTransition, settleDocument, beginProject, setLastError])

  const convertProjectAction = useCallback(async () => runProjectTransition(async () => {
    const result = await browseProjectSave()
    if (result.cancelled || !result.path) return
    await settleDocument()
    openPayload(await convertProject({ path: result.path }), selectedShotId)
  }), [runProjectTransition, settleDocument, openPayload, selectedShotId])

  return { initialLoading, reloadProject, newProjectAction, newProjectType, finishNewProjectChoice, openProjectFromDialog, openProjectPath,
    closeProjectToHome, saveProjectAction, saveProjectAsAction, convertProjectAction }
}
