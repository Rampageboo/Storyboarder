import type { BaseBrush, Canvas, Point } from 'fabric'
import { getStroke } from 'perfect-freehand'

type FabricModule = typeof import('fabric')
type BrushEvent = Parameters<BaseBrush['onMouseDown']>[1]
type Sample = [number, number, number]

export interface FreehandSettings {
  color: string
  size: number
  opacity: number
  stabilize: number
  pressure: boolean
  marker: boolean
  eraser: boolean
}

// Use the same closed outline for the live canvas and the editable Fabric path.
function outlinePath(points: number[][]): string {
  if (!points.length) return ''
  const start = points[0]
  let path = `M ${start[0]} ${start[1]}`
  for (let index = 0; index < points.length; index++) {
    const point = points[index]
    const next = points[(index + 1) % points.length]
    path += ` Q ${point[0]} ${point[1]} ${(point[0] + next[0]) / 2} ${(point[1] + next[1]) / 2}`
  }
  return `${path} Z`
}

export function createFreehandBrush(fabric: FabricModule, canvas: Canvas, settings: FreehandSettings) {
  return new class extends fabric.BaseBrush {
    private samples: Sample[] = []
    private stylus = false
    private frame = 0

    constructor() {
      super(canvas)
      this.width = settings.size
      this.color = settings.color
    }

    private path() {
      return outlinePath(getStroke(this.samples, {
        size: this.width,
        thinning: settings.pressure && !settings.marker && !settings.eraser ? 0.65 : 0,
        simulatePressure: !this.stylus,
        smoothing: 0.55,
        streamline: settings.eraser ? 0 : settings.stabilize / 100 * 0.8,
        // Keep the live tip under the pointer, including when ending a short stroke.
        last: true,
      }))
    }

    private addSample(point: Point, event: BrushEvent['e']) {
      const pointer = event as PointerEvent
      const pressure = this.stylus ? Math.max(0.01, Math.min(1, pointer.pressure)) : 0.5
      const last = this.samples.at(-1)
      if (last && Math.hypot(point.x - last[0], point.y - last[1]) < 0.25 && Math.abs(pressure - last[2]) < 0.01) return
      if (event.shiftKey && this.samples.length > 1) this.samples.splice(1)
      this.samples.push([point.x, point.y, pressure])
    }

    onMouseDown(point: Point, { e }: BrushEvent) {
      if (!canvas._isMainEvent(e)) return
      this.cancel()
      this.stylus = (e as PointerEvent).pointerType === 'pen'
      this.addSample(point, e)
      this._render()
    }

    onMouseMove(point: Point, { e }: BrushEvent) {
      if (!this.samples.length || !canvas._isMainEvent(e)) return
      const pointer = e as PointerEvent
      const coalesced = pointer.getCoalescedEvents?.() ?? []
      if (coalesced.length && !e.shiftKey) {
        const bounds = canvas.upperCanvasEl.getBoundingClientRect()
        for (const sample of coalesced) {
          this.addSample(new fabric.Point(
            point.x + (sample.clientX - pointer.clientX) * canvas.width / bounds.width,
            point.y + (sample.clientY - pointer.clientY) * canvas.height / bounds.height,
          ), sample)
        }
      }
      this.addSample(point, e)
      if (!this.frame) this.frame = requestAnimationFrame(() => { this.frame = 0; this._render() })
    }

    onMouseUp({ e, pointer }: BrushEvent) {
      if (!canvas._isMainEvent(e)) return true
      if (this.samples.length) {
        // Pointer-up pressure is normally zero. Preserve the final contact pressure.
        const last = this.samples.at(-1)!
        if (Math.hypot(pointer.x - last[0], pointer.y - last[1]) >= 0.25) {
          this.samples.push([pointer.x, pointer.y, last[2]])
        }
      }
      this.finish()
      return false
    }

    _render() {
      if (!this.samples.length || canvas.destroyed) return
      canvas.clearContext(canvas.contextTop)
      // Erase the visible artwork during the gesture, not an unrelated white overlay.
      if (settings.eraser) canvas.renderAll()
      const context = settings.eraser ? canvas.getContext() : canvas.contextTop
      this._saveAndTransform(context)
      context.globalCompositeOperation = settings.eraser ? 'destination-out' : 'source-over'
      context.globalAlpha = settings.eraser ? 1 : settings.opacity / 100
      context.fillStyle = this.color
      context.fill(new Path2D(this.path()))
      context.restore()
    }

    finish() {
      if (this.frame) cancelAnimationFrame(this.frame)
      this.frame = 0
      if (!this.samples.length || canvas.destroyed) return
      const path = new fabric.Path(this.path(), {
        fill: this.color,
        strokeWidth: 0,
        opacity: settings.eraser ? 1 : settings.opacity / 100,
        globalCompositeOperation: settings.eraser ? 'destination-out' : 'source-over',
        // destination-out must composite against prior objects, not its own empty cache.
        objectCaching: !settings.eraser,
      })
      this.samples = []
      canvas.clearContext(canvas.contextTop)
      canvas.fire('before:path:created', { path })
      canvas.add(path)
      path.setCoords()
      canvas.requestRenderAll()
      canvas.fire('path:created', { path })
    }

    cancel() {
      if (this.frame) cancelAnimationFrame(this.frame)
      this.frame = 0
      this.samples = []
      if (!canvas.destroyed) {
        canvas.clearContext(canvas.contextTop)
        canvas.requestRenderAll()
      }
    }
  }()
}
