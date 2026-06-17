/**
 * Camera state export and view serialization for the Scene3D workspace.
 */

import type { Scene3dReferenceView } from '../scene3dTypes'

import type { WorkspaceVec3 } from './workspaceTypes'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type WorkspaceImportedCameraRef = {
  id: string
  name: string
}

export type WorkspaceCameraState = {
  position: number[]
  target: number[]
  rotation: number[]
  fov: number
  focal_length: number
}

export function fovToFocalLength(fov: number, sensorWidth = 36): number {
  return sensorWidth / (2 * Math.tan((fov * Math.PI) / 360))
}

export function getProjectCanvasSize(): { width: number; height: number } {
  const getter = (globalThis as { getProjectCanvasSize?: () => { width: number; height: number } }).getProjectCanvasSize
  if (typeof getter === 'function') {
    const size = getter()
    return {
      width: Math.max(1, Math.floor(Number(size.width) || 1920)),
      height: Math.max(1, Math.floor(Number(size.height) || 1080)),
    }
  }
  return { width: 1920, height: 1080 }
}

export function getProjectCanvasAspect(): number {
  const size = getProjectCanvasSize()
  return size.width / Math.max(1, size.height)
}

export function getCameraStateFromEditor(camera: ThreeObject, orbit: { target: ThreeObject }): WorkspaceCameraState {
  const target = orbit.target.clone()
  return {
    position: camera.position.toArray(),
    target: target.toArray(),
    rotation: camera.rotation.toArray().slice(0, 3),
    fov: camera.fov,
    focal_length: Math.round(fovToFocalLength(Number(camera.fov) || 50)),
  }
}

export function exportViewState(
  THREE: ThreeModule,
  options: {
    camera: ThreeObject
    orbit: { target: ThreeObject }
    followCamera: boolean
    activeCamera: WorkspaceImportedCameraRef | null
    animationTime: number
  },
): Scene3dReferenceView {
  const base = getCameraStateFromEditor(options.camera, options.orbit)
  const forward = options.camera.getWorldDirection(new THREE.Vector3())
  const distance = Math.max(0.001, options.camera.position.distanceTo(options.orbit.target)) || 1
  const target = options.camera.position.clone().add(forward.multiplyScalar(distance))
  const usingSceneCamera = Boolean(options.followCamera && options.activeCamera)
  return {
    mode: usingSceneCamera ? 'scene_camera' : 'free_view',
    camera_name: usingSceneCamera ? options.activeCamera?.name || '' : '',
    time: Number(options.animationTime) || 0,
    position: base.position as [number, number, number],
    target: target.toArray() as [number, number, number],
    rotation: base.rotation as [number, number, number],
    fov: base.fov,
    source: 'workspace',
  }
}

export function loadShotCameraIntoEditor(
  THREE: ThreeModule,
  camera: ThreeObject,
  orbit: { target: ThreeObject; update(): void },
  cameraData: Record<string, unknown> | null | undefined,
  defaultPosition: WorkspaceVec3 = [6, 4, 8],
  defaultTarget: WorkspaceVec3 = [0, 0.5, 0],
): boolean {
  if (!cameraData?.position) return false
  const pos = vec3FromArray(cameraData.position, defaultPosition)
  camera.position.set(pos[0], pos[1], pos[2])
  if (cameraData.target) {
    const target = vec3FromArray(cameraData.target, defaultTarget)
    orbit.target.set(target[0], target[1], target[2])
  } else if (cameraData.rotation) {
    const [rx, ry, rz] = vec3FromArray(cameraData.rotation)
    camera.rotation.set(rx, ry, rz)
    orbit.target.copy(
      camera.position.clone().add(camera.getWorldDirection(new THREE.Vector3())),
    )
  }
  if (cameraData.fov) {
    camera.fov = Number(cameraData.fov) || 50
    camera.updateProjectionMatrix()
  }
  orbit.update()
  return true
}

export type WorkspaceFollowCameraScratch = {
  position: ThreeObject
  quaternion: ThreeObject
  scale: ThreeObject
}

export type WorkspaceImportedCameraObject = {
  object3d: ThreeObject
  viewNode?: ThreeObject
}

/** Copy the active GLB scene camera onto the editor camera (scene3d.js _applyFollowCamera). */
export function applyFollowCameraToEditor(
  camera: ThreeObject,
  orbit: { enabled: boolean },
  activeCamera: WorkspaceImportedCameraObject | null | undefined,
  scratch: WorkspaceFollowCameraScratch,
): boolean {
  if (!activeCamera?.object3d) return false
  const source = activeCamera.viewNode || activeCamera.object3d
  source.updateWorldMatrix(true, false)
  source.matrixWorld.decompose(scratch.position, scratch.quaternion, scratch.scale)
  camera.position.copy(scratch.position)
  camera.quaternion.copy(scratch.quaternion)
  const proj = activeCamera.object3d.isCamera ? activeCamera.object3d : null
  if (proj?.isPerspectiveCamera) {
    camera.fov = proj.fov
    camera.near = Math.max(0.001, proj.near)
    camera.far = Math.max(camera.near + 1, proj.far)
    camera.updateProjectionMatrix()
  }
  orbit.enabled = false
  return true
}

function vec3FromArray(value: unknown, fallback: WorkspaceVec3 = [0, 0, 0]): WorkspaceVec3 {
  if (Array.isArray(value) && value.length >= 3) {
    return [Number(value[0]) || 0, Number(value[1]) || 0, Number(value[2]) || 0]
  }
  return [...fallback]
}
