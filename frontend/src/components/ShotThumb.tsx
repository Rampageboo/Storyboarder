import { useState } from 'react'
import { shotBoardBackgroundUrl, shotImageUrl, shotThumbnailUrl } from '../api'
import './ShotThumb.css'

type ThumbStage = 'thumb' | 'image' | 'background' | 'failed'

/** Thumbnail with silent fallback: thumbnail → full image → board background → empty placeholder. */
export function ShotThumb({
  shotId,
  version,
  hasImage,
  hasBg = false,
}: {
  shotId: string
  version: string | number
  hasImage: boolean
  hasBg?: boolean
}) {
  const resetKey = `${shotId}:${String(version)}:${hasImage ? '1' : '0'}:${hasBg ? '1' : '0'}`
  const [prevResetKey, setPrevResetKey] = useState(resetKey)
  const [stage, setStage] = useState<ThumbStage>(hasImage ? 'thumb' : hasBg ? 'background' : 'failed')
  const [loaded, setLoaded] = useState(false)

  if (resetKey !== prevResetKey) {
    setPrevResetKey(resetKey)
    setStage(hasImage ? 'thumb' : hasBg ? 'background' : 'failed')
    setLoaded(false)
  }

  const showImage = (hasImage || hasBg) && stage !== 'failed'
  const imageSrc = showImage
    ? `${
        stage === 'thumb'
          ? shotThumbnailUrl(shotId)
          : stage === 'image'
            ? shotImageUrl(shotId)
            : shotBoardBackgroundUrl(shotId)
      }?v=${encodeURIComponent(String(version))}`
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
            setStage((current) => {
              if (current === 'thumb') return 'image'
              if (current === 'image') return hasBg ? 'background' : 'failed'
              return 'failed'
            })
          }}
        />
      ) : null}
    </div>
  )
}
