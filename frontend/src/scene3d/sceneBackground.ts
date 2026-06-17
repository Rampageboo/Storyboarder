/** Parse project canvas hex (#rrggbb) into a Three.js color integer. */
export function canvasHexToThreeColor(hex: string | undefined | null, fallback = 0x1a1d21): number {
  const raw = String(hex || '').trim()
  const match = /^#?([0-9a-f]{6})$/i.exec(raw)
  if (!match) return fallback
  return Number.parseInt(match[1], 16)
}
