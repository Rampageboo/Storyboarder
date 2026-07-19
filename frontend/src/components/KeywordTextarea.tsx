import { useMemo, useRef, type TextareaHTMLAttributes } from 'react'
import './KeywordTextarea.css'

export interface KeywordAssetHint {
  id: string
  title: string
  keywords: string[]
  path: string
}

interface HighlightRange {
  start: number
  end: number
  keyword: string
  assetIds: string[]
}

type KeywordTextareaProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'value' | 'onChange'> & {
  value: string
  onValueChange: (value: string) => void
  assets: KeywordAssetHint[]
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function isAsciiWordCharacter(value: string | undefined) {
  return !!value && /[A-Za-z0-9_]/.test(value)
}

function highlightRanges(value: string, assets: KeywordAssetHint[]): HighlightRange[] {
  const keywordAssets = new Map<string, { keyword: string; assetIds: Set<string> }>()
  for (const asset of assets) {
    for (const rawKeyword of asset.keywords) {
      const keyword = rawKeyword.trim()
      const key = keyword.toLocaleLowerCase()
      if (!keyword) continue
      const existing = keywordAssets.get(key)
      if (existing) existing.assetIds.add(asset.id)
      else keywordAssets.set(key, { keyword, assetIds: new Set([asset.id]) })
    }
  }

  const ranges: HighlightRange[] = []
  const entries = [...keywordAssets.values()].sort((a, b) => b.keyword.length - a.keyword.length)
  for (const entry of entries) {
    const matcher = new RegExp(escapeRegExp(entry.keyword), 'giu')
    for (const match of value.matchAll(matcher)) {
      const start = match.index ?? 0
      const end = start + match[0].length
      const enforceStartBoundary = isAsciiWordCharacter(entry.keyword[0])
      const enforceEndBoundary = isAsciiWordCharacter(entry.keyword.at(-1))
      if (enforceStartBoundary && isAsciiWordCharacter(value[start - 1])) continue
      if (enforceEndBoundary && isAsciiWordCharacter(value[end])) continue
      if (ranges.some((range) => start < range.end && end > range.start)) continue
      ranges.push({ start, end, keyword: entry.keyword, assetIds: [...entry.assetIds] })
    }
  }
  return ranges.sort((a, b) => a.start - b.start)
}

export function KeywordTextarea({ value, onValueChange, assets, className = '', ...props }: KeywordTextareaProps) {
  const backdropRef = useRef<HTMLDivElement | null>(null)
  const ranges = useMemo(() => highlightRanges(value, assets), [assets, value])
  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets])
  const matchedAssets = useMemo(() => {
    const ids = new Set(ranges.flatMap((range) => range.assetIds))
    return [...ids].map((id) => assetById.get(id)).filter((asset): asset is KeywordAssetHint => !!asset)
  }, [assetById, ranges])

  const highlightedContent = useMemo(() => {
    const content = []
    let cursor = 0
    for (const range of ranges) {
      content.push(value.slice(cursor, range.start))
      const labels = range.assetIds.map((id) => assetById.get(id)?.title || id).join(', ')
      content.push(<mark key={`${range.start}:${range.end}`} title={`Linked 3D asset: ${labels}`}>{value.slice(range.start, range.end)}</mark>)
      cursor = range.end
    }
    content.push(value.slice(cursor))
    if (value.endsWith('\n')) content.push(' ')
    return content
  }, [assetById, ranges, value])

  return (
    <div className="keyword-textarea-field">
      <div className="keyword-textarea-shell">
        <div ref={backdropRef} className="keyword-textarea-backdrop" aria-hidden="true">
          {highlightedContent}
        </div>
        <textarea
          {...props}
          className={`keyword-textarea-control ${className}`.trim()}
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onScroll={(event) => {
            if (backdropRef.current) {
              backdropRef.current.scrollTop = event.currentTarget.scrollTop
              backdropRef.current.scrollLeft = event.currentTarget.scrollLeft
            }
            props.onScroll?.(event)
          }}
        />
      </div>
      {matchedAssets.length ? (
        <div className="keyword-asset-matches" aria-live="polite">
          <span>Linked 3D</span>
          {matchedAssets.map((asset) => (
            <span className="keyword-asset-match" key={asset.id} title={asset.path}>{asset.title}</span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
