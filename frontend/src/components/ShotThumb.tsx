import { useMemo, useState } from 'react'
import { shotBoardBackgroundUrl, shotCodexLayerUrl, shotImageUrl, shotThumbnailUrl } from '../api'
import './ShotThumb.css'

type ThumbStage = 'thumb' | 'image' | 'background' | 'failed'

/** Thumbnail with silent fallback and background/artwork compositing. */
export function ShotThumb({
  shotId,
  version,
  hasImage,
  hasBg = false,
  hasCodex = false,
}: {
  shotId: string
  version: string | number
  hasImage: boolean
  hasBg?: boolean
  hasCodex?: boolean
}) {
  const resetKey = `${shotId}:${String(version)}:${hasImage ? '1' : '0'}:${hasBg ? '1' : '0'}:${hasCodex ? '1' : '0'}`
  const [prevResetKey, setPrevResetKey] = useState(resetKey)
  const [stage, setStage] = useState<ThumbStage>(hasImage ? (hasBg ? 'image' : 'thumb') : hasBg ? 'background' : 'failed')
  const [artworkLoaded, setArtworkLoaded] = useState(false)
  const [backgroundLoaded, setBackgroundLoaded] = useState(false)
  const [codexLoaded, setCodexLoaded] = useState(false)

  if (resetKey !== prevResetKey) {
    setPrevResetKey(resetKey)
    setStage(hasImage ? (hasBg ? 'image' : 'thumb') : hasBg ? 'background' : 'failed')
    setArtworkLoaded(false)
    setBackgroundLoaded(false)
    setCodexLoaded(false)
  }

  const versionQuery = encodeURIComponent(String(version))
  const backgroundSrc = hasBg ? `${shotBoardBackgroundUrl(shotId)}?v=${versionQuery}` : ''
  const codexSrc = hasCodex ? `${shotCodexLayerUrl(shotId)}?v=${versionQuery}` : ''
  const artworkSrc = useMemo(() => {
    if (!hasImage || stage === 'failed' || stage === 'background') return ''
    const url = hasBg || stage === 'image' ? shotImageUrl(shotId) : shotThumbnailUrl(shotId)
    return `${url}?v=${versionQuery}`
  }, [hasBg, hasImage, shotId, stage, versionQuery])
  const showImage = !!backgroundSrc || !!codexSrc || !!artworkSrc
  const artworkVisible = artworkLoaded || !backgroundSrc

  return (
    <div className="shot-thumb" data-stage={showImage ? stage : 'empty'}>
      <div className="shot-thumb-placeholder" aria-hidden="true" />
      {backgroundSrc ? (
        <img
          className={`shot-thumb-img shot-thumb-bg ${backgroundLoaded ? 'is-loaded' : 'is-loading'}`}
          src={backgroundSrc}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setBackgroundLoaded(true)}
          onError={() => setBackgroundLoaded(false)}
        />
      ) : null}
      {codexSrc ? (
        <img
          className={`shot-thumb-img shot-thumb-codex ${codexLoaded ? 'is-loaded' : 'is-loading'}`}
          src={codexSrc}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setCodexLoaded(true)}
          onError={() => setCodexLoaded(false)}
        />
      ) : null}
      {artworkSrc ? (
        <img
          className={`shot-thumb-img shot-thumb-artwork ${artworkVisible ? 'is-loaded' : 'is-loading'}`}
          src={artworkSrc}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setArtworkLoaded(true)}
          onError={() => {
            setArtworkLoaded(false)
            setStage((current) => {
              if (current === 'thumb') return 'image'
              if (current === 'image') return 'failed'
              return 'failed'
            })
          }}
        />
      ) : null}
    </div>
  )
}
