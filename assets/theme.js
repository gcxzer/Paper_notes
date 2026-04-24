(function () {
  const STORAGE_KEY = "paper-notes-theme";
  const DOCUMENT_STORAGE_KEY = "paper-notes-document-theme";
  const MODES = new Set(["light", "dark"]);
  const DEFAULT_MODE = "dark";
  const DEFAULT_DOCUMENT_MODE = "light";

  function readStoredMode(key, fallback) {
    const value = localStorage.getItem(key) || fallback;
    return MODES.has(value) ? value : fallback;
  }

  function readMode() {
    return readStoredMode(STORAGE_KEY, DEFAULT_MODE);
  }

  function readDocumentMode() {
    return readStoredMode(DOCUMENT_STORAGE_KEY, DEFAULT_DOCUMENT_MODE);
  }

  function resolvedMode(mode = readMode()) {
    return MODES.has(mode) ? mode : DEFAULT_MODE;
  }

  function applyTheme() {
    const mode = readMode();
    const resolved = resolvedMode(mode);
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themeMode = mode;
    document.documentElement.style.colorScheme = resolved;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      const label = mode === "dark" ? "Dark" : "Light";
      button.textContent = label;
      button.dataset.themeState = mode;
      button.setAttribute("aria-label", `Theme: ${label}. Click to switch theme.`);
      button.setAttribute("aria-pressed", String(mode === "dark"));
    });

    const documentMode = readDocumentMode();
    document.documentElement.dataset.documentTheme = documentMode;
    document.querySelectorAll("[data-document-theme-toggle]").forEach((button) => {
      const label = documentMode === "dark" ? "Paper Dark" : "Paper Light";
      button.textContent = label;
      button.dataset.documentThemeState = documentMode;
      button.setAttribute("aria-label", `${label}. Click to switch PDF and HTML theme.`);
      button.setAttribute("aria-pressed", String(documentMode === "dark"));
    });
  }

  function setMode(mode) {
    localStorage.setItem(STORAGE_KEY, MODES.has(mode) ? mode : DEFAULT_MODE);
    applyTheme();
    window.dispatchEvent(new CustomEvent("paper-theme-change", {
      detail: { mode: readMode(), resolved: resolvedMode() }
    }));
  }

  function setDocumentMode(mode) {
    localStorage.setItem(DOCUMENT_STORAGE_KEY, MODES.has(mode) ? mode : DEFAULT_DOCUMENT_MODE);
    applyTheme();
    window.dispatchEvent(new CustomEvent("paper-document-theme-change", {
      detail: { mode: readDocumentMode() }
    }));
  }

  window.paperTheme = {
    get: readMode,
    set: setMode,
    resolved: () => resolvedMode(),
    document: {
      get: readDocumentMode,
      set: setDocumentMode
    }
  };

  applyTheme();
  document.addEventListener("DOMContentLoaded", () => {
    applyTheme();
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-theme-toggle]");
      if (button) {
        setMode(readMode() === "dark" ? "light" : "dark");
        return;
      }

      const documentButton = event.target.closest("[data-document-theme-toggle]");
      if (documentButton) {
        setDocumentMode(readDocumentMode() === "dark" ? "light" : "dark");
      }
    });
  });
}());
