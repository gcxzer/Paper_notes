(function () {
  const STORAGE_KEY = "paper-notes-theme";
  const MODES = new Set(["light", "dark"]);
  const DEFAULT_MODE = "light";

  function readStoredMode(key, fallback) {
    const value = localStorage.getItem(key) || fallback;
    return MODES.has(value) ? value : fallback;
  }

  function readMode() {
    return readStoredMode(STORAGE_KEY, DEFAULT_MODE);
  }

  function readDocumentMode() {
    return resolvedMode();
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
    document.querySelectorAll("[data-theme-option]").forEach((button) => {
      const selected = button.dataset.themeOption === mode;
      button.dataset.themeState = selected ? "selected" : "";
      button.setAttribute("aria-checked", String(selected));
    });
    document.querySelectorAll("[data-theme-switch]").forEach((button) => {
      const isDark = mode === "dark";
      const label = isDark ? "Dark" : "Light";
      button.dataset.themeState = mode;
      button.setAttribute("aria-checked", String(isDark));
      button.setAttribute("aria-label", `Theme: ${label}. Click to switch theme.`);
      button.querySelectorAll("[data-theme-switch-label]").forEach((labelNode) => {
        labelNode.textContent = label;
      });
    });

    const documentMode = resolved;
    document.documentElement.dataset.documentTheme = documentMode;
  }

  function setMode(mode) {
    localStorage.setItem(STORAGE_KEY, MODES.has(mode) ? mode : DEFAULT_MODE);
    applyTheme();
    window.dispatchEvent(new CustomEvent("paper-theme-change", {
      detail: { mode: readMode(), resolved: resolvedMode() }
    }));
  }

  function setDocumentMode(mode) {
    setMode(mode);
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

      const option = event.target.closest("[data-theme-option]");
      if (option) {
        setMode(option.dataset.themeOption);
        return;
      }

      const themeSwitch = event.target.closest("[data-theme-switch]");
      if (themeSwitch) {
        setMode(readMode() === "dark" ? "light" : "dark");
      }
    });
  });
}());
