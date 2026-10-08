export interface StoryRoute {
  id: string
  name: string
  shot_ids: string[]
}

export interface StoryGraph {
  version: 1
  revision: number
  active_route_id: string
  routes: StoryRoute[]
  positions: Record<string, { x: number; y: number }>
}

