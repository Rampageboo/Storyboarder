import type { ProjectSettings } from '../types/settings'
import type { Shot } from '../types/shot'

export type {
  Scene3dCaptureRequest,
  Scene3dReferenceView,
  Scene3dViewMode,
  Scene3dViewSource,
} from '../scene3d/scene3dTypes'
import type { Scene3dReferenceView, Scene3dViewMode, Scene3dViewSource } from '../scene3d/scene3dTypes'

function triple(value: unknown): [number, number, number] | undefined {
  if (Array.isArray(value) && value.length >= 3) {
    const out: [number, number, number] = [Number(value[0]), Number(value[1]), Number(value[2])]
    if (out.every((n) => Number.isFinite(n))) return out
  }
  return undefined
}

function num(value: unknown): number | undefined {
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

// Coerce a loosely-typed stored view into a Scene3dReferenceView. Returns null when there is
// nothing usable (no numeric position and no camera name) so the caller can fall through.
function normalizeView(raw: Record<string, unknown>, source: Scene3dViewSource): Scene3dReferenceView | null {
  const position = triple(raw.position)
  const cameraName = typeof raw.camera_name === 'string' ? raw.camera_name.trim() : ''
  if (!position && !cameraName) return null
  const modeRaw = String(raw.mode || '')
  const mode: Scene3dViewMode =
    modeRaw === 'scene_camera' ? 'scene_camera' : modeRaw === 'free_view' ? 'free_view' : cameraName ? 'scene_camera' : 'free_view'
  return {
    mode,
    camera_name: cameraName || undefined,
    time: num(raw.time),
    position,
    target: triple(raw.target),
    rotation: triple(raw.rotation),
    fov: num(raw.fov),
    source,
  }
}

// The shot's own saved 3D view. Prefer an explicit scene3d_view object, then fall back to the
// legacy split fields (position/target/rotation/fov + scene3d_camera + scene3d_time).
function viewFromShotCameraData(cam: Record<string, unknown>): Scene3dReferenceView | null {
  const stored = cam.scene3d_view
  if (stored && typeof stored === 'object') {
    const v = normalizeView(stored as Record<string, unknown>, 'shot')
    if (v) return v
  }
  const cameraName = String(cam.scene3d_camera || '')
  return normalizeView(
    {
      mode: cameraName ? 'scene_camera' : 'free_view',
      camera_name: cameraName,
      position: cam.position,
      target: cam.target,
      rotation: cam.rotation,
      fov: cam.fov,
      time: cam.scene3d_time,
    },
    'shot',
  )
}

/**
 * Resolve which Scene3D view a model reference should preview/apply with, in priority order:
 *   1. the current workspace view persisted at settings.scene3d.reference_view;
 *   2. the anchor shot's saved view (camera_data.scene3d_view, or legacy position/scene3d_camera);
 *   3. the saved scene camera name at settings.scene3d.camera_name (resolved by name in the GLB);
 *   4. null → caller uses the generic framed GLB preview.
 * Workspace-first: assigning a new segment should follow the current Scene3D workspace camera/free
 * view, not be overridden by a stale per-board view. Never silently uses the generic preview when a
 * saved Scene3D camera/view exists.
 */
export function resolveScene3dReferenceView(opts: {
  shot?: Shot | null
  settings?: ProjectSettings | null
}): Scene3dReferenceView | null {
  const cam = (opts.shot?.camera_data ?? null) as Record<string, unknown> | null
  const scene3d = (opts.settings?.scene3d ?? {}) as Record<string, unknown>

  const referenceView = scene3d.reference_view
  if (referenceView && typeof referenceView === 'object') {
    const v = normalizeView(referenceView as Record<string, unknown>, 'workspace')
    if (v) return v
  }

  const fromShot = cam ? viewFromShotCameraData(cam) : null
  if (fromShot) return fromShot

  const sceneCameraName = String(scene3d.camera_name || '').trim()
  if (sceneCameraName) return { mode: 'scene_camera', camera_name: sceneCameraName, source: 'scene_camera' }

  return null
}

/** Short human label for the resolved view, e.g. "Scene camera — Camera", "Free view". */
export function describeScene3dView(view: Scene3dReferenceView | null): string {
  if (!view) return 'Generic preview fallback'
  if (view.mode === 'scene_camera') return view.camera_name ? `Scene camera — ${view.camera_name}` : 'Scene camera'
  return 'Free view'
}
