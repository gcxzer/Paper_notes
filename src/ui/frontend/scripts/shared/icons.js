(function () {
  const ICON_BASE = "/node_modules/lucide-static/icons";
  const FALLBACK_ICON = "circle-help";
  const ICONS = new Set([
    "archive",
    "arrow-left",
    "book-open",
    "bot",
    "bookmark",
    "calendar",
    "check",
    "chevron-down",
    "chevron-left",
    "chevron-right",
    "circle-help",
    "circle-stop",
    "clipboard-list",
    "copy",
    "download",
    "edit-3",
    "external-link",
    "file",
    "file-code",
    "file-plus",
    "file-json",
    "file-spreadsheet",
    "file-text",
    "folder",
    "folder-plus",
    "flask-conical",
    "globe",
    "highlighter",
    "image",
    "inbox",
    "layers-3",
    "layout-list",
    "library",
    "list",
    "message-circle",
    "minus",
    "moon",
    "more-horizontal",
    "panel-left",
    "panel-right",
    "paperclip",
    "plus",
    "refresh-cw",
    "rotate-ccw",
    "rotate-cw",
    "search",
    "send",
    "settings",
    "sparkles",
    "square",
    "sticky-note",
    "sun",
    "tag",
    "tags",
    "trash-2",
    "underline",
    "wand-sparkles",
    "x",
    "zoom-in",
    "zoom-out"
  ]);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;"
    })[character]);
  }

  function normalizeIconName(name) {
    const value = String(name || "").trim().toLowerCase();
    if (!/^[a-z0-9-]+$/.test(value)) return FALLBACK_ICON;
    return ICONS.has(value) ? value : FALLBACK_ICON;
  }

  function normalizeSize(size) {
    const value = Number(size);
    if (!Number.isFinite(value)) return 18;
    return Math.min(Math.max(Math.round(value), 10), 48);
  }

  function iconUrl(name) {
    return `${ICON_BASE}/${normalizeIconName(name)}.svg`;
  }

  function render(name, options = {}) {
    const className = ["ui-icon", options.className].filter(Boolean).join(" ");
    const label = String(options.label || "");
    const attributes = label
      ? `role="img" aria-label="${escapeHtml(label)}"`
      : `aria-hidden="true"`;
    return `<span class="${escapeHtml(className)}" ${attributes} style="--ui-icon-url: url('${iconUrl(name)}'); --ui-icon-size: ${normalizeSize(options.size)}px;"></span>`;
  }

  function apply(root = document) {
    root.querySelectorAll("[data-paper-icon]").forEach((element) => {
      const iconName = normalizeIconName(element.dataset.paperIcon);
      const size = normalizeSize(element.dataset.paperIconSize);
      element.classList.add("ui-icon");
      element.style.setProperty("--ui-icon-url", `url('${ICON_BASE}/${iconName}.svg')`);
      element.style.setProperty("--ui-icon-size", `${size}px`);
      element.removeAttribute("data-icon-loading");
      if (!element.hasAttribute("aria-label")) {
        element.setAttribute("aria-hidden", "true");
      }
    });
  }

  window.paperIcons = { render, apply, normalize: normalizeIconName };
  window.renderPaperIcon = render;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => apply());
  } else {
    apply();
  }
}());
