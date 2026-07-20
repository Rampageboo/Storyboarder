import type { Shot } from '../types'

/** True when the shot has a non-solid artist artwork preview. */
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

/** True when the shot has a reference/background plate (separate from artist artwork). */
export function shotHasBoardBackground(
  shot: Pick<Shot, 'has_board_background'>,
): boolean {
  return shot.has_board_background === true
}

/** True when the shot has an accepted generated image layer. */
export function shotHasCodexLayer(
  shot: Pick<Shot, 'has_codex_layer'>,
): boolean {
  return shot.has_codex_layer === true
}

/**
 * True when the shot has any displayable visual — either artist artwork preview
 * a reference background plate, or an accepted Codex layer. Use this to decide whether to show a thumbnail
 * or enable display controls (Refresh); do NOT use it for artwork-only operations
 * (Delete image, Open preview) — use `shotHasPreview` for those.
 */
export function shotHasBoardVisual(
  shot: Pick<Shot, 'image_path' | 'preview_image_path' | 'thumbnail_path' | 'has_artwork_preview' | 'has_board_background' | 'has_codex_layer'>,
): boolean {
  return shotHasPreview(shot) || shotHasBoardBackground(shot) || shotHasCodexLayer(shot)
}

/** True when the preview file is safe to draw over a fresher board background. */
export function shotShouldOverlayPreview(
  shot: Pick<
    Shot,
    | 'image_path'
    | 'preview_image_path'
    | 'thumbnail_path'
    | 'has_artwork_preview'
    | 'has_board_background'
    | 'has_codex_layer'
    | 'preview_disk_mtime'
    | 'board_background_disk_mtime'
    | 'codex_layer_disk_mtime'
    | 'preview_has_transparency'
  >,
): boolean {
  if (!shotHasPreview(shot)) return false
  const previewMtime = Number(shot.preview_disk_mtime || 0)
  const backgroundMtime = Number(shot.board_background_disk_mtime || 0)
  if (shot.has_board_background === true && backgroundMtime > previewMtime && shot.preview_has_transparency !== true) {
    return false
  }
  return true
}

/**
 * Cache-bust version key for any board visual (artwork or background plate).
 * Returns a stable `empty-{epoch}` string when the shot has no visual at all,
 * so React can skip image renders without a stale cache hit.
 */
export function shotDisplayVersion(
  shot: Pick<
    Shot,
    | 'image_path'
    | 'preview_image_path'
    | 'thumbnail_path'
    | 'has_artwork_preview'
    | 'has_board_background'
    | 'has_codex_layer'
    | 'preview_disk_mtime'
    | 'thumbnail_disk_mtime'
    | 'board_background_disk_mtime'
    | 'codex_layer_disk_mtime'
  >,
  visualEpoch: number,
  index: number,
): string | number {
  if (!shotHasBoardVisual(shot)) return `empty-${visualEpoch}`
  return [
    shot.board_background_disk_mtime || 0,
    shot.codex_layer_disk_mtime || 0,
    shot.preview_disk_mtime || 0,
    shot.thumbnail_disk_mtime || 0,
    visualEpoch,
    index,
  ].join(':')
}

/**
 * Cache-bust key for filmstrip thumbnails after sync, reference apply, or project reload.
 * Delegates to `shotDisplayVersion` so background-only shots also get mtime-based keys.
 */
export function shotThumbVersion(
  shot: Pick<
    Shot,
    | 'image_path'
    | 'preview_image_path'
    | 'thumbnail_path'
    | 'has_artwork_preview'
    | 'has_board_background'
    | 'has_codex_layer'
    | 'preview_disk_mtime'
    | 'thumbnail_disk_mtime'
    | 'board_background_disk_mtime'
    | 'codex_layer_disk_mtime'
  >,
  visualEpoch: number,
  index: number,
): string | number {
  return shotDisplayVersion(shot, visualEpoch, index)
}
