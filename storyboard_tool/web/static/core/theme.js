const UI_THEME_STORAGE_KEY = "storyboard_ui_theme";

const UI_THEMES = [
  {
    id: "studio",
    label: "Studio",
    hint: "Default dark suite",
    swatch: ["#1a1d21", "#3d8bfd", "#24282e"],
  },
  {
    id: "cinema",
    label: "Cinema",
    hint: "Film room · gold accents",
    swatch: ["#080809", "#e8b923", "#121216"],
  },
  {
    id: "paper",
    label: "Paper",
    hint: "Light storyboard pad",
    swatch: ["#e8e2d6", "#b45309", "#f6f2ea"],
  },
  {
    id: "slate",
    label: "Slate",
    hint: "Cool pro · soft corners",
    swatch: ["#111827", "#818cf8", "#1a2233"],
  },
  {
    id: "noir",
    label: "Noir",
    hint: "High contrast · red accent",
    swatch: ["#000000", "#ff3344", "#0d0d0d"],
  },
];

function normalizeUiTheme(themeId) {
  return UI_THEMES.some((theme) => theme.id === themeId) ? themeId : "studio";
}

function getStoredUiTheme() {
  try {
    return normalizeUiTheme(localStorage.getItem(UI_THEME_STORAGE_KEY) || "studio");
  } catch {
    return "studio";
  }
}

function applyUiTheme(themeId, { persist = true } = {}) {
  const theme = normalizeUiTheme(themeId);
  document.documentElement.setAttribute("data-theme", theme);
  if (persist) {
    try {
      localStorage.setItem(UI_THEME_STORAGE_KEY, theme);
    } catch {
      // Ignore storage failures in restricted contexts.
    }
  }
  refreshThemePicker(theme);
  return theme;
}

async function persistUiThemePreference(themeId) {
  const theme = applyUiTheme(themeId);
  if (typeof saveAppSessionSoon === "function") saveAppSessionSoon();
  return theme;
}

function refreshThemePicker(activeTheme = getStoredUiTheme(), container = null) {
  const containers = [];
  if (container) {
    containers.push(container);
  } else {
    if (el.themePicker) containers.push(el.themePicker);
    if (el.settingsThemePicker) containers.push(el.settingsThemePicker);
  }
  for (const node of containers) {
    node.querySelectorAll("[data-theme-id]").forEach((button) => {
      button.classList.toggle("active", button.dataset.themeId === activeTheme);
      button.setAttribute("aria-pressed", button.dataset.themeId === activeTheme ? "true" : "false");
    });
  }
}

function renderThemePicker(container = el.themePicker) {
  if (!container) return;
  container.replaceChildren();
  for (const theme of UI_THEMES) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "theme-option";
    button.dataset.themeId = theme.id;
    button.title = theme.hint;
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = `
      <span class="theme-option-swatches" aria-hidden="true">
        ${theme.swatch.map((color) => `<span style="background:${color}"></span>`).join("")}
      </span>
      <span class="theme-option-copy">
        <strong>${escapeHtml(theme.label)}</strong>
        <span>${escapeHtml(theme.hint)}</span>
      </span>
    `;
    button.addEventListener("click", () => {
      applyUiTheme(theme.id);
      refreshThemePicker(theme.id, container);
      if (container === el.themePicker) showToast(`Style: ${theme.label}`);
    });
    container.appendChild(button);
  }
  refreshThemePicker(getStoredUiTheme(), container);
}

function bindThemeUi() {
  renderThemePicker();
}

applyUiTheme(getStoredUiTheme(), { persist: false });


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  UI_THEME_STORAGE_KEY,
  UI_THEMES,
  normalizeUiTheme,
  getStoredUiTheme,
  applyUiTheme,
  persistUiThemePreference,
  refreshThemePicker,
  renderThemePicker,
  bindThemeUi,
});
