import { useState } from 'react'
import { shotImageUrl, shotThumbnailUrl } from '../api'
import './ShotThumb.css'

type ThumbStage = 'thumb' | 'image' | 'failed'

/** Thumbnail with silent fallback: thumbnail → full image → empty placeholder. */
export function ShotThumb({
  shotId,
  version,
  hasImage,
}: {
  shotId: string
  version: string | number
  hasImage: boolean
}) {
  const resetKey = `${shotId}:${String(version)}:${hasImage ? '1' : '0'}`
  const [prevResetKey, setPrevResetKey] = useState(resetKey)
  const [stage, setStage] = useState<ThumbStage>(hasImage ? 'thumb' : 'failed')
  const [loaded, setLoaded] = useState(false)

  if (resetKey !== prevResetKey) {
    setPrevResetKey(resetKey)
    setStage(hasImage ? 'thumb' : 'failed')
    setLoaded(false)
  }

  const showImage = hasImage && stage !== 'failed'
  const imageSrc = showImage
    ? `${stage === 'thumb' ? shotThumbnailUrl(shotId) : shotImageUrl(shotId)}?v=${encodeURIComponent(String(version))}`
    : ''

  return (
    <div className="shot-thumb" data-stage={showImage ? stage : 'empty'}>
      <div className="shot-thumb-placeholder" aria-hidden="true" />
      {showImage ? (
        <img
          className={`shot-thumb-img ${loaded ? 'is-loaded' : 'is-loading'}`}
          src={imageSrc}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setLoaded(true)}
          onError={() => {
            setLoaded(false)
            setStage((current) => (current === 'thumb' ? 'image' : 'failed'))
          }}
        />
      ) : null}
    </div>
  )
}
