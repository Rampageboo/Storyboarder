import type { Shot } from '../types'

export function shotHasPreview(
  shot: Pick<Shot, 'image_path' | 'preview_image_path' | 'thumbnail_path' | 'has_artwork_preview'>,
): boolean {
  if (shot.has_artwork_preview === false) return false
  if (shot.has_artwork_preview === true) return true
  return !!(
    shot.image_path?.trim() ||
    shot.preview_image_path?.trim() ||
    shot.thumbnail_path?.trim()
  )
}

/** Cache-bust key for filmstrip thumbnails after sync, reference apply, or project reload. */
export function shotThumbVersion(
  shot: Pick<
    Shot,
    'image_path' | 'preview_image_path' | 'thumbnail_path' | 'has_artwork_preview' | 'preview_disk_mtime' | 'thumbnail_disk_mtime'
  >,
  visualEpoch: number,
  index: number,
): string | number {
  if (!shotHasPreview(shot)) return `empty-${visualEpoch}`
  return shot.preview_disk_mtime || shot.thumbnail_disk_mtime || `${visualEpoch}-${index}`
}
