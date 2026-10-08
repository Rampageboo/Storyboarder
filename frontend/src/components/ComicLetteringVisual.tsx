import type { ComicLettering } from '../types/comic'
import { letteringLines, textUnits } from '../utils/comicLettering'

export function ComicLetteringVisual({ item }: { item: ComicLettering }) {
  const { width: w, height: h, font_size: size } = item
  const body = item.kind === 'speech' ? h * .82 : h
  const lines = letteringLines(item)
  return <svg width="100%" height="100%" viewBox={`0 0 ${w} ${h}`} aria-label={item.text}>
    <defs><clipPath id={`text-${item.id}`}><rect x={8} y={8} width={Math.max(0, w - 16)} height={Math.max(0, body - 16)} /></clipPath></defs>
    {item.kind === 'speech' ? <>
      <path d={`M ${w * .36} ${body * .8} L ${w * item.tail} ${h - item.border / 2} L ${w * .6} ${body * .82}`} fill={item.fill} stroke={item.color} strokeWidth={item.border} />
      <ellipse cx={w / 2} cy={body / 2} rx={Math.max(0, (w - item.border) / 2)} ry={Math.max(0, (body - item.border) / 2)} fill={item.fill} stroke={item.color} strokeWidth={item.border} />
    </> : item.kind === 'caption' ? <rect x={item.border / 2} y={item.border / 2} width={w - item.border} height={h - item.border} fill={item.fill} stroke={item.color} strokeWidth={item.border} /> : null}
    <g fill={item.color} fontFamily="Microsoft YaHei, Arial, sans-serif" fontSize={size} xmlSpace="preserve" clipPath={`url(#text-${item.id})`}>
      {item.vertical ? lines.map((line, i) => Array.from(line).map((char, j) =>
        <text key={`${i}-${j}`} x={w / 2 + (lines.length - 1) * size * .6 - i * size * 1.2} y={16 + size + j * size} textAnchor="middle">{char}</text>)) :
        lines.map((line, i) => <text key={i} x={Math.max(8, (w - textUnits(line) * size) / 2)} y={Math.max(size + 8, (body - lines.length * size * 1.2) / 2 + size) + i * size * 1.2}>{line}</text>)}
    </g>
  </svg>
}
