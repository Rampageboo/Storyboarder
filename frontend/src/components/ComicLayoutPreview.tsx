import type { PanelRect } from '../utils/comicLayout'
import { panelPoints } from '../utils/comicLayout'
import type { ComicPanel } from '../types/comic'

export function ComicLayoutPreview({ width, height, panels, spread = false }: {
  width: number; height: number; panels: (PanelRect & Pick<ComicPanel, 'points'>)[]; spread?: boolean
}) {
  return <svg className="comic-layout-preview" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
    <rect className="comic-preview-paper" x={0} y={0} width={width} height={height} />
    {spread ? <line className="comic-preview-spine" x1={width / 2} x2={width / 2} y1={0} y2={height} /> : null}
    {panels.map((panel, index) => <polygon key={index} className="comic-preview-cell"
      points={panelPoints(panel).map(([x, y]) => `${panel.x + x * panel.width},${panel.y + y * panel.height}`).join(' ')} />)}
  </svg>
}
