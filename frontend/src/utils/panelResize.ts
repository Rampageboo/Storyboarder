export type ResizeEdge = 'left' | 'right' | 'top' | 'bottom' | 'bottom-left'

export interface ResizeAxis {
  property: string
  min: number
  max?: number
  fraction?: number
  reserve?: number
}

interface PanelResizeOptions {
  key: string
  edge: ResizeEdge
  panel: HTMLElement
  host: HTMLElement
  bounds: HTMLElement
  width?: ResizeAxis
  height?: ResizeAxis
}

const storagePrefix = 'storyboarder.panel-size.'

function readSize(key: string): Record<string, number> {
  try {
    const value = JSON.parse(localStorage.getItem(storagePrefix + key) ?? '{}')
    return value && typeof value === 'object' ? value : {}
  } catch { return {} }
}

/** Shared by React panels and the independently mounted Scene3D editor. */
export function bindPanelResize(handle: HTMLElement, options: PanelResizeOptions): () => void {
  const { key, edge, panel, host, bounds, width, height } = options
  const axes = { width, height }
  const saved = readSize(key)
  for (const dimension of ['width', 'height'] as const) {
    const axis = axes[dimension], value = saved[dimension]
    if (axis && Number.isFinite(value) && value > 0) {
      host.style.setProperty(axis.property, `${Math.min(axis.max ?? Infinity, Math.max(axis.min, value))}px`)
    }
  }

  const limits = (dimension: 'width' | 'height', axis: ResizeAxis) => {
    const available = bounds.getBoundingClientRect()[dimension]
    const max = Math.max(0, Math.min(axis.max ?? Infinity, available * (axis.fraction ?? 1) - (axis.reserve ?? 0)))
    return { min: Math.min(axis.min, max), max }
  }
  const setSize = (dimension: 'width' | 'height', value: number) => {
    const axis = axes[dimension]
    if (!axis) return
    const { min, max } = limits(dimension, axis)
    host.style.setProperty(axis.property, `${Math.round(Math.max(min, Math.min(max, value)))}px`)
  }
  const save = () => {
    const next = readSize(key), rect = panel.getBoundingClientRect()
    for (const dimension of ['width', 'height'] as const) {
      if (axes[dimension]) next[dimension] = Math.round(rect[dimension])
    }
    try { localStorage.setItem(storagePrefix + key, JSON.stringify(next)) } catch { /* Layout remains usable without storage. */ }
  }
  const reset = () => {
    const next = readSize(key)
    for (const dimension of ['width', 'height'] as const) {
      const axis = axes[dimension]
      if (!axis) continue
      host.style.removeProperty(axis.property)
      delete next[dimension]
    }
    try { localStorage.setItem(storagePrefix + key, JSON.stringify(next)) } catch { /* Optional preference. */ }
  }
  const updateAria = () => {
    if (width && height) return
    const dimension = width ? 'width' : 'height', axis = axes[dimension]
    if (!axis) return
    const { min, max } = limits(dimension, axis)
    handle.setAttribute('aria-valuemin', String(Math.round(min)))
    handle.setAttribute('aria-valuemax', String(Math.round(max)))
    handle.setAttribute('aria-valuenow', String(Math.round(panel.getBoundingClientRect()[dimension])))
  }
  const observer = new ResizeObserver(updateAria)
  observer.observe(panel)
  observer.observe(bounds)

  let drag: { id: number; x: number; y: number; width: number; height: number; cursor: string; selection: string; previousWidth: string; previousHeight: string } | null = null
  const stop = (cancel: boolean) => {
    if (!drag) return
    const previous = drag
    drag = null
    if (cancel) {
      if (width) host.style.setProperty(width.property, previous.previousWidth)
      if (height) host.style.setProperty(height.property, previous.previousHeight)
    } else save()
    document.body.style.cursor = previous.cursor
    document.body.style.userSelect = previous.selection
    handle.removeAttribute('data-resizing')
    if (handle.hasPointerCapture(previous.id)) handle.releasePointerCapture(previous.id)
  }
  const onDown = (event: PointerEvent) => {
    if (event.button !== 0 || !event.isPrimary || drag) return
    event.preventDefault()
    event.stopPropagation()
    const rect = panel.getBoundingClientRect()
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, width: rect.width, height: rect.height,
      cursor: document.body.style.cursor, selection: document.body.style.userSelect,
      previousWidth: width ? host.style.getPropertyValue(width.property) : '',
      previousHeight: height ? host.style.getPropertyValue(height.property) : '' }
    handle.focus({ preventScroll: true })
    handle.setPointerCapture(event.pointerId)
    handle.setAttribute('data-resizing', 'true')
    document.body.style.cursor = getComputedStyle(handle).cursor
    document.body.style.userSelect = 'none'
  }
  const onMove = (event: PointerEvent) => {
    if (!drag || drag.id !== event.pointerId) return
    if (width) setSize('width', drag.width + (event.clientX - drag.x) * (edge.includes('left') ? -1 : 1))
    if (height) setSize('height', drag.height + (event.clientY - drag.y) * (edge === 'top' ? -1 : 1))
  }
  const onUp = (event: PointerEvent) => { if (drag?.id === event.pointerId) stop(false) }
  const onCancel = () => stop(true)
  const onDoubleClick = (event: MouseEvent) => { event.preventDefault(); event.stopPropagation(); reset() }
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && drag) { event.preventDefault(); event.stopPropagation(); stop(true); return }
    if (event.key === 'Home') { event.preventDefault(); event.stopPropagation(); reset(); return }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
    event.preventDefault()
    event.stopPropagation()
    const delta = (event.shiftKey ? 50 : 10)
    const rect = panel.getBoundingClientRect()
    if (width && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
      setSize('width', rect.width + delta * (event.key === 'ArrowRight' ? 1 : -1) * (edge.includes('left') ? -1 : 1))
    } else if (height && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
      setSize('height', rect.height + delta * (event.key === 'ArrowDown' ? 1 : -1) * (edge === 'top' ? -1 : 1))
    } else return
    save()
  }
  handle.addEventListener('pointerdown', onDown)
  handle.addEventListener('pointermove', onMove)
  handle.addEventListener('pointerup', onUp)
  handle.addEventListener('pointercancel', onCancel)
  handle.addEventListener('lostpointercapture', onCancel)
  handle.addEventListener('dblclick', onDoubleClick)
  handle.addEventListener('keydown', onKey)
  return () => {
    stop(true)
    observer.disconnect()
    handle.removeEventListener('pointerdown', onDown)
    handle.removeEventListener('pointermove', onMove)
    handle.removeEventListener('pointerup', onUp)
    handle.removeEventListener('pointercancel', onCancel)
    handle.removeEventListener('lostpointercapture', onCancel)
    handle.removeEventListener('dblclick', onDoubleClick)
    handle.removeEventListener('keydown', onKey)
  }
}
