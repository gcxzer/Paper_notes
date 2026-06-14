function renderReaderToolControls() {
  const level = normalizeToolMenuLevel(readerState.toolMenuLevel);

  if (elements.readerToolMenuButton) {
    elements.readerToolMenuButton.textContent = "+";
    elements.readerToolMenuButton.title = "Ask tools";
    elements.readerToolMenuButton.setAttribute("aria-expanded", String(readerState.toolMenuOpen));
  }

  if (elements.readerToolPopover) {
    elements.readerToolPopover.hidden = !readerState.toolMenuOpen;
  }
  if (!readerState.toolMenuOpen) return;

  if (elements.readerToolBack) {
    elements.readerToolBack.hidden = level === "root";
  }
  if (elements.readerToolTitle) {
    elements.readerToolTitle.textContent = toolMenuTitle(level);
    elements.readerToolTitle.hidden = level === "root";
  }
  if (elements.readerToolSubtitle) {
    elements.readerToolSubtitle.textContent = toolMenuSubtitle(level);
    elements.readerToolSubtitle.hidden = level === "root";
  }
  if (elements.readerToolRoot) {
    elements.readerToolRoot.hidden = level !== "root";
    if (level === "root") {
      elements.readerToolRoot.innerHTML = renderToolRootMenu();
    }
  }
  if (elements.readerToolNoteWriting) {
    elements.readerToolNoteWriting.hidden = true;
  }
  if (elements.readerToolFileGeneration) {
    elements.readerToolFileGeneration.hidden = level !== "file_generation";
  }
  if (elements.readerToolSavedPrompts) {
    elements.readerToolSavedPrompts.hidden = level !== "saved_prompts";
    if (level === "saved_prompts") {
      elements.readerToolSavedPrompts.innerHTML = renderSavedPromptToolSection();
    }
  }

  elements.readerToolPopover?.querySelectorAll("[data-tool-mode]").forEach((button) => {
    const active = normalizeWriteToolMode(button.dataset.toolMode) === normalizeWriteToolMode(readerState.writeToolMode);
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  elements.readerToolPopover?.querySelectorAll("[data-file-generation-format]").forEach((button) => {
    const active = normalizeFileGenerationFormat(button.dataset.fileGenerationFormat) === normalizeFileGenerationFormat(readerState.fileGenerationFormat);
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });

  if (elements.readerToolStatus) {
    elements.readerToolStatus.textContent = readerState.toolStatus;
    const statusLevel = normalizeToolMenuLevel(readerState.toolStatusLevel);
    elements.readerToolStatus.hidden = !readerState.toolStatus || statusLevel !== level;
  }
}

function normalizeToolMenuLevel(value) {
  const level = normalizeText(value);
  return ["root", "file_generation", "saved_prompts"].includes(level) ? level : "root";
}

function normalizeFileGenerationFormat(value) {
  const format = normalizeText(value).toLowerCase();
  return FILE_GENERATION_FORMATS.has(format) ? format : "markdown";
}

function fileGenerationFormatLabel(value) {
  return {
    markdown: "Markdown file",
    text: "Text file",
    json: "JSON file",
    csv: "CSV file",
    html: "HTML file"
  }[normalizeFileGenerationFormat(value)] || "Markdown file";
}

function toolMenuTitle(level) {
  if (level === "file_generation") return "Generate file";
  if (level === "saved_prompts") return "Saved Prompts";
  return "Ask tools";
}

function toolMenuSubtitle(level) {
  if (level === "file_generation") return "Choose file format";
  if (level === "saved_prompts") return "Reuse your prompts";
  return "More actions";
}

function renderToolRootMenu() {
  const imageGenerationSupported = activeProviderSupportsImageArtifacts();
  const imageGenerationTitle = imageGenerationSupported
    ? "Generate image"
    : activeProviderImageGenerationUnsupportedMessage();
  const screenshotSupported = activeProviderSupportsImageInput();
  const screenshotTitle = screenshotSupported
    ? "Add page"
    : activeProviderImageInputUnsupportedMessage();
  return `
    <div class="ask-tool-menu-section">
      <button class="ask-tool-menu-option" type="button" data-tool-action="attach-image">
        ${renderAskToolMenuIcon("attach")}
        <span>
          <strong>Add Images & Files</strong>
        </span>
      </button>
      <button class="ask-tool-menu-option" type="button" data-tool-action="add-screenshot"${screenshotSupported ? "" : " disabled"} title="${escapeHtml(screenshotTitle)}">
        ${renderAskToolMenuIcon("page_add")}
        <span>
          <strong>Add page</strong>
        </span>
      </button>
      <div class="ask-tool-submenu-shell">
        <div class="ask-tool-menu-option ask-tool-submenu-trigger" aria-haspopup="menu">
          ${renderAskToolMenuIcon("bookmark")}
          <span>
            <strong>Saved Prompts</strong>
          </span>
        <span class="ask-tool-menu-arrow" aria-hidden="true">›</span>
        </div>
        <div class="ask-tool-submenu" role="menu" aria-label="Saved Prompts">
          ${renderSavedPromptSubmenuContent()}
        </div>
      </div>
    </div>
    <div class="ask-tool-menu-section">
      <button class="ask-tool-menu-option" type="button" data-tool-action="generate-image"${imageGenerationSupported ? "" : " disabled"} title="${escapeHtml(imageGenerationTitle)}">
        ${renderAskToolMenuIcon("image")}
        <span>
          <strong>Generate image</strong>
        </span>
      </button>
      <div class="ask-tool-submenu-shell">
        <div class="ask-tool-menu-option ask-tool-submenu-trigger" aria-haspopup="menu">
          ${renderAskToolMenuIcon("file")}
          <span>
            <strong>Generate file</strong>
          </span>
          <span class="ask-tool-menu-arrow" aria-hidden="true">›</span>
        </div>
        <div class="ask-tool-submenu" role="menu" aria-label="Generate file">
          ${renderFileGenerationFormatMenuContent()}
        </div>
      </div>
    </div>
    <div class="ask-tool-menu-section">
      <button class="ask-tool-menu-option" type="button" data-tool-action="new-chat">
        ${renderAskToolMenuIcon("new_chat")}
        <span>
          <strong>New chat</strong>
        </span>
      </button>
    </div>
  `;
}

function renderFileGenerationFormatMenuContent() {
  const formats = [
    ["markdown", "markdown", "Markdown"],
    ["text", "text", "Text"],
    ["json", "json", "JSON"],
    ["csv", "csv", "CSV"],
    ["html", "html", "HTML"]
  ];
  return `
    <div class="ask-tool-menu-section">
      ${formats.map(([format, icon, label]) => `
        <button class="ask-tool-menu-option" type="button" data-file-generation-format="${format}" aria-pressed="false" role="menuitemradio">
          ${renderAskToolMenuIcon(icon)}
          <span><strong>${label}</strong></span>
          <span class="ask-tool-check" aria-hidden="true">✓</span>
        </button>
      `).join("")}
    </div>
  `;
}

const ASK_TOOL_ICON_PATHS = {
  attach: `<path d="M6 12.5v3.25A3.25 3.25 0 0 0 9.25 19h5.5A3.25 3.25 0 0 0 18 15.75v-7.5A3.25 3.25 0 0 0 14.75 5h-5.5A3.25 3.25 0 0 0 6 8.25v.25"/><path d="M9 12.25 12 15l4-5"/><path d="M4 8.5h6"/>`,
  send: `<path d="M4.5 12 20 4.5l-5.2 15-3-6.3L4.5 12Z"/><path d="m11.8 13.2 8.2-8.7"/>`,
  stop: `<rect x="8" y="8" width="8" height="8" rx="1.8" fill="currentColor" stroke="none"/>`,
  bookmark: `<path d="M7 4.75A2.75 2.75 0 0 1 9.75 2h4.5A2.75 2.75 0 0 1 17 4.75v16l-5-3.25-5 3.25v-16Z"/>`,
  image: `<rect x="4" y="6" width="14" height="12" rx="2.5"/><path d="m6.5 15 2.8-2.8a1.2 1.2 0 0 1 1.7 0l1.1 1.1 1.8-2a1.2 1.2 0 0 1 1.8.1L18 14"/><path d="M8 4.5 18.5 2.6a2 2 0 0 1 2.3 1.6l1.4 8.1"/>`,
  screenshot: `<rect x="4" y="5" width="16" height="13" rx="2.5"/><path d="M8 21h8"/><path d="M12 18v3"/><path d="M8 9h2.5l1-1.5h1l1 1.5H16a2 2 0 0 1 2 2v2.5a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V11a2 2 0 0 1 2-2Z"/><circle cx="12" cy="12.5" r="2"/>`,
  page_add: `<path d="M7 3.75h6.5L18 8.25v11.5A2.25 2.25 0 0 1 15.75 22H7a2.25 2.25 0 0 1-2.25-2.25V6A2.25 2.25 0 0 1 7 3.75Z"/><path d="M13.5 4v4.25H18"/><path d="M9 13h5.5"/><path d="M11.75 10.25v5.5"/>`,
  file: `<path d="M7 3.75h6.5L18 8.25v12H7a2 2 0 0 1-2-2V5.75a2 2 0 0 1 2-2Z"/><path d="M13.5 4v4.25H18M8.5 12h6M8.5 15.5h5"/>`,
  new_chat: `<path d="M5 5.5A2.5 2.5 0 0 1 7.5 3h8.5A2.5 2.5 0 0 1 18.5 5.5v6A2.5 2.5 0 0 1 16 14H11l-4.5 4v-4A2.5 2.5 0 0 1 4 11.5v-6Z"/><path d="M11.25 6.75v4.5M9 9h4.5"/>`,
  edit: `<path d="m5 16.8-.7 3 3-.7L18.5 7.9a2.1 2.1 0 0 0-3-3L5 16.8Z"/><path d="m14 6.3 3.2 3.2"/>`,
  settings: `<path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7.5 7.5 0 0 0-1.8-1L14.4 3h-4.8l-.3 3.1a7.5 7.5 0 0 0-1.8 1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7.5 7.5 0 0 0 1.8 1l.3 3.1h4.8l.3-3.1a7.5 7.5 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5c.1-.3.1-.7.1-1Z"/>`,
  prompt: `<path d="M5 5.5A2.5 2.5 0 0 1 7.5 3h9A2.5 2.5 0 0 1 19 5.5v7A2.5 2.5 0 0 1 16.5 15H11l-4.5 4v-4A2.5 2.5 0 0 1 4 12.5v-7Z"/><path d="M8 7h8M8 10.5h5"/>`,
  markdown: `<path d="M5 16V8l3 4 3-4v8"/><path d="M15 8v6"/><path d="m12.8 12 2.2 2.2 2.2-2.2"/>`,
  text: `<path d="M4 6h16"/><path d="M12 6v12"/><path d="M8 18h8"/>`,
  json: `<path d="M8.5 7 5 12l3.5 5"/><path d="M15.5 7 19 12l-3.5 5"/><path d="m13.5 6-3 12"/>`,
  csv: `<path d="M4.5 5.5h15v13h-15z"/><path d="M4.5 10h15"/><path d="M4.5 14h15"/><path d="M9.5 5.5v13"/><path d="M14.5 5.5v13"/>`,
  html: `<path d="m9 8-4 4 4 4"/><path d="m15 8 4 4-4 4"/><path d="m13 6-2 12"/>`,
  search: `<path d="m21 21-4.3-4.3"/><circle cx="11" cy="11" r="7"/>`,
  globe: `<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.7 5.6 3.7 9S14.5 18.4 12 21c-2.5-2.6-3.7-5.6-3.7-9S9.5 5.6 12 3Z"/>`,
  book: `<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21V5.5Z"/><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20"/>`,
  code: `<path d="m9 8-4 4 4 4M15 8l4 4-4 4"/>`,
  lab: `<path d="M9 3h6M10 3v5l-5 9a3 3 0 0 0 2.6 4.5h8.8A3 3 0 0 0 19 17l-5-9V3"/><path d="M7 15h10"/>`
};

const ASK_TOOL_ICON_ALIASES = {
  attach: "paperclip",
  send: "send",
  stop: "square",
  bookmark: "bookmark",
  image: "image",
  screenshot: "image",
  page_add: "file-plus",
  file: "file",
  new_chat: "message-circle",
  edit: "edit-3",
  settings: "settings",
  prompt: "clipboard-list",
  markdown: "file-text",
  text: "file-text",
  json: "file-json",
  csv: "file-spreadsheet",
  html: "file-code",
  search: "search",
  globe: "globe",
  book: "book-open",
  code: "file-code",
  lab: "flask-conical"
};

function renderAskToolSvg(name, size = 18) {
  const iconName = ASK_TOOL_ICON_ALIASES[name] || "clipboard-list";
  if (window.paperIcons?.render) {
    return window.paperIcons.render(iconName, { size: Number(size) || 18 });
  }
  return `
    <svg viewBox="0 0 24 24" width="${Number(size) || 18}" height="${Number(size) || 18}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      ${ASK_TOOL_ICON_PATHS[name] || ASK_TOOL_ICON_PATHS.prompt}
    </svg>
  `;
}

function renderAskToolMenuIcon(name) {
  return `
    <span class="ask-tool-option-icon" aria-hidden="true">
      ${renderAskToolSvg(name, 18)}
    </span>
  `;
}

function imageToolSummary() {
  return attachmentToolSummary();
}

function attachmentToolSummary() {
  const count = normalizeAttachmentArtifacts(readerState.chatAttachments).length;
  if (count) return `${count} attached`;
  return "Attach images or files";
}

function setReaderToolMenuOpen(open) {
  readerState.toolMenuOpen = open;
  if (open) {
    readerState.toolMenuLevel = "root";
    setChatSessionMenuOpen(false);
    closeReaderModelMenu();
  }
  renderReaderToolControls();
}

function closeReaderToolMenu() {
  readerState.toolMenuOpen = false;
  readerState.toolMenuLevel = "root";
  renderReaderToolControls();
}

function showReaderToolRootMenu() {
  readerState.toolMenuLevel = "root";
  renderReaderToolControls();
}

function showReaderToolSection(section) {
  const nextLevel = normalizeToolMenuLevel(section);
  readerState.toolMenuLevel = nextLevel === "root" ? "root" : nextLevel;
  renderReaderToolControls();
}

function setReaderGenerationMode(mode, options = {}) {
  const nextMode = ["image", "file"].includes(normalizeText(mode)) ? normalizeText(mode) : "";
  if (nextMode === "image" && !activeProviderSupportsImageArtifacts()) {
    setReaderChatError(activeProviderImageGenerationUnsupportedMessage());
    closeReaderToolMenu();
    return;
  }
  readerState.generationMode = nextMode;
  if (options.format) readerState.fileGenerationFormat = normalizeFileGenerationFormat(options.format);
  renderAttachmentTray();
  renderReaderToolControls();
}

function clearReaderGenerationMode() {
  readerState.generationMode = "";
  renderAttachmentTray();
  renderReaderToolControls();
}

function setReaderWriteToolMode(mode) {
  readerState.writeToolMode = writeStoredWriteToolMode(mode);
  readerState.toolStatus = `Write mode: ${writeToolModeLabel(readerState.writeToolMode)}`;
  readerState.toolStatusLevel = "root";
  renderReaderToolControls();
}

function handleReaderToolPopoverClick(event) {
  const backButton = event.target.closest("#readerToolBack");
  if (backButton) {
    event.preventDefault();
    showReaderToolRootMenu();
    return;
  }

  const sectionButton = event.target.closest("[data-tool-section]");
  if (sectionButton) {
    event.preventDefault();
    showReaderToolSection(sectionButton.dataset.toolSection);
    return;
  }

  const modeButton = event.target.closest("[data-tool-mode]");
  if (modeButton) {
    event.preventDefault();
    setReaderWriteToolMode(modeButton.dataset.toolMode);
    return;
  }

  const fileFormatButton = event.target.closest("[data-file-generation-format]");
  if (fileFormatButton) {
    event.preventDefault();
    setReaderGenerationMode("file", { format: fileFormatButton.dataset.fileGenerationFormat });
    closeReaderToolMenu();
    elements.readerChatInput?.focus();
    return;
  }

  const savedPromptInsert = event.target.closest("[data-saved-prompt-insert]");
  if (savedPromptInsert) {
    event.preventDefault();
    insertSavedPrompt(savedPromptInsert.dataset.savedPromptInsert);
    return;
  }

  const savedPromptAction = event.target.closest("[data-saved-prompt-action]")?.dataset?.savedPromptAction;
  if (savedPromptAction === "create") {
    event.preventDefault();
    openSavedPromptDialog();
    return;
  }
  if (savedPromptAction === "manage") {
    event.preventDefault();
    openSavedPromptManageDialog();
    return;
  }

  const action = event.target.closest("[data-tool-action]")?.dataset?.toolAction;
  if (action === "attach-image") {
    event.preventDefault();
    elements.readerAttachmentInput?.click();
    return;
  }
  if (action === "add-screenshot") {
    event.preventDefault();
    addCurrentPdfPageScreenshot().catch((error) => {
      setReaderChatError(error.message || "Could not add page.");
    });
    return;
  }
  if (action === "generate-image") {
    event.preventDefault();
    setReaderGenerationMode("image");
    closeReaderToolMenu();
    elements.readerChatInput?.focus();
    return;
  }
  if (action === "new-chat") {
    event.preventDefault();
    closeReaderToolMenu();
    void createReaderChatSession();
    return;
  }

}


function setReaderChatError(message = "") {
  if (!elements.readerChatError) return;
  elements.readerChatError.textContent = message ? sanitizeVisibleAgentError(message) : "";
  elements.readerChatError.hidden = !message;
}

function setReaderChatNotice(message = "", { duration = 1500 } = {}) {
  if (!elements.readerChatNotice) return;
  window.clearTimeout(readerState.chatNoticeTimer);
  readerState.chatNoticeTimer = 0;

  const text = String(message || "").trim();
  elements.readerChatNotice.textContent = text;
  elements.readerChatNotice.hidden = !text;
  elements.readerChatNotice.classList.toggle("is-visible", Boolean(text));

  if (!text || duration <= 0) return;
  readerState.chatNoticeTimer = window.setTimeout(() => {
    elements.readerChatNotice.textContent = "";
    elements.readerChatNotice.hidden = true;
    elements.readerChatNotice.classList.remove("is-visible");
    readerState.chatNoticeTimer = 0;
  }, duration);
}
