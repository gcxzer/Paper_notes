async function initialize() {
  state.expandedCategoryIds = readExpandedState();

  try {
    state.library = await fetchDefaultLibrary();
    state.dataSource = "default";
  } catch (error) {
    const cached = readLibraryFromStorage();
    if (cached) {
      state.library = cached;
      state.dataSource = "storage";
    } else {
      console.warn("Falling back to embedded starter library.", error);
      state.library = sanitizeLibrary(cloneLibrary(DEFAULT_LIBRARY));
      state.dataSource = "default";
    }
  }

  renderApp();
  applyScratchpadSettingControls();
  void loadAiSettings();
  void openSettingsPanelFromUrl();
}

elements.categoryList.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-toggle-category-id]");
  if (toggle) {
    event.stopPropagation();
    const categoryId = toggle.dataset.toggleCategoryId;
    if (state.expandedCategoryIds.has(categoryId)) state.expandedCategoryIds.delete(categoryId);
    else state.expandedCategoryIds.add(categoryId);
    saveExpandedState();
    renderCategories();
    return;
  }

  const addChild = event.target.closest("[data-add-child-id]");
  if (addChild) {
    event.stopPropagation();
    openCategoryDialog("create-child", null, addChild.dataset.addChildId);
    return;
  }

  const menuButton = event.target.closest("[data-menu-category-id]");
  if (menuButton) {
    event.stopPropagation();
    const categoryId = menuButton.dataset.menuCategoryId;
    if (!elements.contextMenu.hidden && state.contextCategoryId === categoryId) closeContextMenu();
    else openContextMenu(categoryId, menuButton);
    return;
  }

  const button = event.target.closest("[data-category-id]");
  if (!button) return;
  const categoryId = button.dataset.categoryId;
  if (hasChildren(categoryId)) {
    if (state.expandedCategoryIds.has(categoryId)) state.expandedCategoryIds.delete(categoryId);
    else state.expandedCategoryIds.add(categoryId);
    saveExpandedState();
  }
  state.activeCategoryId = categoryId;
  state.selectedNoteId = null;
  renderApp();
});

elements.categoryList.addEventListener("dragstart", (event) => {
  const node = event.target.closest("[data-tree-node-id]");
  if (!node) return;
  const categoryId = node.dataset.treeNodeId;
  if (!isCustomCategory(categoryId)) {
    event.preventDefault();
    return;
  }
  state.draggedCategoryId = categoryId;
  node.classList.add("is-dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", categoryId);
  setCompactDragImage(event, getCategoryById(categoryId)?.name || "Collection", "Collection");
});

elements.categoryList.addEventListener("dragover", (event) => {
  if (state.draggedNoteId) {
    const target = getNoteDropTargetFromEvent(event);
    if (!target) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (dropTargetsEqual(state.dragTarget, target)) return;
    state.dragTarget = target;
    applyNoteDropIndicator(target);
    return;
  }

  if (!state.draggedCategoryId) return;
  const target = getDropTargetFromEvent(event);
  if (!target) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  if (dropTargetsEqual(state.dragTarget, target)) return;
  state.dragTarget = target;
  applyCategoryDropIndicator(target);
});

elements.categoryList.addEventListener("drop", (event) => {
  if (state.draggedNoteId) {
    event.preventDefault();
    const target = state.dragTarget || getNoteDropTargetFromEvent(event);
    if (target?.leafId) moveNoteToCategory(state.draggedNoteId, target.leafId);
    state.draggedNoteId = null;
    state.dragTarget = null;
    clearCategoryDropIndicators();
    renderApp();
    return;
  }

  if (!state.draggedCategoryId) return;
  event.preventDefault();
  const target = state.dragTarget || getDropTargetFromEvent(event);
  if (target) applyDropTarget(state.draggedCategoryId, target);
  state.draggedCategoryId = null;
  state.dragTarget = null;
  clearCategoryDropIndicators();
  renderApp();
});

elements.categoryList.addEventListener("dragend", () => {
  state.draggedCategoryId = null;
  state.draggedNoteId = null;
  state.dragTarget = null;
  clearCategoryDropIndicators();
  elements.categoryList.querySelectorAll(".is-dragging").forEach((node) => node.classList.remove("is-dragging"));
});

elements.contextMenu.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-menu-action]");
  if (!actionButton) return;
  handleCategoryAction(actionButton.dataset.menuAction, state.contextCategoryId);
  closeContextMenu();
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".context-menu") && !event.target.closest("[data-menu-category-id]")) {
    closeContextMenu();
  }
  if (!event.target.closest(".settings-control")) {
    closeSettingsMenu();
  }
  if (!event.target.closest(".sort-control")) {
    elements.sortMenu.hidden = true;
    elements.sortButton.setAttribute("aria-expanded", "false");
  }
  if (!event.target.closest(".import-control")) {
    setImportMenuOpen(false);
  }
});

elements.searchInput.addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  syncSelectedNote();
  renderCategories();
  renderStatus();
  renderNotes();
  renderDetails();
});

elements.libraryStatus.addEventListener("click", (event) => {
  const removeButton = event.target.closest("[data-remove-tag-filter]");
  if (!removeButton) return;
  event.preventDefault();
  removeTagFilter(removeButton.dataset.removeTagFilter);
});

elements.newCategoryButton.addEventListener("click", () => {
  openCategoryDialog("create");
});

elements.addPdfButton.addEventListener("click", () => {
  toggleImportMenu();
});

elements.importMenu?.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-import-action]");
  if (!actionButton) return;
  setImportMenuOpen(false);
  if (actionButton.dataset.importAction === "local") {
    elements.pdfInput.click();
    return;
  }
  if (actionButton.dataset.importAction === "url") {
    openImportUrlDialog();
  }
});

elements.emptyState?.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-empty-import-action]");
  if (!actionButton) return;
  if (actionButton.dataset.emptyImportAction === "local") {
    elements.pdfInput.click();
    return;
  }
  if (actionButton.dataset.emptyImportAction === "url") {
    openImportUrlDialog();
  }
});

elements.settingsButton.addEventListener("click", toggleSettingsMenu);
elements.settingsMenuShield?.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  event.stopPropagation();
  closeSettingsMenu();
});
elements.settingsMenu.addEventListener("click", (event) => {
  if (event.target.closest("[data-theme-option]")) closeSettingsMenu();
});
elements.scratchpadSettingsSwitch?.addEventListener("click", () => {
  setScratchpadEnabled(!scratchpadEnabled());
});
elements.openAiSettings?.addEventListener("click", settingsLinkHandler(openAiSettingsDialog));
elements.closeAiSettingsDialog?.addEventListener("click", closeAiSettingsDialog);
elements.cancelAiSettings?.addEventListener("click", closeAiSettingsDialog);
elements.aiSettingsDialog?.addEventListener("keydown", handleAiSettingsKeydown);
elements.aiSettingsForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.aiKeyEditingProvider) {
    await confirmAiKeyEdit();
    return;
  }
  await saveAiSettings();
});
elements.aiProviderInput?.addEventListener("change", handleAiProviderChange);
elements.setOpenAiDefaultButton?.addEventListener("click", () => selectDefaultAiProvider("openai"));
elements.setCodexDefaultButton?.addEventListener("click", () => selectDefaultAiProvider("codex-oauth"));
elements.setDeepSeekDefaultButton?.addEventListener("click", () => selectDefaultAiProvider("deepseek"));
elements.addAiKeyButton?.addEventListener("click", () => startAiKeyEdit("openai"));
elements.addDeepSeekKeyButton?.addEventListener("click", () => startAiKeyEdit("deepseek"));
elements.closeProviderKeyDialog?.addEventListener("click", cancelAiKeyEdit);
elements.cancelAiKeyEditButton?.addEventListener("click", cancelAiKeyEdit);
elements.toggleAiKeyVisibilityButton?.addEventListener("click", toggleAiKeyVisibility);
elements.confirmAiKeyEditButton?.addEventListener("click", () => confirmAiKeyEdit());
elements.deleteAiKeyButton?.addEventListener("click", () => deleteAiKey("openai"));
elements.deleteDeepSeekKeyButton?.addEventListener("click", () => deleteAiKey("deepseek"));
elements.connectCodexButton?.addEventListener("click", handleCodexConnectAction);
elements.logoutCodexButton?.addEventListener("click", logoutCodex);
elements.openMemorySettings?.addEventListener("click", settingsLinkHandler(openMemorySettingsDialog));
elements.closeMemorySettingsDialog?.addEventListener("click", closeMemorySettingsDialog);
elements.cancelMemorySettings?.addEventListener("click", closeMemorySettingsDialog);
elements.refreshMemorySettings?.addEventListener("click", () => {
  void loadMemorySettings();
});
elements.memorySettingsForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  void saveMemorySettings();
});
elements.memorySettingsDialog?.addEventListener("close", () => {
  setMemorySettingsError("");
  clearSettingsPanelUrl();
});
elements.memorySystemInput?.addEventListener("input", handleMemorySettingsInput);
elements.memoryUserInput?.addEventListener("input", handleMemorySettingsInput);
elements.openRagSettings?.addEventListener("click", settingsLinkHandler(openRagSettingsDialog));
elements.closeRagSettingsDialog?.addEventListener("click", closeRagSettingsDialog);
elements.cancelRagSettings?.addEventListener("click", (event) => {
  event.preventDefault();
  closeRagSettingsDialog();
});
elements.saveRagSettings?.addEventListener("click", (event) => {
  event.preventDefault();
  closeRagSettingsDialog();
});
elements.ragSettingsDialog?.addEventListener("close", () => {
  setRagSettingsError("");
  clearSettingsPanelUrl();
});
elements.refreshRagSettings?.addEventListener("click", () => {
  void loadRagSettings();
});
elements.ragSettingsList?.addEventListener("click", (event) => {
  const pauseButton = event.target.closest("[data-rag-pause]");
  if (pauseButton) {
    void pauseRagIndex(pauseButton.dataset.ragPause);
    return;
  }
  const resumeButton = event.target.closest("[data-rag-resume]");
  if (resumeButton) {
    void resumeRagIndex(resumeButton.dataset.ragResume);
    return;
  }
  const indexButton = event.target.closest("[data-rag-index]");
  if (indexButton) {
    void buildRagIndex(indexButton.dataset.ragIndex, { rebuild: false });
    return;
  }
  const rebuildButton = event.target.closest("[data-rag-rebuild]");
  if (rebuildButton) {
    void buildRagIndex(rebuildButton.dataset.ragRebuild, { rebuild: true });
  }
});
elements.openMcpSettings?.addEventListener("click", settingsLinkHandler(openMcpSettingsDialog));
elements.openSkillsSettings?.addEventListener("click", settingsLinkHandler(openSkillsSettingsDialog));
elements.cancelSkillsSettings?.addEventListener("click", closeSkillsSettingsDialog);
elements.saveSkillsSettings?.addEventListener("click", () => {
  void saveSkillsSettingsDialog();
});
elements.closeMcpSettingsDialog?.addEventListener("click", cancelMcpSettingsDialog);
elements.cancelMcpSettings?.addEventListener("click", cancelMcpSettingsDialog);
elements.refreshMcpSettings?.addEventListener("click", () => {
  void refreshMcpSettings();
});
elements.mcpSettingsDialog?.addEventListener("cancel", (event) => {
  event.preventDefault();
  cancelMcpSettingsDialog();
});
elements.addMcpServer?.addEventListener("click", addMcpServer);
elements.mcpSettingsForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveMcpSettings();
});
elements.mcpSearchInput?.addEventListener("input", (event) => {
  state.mcpSearchQuery = normalizeText(event.target.value);
  renderMcpSettingsDialog();
});
elements.mcpServerList?.addEventListener("click", (event) => {
  const row = event.target.closest("[data-mcp-select]");
  if (!row) return;
  state.mcpEditingId = row.dataset.mcpSelect;
  clearMcpTransientFeedback();
  renderMcpSettingsDialog();
});
elements.mcpServerEditor?.addEventListener("input", (event) => {
  const fieldInput = event.target.closest("[data-mcp-field]");
  if (fieldInput) {
    const fieldType = normalizeText(fieldInput.type).toLowerCase();
    const tagName = normalizeText(fieldInput.tagName).toLowerCase();
    if (fieldType === "checkbox" || tagName === "select") return;
    updateCurrentMcpServerField(fieldInput);
    return;
  }
  const secretNameInput = event.target.closest("[data-mcp-secret-name]");
  if (secretNameInput) {
    updateMcpSecret(
      secretNameInput.dataset.mcpSecretName,
      Number(secretNameInput.dataset.mcpSecretIndex),
      { name: normalizeText(secretNameInput.value) },
      false
    );
    return;
  }
  const secretValueInput = event.target.closest("[data-mcp-secret-value]");
  if (secretValueInput) {
    const server = currentMcpServer();
    const kind = secretValueInput.dataset.mcpSecretValue;
    const index = Number(secretValueInput.dataset.mcpSecretIndex);
    const entry = server?.[kind]?.[index] || {};
    updateMcpSecret(kind, index, { value: secretValueInput.value, configured: Boolean(entry.configured) }, false);
  }
});
elements.mcpServerEditor?.addEventListener("change", (event) => {
  const fieldInput = event.target.closest("[data-mcp-field]");
  if (!fieldInput) return;
  const previousServer = currentMcpServer();
  if (!previousServer) return;
  const field = fieldInput.dataset.mcpField;
  if (field === "enabled") {
    const enabled = Boolean(fieldInput.checked);
    clearMcpTransientFeedback();
    updateMcpServer(previousServer.id, (current) => ({ ...current, enabled }), false);
    void connectMcpServer(previousServer.id);
    return;
  }
  updateCurrentMcpServerField(fieldInput);
});
elements.mcpServerEditor?.addEventListener("click", (event) => {
  const emptyAddButton = event.target.closest("[data-mcp-empty-add]");
  if (emptyAddButton) {
    addMcpServer();
    return;
  }
  const transportButton = event.target.closest("[data-mcp-transport-option]");
  if (transportButton) {
    const server = currentMcpServer();
    if (!server) return;
    const value = transportButton.dataset.mcpTransportOption === "http" ? "http" : "stdio";
    clearMcpTransientFeedback();
    updateMcpServer(server.id, (current) => ({ ...current, transport: value }), true);
    return;
  }
  const testButton = event.target.closest("[data-mcp-test]");
  if (testButton) {
    void testMcpServer(testButton.dataset.mcpTest);
    return;
  }
  const connectButton = event.target.closest("[data-mcp-connect]");
  if (connectButton) {
    void connectMcpServer(connectButton.dataset.mcpConnect);
    return;
  }
  const reconnectButton = event.target.closest("[data-mcp-reconnect]");
  if (reconnectButton) {
    void reconnectMcpServer(reconnectButton.dataset.mcpReconnect);
    return;
  }
  const resetCircuitButton = event.target.closest("[data-mcp-reset-circuit]");
  if (resetCircuitButton) {
    void resetMcpCircuit(resetCircuitButton.dataset.mcpResetCircuit);
    return;
  }
  const viewLogButton = event.target.closest("[data-mcp-view-log]");
  if (viewLogButton) {
    void viewMcpStderrLog(viewLogButton.dataset.mcpViewLog);
    return;
  }
  const deleteButton = event.target.closest("[data-mcp-delete]");
  if (deleteButton) {
    confirmDeleteMcpServer(deleteButton.dataset.mcpDelete);
    return;
  }
  const addSecretButton = event.target.closest("[data-mcp-secret-add]");
  if (addSecretButton) {
    addMcpSecret(addSecretButton.dataset.mcpSecretAdd);
    return;
  }
  const removeSecretButton = event.target.closest("[data-mcp-secret-remove]");
  if (removeSecretButton) {
    removeMcpSecret(removeSecretButton.dataset.mcpSecretRemove, Number(removeSecretButton.dataset.mcpSecretIndex));
  }
});
function updateCurrentMcpServerField(input) {
  const server = currentMcpServer();
  if (!server) return;
  clearMcpTransientFeedback();
  const field = input.dataset.mcpField;
  let value = normalizeText(input.value);
  if (field === "enabled") value = Boolean(input.checked);
  else if (field === "args") value = input.value.split(/\r?\n/).map(normalizeText).filter(Boolean);
  else if (field === "includeTools" || field === "excludeTools") value = normalizeMcpFilterList(input.value);
  else if (field === "timeoutSeconds" || field === "connectTimeoutSeconds") {
    value = Math.max(1, Number(input.value) || (field === "timeoutSeconds" ? 120 : 10));
  } else if (field === "transport") {
    value = value === "http" ? "http" : "stdio";
  }
  const shouldRender = field === "enabled" || field === "transport";
  updateMcpServer(server.id, (current) => ({ ...current, [field]: value }), shouldRender);
}
elements.closeSkillsSettingsDialog?.addEventListener("click", closeSkillsSettingsDialog);
elements.refreshSkillsSettings?.addEventListener("click", () => {
  void loadSkillsSettings();
});
elements.skillsSearchInput?.addEventListener("input", (event) => {
  state.skillsSearchQuery = normalizeText(event.target.value);
  renderSkillsSettingsDialog();
});
elements.addExternalSkillDirectory?.addEventListener("click", () => {
  void addExternalSkillDirectory();
});
elements.externalSkillDirectoryInput?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  void addExternalSkillDirectory();
});
elements.externalSkillDirectoryInput?.addEventListener("input", () => {
  setSkillsExternalError("");
});
elements.externalSkillDirectoryList?.addEventListener("click", (event) => {
  const removeButton = event.target.closest("[data-external-skill-directory-remove]");
  if (!removeButton) return;
  void removeExternalSkillDirectory(removeButton.dataset.externalSkillDirectoryRemove);
});
elements.skillsSettingsList?.addEventListener("click", (event) => {
  const skillButton = event.target.closest("[data-skill-name]");
  if (!skillButton) return;
  void loadSkillDetail(skillButton.dataset.skillName);
});
elements.skillsSettingsDetail?.addEventListener("click", (event) => {
  const editStart = event.target.closest("[data-skill-edit-start]");
  if (editStart && state.selectedSkillDetail) {
    state.skillEditingName = normalizeSkillDetail(state.selectedSkillDetail).name;
    renderSkillDetail();
    return;
  }
  const editCancel = event.target.closest("[data-skill-edit-cancel]");
  if (editCancel) {
    state.skillEditingName = "";
    renderSkillDetail();
    return;
  }
  const fileButton = event.target.closest("[data-skill-file]");
  if (!fileButton || !state.selectedSkillName) return;
  void loadSkillDetail(state.selectedSkillName, fileButton.dataset.skillFile);
});
elements.skillsSettingsDetail?.addEventListener("change", (event) => {
  const enabledInput = event.target.closest("[data-skill-enabled]");
  if (!enabledInput) return;
  setSkillEnabled(enabledInput.dataset.skillEnabled, enabledInput.checked);
});
elements.skillsSettingsDetail?.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-skill-edit-form]");
  if (!form) return;
  event.preventDefault();
  void saveSkillEdit(form);
});
elements.pdfInput.addEventListener("change", async (event) => {
  try {
    await importPdfFiles(event.target.files);
  } catch (error) {
    showMessageDialog({
      eyebrow: "Import PDF",
      title: "Could not import this PDF",
      body: importPdfErrorMessage(error)
    });
    console.error(error);
  }
  elements.pdfInput.value = "";
});

function importPdfErrorMessage(error) {
  const message = normalizeText(error?.message || "");
  if (message && !/failed to fetch|load failed|networkerror/i.test(message)) {
    return message;
  }
  if (window.location.protocol === "file:") {
    return "Open Paper Notes from http://127.0.0.1:8765 before importing PDFs.";
  }
  return "Paper Notes could not reach the running server. Keep the app open at http://127.0.0.1:8765 and try again.";
}

elements.importUrlForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.importUrlLoading) return;

  const source = normalizeText(elements.importUrlInput.value);
  if (!source) {
    elements.importUrlError.textContent = "Enter a DOI, arXiv link, or PDF URL.";
    elements.importUrlError.hidden = false;
    return;
  }

  try {
    elements.importUrlError.hidden = true;
    setImportUrlLoading(true);
    await importPaperUrl(source);
    closeImportUrlDialog();
  } catch (error) {
    elements.importUrlError.textContent = normalizeText(error.message) || "Could not import from this link.";
    elements.importUrlError.hidden = false;
    console.error(error);
  } finally {
    setImportUrlLoading(false);
  }
});

elements.closeImportUrlDialog?.addEventListener("click", closeImportUrlDialog);
elements.cancelImportUrlDialog?.addEventListener("click", closeImportUrlDialog);

function handleNoteMove(event) {
  const select = event.target.closest("[data-detail-note-id]");
  if (!select) return;
  moveNoteToCategory(select.dataset.detailNoteId, select.value);
}

function handleSummaryInput(event) {
  const textarea = event.target.closest("[data-summary-note-id]");
  if (!textarea) return;
  updateNoteSummary(textarea.dataset.summaryNoteId, textarea.value);
}

elements.sortButton.addEventListener("click", () => {
  const nextHidden = !elements.sortMenu.hidden;
  elements.sortMenu.hidden = nextHidden;
  elements.sortButton.setAttribute("aria-expanded", String(!nextHidden));
});

elements.sortMenu.addEventListener("click", (event) => {
  const button = event.target.closest("[data-sort-mode]");
  if (!button) return;
  state.sortMode = button.dataset.sortMode;
  localStorage.setItem(SORT_KEY, state.sortMode);
  state.selectedNoteId = null;
  elements.sortMenu.hidden = true;
  elements.sortButton.setAttribute("aria-expanded", "false");
  renderApp();
});

elements.detailsCard.addEventListener("change", handleNoteMove);
elements.detailsCard.addEventListener("input", handleSummaryInput);
elements.detailsCard.addEventListener("click", (event) => {
  const removeTagButton = event.target.closest("[data-remove-tag-note]");
  if (removeTagButton) {
    event.preventDefault();
    event.stopPropagation();
    confirmRemoveNoteTag(removeTagButton.dataset.removeTagNote, removeTagButton.dataset.removeTag);
    return;
  }

  const filterTagButton = event.target.closest("[data-filter-tag]");
  if (filterTagButton) {
    event.preventDefault();
    filterNotesByTag(filterTagButton.dataset.filterTag);
    return;
  }

  const addTagButton = event.target.closest("[data-open-tag-dialog]");
  if (addTagButton) {
    event.preventDefault();
    openTagDialog(addTagButton.dataset.openTagDialog);
    return;
  }

  const deleteButton = event.target.closest("[data-delete-note-id]");
  if (!deleteButton) return;
  event.preventDefault();
  confirmDeleteNote(deleteButton.dataset.deleteNoteId);
});
elements.notesGrid.addEventListener("click", (event) => {
  const deleteButton = event.target.closest("[data-delete-note-id]");
  if (deleteButton) {
    event.preventDefault();
    event.stopPropagation();
    confirmDeleteNote(deleteButton.dataset.deleteNoteId);
    return;
  }

  const button = event.target.closest("[data-rename-note-id]");
  if (button) {
    event.preventDefault();
    event.stopPropagation();
    openRenameNoteDialog(button.dataset.renameNoteId);
    return;
  }

  if (event.target.closest("a")) return;
  const card = event.target.closest("[data-note-id]");
  if (!card) return;
  state.selectedNoteId = card.dataset.noteId;
  renderNotes();
  renderDetails();
});

elements.notesGrid.addEventListener("dragstart", (event) => {
  const card = event.target.closest("[data-note-id]");
  if (!card) return;
  if (event.target.closest("a, button")) {
    event.preventDefault();
    return;
  }
  state.draggedNoteId = card.dataset.noteId;
  card.classList.add("is-dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", state.draggedNoteId);
  setCompactDragImage(event, getNoteById(state.draggedNoteId)?.title || "Paper", "Paper");
});

elements.notesGrid.addEventListener("dragend", () => {
  state.draggedNoteId = null;
  state.dragTarget = null;
  clearCategoryDropIndicators();
  elements.notesGrid.querySelectorAll(".is-dragging").forEach((node) => node.classList.remove("is-dragging"));
});

elements.renameNoteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const noteId = state.pendingRenameNoteId;
  const nextTitle = normalizeText(elements.renameNoteInput.value);

  if (!nextTitle) {
    elements.renameNoteError.textContent = "Paper name cannot be empty.";
    elements.renameNoteError.hidden = false;
    return;
  }

  try {
    await renameNote(noteId, nextTitle);
    closeRenameNoteDialog();
  } catch (error) {
    elements.renameNoteError.textContent = "Could not rename this paper.";
    elements.renameNoteError.hidden = false;
    console.error(error);
  }
});

elements.categoryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const mode = elements.categoryDialog.dataset.mode;
  const categoryId = state.pendingCategoryId;
  const name = elements.categoryNameInput.value;
  const error = validateCategoryName(name, categoryId);

  if (error) {
    elements.categoryDialogError.textContent = error;
    elements.categoryDialogError.hidden = false;
    return;
  }

  if (mode === "create") createCategory(name, null);
  if (mode === "create-child") createCategory(name, state.pendingParentId);
  if (mode === "rename" && categoryId) renameCategory(categoryId, name);
  closeCategoryDialog();
});

elements.closeCategoryDialog.addEventListener("click", closeCategoryDialog);
elements.cancelCategoryDialog.addEventListener("click", closeCategoryDialog);
elements.closeRenameNoteDialog.addEventListener("click", closeRenameNoteDialog);
elements.cancelRenameNoteDialog.addEventListener("click", closeRenameNoteDialog);
elements.closeTagDialog.addEventListener("click", closeTagDialog);
elements.cancelTagDialog.addEventListener("click", closeTagDialog);
elements.closeMessageDialog.addEventListener("click", closeMessageDialog);
elements.messageDialogAction.addEventListener("click", closeMessageDialog);

elements.tagForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const added = addNoteTag(state.pendingTagNoteId, elements.tagInput.value);
  if (!added) {
    elements.tagDialogError.textContent = "Tag cannot be empty.";
    elements.tagDialogError.hidden = false;
    return;
  }
  closeTagDialog();
});

elements.tagInput.addEventListener("input", renderTagSuggestions);

elements.tagSuggestions?.addEventListener("click", (event) => {
  const suggestionButton = event.target.closest("[data-tag-suggestion]");
  if (!suggestionButton) return;
  elements.tagInput.value = suggestionButton.dataset.tagSuggestion || "";
  elements.tagInput.focus();
  renderTagSuggestions();
});

elements.confirmDialogAction.addEventListener("click", () => {
  if (typeof state.confirmAction === "function") state.confirmAction();
  closeConfirmDialog();
});

elements.closeConfirmDialog.addEventListener("click", closeConfirmDialog);
elements.cancelConfirmDialog.addEventListener("click", closeConfirmDialog);

function attachResizeHandle(handle, side) {
  if (!handle) return;
  handle.addEventListener("mousedown", (event) => {
    event.preventDefault();
    document.body.classList.add("is-resizing");
    const startX = event.clientX;
    const startSidebar = state.panelWidths.sidebar;
    const startDetails = state.panelWidths.details;

    function onMove(moveEvent) {
      if (side === "left") {
        const next = Math.max(240, Math.min(460, startSidebar + (moveEvent.clientX - startX)));
        state.panelWidths.sidebar = next;
      } else {
        const next = Math.max(260, Math.min(460, startDetails - (moveEvent.clientX - startX)));
        state.panelWidths.details = next;
      }
      applyPanelWidths();
    }

    function onUp() {
      document.body.classList.remove("is-resizing");
      saveLayoutState();
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    }

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });
}

state.panelWidths = readLayoutState();
applyPanelWidths();
attachResizeHandle(elements.leftResizer, "left");
attachResizeHandle(elements.rightResizer, "right");
initialize();
