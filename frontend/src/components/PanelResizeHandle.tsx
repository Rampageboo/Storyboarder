import { useLayoutEffect, useRef } from 'react'
import { bindPanelResize, type ResizeAxis, type ResizeEdge } from '../utils/panelResize'
import './PanelResizeHandle.css'

interface Props {
  panelKey: string
  label: string
  edge: ResizeEdge
  width?: ResizeAxis
  height?: ResizeAxis
  host?: string
  target?: string
  bounds?: string
  className?: string
  hidden?: boolean
}

export function PanelResizeHandle({ panelKey, label, edge, width, height, host, target, bounds, className = '', hidden }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const widthProperty = width?.property, widthMin = width?.min, widthMax = width?.max, widthFraction = width?.fraction, widthReserve = width?.reserve
  const heightProperty = height?.property, heightMin = height?.min, heightMax = height?.max, heightFraction = height?.fraction, heightReserve = height?.reserve
  useLayoutEffect(() => {
    const handle = ref.current
    if (!handle) return
    const root = host ? handle.closest<HTMLElement>(host) : handle.parentElement
    const panel = target ? root?.querySelector<HTMLElement>(target) : handle.parentElement
    const boundary = bounds ? handle.closest<HTMLElement>(bounds) : root
    if (!panel || !root || !boundary) return
    return bindPanelResize(handle, { key: panelKey, edge, panel, host: root, bounds: boundary,
      width: widthProperty && widthMin !== undefined ? { property: widthProperty, min: widthMin, max: widthMax, fraction: widthFraction, reserve: widthReserve } : undefined,
      height: heightProperty && heightMin !== undefined ? { property: heightProperty, min: heightMin, max: heightMax, fraction: heightFraction, reserve: heightReserve } : undefined })
  }, [panelKey, edge, host, target, bounds, widthProperty, widthMin, widthMax, widthFraction, widthReserve, heightProperty, heightMin, heightMax, heightFraction, heightReserve])
  return <div ref={ref} className={`panel-resize-handle ${className}`} data-edge={edge} hidden={hidden}
    role={width && height ? 'button' : 'separator'} tabIndex={0} aria-label={label}
    aria-orientation={width && height ? undefined : width ? 'vertical' : 'horizontal'}
    title="Drag or use arrow keys to resize. Double-click or press Home to reset." />
}
