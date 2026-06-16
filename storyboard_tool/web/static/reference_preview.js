const referencePreviewUi = {
  ready: false,
  modal: null,
  title: null,
  stage: null,
  image: null,
  video: null,
  clickSuppressUntil: 0,
};

function initReferencePreviewModal(root = document) {
  if (referencePreviewUi.ready && referencePreviewUi.modal) return;

  let modal = root.getElementById("referencePreviewModal");
  if (!modal) {
    modal = root.createElement("div");
    modal.id = "referencePreviewModal";
    modal.className = "modal reference-preview-modal";
    modal.hidden = true;
    modal.innerHTML = `
      <div class="reference-preview-backdrop" data-reference-preview-close></div>
      <div class="reference-preview-card" role="dialog" aria-modal="true" aria-labelledby="referencePreviewTitle">
        <div class="reference-preview-header">
          <h3 id="referencePreviewTitle"></h3>
          <button type="button" class="modal-close reference-preview-close" data-reference-preview-close title="Close">×</button>
        </div>
        <div class="reference-preview-stage">
          <img id="referencePreviewImage" alt="" hidden />
          <video id="referencePreviewVideo" controls playsinline hidden></video>
        </div>
      </div>
    `;
    root.body.appendChild(modal);
  }

  referencePreviewUi.modal = modal;
  referencePreviewUi.title = modal.querySelector("#referencePreviewTitle");
  referencePreviewUi.stage = modal.querySelector(".reference-preview-stage");
  referencePreviewUi.image = modal.querySelector("#referencePreviewImage");
  referencePreviewUi.video = modal.querySelector("#referencePreviewVideo");

  modal.querySelectorAll("[data-reference-preview-close]").forEach((node) => {
    node.addEventListener("click", () => closeReferencePreview());
  });

  modal.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeReferencePreview();
  });

  referencePreviewUi.ready = true;
}

function openReferencePreview(ref) {
  if (!ref?.path) return;
  const type =
    typeof resolveReferenceType === "function"
      ? resolveReferenceType(ref, typeof state !== "undefined" ? state?.project : null)
      : ref.type;
  if (type === "model") {
    const openScene = () => {
      if (typeof openRefSegmentOverlay === "function") {
        openRefSegmentOverlay("/ref-segment#model");
      } else if (typeof openRefScene3dOverlay === "function") {
        openRefScene3dOverlay("/ref-segment#model");
      }
    };
    if (typeof selectReferenceModel === "function") {
      selectReferenceModel(ref.path, { silent: true }).then(openScene).catch(openScene);
      return;
    }
    openScene();
    return;
  }

  initReferencePreviewModal();
  const url = referenceMediaUrl(ref.path);
  if (!url) return;

  referencePreviewUi.title.textContent = referenceDisplayTitle(ref);
  referencePreviewUi.image.hidden = true;
  referencePreviewUi.video.hidden = true;
  referencePreviewUi.image.removeAttribute("src");
  referencePreviewUi.video.pause();
  referencePreviewUi.video.removeAttribute("src");

  if (ref.type === "video") {
    referencePreviewUi.video.src = url;
    referencePreviewUi.video.hidden = false;
    referencePreviewUi.video.load();
    referencePreviewUi.video.play().catch(() => {});
  } else {
    referencePreviewUi.image.src = url;
    referencePreviewUi.image.alt = referenceDisplayTitle(ref);
    referencePreviewUi.image.hidden = false;
  }

  referencePreviewUi.modal.hidden = false;
  referencePreviewUi.clickSuppressUntil = Date.now() + 320;
  referencePreviewUi.modal.setAttribute("tabindex", "-1");
  referencePreviewUi.modal.focus();
}

function closeReferencePreview() {
  if (!referencePreviewUi.modal) return;
  referencePreviewUi.modal.hidden = true;
  if (referencePreviewUi.video) {
    referencePreviewUi.video.pause();
    referencePreviewUi.video.removeAttribute("src");
    referencePreviewUi.video.hidden = true;
  }
  if (referencePreviewUi.image) {
    referencePreviewUi.image.removeAttribute("src");
    referencePreviewUi.image.hidden = true;
  }
}

function shouldSuppressReferenceSelect() {
  return Date.now() < referencePreviewUi.clickSuppressUntil;
}

function bindReferencePreviewInteractions(previewButton, ref, options = {}) {
  let clickTimer = null;

  previewButton.addEventListener("click", (event) => {
    if (event.target.closest(".reference-media-delete")) return;
    if (shouldSuppressReferenceSelect()) return;
    window.clearTimeout(clickTimer);
    clickTimer = window.setTimeout(() => {
      if (shouldSuppressReferenceSelect()) return;
      options.onSelect?.(ref);
    }, 220);
  });

  previewButton.addEventListener("dblclick", (event) => {
    if (event.target.closest(".reference-media-delete")) return;
    event.preventDefault();
    window.clearTimeout(clickTimer);
    referencePreviewUi.clickSuppressUntil = Date.now() + 320;
    options.onPreview?.(ref);
  });
}


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  referencePreviewUi,
  initReferencePreviewModal,
  openReferencePreview,
  closeReferencePreview,
  shouldSuppressReferenceSelect,
  bindReferencePreviewInteractions,
});
