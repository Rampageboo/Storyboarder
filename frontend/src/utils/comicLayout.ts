import type { ComicPage, ComicPanel } from '../types/comic'

export type PanelRect = Pick<ComicPanel, 'x' | 'y' | 'width' | 'height'>
export type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'
export const comicGridSize = 24
export type Point = [number, number]
export type Alignment = 'left' | 'center-x' | 'right' | 'top' | 'center-y' | 'bottom' | 'distribute-x' | 'distribute-y'
export function alignPanels(panels: ComicPanel[], operation: Alignment): ComicPanel[] {
  const items = panels.filter(panel => !panel.locked)
  if (items.length < 2) return items
  const left = Math.min(...items.map(p => p.x)), top = Math.min(...items.map(p => p.y))
  const right = Math.max(...items.map(p => p.x + p.width)), bottom = Math.max(...items.map(p => p.y + p.height))
  if (operation.startsWith('distribute')) {
    if (items.length < 3) return items
    const horizontal = operation === 'distribute-x'
    const sorted = [...items].sort((a, b) => horizontal ? a.x - b.x : a.y - b.y)
    const span = horizontal ? right - left : bottom - top
    const gap = (span - sorted.reduce((sum, p) => sum + (horizontal ? p.width : p.height), 0)) / (sorted.length - 1)
    let cursor = horizontal ? left : top
    return sorted.map(p => { const next = { ...p, [horizontal ? 'x' : 'y']: Math.round(cursor) }; cursor += (horizontal ? p.width : p.height) + gap; return next })
  }
  return items.map(p => ({ ...p,
    x: operation === 'left' ? left : operation === 'right' ? right - p.width : operation === 'center-x' ? Math.round((left + right - p.width) / 2) : p.x,
    y: operation === 'top' ? top : operation === 'bottom' ? bottom - p.height : operation === 'center-y' ? Math.round((top + bottom - p.height) / 2) : p.y }))
}
export const rectanglePoints: Point[] = [[0, 0], [1, 0], [1, 1], [0, 1]]
export function panelPoints(panel: Pick<ComicPanel, 'points'>): Point[] { return panel.points ?? rectanglePoints }
export function polygonArea(points: Point[]): number {
  return Math.abs(points.reduce((sum, [x, y], i) => {
    const next = points[(i + 1) % points.length]
    return sum + x * next[1] - next[0] * y
  }, 0)) / 2
}
export function validPolygon(points: Point[]): boolean {
  if (points.length < 3 || points.length > 8 || polygonArea(points) < .01) return false
  let sign = 0
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length], c = points[(i + 2) % points.length]
    if (a.some(value => !Number.isFinite(value) || value < 0 || value > 1)) return false
    const cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
    if (Math.abs(cross) < 1e-8) continue
    if (sign && Math.sign(cross) !== sign) return false
    sign = Math.sign(cross)
  }
  const orientation = (a: Point, b: Point, c: Point) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
  for (let i = 0; i < points.length; i++) for (let j = i + 2; j < points.length; j++) {
    if (i === 0 && j === points.length - 1) continue
    const a = points[i], b = points[(i + 1) % points.length], c = points[j], d = points[(j + 1) % points.length]
    if (orientation(a, b, c) * orientation(a, b, d) < 0 && orientation(c, d, a) * orientation(c, d, b) < 0) return false
  }
  return sign !== 0
}
export function panelClip(panel: Pick<ComicPanel, 'points'>): string {
  return `polygon(${panelPoints(panel).map(([x, y]) => `${x * 100}% ${y * 100}%`).join(',')})`
}

/** Half-plane clipping in page pixels. A line dragged across a convex panel cuts both sides. */
export function knifeSplit(panel: ComicPanel, from: Point, to: Point, gap: number): [PanelRect & { points: Point[] }, PanelRect & { points: Point[] }] | null {
  const dx = to[0] - from[0], dy = to[1] - from[1], length = Math.hypot(dx, dy)
  if (length < 8) return null
  const points: Point[] = panelPoints(panel).map(([x, y]) => [panel.x + x * panel.width, panel.y + y * panel.height])
  const distance = ([x, y]: Point) => (dx * (y - from[1]) - dy * (x - from[0])) / length
  const clip = (side: number) => {
    const result: Point[] = []
    for (let i = 0; i < points.length; i++) {
      const a = points[i], b = points[(i + 1) % points.length]
      const da = side * distance(a) - gap / 2, db = side * distance(b) - gap / 2
      if (da >= 0) result.push(a)
      if ((da >= 0) !== (db >= 0)) {
        const t = da / (da - db)
        result.push([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
      }
    }
    if (result.length < 3 || polygonArea(result) < 256) return null
    const x = Math.floor(Math.min(...result.map(p => p[0]))), y = Math.floor(Math.min(...result.map(p => p[1])))
    const width = Math.ceil(Math.max(...result.map(p => p[0]))) - x, height = Math.ceil(Math.max(...result.map(p => p[1]))) - y
    const normalized: Point[] = result.map(p => [(p[0] - x) / width, (p[1] - y) / height])
    return width >= 16 && height >= 16 && validPolygon(normalized) ? { x, y, width, height, points: normalized } : null
  }
  const a = clip(1), b = clip(-1)
  return a && b ? [a, b] : null
}

/** Insert/remove blank pacing space without changing artwork or the preceding panels. */
export function shiftScrollSpace(page: ComicPage, at: number, amount: number): ComicPage | null {
  const height = page.height + amount
  if (height < 64 || height > 32000 || height * page.width > 64000000) return null
  if (amount && page.panels.some(panel => panel.locked && panel.y >= at)) return null
  const panels = page.panels.map(panel => panel.y >= at ? { ...panel, y: panel.y + amount } : panel)
  const lettering = (page.lettering ?? []).map(item => item.y >= at ? { ...item, y: item.y + amount } : item)
  const original = [...page.panels, ...(page.lettering ?? [])]
  const precedingBottom = Math.max(0, ...original.filter(item => item.y < at).map(item => item.y + item.height))
  if (amount < 0 && original.some(item => item.y >= at && item.y + amount < precedingBottom)) return null
  if ([...panels, ...lettering].some(item => item.y < 0 || item.y + item.height > height)) return null
  return { ...page, height, panels, lettering }
}
export function snapCoordinate(value: number, snap: boolean): number {
  return Math.round(snap ? Math.round(value / comicGridSize) * comicGridSize : value)
}

export function splitPanel(rect: PanelRect, axis: 'horizontal' | 'vertical', gutter: number, direction: 'ltr' | 'rtl'): [PanelRect, PanelRect] | null {
  const span = axis === 'horizontal' ? rect.height : rect.width
  const first = Math.floor((span - gutter) / 2), second = span - gutter - first
  if (first < 16 || second < 16) return null
  if (axis === 'horizontal') return [{ ...rect, height: first }, { ...rect, y: rect.y + first + gutter, height: second }]
  const halves: [PanelRect, PanelRect] = [{ ...rect, width: first }, { ...rect, x: rect.x + first + gutter, width: second }]
  return direction === 'rtl' ? [halves[1], halves[0]] : halves
}

/** Keep the opposite edge fixed; clamp each dragged edge to the page and a 16px minimum. */
export function resizePanel(origin: PanelRect, handle: ResizeHandle, dx: number, dy: number, page: Pick<ComicPage, 'width' | 'height'>): PanelRect {
  let left = origin.x, top = origin.y, right = left + origin.width, bottom = top + origin.height
  if (handle.includes('w')) left = Math.round(Math.max(0, Math.min(right - 16, left + dx)))
  if (handle.includes('e')) right = Math.round(Math.max(left + 16, Math.min(page.width, right + dx)))
  if (handle.includes('n')) top = Math.round(Math.max(0, Math.min(bottom - 16, top + dy)))
  if (handle.includes('s')) bottom = Math.round(Math.max(top + 16, Math.min(page.height, bottom + dy)))
  return { x: left, y: top, width: right - left, height: bottom - top }
}
