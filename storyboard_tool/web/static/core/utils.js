function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatShotId(shotId) {
  const value = String(shotId || "");
  if (value.length <= 12) return value;
  return `${value.slice(0, 8)}…`;
}

function pathBasename(value) {
  return value.split(/[/\\]/).pop() || value;
}

function pathDirname(value) {
  return value.replace(/[/\\][^/\\]+$/, "");
}

function formatCameraVec(value, asDegrees = false) {
  if (!Array.isArray(value) || value.length < 3) return "";
  return value
    .slice(0, 3)
    .map((item) => {
      const num = Number(item) || 0;
      return asDegrees ? num.toFixed(1) : num.toFixed(2);
    })
    .join(", ");
}

function parseCameraVec(text) {
  if (!text || typeof text !== "string") return null;
  const parts = text.split(",").map((item) => Number(item.trim()));
  if (parts.length < 3 || parts.some((item) => Number.isNaN(item))) return null;
  return parts.slice(0, 3);
}

function textNode(value) {
  const span = document.createElement("span");
  span.textContent = value;
  return span;
}

function hasArtworkPreview(shot) {
  return Boolean(shot?.preview_image_path || shot?.image_path);
}

function previewCacheKey(shot) {
  if (!shot) return "";
  const previewPath = shot.preview_image_path || shot.image_path || "";
  const stamp = shot.source_sync_mtime || previewPath || shot.shot_id;
  return `${shot.shot_id}:${stamp}`;
}

function shotPreviewUrl(shot) {
  if (!shot) return "";
  return `/api/shots/${shot.shot_id}/image?v=${encodeURIComponent(previewCacheKey(shot))}`;
}

function shotBoardBackgroundUrl(shot) {
  if (!shot?.ref_video_path) return "";
  return `/api/shots/${shot.shot_id}/board-background?v=${encodeURIComponent(previewCacheKey(shot))}`;
}

function shotCanvasDisplayUrl(shot) {
  if (!shot) return "";
  if (hasArtworkPreview(shot)) return shotPreviewUrl(shot);
  const boardBg = shotBoardBackgroundUrl(shot);
  if (boardBg) return boardBg;
  if (shot.thumbnail_path) {
    return `/api/shots/${shot.shot_id}/thumbnail?v=${encodeURIComponent(previewCacheKey(shot))}`;
  }
  return "";
}

function timelineThumbStyle(shot) {
  const color = shot?.canvas_color || canvasColor();
  const displayUrl = shotCanvasDisplayUrl(shot);
  if (!displayUrl) {
    return { style: `background-color:${color}`, className: "" };
  }
  const escaped = displayUrl.replace(/'/g, "%27");
  return {
    style: `background-color:${color};background-image:url('${escaped}')`,
    className: "has-canvas-preview",
  };
}
