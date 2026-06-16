export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function formatShotId(shotId) {
  const value = String(shotId || "");
  if (value.length <= 12) return value;
  return `${value.slice(0, 8)}…`;
}

export function pathBasename(value) {
  return value.split(/[/\\]/).pop() || value;
}

export function pathDirname(value) {
  return value.replace(/[/\\][^/\\]+$/, "");
}

export function formatCameraVec(value, asDegrees = false) {
  if (!Array.isArray(value) || value.length < 3) return "";
  return value
    .slice(0, 3)
    .map((item) => {
      const num = Number(item) || 0;
      return asDegrees ? num.toFixed(1) : num.toFixed(2);
    })
    .join(", ");
}

export function parseCameraVec(text) {
  if (!text || typeof text !== "string") return null;
  const parts = text.split(",").map((item) => Number(item.trim()));
  if (parts.length < 3 || parts.some((item) => Number.isNaN(item))) return null;
  return parts.slice(0, 3);
}

export function textNode(value) {
  const span = document.createElement("span");
  span.textContent = value;
  return span;
}

export function hasArtworkPreview(shot) {
  return Boolean(shot?.preview_image_path || shot?.image_path);
}

export function shotHasRenderablePreview(shot) {
  return Boolean(
    shot?.preview_image_path ||
      shot?.image_path ||
      shot?.thumbnail_path ||
      shot?.source_file_path
  );
}

export function previewCacheKey(shot) {
  if (!shot) return "";
  const previewPath = shot.preview_image_path || shot.image_path || "";
  const stamp = shot.preview_disk_mtime || shot.source_sync_mtime || previewPath || shot.shot_id;
  return `${shot.shot_id}:${stamp}`;
}

export function timelineCacheKey(shot) {
  if (!shot) return "";
  const stamp =
    shot.thumbnail_disk_mtime ||
    shot.preview_disk_mtime ||
    shot.source_sync_mtime ||
    shot.thumbnail_path ||
    shot.preview_image_path ||
    shot.shot_id;
  return `${shot.shot_id}:${stamp}`;
}

export function shotPreviewUrl(shot, extraBust = "") {
  if (!shot) return "";
  const url = `/api/shots/${shot.shot_id}/image?v=${encodeURIComponent(previewCacheKey(shot))}`;
  return extraBust ? `${url}&_=${extraBust}` : url;
}

export function shotThumbnailUrl(shot, extraBust = "") {
  if (!shot) return "";
  const url = `/api/shots/${shot.shot_id}/thumbnail?v=${encodeURIComponent(timelineCacheKey(shot))}`;
  return extraBust ? `${url}&_=${extraBust}` : url;
}

export function shotHasBoardBackground(shot) {
  return Boolean(shot?.has_board_background || shot?.ref_video_path);
}

export function shotBoardBackgroundUrl(shot) {
  if (!shotHasBoardBackground(shot)) return "";
  return `/api/shots/${shot.shot_id}/board-background?v=${encodeURIComponent(previewCacheKey(shot))}`;
}

export function shotArtworkPreviewUrl(shot, extraBust = "") {
  if (!shotHasRenderablePreview(shot)) return "";
  return shotPreviewUrl(shot, extraBust);
}

export function shotCanvasLayerUrls(shot, extraBust = "") {
  return {
    background: shotBoardBackgroundUrl(shot),
    artwork: shotArtworkPreviewUrl(shot, extraBust),
  };
}

export function shotCanvasDisplayUrl(shot) {
  if (!shot) return "";
  const { background, artwork } = shotCanvasLayerUrls(shot);
  if (artwork) return artwork;
  if (background) return background;
  return shotPreviewUrl(shot);
}

export function shotTimelineThumbUrl(shot, extraBust = "") {
  if (!shot) return "";
  const { background, artwork } = shotCanvasLayerUrls(shot, extraBust);
  if (artwork) return artwork;
  if (background) return background;
  return shotThumbnailUrl(shot, extraBust);
}

export function timelineThumbStyle(shot, { bust = "" } = {}) {
  const color = shot?.canvas_color || canvasColor();
  const { background, artwork } = shotCanvasLayerUrls(shot, bust);
  const layers = [];
  if (artwork) layers.push(artwork.replace(/'/g, "%27"));
  if (background) layers.push(background.replace(/'/g, "%27"));
  if (!layers.length) {
    return { style: `background-color:${color}`, className: "" };
  }
  const imageCss = layers.map((url) => `url('${url}')`).join(",");
  const size = layers.map(() => "contain").join(",");
  const position = layers.map(() => "center").join(" ");
  const repeat = layers.map(() => "no-repeat").join(",");
  return {
    style: `background-color:${color};background-image:${imageCss};background-size:${size};background-position:${position};background-repeat:${repeat}`,
    className: "has-canvas-preview",
  };
}
