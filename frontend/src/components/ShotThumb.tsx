import { useEffect, useState } from 'react'
import { shotImageUrl, shotThumbnailUrl } from '../api'
import './ShotThumb.css'

type ThumbStage = 'thumb' | 'image' | 'failed'

/** Thumbnail with silent fallback: thumbnail → full image → placeholder. */
export function ShotThumb({
  shotId,
  version,
  hasImage,
}: {
  shotId: string
  version: string | number
  hasImage: boolean
}) {
  const [stage, setStage] = useState<ThumbStage>(hasImage ? 'thumb' : 'failed')

  useEffect(() => {
    setStage(hasImage ? 'thumb' : 'failed')
  }, [shotId, version, hasImage])

  if (stage === 'failed') {
    return <div className="shot-thumb-empty">No image</div>
  }

  const base = stage === 'thumb' ? shotThumbnailUrl(shotId) : shotImageUrl(shotId)
  return (
    <img
      className="shot-thumb-img"
      src={`${base}?v=${encodeURIComponent(String(version))}`}
      alt=""
      loading="lazy"
      draggable={false}
      onError={() => setStage((s) => (s === 'thumb' ? 'image' : 'failed'))}
    />
  )
}
