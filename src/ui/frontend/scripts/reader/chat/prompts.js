function initializeSavedPrompts() {
  const storedPrompts = readStoredSavedPrompts();
  applySavedPrompts(storedPrompts);
  loadSavedPrompts({ legacyPrompts: storedPrompts }).catch((error) => {
    console.warn("Failed to load saved prompts.", error);
  });
}

const SAVED_PROMPT_EMOJI_OPTIONS = [
  ["📁", "folder"], ["🗂️", "index cards"], ["🧠", "brain"], ["💼", "briefcase"], ["📷", "camera"], ["✈️", "plane"],
  ["🎈", "balloon"], ["📘", "book"], ["🎨", "palette"], ["📄", "document"], ["🧪", "lab"], ["🌐", "globe"],
  ["🌸", "flower"], ["🎮", "game"], ["🔎", "search"], ["💬", "chat"], ["⭐", "star"], ["✅", "check"]
];
const SAVED_PROMPT_ICON_OPTIONS = [
  ["bookmark", "bookmark"], ["prompt", "prompt"], ["edit", "edit"], ["settings", "settings"], ["image", "image"], ["file", "file"],
  ["search", "search"], ["globe", "globe"], ["book", "book"], ["code", "code"], ["lab", "lab"], ["markdown", "markdown"]
];

function readStoredSavedPrompts() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SAVED_PROMPTS_KEY) || "[]");
    return normalizeSavedPromptCollection(parsed);
  } catch (error) {
    console.warn("Failed to read saved prompts.", error);
    return [];
  }
}

function clearStoredSavedPrompts() {
  try {
    localStorage.removeItem(SAVED_PROMPTS_KEY);
  } catch (error) {
    console.warn("Failed to clear legacy saved prompts.", error);
  }
}

function normalizeSavedPromptCollection(payload) {
  const rawPrompts = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.prompts)
      ? payload.prompts
      : [];
  return rawPrompts
    .map(normalizeSavedPrompt)
    .filter((prompt) => prompt.id && prompt.content)
    .sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")));
}

function applySavedPrompts(prompts) {
  readerState.savedPrompts = normalizeSavedPromptCollection(prompts);
  renderReaderToolControls();
  if (elements.savedPromptManageDialog?.open) renderSavedPromptManageList();
  return readerState.savedPrompts;
}

function mergeSavedPromptCollections(primaryPrompts, secondaryPrompts) {
  const byId = new Map();
  [...normalizeSavedPromptCollection(primaryPrompts), ...normalizeSavedPromptCollection(secondaryPrompts)].forEach((prompt) => {
    const existing = byId.get(prompt.id);
    const existingTimestamp = String(existing?.updatedAt || existing?.createdAt || "");
    const promptTimestamp = String(prompt.updatedAt || prompt.createdAt || "");
    if (!existing || promptTimestamp >= existingTimestamp) {
      byId.set(prompt.id, prompt);
    }
  });
  return normalizeSavedPromptCollection(Array.from(byId.values()));
}

async function loadSavedPrompts({ legacyPrompts = [] } = {}) {
  const payload = await fetchAgentJson("/api/saved-prompts");
  const serverPrompts = normalizeSavedPromptCollection(payload);
  const promptsToMigrate = normalizeSavedPromptCollection(legacyPrompts);
  if (promptsToMigrate.length) {
    const merged = mergeSavedPromptCollections(serverPrompts, promptsToMigrate);
    applySavedPrompts(merged);
    const saved = await saveSavedPromptsToBackend(merged);
    applySavedPrompts(saved);
    clearStoredSavedPrompts();
    return;
  }
  applySavedPrompts(serverPrompts);
}

async function saveSavedPromptsToBackend(prompts) {
  const payload = await fetchAgentJson("/api/saved-prompts", {
    method: "POST",
    body: { prompts: normalizeSavedPromptCollection(prompts) }
  });
  return normalizeSavedPromptCollection(payload);
}

async function writeStoredSavedPrompts(prompts) {
  const savedPrompts = await saveSavedPromptsToBackend(prompts);
  clearStoredSavedPrompts();
  return applySavedPrompts(savedPrompts);
}

function normalizeSavedPrompt(value) {
  const content = normalizeText(value?.content);
  const title = normalizeText(value?.title) || savedPromptTitleFromContent(content);
  const toolMode = normalizeSavedPromptToolMode(value?.toolMode || value?.tool?.mode);
  const fileFormat = normalizeFileGenerationFormat(value?.fileFormat || value?.tool?.format);
  const icon = normalizeSavedPromptIcon(value);
  return {
    id: normalizeText(value?.id),
    title,
    content,
    toolMode,
    fileFormat,
    iconType: icon.type,
    iconValue: icon.value,
    createdAt: normalizeText(value?.createdAt),
    updatedAt: normalizeText(value?.updatedAt || value?.createdAt)
  };
}

function normalizeSavedPromptIcon(value) {
  const type = normalizeText(value?.iconType || value?.icon?.type).toLowerCase();
  const rawValue = normalizeText(value?.iconValue || value?.icon?.value);
  if (type === "emoji" && rawValue) return { type: "emoji", value: rawValue };
  if (type === "icon" && rawValue) return { type: "icon", value: rawValue };
  return { type: "icon", value: "bookmark" };
}

function normalizeSavedPromptToolMode(value) {
  const mode = normalizeText(value).toLowerCase();
  return ["image", "file"].includes(mode) ? mode : "";
}

function savedPromptTitleFromContent(content) {
  const firstLine = normalizeText(content).split(/\n/).map((line) => line.trim()).find(Boolean) || "Untitled prompt";
  return firstLine.length > 56 ? `${firstLine.slice(0, 53)}...` : firstLine;
}

function createSavedPromptId() {
  if (globalThis.crypto?.randomUUID) return `prompt-${globalThis.crypto.randomUUID()}`;
  return `prompt-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function renderSavedPromptToolSection() {
  return `
    <div class="ask-tool-menu">
      ${renderSavedPromptSubmenuContent()}
    </div>
  `;
}

function renderSavedPromptSubmenuContent() {
  const promptRows = readerState.savedPrompts.length
    ? `
      <div class="ask-tool-menu-section">
        ${readerState.savedPrompts.map(renderSavedPromptMenuItem).join("")}
      </div>
    `
    : `<p class="saved-prompts-empty">No saved prompts yet.</p>`;

  return `
      <div class="ask-tool-menu-section">
        <button class="ask-tool-menu-option" type="button" data-saved-prompt-action="create">
          ${renderAskToolMenuIcon("edit")}
          <span><strong>Create prompt...</strong></span>
        </button>
        <button class="ask-tool-menu-option" type="button" data-saved-prompt-action="manage">
          ${renderAskToolMenuIcon("settings")}
          <span><strong>Manage prompts...</strong></span>
        </button>
      </div>
      ${promptRows}
  `;
}

function renderSavedPromptMenuItem(prompt) {
  const capabilityLabel = savedPromptCapabilityLabel(prompt);
  return `
    <button class="ask-tool-menu-option" type="button" data-saved-prompt-insert="${escapeHtml(prompt.id)}" title="${escapeHtml(prompt.title)}">
      ${renderSavedPromptIcon(prompt, "ask-tool-option-icon")}
      <span>
        <strong>${escapeHtml(prompt.title)}</strong>
        ${capabilityLabel ? `<small>${escapeHtml(capabilityLabel)}</small>` : ""}
      </span>
    </button>
  `;
}

function savedPromptCapabilityLabel(prompt) {
  const mode = normalizeSavedPromptToolMode(prompt?.toolMode);
  if (mode === "image") return "Generate image";
  if (mode === "file") return `Generate file: ${fileGenerationFormatLabel(prompt?.fileFormat)}`;
  return "";
}

function openSavedPromptDialog(promptId = "") {
  const prompt = readerState.savedPrompts.find((entry) => entry.id === normalizeText(promptId));
  if (elements.savedPromptDialogTitle) {
    elements.savedPromptDialogTitle.textContent = prompt ? "Edit prompt" : "Create prompt";
  }
  if (elements.savedPromptIdInput) elements.savedPromptIdInput.value = prompt?.id || "";
  if (elements.savedPromptTitleInput) elements.savedPromptTitleInput.value = prompt?.title || "";
  if (elements.savedPromptContentInput) {
    elements.savedPromptContentInput.value = prompt?.content || normalizeText(elements.readerChatInput?.value);
  }
  setSavedPromptIconSelection(prompt?.iconType || "icon", prompt?.iconValue || "bookmark");
  closeSavedPromptIconPanel();
  setSavedPromptToolSelection(prompt?.toolMode || "", prompt?.fileFormat || "markdown");
  closeSavedPromptToolPanel();
  setSavedPromptStatus("");
  updateSavedPromptSubmitState();
  closeReaderToolMenu();
  if (elements.savedPromptDialog && !elements.savedPromptDialog.open) elements.savedPromptDialog.showModal();
  window.setTimeout(() => {
    (elements.savedPromptTitleInput?.value ? elements.savedPromptContentInput : elements.savedPromptTitleInput)?.focus();
  }, 0);
}

function closeSavedPromptDialog() {
  elements.savedPromptDialog?.close();
  closeSavedPromptIconPanel();
  closeSavedPromptToolPanel();
  setSavedPromptStatus("");
}

function renderSavedPromptIcon(prompt, className = "saved-prompts-display-icon") {
  const icon = normalizeSavedPromptIcon(prompt);
  if (icon.type === "emoji") {
    return `<span class="${escapeHtml(className)} saved-prompts-emoji-icon" aria-hidden="true">${escapeHtml(icon.value)}</span>`;
  }
  return `<span class="${escapeHtml(className)}" aria-hidden="true">${renderAskToolSvg(icon.value, 18)}</span>`;
}

function toggleSavedPromptIconPanel() {
  if (!elements.savedPromptIconPanel) return;
  elements.savedPromptIconPanel.hidden = !elements.savedPromptIconPanel.hidden;
  elements.savedPromptIconButton?.setAttribute("aria-expanded", String(!elements.savedPromptIconPanel.hidden));
  if (!elements.savedPromptIconPanel.hidden) closeSavedPromptToolPanel();
  renderSavedPromptIconPicker();
}

function closeSavedPromptIconPanel() {
  if (!elements.savedPromptIconPanel) return;
  elements.savedPromptIconPanel.hidden = true;
  elements.savedPromptIconButton?.setAttribute("aria-expanded", "false");
}

function handleSavedPromptIconPanelClick(event) {
  const tabButton = event.target.closest("[data-saved-prompt-icon-tab]");
  if (!tabButton) return;
  event.preventDefault();
  readerState.savedPromptIconTab = tabButton.dataset.savedPromptIconTab === "icon" ? "icon" : "emoji";
  readerState.savedPromptIconQuery = "";
  if (elements.savedPromptIconSearch) elements.savedPromptIconSearch.value = "";
  renderSavedPromptIconPicker();
}

function handleSavedPromptIconSearch(event) {
  readerState.savedPromptIconQuery = normalizeText(event.target?.value).toLowerCase();
  renderSavedPromptIconPicker();
}

function handleSavedPromptIconGridClick(event) {
  const button = event.target.closest("[data-saved-prompt-icon-value]");
  if (!button) return;
  event.preventDefault();
  setSavedPromptIconSelection(button.dataset.savedPromptIconType, button.dataset.savedPromptIconValue);
  closeSavedPromptIconPanel();
}

function setSavedPromptIconSelection(type, value) {
  const normalized = normalizeSavedPromptIcon({ iconType: type, iconValue: value });
  readerState.savedPromptDraftIconType = normalized.type;
  readerState.savedPromptDraftIconValue = normalized.value;
  renderSavedPromptIconPreview();
}

function renderSavedPromptIconPreview() {
  if (!elements.savedPromptIconPreview) return;
  elements.savedPromptIconPreview.innerHTML = renderSavedPromptIcon({
    iconType: readerState.savedPromptDraftIconType,
    iconValue: readerState.savedPromptDraftIconValue
  }, "saved-prompts-preview-icon");
}

function renderSavedPromptIconPicker() {
  if (!elements.savedPromptIconGrid) return;
  const tab = readerState.savedPromptIconTab === "icon" ? "icon" : "emoji";
  const query = normalizeText(readerState.savedPromptIconQuery).toLowerCase();
  const options = (tab === "icon" ? SAVED_PROMPT_ICON_OPTIONS : SAVED_PROMPT_EMOJI_OPTIONS)
    .filter(([, label]) => !query || label.includes(query));
  elements.savedPromptIconPanel?.querySelectorAll("[data-saved-prompt-icon-tab]").forEach((button) => {
    const active = button.dataset.savedPromptIconTab === tab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  elements.savedPromptIconGrid.innerHTML = options.length
    ? options.map(([value, label]) => {
      const active = readerState.savedPromptDraftIconType === tab && readerState.savedPromptDraftIconValue === value;
      const iconHtml = tab === "emoji" ? escapeHtml(value) : renderAskToolSvg(value, 20);
      return `
        <button class="${active ? "is-active" : ""}" type="button" data-saved-prompt-icon-type="${escapeHtml(tab)}" data-saved-prompt-icon-value="${escapeHtml(value)}" title="${escapeHtml(label)}">
          ${iconHtml}
        </button>
      `;
    }).join("")
    : `<p class="saved-prompts-empty">No matches.</p>`;
}

function setSavedPromptStatus(message) {
  if (!elements.savedPromptStatus) return;
  elements.savedPromptStatus.textContent = normalizeText(message);
  elements.savedPromptStatus.hidden = !elements.savedPromptStatus.textContent;
}

function toggleSavedPromptToolPanel() {
  const panel = elements.savedPromptToolPanel;
  if (!panel) return;
  panel.hidden = !panel.hidden;
  elements.savedPromptToolButton?.setAttribute("aria-expanded", String(!panel.hidden));
  if (!panel.hidden) closeSavedPromptIconPanel();
  if (panel.hidden) {
    readerState.savedPromptFileFormatMenuOpen = false;
  }
  renderSavedPromptToolSelection();
}

function closeSavedPromptToolPanel() {
  if (!elements.savedPromptToolPanel) return;
  elements.savedPromptToolPanel.hidden = true;
  elements.savedPromptToolButton?.setAttribute("aria-expanded", "false");
  readerState.savedPromptFileFormatMenuOpen = false;
  renderSavedPromptToolSelection();
}

function handleSavedPromptToolPanelClick(event) {
  const fileParentButton = event.target.closest("[data-saved-prompt-file-parent]");
  if (fileParentButton) {
    event.preventDefault();
    return;
  }

  const modeButton = event.target.closest("[data-saved-prompt-tool-mode]");
  if (modeButton) {
    event.preventDefault();
    const mode = normalizeSavedPromptToolMode(modeButton.dataset.savedPromptToolMode);
    setSavedPromptToolSelection(mode, readerState.savedPromptDraftFileFormat);
    closeSavedPromptToolPanel();
    return;
  }

  const formatButton = event.target.closest("[data-saved-prompt-file-format]");
  if (formatButton) {
    event.preventDefault();
    setSavedPromptToolSelection("file", formatButton.dataset.savedPromptFileFormat);
    closeSavedPromptToolPanel();
  }
}

function clearSavedPromptToolSelection() {
  readerState.savedPromptFileFormatMenuOpen = false;
  setSavedPromptToolSelection("", readerState.savedPromptDraftFileFormat);
  closeSavedPromptToolPanel();
}

function setSavedPromptToolSelection(mode, format) {
  readerState.savedPromptDraftToolMode = normalizeSavedPromptToolMode(mode);
  readerState.savedPromptDraftFileFormat = normalizeFileGenerationFormat(format);
  if (readerState.savedPromptDraftToolMode !== "file") {
    readerState.savedPromptFileFormatMenuOpen = false;
  }
  renderSavedPromptToolSelection();
}

function renderSavedPromptToolSelection() {
  const mode = normalizeSavedPromptToolMode(readerState.savedPromptDraftToolMode);
  const format = normalizeFileGenerationFormat(readerState.savedPromptDraftFileFormat);
  const label = mode === "image"
    ? "Generate image"
    : mode === "file"
      ? `Generate file: ${fileGenerationFormatLabel(format)}`
      : "Select tool";

  if (elements.savedPromptToolLabel) elements.savedPromptToolLabel.textContent = label;
  if (elements.savedPromptToolButton) elements.savedPromptToolButton.hidden = Boolean(mode);
  if (elements.savedPromptToolChip) elements.savedPromptToolChip.hidden = !mode;
  if (elements.savedPromptToolChipLabel) {
    elements.savedPromptToolChipLabel.textContent = mode === "image"
      ? "Image"
      : mode === "file"
        ? fileGenerationFormatLabel(format)
        : "";
  }
  elements.savedPromptToolPanel?.querySelectorAll("[data-saved-prompt-tool-mode]").forEach((button) => {
    const buttonMode = normalizeSavedPromptToolMode(button.dataset.savedPromptToolMode);
    const active = buttonMode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  elements.savedPromptToolPanel?.querySelectorAll("[data-saved-prompt-file-parent]").forEach((button) => {
    const active = mode === "file";
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-expanded", String(active));
  });
  elements.savedPromptToolPanel?.querySelectorAll("[data-saved-prompt-file-format]").forEach((button) => {
    const active = normalizeFileGenerationFormat(button.dataset.savedPromptFileFormat) === format;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function updateSavedPromptSubmitState() {
  if (!elements.saveSavedPrompt) return;
  const content = normalizeText(elements.savedPromptContentInput?.value);
  elements.saveSavedPrompt.disabled = !content;
}

async function handleSavedPromptSubmit(event) {
  event.preventDefault();
  const id = normalizeText(elements.savedPromptIdInput?.value);
  const content = normalizeText(elements.savedPromptContentInput?.value);
  const title = normalizeText(elements.savedPromptTitleInput?.value) || savedPromptTitleFromContent(content);
  if (!content) {
    setSavedPromptStatus("Write a prompt before saving.");
    elements.savedPromptContentInput?.focus();
    return;
  }

  const now = new Date().toISOString();
  const existing = readerState.savedPrompts.find((prompt) => prompt.id === id);
  const nextPrompt = {
    id: id || createSavedPromptId(),
    title,
    content,
    toolMode: normalizeSavedPromptToolMode(readerState.savedPromptDraftToolMode),
    fileFormat: normalizeFileGenerationFormat(readerState.savedPromptDraftFileFormat),
    iconType: readerState.savedPromptDraftIconType,
    iconValue: readerState.savedPromptDraftIconValue,
    createdAt: existing?.createdAt || now,
    updatedAt: now
  };
  const prompts = [
    nextPrompt,
    ...readerState.savedPrompts.filter((prompt) => prompt.id !== nextPrompt.id)
  ];
  setSavedPromptStatus("Saving...");
  if (elements.saveSavedPrompt) elements.saveSavedPrompt.disabled = true;
  try {
    await writeStoredSavedPrompts(prompts);
    closeSavedPromptDialog();
  } catch (error) {
    setSavedPromptStatus(sanitizeVisibleAgentError(error.message || "Could not save prompt."));
  } finally {
    updateSavedPromptSubmitState();
  }
}

function openSavedPromptManageDialog() {
  closeReaderToolMenu();
  renderSavedPromptManageList();
  if (elements.savedPromptManageDialog && !elements.savedPromptManageDialog.open) {
    elements.savedPromptManageDialog.showModal();
  }
}

function closeSavedPromptManageDialog() {
  elements.savedPromptManageDialog?.close();
}

function renderSavedPromptManageList() {
  if (!elements.savedPromptManageList) return;
  if (!readerState.savedPrompts.length) {
    elements.savedPromptManageList.innerHTML = `<p class="saved-prompts-empty">No saved prompts yet.</p>`;
    return;
  }
  elements.savedPromptManageList.innerHTML = readerState.savedPrompts.map((prompt) => `
    <article class="saved-prompts-row" data-saved-prompt-row="${escapeHtml(prompt.id)}">
      ${renderSavedPromptIcon(prompt, "saved-prompts-row-icon")}
      <div class="saved-prompts-row-copy">
        <strong>${escapeHtml(prompt.title)}</strong>
        ${savedPromptCapabilityLabel(prompt) ? `<small>${escapeHtml(savedPromptCapabilityLabel(prompt))}</small>` : ""}
        <span>${escapeHtml(prompt.content)}</span>
      </div>
      <div class="saved-prompts-row-actions">
        <button type="button" data-saved-prompt-insert="${escapeHtml(prompt.id)}">Use it</button>
        <button type="button" data-saved-prompt-edit="${escapeHtml(prompt.id)}">Edit</button>
        <button type="button" data-saved-prompt-delete="${escapeHtml(prompt.id)}">Delete</button>
      </div>
    </article>
  `).join("");
}

function insertSavedPrompt(promptId) {
  const prompt = readerState.savedPrompts.find((entry) => entry.id === normalizeText(promptId));
  const input = elements.readerChatInput;
  if (!prompt || !input) return;
  const existing = input.value || "";
  input.value = existing.trim()
    ? `${existing.trimEnd()}\n\n${prompt.content}`
    : prompt.content;
  applySavedPromptCapability(prompt);
  resizeReaderChatInput();
  closeReaderToolMenu();
  closeSavedPromptManageDialog();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

function applySavedPromptCapability(prompt) {
  const mode = normalizeSavedPromptToolMode(prompt?.toolMode);
  if (mode === "image") {
    setReaderGenerationMode("image");
    return;
  }
  if (mode === "file") {
    setReaderGenerationMode("file", { format: normalizeFileGenerationFormat(prompt?.fileFormat) });
  }
}

async function deleteSavedPrompt(promptId) {
  const id = normalizeText(promptId);
  if (!id) return false;
  try {
    await writeStoredSavedPrompts(readerState.savedPrompts.filter((prompt) => prompt.id !== id));
    return true;
  } catch (error) {
    const message = sanitizeVisibleAgentError(error.message || "Could not delete prompt.");
    if (elements.savedPromptDeleteMessage && elements.savedPromptDeleteDialog?.open) {
      elements.savedPromptDeleteMessage.textContent = message;
    } else {
      readerState.toolStatus = message;
      renderReaderToolControls();
    }
    return false;
  }
}

function openSavedPromptDeleteDialog(promptId) {
  const id = normalizeText(promptId);
  const prompt = readerState.savedPrompts.find((entry) => entry.id === id);
  if (!prompt) return;
  readerState.pendingDeleteSavedPromptId = id;
  if (elements.savedPromptDeleteMessage) {
    elements.savedPromptDeleteMessage.textContent = `Delete "${prompt.title}" from Saved Prompts?`;
  }
  if (elements.savedPromptDeleteDialog && !elements.savedPromptDeleteDialog.open) {
    elements.savedPromptDeleteDialog.showModal();
  }
}

function closeSavedPromptDeleteDialog() {
  readerState.pendingDeleteSavedPromptId = "";
  elements.savedPromptDeleteDialog?.close();
}

async function confirmSavedPromptDelete() {
  const id = normalizeText(readerState.pendingDeleteSavedPromptId);
  if (id && !(await deleteSavedPrompt(id))) return;
  closeSavedPromptDeleteDialog();
}

function handleSavedPromptManageClick(event) {
  const insertButton = event.target.closest("[data-saved-prompt-insert]");
  if (insertButton) {
    event.preventDefault();
    insertSavedPrompt(insertButton.dataset.savedPromptInsert);
    return;
  }

  const editButton = event.target.closest("[data-saved-prompt-edit]");
  if (editButton) {
    event.preventDefault();
    closeSavedPromptManageDialog();
    openSavedPromptDialog(editButton.dataset.savedPromptEdit);
    return;
  }

  const deleteButton = event.target.closest("[data-saved-prompt-delete]");
  if (deleteButton) {
    event.preventDefault();
    openSavedPromptDeleteDialog(deleteButton.dataset.savedPromptDelete);
  }
}
