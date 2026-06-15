// Export triggers and file-open UI (preview, Photoshop source, relink).
//
// Loaded as a classic script AFTER core/api.js and BEFORE core/status.js
// (see APP_SCRIPTS in main.js). Relies on api, runWithProgress, flushSelectedShot,
// showToast, setProject, selectShot, selectedShot, createCanvasForShot, showDialog.

async function runDownloadExport(url, label = "Exporting…") {
  try {
    const result = await runWithProgress(label, async () => {
      await flushSelectedShot();
      return api(url, { method: "POST" });
    });
    showToast(`Exported: ${result.path}`);
    if (result.download_url) window.open(result.download_url, "_blank");
  } catch {
    // api() already toasts
  }
}

async function openShotInPhotoshop() {
  const shot = selectedShot();
  if (!shot || !state.project) return;
  if (!shot.source_file_path) {
    await createCanvasForShot(shot.shot_id);
  }
  const current = selectedShot();
  if (!current?.source_file_path) return;
  const result = await api(`/api/shots/${current.shot_id}/open-source`, { method: "POST" });
  showToast(`Opened in Photoshop: ${result.path}`);
}

async function openRelinkPreviewDialog() {
  const shot = selectedShot();
  if (!shot) return;
  const relativePath = await showDialog({
    title: "Relink preview",
    hint: "Enter a project-relative path, e.g. shots/shot_001/shot_001_preview.png",
    input: {
      label: "Relative path",
      value: shot.preview_image_path || shot.image_path || "",
      placeholder: "shots/shot_001/shot_001_preview.png",
    },
    validate: (value) => (value ? null : "Enter a relative path."),
    actions: [
      { label: "Cancel", value: null },
      { label: "OK", value: "ok", primary: true },
    ],
  });
  if (!relativePath) return;
  try {
    await api(`/api/shots/${shot.shot_id}/relink-preview`, {
      method: "POST",
      body: JSON.stringify({ relative_path: relativePath }),
    }).then(setProject);
    selectShot(shot.shot_id);
    showToast("Preview relinked.");
  } catch {
    // api() already toasts
  }
}

el.exportPdf.addEventListener("click", async () => {
  try {
    const result = await runWithProgress("Exporting PDF…", async () => {
      await flushSelectedShot();
      return api("/api/export/pdf", {
        method: "POST",
        body: JSON.stringify({ layout: el.pdfLayout.value || "two_per_page" }),
      });
    });
    showToast(`PDF exported: ${result.path}`);
    if (result.download_url) window.open(result.download_url, "_blank");
  } catch {
    // api() already toasts
  }
});

el.exportShotList.addEventListener("click", () => runDownloadExport("/api/export/shot-list", "Exporting shot list…"));
el.exportContactSheet.addEventListener("click", () => runDownloadExport("/api/export/contact-sheet", "Exporting contact sheet…"));
el.exportTiming.addEventListener("click", () => runDownloadExport("/api/export/timing", "Exporting timing JSON…"));
el.exportImageSequence.addEventListener("click", async () => {
  try {
    const result = await runWithProgress("Exporting image sequence…", async () => {
      await flushSelectedShot();
      return api("/api/export/image-sequence", { method: "POST" });
    });
    showToast(`Image sequence exported: ${result.path}`);
  } catch {
    // api() already toasts
  }
});

el.relinkPreview.addEventListener("click", () => openRelinkPreviewDialog());

el.previewBox.addEventListener("click", (event) => {
  if (state.annotationTool !== "select") return;
  if (!event.target.closest("#canvasBoard")) return;
  if (!el.canvasBoard.classList.contains("canvas-openable")) return;
  openShotInPhotoshop();
});

el.openPreview.addEventListener("click", async () => {
  const shot = selectedShot();
  if (!shot) return;
  const result = await api(`/api/shots/${shot.shot_id}/open-preview`, { method: "POST" });
  showToast(`Opened: ${result.path}`);
});
