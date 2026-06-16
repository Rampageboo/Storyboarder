import type { Shot } from '../types'

export function shotHasPreview(shot: Pick<Shot, 'image_path' | 'preview_image_path' | 'thumbnail_path'>): boolean {
  return !!(
    shot.image_path?.trim() ||
    shot.preview_image_path?.trim() ||
    shot.thumbnail_path?.trim()
  )
}

/** Cache-bust key for filmstrip thumbnails after sync, reference apply, or project reload. */
export function shotThumbVersion(
  shot: Pick<Shot, 'preview_disk_mtime' | 'thumbnail_disk_mtime'>,
  visualEpoch: number,
  index: number,
): string | number {
  return shot.preview_disk_mtime || shot.thumbnail_disk_mtime || `${visualEpoch}-${index}`
}
