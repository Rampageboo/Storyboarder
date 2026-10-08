import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import {
  ArrowUpRight, Circle, Cursor, Eye, EyeSlash, Highlighter, LineSegment, Square, TextT, Trash,
} from '@phosphor-icons/react'
import type { Annotation, AnnotationPoint as Point } from '../hooks/useBoardAnnotations'
import './AnnotationLayer.css'

/**
 * Board annotations: a palette of markup tools and an SVG overlay drawn over the
 * board composite. Items keep the stored shape {type, start:{x,y}, end:{x,y}, text?}
 * with coordinates normalised to the board (0..1), the format the annotation file
 * has always used. Unknown item types are preserved untouched.
 */

type ShapeType = 'arrow' | 'line' | 'box' | 'circle' | 'highlight' | 'text'
type Tool = 'select' | ShapeType

const TOOLS: { tool: Tool; label: string; Icon: typeof Cursor }[] = [
  { tool: 'select', label: 'Select', Icon: Cursor },
  { tool: 'arrow', label: 'Arrow', Icon: ArrowUpRight },
  { tool: 'line', label: 'Line', Icon: LineSegment },
  { tool: 'box', label: 'Box', Icon: Square },
  { tool: 'circle', label: 'Ellipse', Icon: Circle },
  { tool: 'highlight', label: 'Highlight', Icon: Highlighter },
  { tool: 'text', label: 'Text', Icon: TextT },
]
const DRAWN = new Set(['arrow', 'line', 'box', 'circle', 'highlight', 'text'])
const MARK = '#ff4d2e'
const HIGHLIGHT = '#ffd23f'

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value))
}

function isPoint(value: unknown): value is Point {
  return !!value && typeof value === 'object' && Number.isFinite((value as Point).x) && Number.isFinite((value as Point).y)
}

function drawable(item: Annotation): item is Annotation & { type: ShapeType; start: Point; end: Point } {
  return DRAWN.has(String(item.type)) && isPoint(item.start) && isPoint(item.end)
}

export function AnnotationPalette({
  tool, visible, count, disabled, onTool, onToggleVisible, onClear,
}: {
  tool: Tool
  visible: boolean
  count: number
  disabled: boolean
  onTool: (tool: Tool) => void
  onToggleVisible: () => void
  onClear: () => void
}) {
  return (
    <div className="annot-palette" role="toolbar" aria-label="Annotation tools">
      {TOOLS.map(({ tool: item, label, Icon }) => (
        <button key={item} type="button" className="ghost icon-btn" aria-label={label} title={label}
          aria-pressed={tool === item} disabled={disabled} onClick={() => onTool(item)}>
          <Icon size={17} />
        </button>
      ))}
      <span className="annot-palette-divider" />
      <button type="button" className="ghost icon-btn" aria-label={visible ? 'Hide annotations' : 'Show annotations'}
        title={visible ? 'Hide annotations' : 'Show annotations'} onClick={onToggleVisible}>
        {visible ? <Eye size={17} /> : <EyeSlash size={17} />}
      </button>
      <button type="button" className="ghost icon-btn" aria-label="Clear all annotations" title="Clear all annotations"
        disabled={disabled || !count} onClick={onClear}>
        <Trash size={17} />
      </button>
    </div>
  )
}

export function AnnotationOverlay({
  items, tool, visible, onChange,
}: {
  items: Annotation[]
  tool: Tool
  visible: boolean
  onChange: (next: Annotation[]) => void
}) {
  const ref = useRef<SVGSVGElement | null>(null)
  const [size, setSize] = useState({ w: 1, h: 1 })
  const [draft, setDraft] = useState<Annotation | null>(null)
  const [selected, setSelected] = useState(-1)

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      const box = entry.contentRect
      setSize({ w: Math.max(1, box.width), h: Math.max(1, box.height) })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (tool !== 'select' || selected < 0) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault()
        event.stopPropagation()
        onChange(items.filter((_item, index) => index !== selected))
        setSelected(-1)
      } else if (event.key === 'Escape') {
        setSelected(-1)
      }
    }
    // Capture so the board-level Delete shortcut does not also delete the board.
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [items, onChange, selected, tool])

  const toPoint = (event: ReactPointerEvent) => {
    const box = ref.current!.getBoundingClientRect()
    return { x: clamp01((event.clientX - box.left) / box.width), y: clamp01((event.clientY - box.top) / box.height) }
  }

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (tool === 'select' || event.button !== 0) return
    event.preventDefault()
    const point = toPoint(event)
    if (tool === 'text') {
      const text = window.prompt('Annotation text')?.trim()
      if (text) onChange([...items, { type: 'text', start: point, end: point, text, color: MARK }])
      return
    }
    ref.current?.setPointerCapture(event.pointerId)
    setDraft({ type: tool, start: point, end: point, color: tool === 'highlight' ? HIGHLIGHT : MARK })
  }

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!draft) return
    setDraft({ ...draft, end: toPoint(event) })
  }

  const onPointerUp = () => {
    if (!draft) return
    const start = draft.start as Point
    const end = draft.end as Point
    setDraft(null)
    if (Math.hypot((end.x - start.x) * size.w, (end.y - start.y) * size.h) < 6) return
    onChange([...items, draft])
  }

  if (!visible && tool === 'select') return null
  const px = (point: Point) => ({ x: point.x * size.w, y: point.y * size.h })
  const shapes = visible ? items : []

  const render = (item: Annotation, index: number, isDraft = false) => {
    if (!drawable(item)) return null
    const a = px(item.start)
    const b = px(item.end)
    const isHighlight = item.type === 'highlight'
    const color = typeof item.color === 'string' ? item.color : isHighlight ? HIGHLIGHT : MARK
    const pick = tool === 'select' && !isDraft ? () => setSelected(index) : undefined
    const className = 'annot-shape' + (index === selected && !isDraft ? ' is-selected' : '') + (pick ? ' is-pickable' : '')
    const common = { className, onPointerDown: pick, stroke: color, strokeWidth: 3, fill: 'none' }
    switch (item.type) {
      case 'line':
      case 'arrow': {
        const angle = Math.atan2(b.y - a.y, b.x - a.x)
        const head = 14
        const wing = (offset: number) => `${b.x - head * Math.cos(angle + offset)},${b.y - head * Math.sin(angle + offset)}`
        return (
          <g key={index} {...common}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="annot-hit" />
            {item.type === 'arrow' ? <polygon points={`${b.x},${b.y} ${wing(Math.PI / 7)} ${wing(-Math.PI / 7)}`} fill={color} /> : null}
          </g>
        )
      }
      case 'box':
      case 'highlight':
        return (
          <rect key={index} {...common} x={Math.min(a.x, b.x)} y={Math.min(a.y, b.y)} width={Math.abs(b.x - a.x)} height={Math.abs(b.y - a.y)}
            fill={isHighlight ? color : 'transparent'} fillOpacity={isHighlight ? 0.28 : 0} strokeOpacity={isHighlight ? 0.85 : 1} />
        )
      case 'circle':
        return (
          <ellipse key={index} {...common} cx={(a.x + b.x) / 2} cy={(a.y + b.y) / 2} rx={Math.abs(b.x - a.x) / 2} ry={Math.abs(b.y - a.y) / 2}
            fill="transparent" />
        )
      case 'text':
        return (
          <text key={index} className={className} onPointerDown={pick} x={a.x} y={a.y} fill={color} stroke="rgba(0,0,0,0.55)"
            strokeWidth={3} paintOrder="stroke" fontSize={Math.max(14, size.h * 0.035)} fontWeight={600}>
            {String(item.text || 'Text')}
          </text>
        )
      default:
        return null
    }
  }

  return (
    <svg
      ref={ref}
      className={'annot-overlay' + (tool !== 'select' ? ' is-drawing' : '') + (tool === 'select' ? ' is-selecting' : '')}
      viewBox={`0 0 ${size.w} ${size.h}`}
      onPointerDown={(event) => {
        if (tool === 'select' && event.target === ref.current) setSelected(-1)
        onPointerDown(event)
      }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => setDraft(null)}
      aria-label="Board annotations"
    >
      {shapes.map((item, index) => render(item, index))}
      {draft ? render(draft, -1, true) : null}
    </svg>
  )
}

export type { Tool as AnnotationTool }
