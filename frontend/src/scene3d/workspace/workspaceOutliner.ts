/**
 * Outliner and camera-select UI data (extracted from scene3d.js).
 */

import type { WorkspaceImportedCamera } from './workspaceGlb'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type WorkspaceOutlinerEntry =
  | { kind: 'camera'; id: string; label: string; active: boolean }
  | { kind: 'object'; id: string; label: string; active: boolean }
  | { kind: 'empty'; label: string }

export function buildOutlinerEntries(
  mode: 'builtin' | 'blender',
  objects: Map<string, ThreeObject> | Iterable<[string, ThreeObject]>,
  importedCameras: WorkspaceImportedCamera[],
  activeCameraId: string,
  selectedId: string | null,
): WorkspaceOutlinerEntry[] {
  if (mode === 'blender') {
    if (!importedCameras.length) {
      return [{ kind: 'empty', label: '无相机' }]
    }
    return importedCameras.map((item) => ({
      kind: 'camera' as const,
      id: item.id,
      label: item.name,
      active: item.id === activeCameraId,
    }))
  }

  const entries: WorkspaceOutlinerEntry[] = []
  const iterable = objects instanceof Map ? objects.entries() : objects
  for (const [id, mesh] of iterable) {
    entries.push({
      kind: 'object',
      id,
      label: String(mesh.userData?.objectName || id),
      active: id === selectedId,
    })
  }
  return entries
}

export function renderOutlinerDom(outlinerEl: HTMLElement, entries: WorkspaceOutlinerEntry[]): void {
  outlinerEl.innerHTML = ''
  for (const entry of entries) {
    const li = document.createElement('li')
    if (entry.kind === 'empty') {
      li.className = 'scene3d-empty'
      li.textContent = entry.label
    } else if (entry.kind === 'camera') {
      li.dataset.cameraId = entry.id
      li.className = entry.active ? 'active' : ''
      li.textContent = `📷 ${entry.label}`
    } else {
      li.dataset.objectId = entry.id
      li.className = entry.active ? 'active' : ''
      li.textContent = entry.label
    }
    outlinerEl.appendChild(li)
  }
}

export type WorkspaceCameraSelectOption = { value: string; label: string }

export function buildCameraSelectOptions(
  importedCameras: WorkspaceImportedCamera[],
): WorkspaceCameraSelectOption[] {
  if (!importedCameras.length) {
    return [{ value: '', label: '（无相机）' }]
  }
  return importedCameras.map((item) => ({ value: item.id, label: item.name }))
}

export function populateCameraSelectDom(
  selectEl: HTMLSelectElement,
  options: WorkspaceCameraSelectOption[],
  activeCameraId = '',
): void {
  selectEl.innerHTML = ''
  for (const option of options) {
    const el = document.createElement('option')
    el.value = option.value
    el.textContent = option.label
    selectEl.appendChild(el)
  }
  selectEl.disabled = options.length === 1 && options[0].value === ''
  if (activeCameraId && !selectEl.disabled) {
    selectEl.value = activeCameraId
  }
}
