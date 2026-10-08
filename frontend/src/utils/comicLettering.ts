import type { ComicLettering } from '../types/comic'

// Explicit newline and CJK character wrapping are shared with the PNG compositor.
export function textUnits(text: string): number {
  return Array.from(text).reduce((sum, char) => sum + (char.codePointAt(0)! > 255 ? 1 : .6), 0)
}
export function letteringLines(item: ComicLettering): string[] {
  const width = item.width * (item.kind === 'speech' ? .66 : 1) - 16
  const height = item.height * (item.kind === 'speech' ? .78 : 1) - 16
  const limit = Math.max(1, (item.vertical ? height : width) / item.font_size)
  const lines: string[] = []
  for (const paragraph of item.text.split('\n')) {
    let line = ''
    for (const char of Array.from(paragraph)) {
      if (line && (item.vertical ? Array.from(line).length + 1 : textUnits(line + char)) > limit) { lines.push(line); line = '' }
      line += char
    }
    lines.push(line)
  }
  return lines
}
export function letteringOverflows(item: ComicLettering): boolean {
  const available = item.vertical ? item.width * (item.kind === 'speech' ? .66 : 1) - 16 : item.height * (item.kind === 'speech' ? .78 : 1) - 16
  return letteringLines(item).length * item.font_size * 1.2 > available
}
