import { useCallback, useLayoutEffect, useMemo, useRef } from 'react'
import { postStoryBranch, putStoryGraph } from '../api/storyGraph'
import type { ProjectPayload } from '../types'
import type { StoryGraph } from '../types/storyGraph'

/** Read-only legacy projection. Only the backend writes canonical route state. */
export function projectStoryGraph(project: ProjectPayload | null): StoryGraph | null {
  if (!project) return null
  return project.story_graph ?? {
    version: 1,
    revision: 0,
    active_route_id: 'main',
    routes: [{ id: 'main', name: '主线', shot_ids: project.shots.map(shot => shot.shot_id) }],
    positions: {},
  }
}

interface StoryGraphOptions {
  project: ProjectPayload | null
  selectedShotId: string | null
  drawingActive: boolean
  flushDirtyShots: () => Promise<void>
  replaceProject: (payload: ProjectPayload, selected?: string | null) => void
  setSelectedShotId: (id: string | null) => void
  runExclusive: <T>(operation: () => Promise<T>) => Promise<T>
  clearHistory: () => void
}

export function useStoryGraph(options: StoryGraphOptions) {
  const latest = useRef(options)
  useLayoutEffect(() => { latest.current = options })
  const storyGraph = useMemo(() => projectStoryGraph(options.project), [options.project])
  const activeRouteShots = useMemo(() => {
    if (!storyGraph || !options.project) return []
    const shots = new Map(options.project.shots.map(shot => [shot.shot_id, shot]))
    return (storyGraph.routes.find(route => route.id === storyGraph.active_route_id)?.shot_ids ?? [])
      .flatMap(id => { const shot = shots.get(id); return shot ? [shot] : [] })
  }, [storyGraph, options.project])

  const updateStoryGraph = useCallback(async (next: StoryGraph) => {
    const current = latest.current
    if (current.drawingActive) throw new Error('请先保存或关闭绘画编辑器，再修改故事路线。')
    return current.runExclusive(async () => {
      await current.flushDirtyShots()
      const payload = await putStoryGraph(next)
      const route = payload.story_graph?.routes.find(item => item.id === payload.story_graph?.active_route_id)
      const selected = route?.shot_ids.includes(current.selectedShotId ?? '') ? current.selectedShotId : route?.shot_ids[0] ?? null
      current.replaceProject(payload, selected)
      current.clearHistory()
    })
  }, [])

  const setActiveStoryRoute = useCallback(async (routeId: string) => {
    const graph = projectStoryGraph(latest.current.project)
    if (!graph || graph.active_route_id === routeId) return
    if (!graph.routes.some(route => route.id === routeId)) throw new Error('这条路线已不存在，请刷新后重试。')
    await updateStoryGraph({ ...graph, active_route_id: routeId })
  }, [updateStoryGraph])

  const selectStoryShot = useCallback(async (shotId: string) => {
    const current = latest.current
    const graph = projectStoryGraph(current.project)
    if (!graph || !current.project?.shots.some(shot => shot.shot_id === shotId)) return
    const activeRoute = graph.routes.find(route => route.id === graph.active_route_id)
    if (current.selectedShotId === shotId && activeRoute?.shot_ids.includes(shotId)) return
    if (current.drawingActive) throw new Error('请先保存或关闭绘画编辑器，再切换镜头。')
    await current.runExclusive(async () => {
      await current.flushDirtyShots()
      const active = graph.routes.find(route => route.id === graph.active_route_id)
      const route = active?.shot_ids.includes(shotId) ? active : graph.routes.find(item => item.shot_ids.includes(shotId))
      if (!route) throw new Error('镜头未属于任何路线。')
      if (route.id !== graph.active_route_id) {
        current.replaceProject(await putStoryGraph({ ...graph, active_route_id: route.id }), shotId)
      } else current.setSelectedShotId(shotId)
    })
  }, [])

  const createStoryBranch = useCallback(async (title: string, fromShotId?: string) => {
    const current = latest.current
    const graph = projectStoryGraph(current.project)
    const source = fromShotId ?? current.selectedShotId
    if (!graph || !source) throw new Error('先选择一个分支起点镜头。')
    if (current.drawingActive) throw new Error('请先保存或关闭绘画编辑器，再创建分支。')
    await current.runExclusive(async () => {
      await current.flushDirtyShots()
      const payload = await postStoryBranch({ route_id: graph.active_route_id, from_shot_id: source, title: title.trim() })
      current.replaceProject(payload, payload.shot.shot_id)
      current.clearHistory()
    })
  }, [])

  return useMemo(() => ({ storyGraph, activeRouteShots, updateStoryGraph, createStoryBranch, setActiveStoryRoute, selectStoryShot }),
    [storyGraph, activeRouteShots, updateStoryGraph, createStoryBranch, setActiveStoryRoute, selectStoryShot])
}
