const APP_HINTS = [
  "← / → switch boards · Ctrl+Z undo",
  "Drag boards on the timeline to reorder",
  "Drop images onto the canvas to import preview",
  "Drop project.json to open a project",
  "Settings: Photoshop, Blender, canvas & style",
];

let hintIndex = 0;
let hintTimer = null;

function currentAppHint() {
  if (!APP_HINTS.length) return "";
  return APP_HINTS[hintIndex % APP_HINTS.length];
}

function advanceAppHint() {
  if (APP_HINTS.length <= 1) return;
  hintIndex = (hintIndex + 1) % APP_HINTS.length;
  if (el.filmstripHint) el.filmstripHint.textContent = currentAppHint();
}

function startHintRotation() {
  window.clearInterval(hintTimer);
  if (el.filmstripHint) el.filmstripHint.textContent = currentAppHint();
  hintTimer = window.setInterval(advanceAppHint, 12000);
}

function bindHintsUi() {
  startHintRotation();
}

bindHintsUi();
