const UI_THEME_STORAGE_KEY = 'storyboard_ui_theme'
const VALID_THEMES = new Set(['studio', 'cinema', 'paper', 'slate', 'noir'])

/** Read the same theme preference as legacy `/` (no UI — visual sync only). */
export function applyStoredUiTheme(): void {
  let theme = 'studio'
  try {
    const stored = localStorage.getItem(UI_THEME_STORAGE_KEY)
    if (stored && VALID_THEMES.has(stored)) theme = stored
  } catch {
    // restricted storage
  }
  document.documentElement.setAttribute('data-theme', theme)
}
