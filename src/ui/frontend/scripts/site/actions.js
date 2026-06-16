function openRenameNoteDialog(noteId) {
  const note = getNoteById(noteId);
  if (!note) return;
  state.pendingRenameNoteId = noteId;
  elements.renameNoteInput.value = note.title;
  elements.renameNoteError.hidden = true;
  elements.renameNoteError.textContent = "";
  elements.renameNoteDialog.showModal();
  elements.renameNoteInput.focus();
  elements.renameNoteInput.select();
}

function closeRenameNoteDialog() {
  state.pendingRenameNoteId = null;
  elements.renameNoteDialog.close();
}

function filterNotesByTag(rawTag) {
  const [tag] = normalizeTags([rawTag]);
  if (!tag) return;
  const activeTags = normalizeTags(state.activeTagFilters);
  state.activeTagFilters = activeTags.includes(tag)
    ? activeTags.filter((activeTag) => activeTag !== tag)
    : [...activeTags, tag];
  state.selectedNoteId = null;
  renderApp();
}

function removeTagFilter(rawTag) {
  const [tag] = normalizeTags([rawTag]);
  if (!tag) return;
  const activeTags = normalizeTags(state.activeTagFilters);
  state.activeTagFilters = activeTags.filter((activeTag) => activeTag !== tag);
  state.selectedNoteId = null;
  renderApp();
}

function createCategory(name, parentId = null) {
  updateLibrary((library) => {
    const siblings = library.categories.filter((category) => (category.parentId || null) === (parentId || null));
    const nextOrder = siblings.length ? Math.max(...siblings.map((category) => category.order)) + 1 : 0;
    const id = uniqueId(parentId ? "subcollection" : "collection");
    library.categories.push({
      id,
      name: normalizeText(name),
      parentId: parentId || null,
      order: nextOrder,
      system: false
    });
    if (parentId) state.expandedCategoryIds.add(parentId);
    state.activeCategoryId = id;
    state.selectedNoteId = null;
  });
}

function renameCategory(categoryId, name) {
  updateLibrary((library) => {
    const category = library.categories.find((entry) => entry.id === categoryId);
    if (category) category.name = normalizeText(name);
  });
}

function deleteCategory(categoryId) {
  updateLibrary((library) => {
    const descendants = library.categories.filter((category) => category.parentId === categoryId).map((category) => category.id);
    const movedIds = new Set([categoryId, ...descendants]);
    library.notes.forEach((note) => {
      if (movedIds.has(note.categoryId)) note.categoryId = UNCATEGORIZED_ID;
    });
    library.categories = library.categories.filter((category) => !movedIds.has(category.id));
    state.expandedCategoryIds.delete(categoryId);
    descendants.forEach((childId) => state.expandedCategoryIds.delete(childId));
    if (movedIds.has(state.activeCategoryId)) state.activeCategoryId = UNCATEGORIZED_ID;
    if (state.selectedNoteId && !getNoteById(state.selectedNoteId)) state.selectedNoteId = null;
  });
}

async function deleteNote(noteId) {
  const previousLibrary = cloneLibrary(state.library);
  const previousSelectedNoteId = state.selectedNoteId;
  updateLibrary((library) => {
    library.notes = library.notes.filter((note) => note.id !== noteId);
    if (state.selectedNoteId === noteId) state.selectedNoteId = null;
  });

  try {
    const payload = await fetchJson(`/api/library/notes/${encodeURIComponent(noteId)}`, {
      method: "DELETE"
    });
    if (payload.library) {
      state.library = sanitizeLibrary(payload.library);
      if (state.selectedNoteId && !getNoteById(state.selectedNoteId)) state.selectedNoteId = null;
      state.dataSource = "default";
      saveLibraryToStorage();
      saveExpandedState();
      renderApp();
    }
  } catch (error) {
    console.warn("Could not delete note from the backend.", error);
    state.library = previousLibrary;
    state.selectedNoteId = previousSelectedNoteId;
    saveLibraryToStorage();
    renderApp();
    showMessageDialog({
      eyebrow: "Delete Failed",
      title: "Could not delete this paper",
      body: error?.message || "The paper was restored because the backend delete request failed."
    });
  }
}

function confirmDeleteNote(noteId) {
  const note = getNoteById(noteId);
  if (!note) return;
  openConfirmDialog({
    title: `Delete ${note.title}?`,
    body: "This removes the paper from the website list. The PDF and HTML files stay in your local folders.",
    action: () => deleteNote(noteId)
  });
}

function normalizeSiblingOrder(library, parentId) {
  const siblings = library.categories
    .filter((category) => (category.parentId || null) === (parentId || null))
    .sort((left, right) => left.order - right.order || left.name.localeCompare(right.name));
  siblings.forEach((category, index) => {
    if (parentId === null) {
      if (category.id === ALL_CATEGORY_ID) category.order = 0;
      else if (category.id === UNCATEGORIZED_ID) category.order = 1;
      else category.order = Math.max(index, 2);
    } else {
      category.order = index;
    }
  });
}

function reorderWithinParent(categoryId, direction) {
  updateLibrary((library) => {
    const category = library.categories.find((entry) => entry.id === categoryId);
    if (!category || category.system) return;
    const parentId = category.parentId || null;
    const siblings = library.categories
      .filter((entry) => (entry.parentId || null) === parentId)
      .sort((left, right) => left.order - right.order);
    const index = siblings.findIndex((entry) => entry.id === categoryId);
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= siblings.length) return;
    const [moved] = siblings.splice(index, 1);
    siblings.splice(targetIndex, 0, moved);
    siblings.forEach((entry, order) => {
      const target = library.categories.find((item) => item.id === entry.id);
      target.order = order;
    });
    normalizeSiblingOrder(library, parentId);
  });
}

function moveCategory(categoryId, targetParentId, targetOrder) {
  updateLibrary((library) => {
    const category = library.categories.find((entry) => entry.id === categoryId);
    if (!category || category.system) return;
    const previousParentId = category.parentId || null;
    const nextParentId = targetParentId || null;
    if (nextParentId && getCategoryById(nextParentId)?.parentId) return;
    if (category.id === nextParentId) return;
    category.parentId = nextParentId;
    const siblings = library.categories
      .filter((entry) => entry.id !== categoryId && (entry.parentId || null) === nextParentId)
      .sort((left, right) => left.order - right.order);
    siblings.splice(Math.min(targetOrder, siblings.length), 0, category);
    siblings.forEach((entry, index) => {
      const target = library.categories.find((item) => item.id === entry.id);
      target.order = index;
    });
    normalizeSiblingOrder(library, nextParentId);
    normalizeSiblingOrder(library, previousParentId);
  });
}

function moveNoteToCategory(noteId, categoryId) {
  updateLibrary((library) => {
    const note = library.notes.find((entry) => entry.id === noteId);
    if (note && isLeafCategory(categoryId)) note.categoryId = categoryId;
  });
}

function resolveCategoryDropLeafId(categoryId) {
  if (isLeafCategory(categoryId)) return categoryId;
  const leaves = getLeafDescendants(categoryId);
  return leaves[0]?.id || "";
}

async function saveNoteSummaryToServer(noteId, summary) {
  await fetchJson(`/api/library/notes/${encodeURIComponent(noteId)}/summary`, {
    method: "POST",
    body: { summary }
  });
}

function updateNoteSummary(noteId, summary) {
  const note = getNoteById(noteId);
  if (!note) return;

  note.summary = normalizeText(summary);
  saveLibraryToStorage();
  state.dataSource = "storage";

  window.clearTimeout(summarySaveTimers.get(noteId));
  summarySaveTimers.set(noteId, window.setTimeout(() => {
    saveNoteSummaryToServer(noteId, note.summary).catch((error) => {
      console.warn("Could not sync summary to the backend.", error);
    });
  }, 400));
}

function openTagDialog(noteId) {
  const note = getNoteById(noteId);
  if (!note) return;
  state.pendingTagNoteId = noteId;
  elements.tagInput.value = "";
  elements.tagDialogError.hidden = true;
  elements.tagDialogError.textContent = "";
  renderTagSuggestions();
  elements.tagDialog.showModal();
  elements.tagInput.focus();
}

function closeTagDialog() {
  state.pendingTagNoteId = "";
  if (elements.tagSuggestions) {
    elements.tagSuggestions.hidden = true;
    elements.tagSuggestions.innerHTML = "";
  }
  elements.tagDialog.close();
}

function getExistingTagSuggestions(query = "") {
  const limit = 10;
  const normalizedQuery = normalizeText(query).toLowerCase();
  const currentNoteTags = new Set(normalizeTags(getNoteById(state.pendingTagNoteId)?.tags));
  const counts = new Map();
  state.library.notes.forEach((note) => {
    normalizeTags(note.tags).forEach((tag) => {
      if (currentNoteTags.has(tag)) return;
      if (normalizedQuery && !tag.toLowerCase().includes(normalizedQuery)) return;
      counts.set(tag, (counts.get(tag) || 0) + 1);
    });
  });
  const tags = [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([tag]) => tag);
  return {
    tags: tags.slice(0, limit),
    hasMore: tags.length > limit
  };
}

function renderTagSuggestions() {
  if (!elements.tagSuggestions) return;
  const suggestions = getExistingTagSuggestions(elements.tagInput.value);
  elements.tagSuggestions.hidden = !suggestions.tags.length && !suggestions.hasMore;
  elements.tagSuggestions.innerHTML = `
    ${suggestions.tags.map((tag) => `
    <button class="tag-suggestion" type="button" data-tag-suggestion="${escapeHtml(tag)}">${escapeHtml(tag)}</button>
  `).join("")}
    ${suggestions.hasMore ? `<span class="tag-suggestion-more" title="More matching tags available">+ more</span>` : ""}
  `;
}

function addNoteTag(noteId, rawTag) {
  const note = getNoteById(noteId);
  if (!note) return false;

  const [tag] = normalizeTags([rawTag]);
  if (!tag) return false;

  updateLibrary((library) => {
    const entry = library.notes.find((item) => item.id === noteId);
    if (!entry) return;
    const tags = normalizeTags(entry.tags);
    if (!tags.includes(tag)) tags.push(tag);
    entry.tags = tags;
  });
  return true;
}

function removeNoteTag(noteId, rawTag) {
  const note = getNoteById(noteId);
  if (!note) return false;

  const [tag] = normalizeTags([rawTag]);
  if (!tag) return false;

  updateLibrary((library) => {
    const entry = library.notes.find((item) => item.id === noteId);
    if (!entry) return;
    entry.tags = normalizeTags(entry.tags).filter((item) => item !== tag);
  });
  return true;
}

function confirmRemoveNoteTag(noteId, rawTag) {
  const note = getNoteById(noteId);
  const [tag] = normalizeTags([rawTag]);
  if (!note || !tag) return;
  openConfirmDialog({
    eyebrow: "Remove Tag",
    title: `Remove #${tag}?`,
    body: `This only removes the tag from "${note.title}". Other papers with this tag will stay unchanged.`,
    actionLabel: "Remove",
    action: () => removeNoteTag(noteId, tag)
  });
}

async function renameNote(noteId, nextTitle) {
  const note = getNoteById(noteId);
  if (!note) return;

  const cleanTitle = normalizeText(nextTitle);
  if (!cleanTitle || cleanTitle === note.title) return;

  const payload = await fetchJson(`/api/library/notes/${encodeURIComponent(note.id)}/rename`, {
    method: "POST",
    body: { title: cleanTitle }
  });

  const updatedNote = payload.note || payload;
  updateLibrary((library) => {
    const entry = library.notes.find((item) => item.id === noteId);
    if (entry) entry.title = normalizeText(updatedNote.title) || cleanTitle;
  });
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",").pop() : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function importPdfWithServer(file, categoryId) {
  const payload = await fetchJson("/api/library/import/pdf", {
    method: "POST",
    body: {
      fileName: file.name,
      mimeType: file.type || "application/pdf",
      dataBase64: await readFileAsBase64(file),
      categoryId
    }
  });
  return payload.note || payload;
}

async function importPaperUrlWithServer(url, categoryId) {
  const payload = await fetchJson("/api/library/import/url", {
    method: "POST",
    body: { url, categoryId }
  });
  return payload.note || payload;
}

function appendImportedNotes(importedNotes) {
  updateLibrary((library) => {
    const nextOrder = library.notes.reduce((max, note, index) => (
      Math.max(max, Number.isFinite(Number(note.order)) ? Number(note.order) : index)
    ), -1) + 1;
    importedNotes.forEach((note, index) => {
      note.order = Number.isFinite(Number(note.order)) ? Number(note.order) : nextOrder + index;
    });
    importedNotes.forEach((note) => library.notes.push(note));
    state.selectedNoteId = importedNotes.at(-1)?.id || state.selectedNoteId;
  });
}

async function importPdfFiles(files) {
  const pdfFiles = Array.from(files || []).filter((file) => (
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
  ));
  if (!pdfFiles.length) return;

  const categoryId = getDefaultImportCategoryId();
  const importedNotes = [];
  for (const file of pdfFiles) {
    importedNotes.push(await importPdfWithServer(file, categoryId));
  }

  appendImportedNotes(importedNotes);
}

async function importPaperUrl(url) {
  const source = normalizeText(url);
  if (!source) throw new Error("Enter a DOI, arXiv link, or PDF URL.");
  const note = await importPaperUrlWithServer(source, getDefaultImportCategoryId());
  appendImportedNotes([note]);
}

function setImportMenuOpen(open) {
  if (!elements.importMenu || !elements.addPdfButton) return;
  elements.importMenu.hidden = !open;
  elements.addPdfButton.setAttribute("aria-expanded", String(open));
}

function toggleImportMenu() {
  setImportMenuOpen(elements.importMenu?.hidden ?? true);
}

function openImportUrlDialog() {
  if (!elements.importUrlDialog) return;
  elements.importUrlInput.value = "";
  elements.importUrlError.textContent = "";
  elements.importUrlError.hidden = true;
  state.importUrlLoading = false;
  elements.submitImportUrl.disabled = false;
  elements.submitImportUrl.textContent = "Import";
  elements.importUrlDialog.showModal();
  elements.importUrlInput.focus();
}

function closeImportUrlDialog() {
  if (!elements.importUrlDialog) return;
  state.importUrlLoading = false;
  elements.importUrlDialog.close();
}

function setImportUrlLoading(loading) {
  state.importUrlLoading = loading;
  elements.submitImportUrl.disabled = loading;
  elements.importUrlInput.disabled = loading;
  elements.submitImportUrl.textContent = loading ? "Importing..." : "Import";
}

function closeContextMenu() {
  state.contextCategoryId = null;
  elements.contextMenu.hidden = true;
  elements.contextMenu.innerHTML = "";
}

function closeSettingsMenu() {
  if (!elements.settingsMenu || !elements.settingsButton) return;
  elements.settingsMenu.hidden = true;
  if (elements.settingsMenuShield) elements.settingsMenuShield.hidden = true;
  elements.settingsButton.setAttribute("aria-expanded", "false");
}

function scratchpadEnabled() {
  return localStorage.getItem(SCRATCHPAD_ENABLED_KEY) === "true";
}

function applyScratchpadSettingControls() {
  const enabled = scratchpadEnabled();
  elements.scratchpadSettingsSwitch?.setAttribute("aria-checked", String(enabled));
  elements.scratchpadSettingsSwitch?.setAttribute("aria-label", `Scratchpad: ${enabled ? "On" : "Off"}. Click to ${enabled ? "disable" : "enable"}.`);
  if (elements.scratchpadSettingsValue) elements.scratchpadSettingsValue.textContent = enabled ? "On" : "Off";
}

function setScratchpadEnabled(enabled) {
  localStorage.setItem(SCRATCHPAD_ENABLED_KEY, enabled ? "true" : "false");
  applyScratchpadSettingControls();
  document.querySelector(".floating-pad")?.toggleAttribute("hidden", !enabled);
  window.dispatchEvent(new CustomEvent("paper-scratchpad-setting-change", {
    detail: { enabled }
  }));
}

function shouldOpenLinkInCurrentTab(event) {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

function settingsPanelFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const value = normalizeText(params.get("settings") || params.get("panel"));
  if (value) return value;
  return normalizeText(window.location.hash).replace(/^#settings-?/, "");
}

function clearSettingsPanelUrl() {
  const params = new URLSearchParams(window.location.search);
  const hasSettingsPanel = params.has("settings") || params.has("panel") || window.location.hash.startsWith("#settings");
  if (!hasSettingsPanel) return;
  params.delete("settings");
  params.delete("panel");
  const query = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

function settingsLinkHandler(openDialog) {
  return (event) => {
    if (!shouldOpenLinkInCurrentTab(event)) return;
    event.preventDefault();
    closeSettingsMenu();
    void openDialog();
  };
}

async function openSettingsPanelFromUrl() {
  const panel = settingsPanelFromUrl();
  if (!panel) return;
  if (panel === "ai" || panel === "ai-provider" || panel === "provider") {
    await openAiSettingsDialog();
  } else if (panel === "memory") {
    await openMemorySettingsDialog();
  } else if (panel === "rag") {
    await openRagSettingsDialog();
  } else if (panel === "mcp") {
    await openMcpSettingsDialog();
  } else if (panel === "skills") {
    await openSkillsSettingsDialog();
  }
}

function toggleSettingsMenu() {
  if (!elements.settingsMenu || !elements.settingsButton) return;
  const nextOpen = elements.settingsMenu.hidden;
  elements.settingsMenu.hidden = !nextOpen;
  if (elements.settingsMenuShield) elements.settingsMenuShield.hidden = !nextOpen;
  elements.settingsButton.setAttribute("aria-expanded", String(nextOpen));
}

function openContextMenu(categoryId, anchor) {
  const category = getCategoryById(categoryId);
  if (!category) return;
  const childAction = category.parentId === null && !category.system
    ? `<button class="menu-button" type="button" data-menu-action="new-child">New Sub-collection</button>`
    : "";
  elements.contextMenu.innerHTML = `
    ${childAction}
    <button class="menu-button" type="button" data-menu-action="rename">Rename</button>
    <button class="menu-button" type="button" data-menu-action="move-up">Move Up</button>
    <button class="menu-button" type="button" data-menu-action="move-down">Move Down</button>
    <button class="menu-button" type="button" data-menu-action="move-to-root"${category.parentId === null ? " disabled" : ""}>Move to Root</button>
    <button class="menu-button menu-button-danger" type="button" data-menu-action="delete">Delete</button>
  `;
  const rect = anchor.getBoundingClientRect();
  elements.contextMenu.style.top = `${rect.bottom + 6}px`;
  elements.contextMenu.style.left = `${Math.max(12, rect.left - 130)}px`;
  elements.contextMenu.hidden = false;
  state.contextCategoryId = categoryId;
}

function handleCategoryAction(action, categoryId) {
  const category = getCategoryById(categoryId);
  if (!category || category.system) return;

  if (action === "new-child" && category.parentId === null) {
    openCategoryDialog("create-child", null, categoryId);
    return;
  }
  if (action === "rename") {
    openCategoryDialog("rename", categoryId);
    return;
  }
  if (action === "move-up") {
    reorderWithinParent(categoryId, -1);
    return;
  }
  if (action === "move-down") {
    reorderWithinParent(categoryId, 1);
    return;
  }
  if (action === "move-to-root") {
    moveCategory(categoryId, null, getChildren(null).length);
    return;
  }
  if (action === "delete") {
    openConfirmDialog({
      title: `Delete ${category.name}?`,
      body: "Notes inside this collection will move to Uncategorized.",
      action: () => deleteCategory(categoryId)
    });
  }
}

function getDropTargetFromEvent(event) {
  const node = event.target.closest("[data-tree-node-id]");
  if (!node) {
    if (event.target.closest("#categoryList")) {
      return { type: "root", order: getChildren(null).length };
    }
    return null;
  }
  const categoryId = node.dataset.treeNodeId;
  const category = getCategoryById(categoryId);
  if (!category || category.id === state.draggedCategoryId) return null;
  if (category.system) {
    return category.id === ALL_CATEGORY_ID ? { type: "root", order: getChildren(null).length } : null;
  }

  const row = node.querySelector(".tree-row") || node;
  const rect = row.getBoundingClientRect();
  const offset = event.clientY - rect.top;
  const topZone = rect.height * 0.30;
  const bottomZone = rect.height * 0.70;

  if (offset < topZone) return { type: "before", categoryId };
  if (offset > bottomZone) return { type: "after", categoryId };
  if (category.parentId === null) return { type: "nest", categoryId };
  return { type: "after", categoryId };
}

function dropTargetsEqual(left, right) {
  if (!left || !right) return left === right;
  return left.type === right.type && left.categoryId === right.categoryId && left.order === right.order;
}

function clearCategoryDropIndicators() {
  elements.categoryList.querySelectorAll(".is-drop-target, .is-note-drop-target, .is-drop-before, .is-drop-after").forEach((node) => {
    node.classList.remove("is-drop-target", "is-note-drop-target", "is-drop-before", "is-drop-after");
  });
}

function applyCategoryDropIndicator(target) {
  clearCategoryDropIndicators();
  if (!target?.categoryId) return;
  const node = elements.categoryList.querySelector(`[data-tree-node-id="${CSS.escape(target.categoryId)}"]`);
  if (!node) return;
  if (target.type === "nest") node.classList.add("is-drop-target");
  if (target.type === "before") node.classList.add("is-drop-before");
  if (target.type === "after") node.classList.add("is-drop-after");
}

function getNoteDropTargetFromEvent(event) {
  const node = event.target.closest("[data-tree-node-id]");
  if (!node) return null;
  const categoryId = node.dataset.treeNodeId;
  const category = getCategoryById(categoryId);
  if (!category || category.id === ALL_CATEGORY_ID) return null;
  const leafId = resolveCategoryDropLeafId(categoryId);
  if (!leafId) return null;
  return { categoryId, leafId };
}

function applyNoteDropIndicator(target) {
  clearCategoryDropIndicators();
  if (!target?.categoryId) return;
  const node = elements.categoryList.querySelector(`[data-tree-node-id="${CSS.escape(target.categoryId)}"]`);
  if (node) node.classList.add("is-note-drop-target");
}

function setCompactDragImage(event, label, detail = "") {
  if (!event.dataTransfer) return;
  const preview = document.createElement("div");
  preview.className = "drag-preview";
  preview.innerHTML = `
    <span>${escapeHtml(label)}</span>
    ${detail ? `<small>${escapeHtml(detail)}</small>` : ""}
  `;
  document.body.appendChild(preview);
  event.dataTransfer.setDragImage(preview, 16, 16);
  window.setTimeout(() => preview.remove(), 0);
}

function applyDropTarget(draggedId, target) {
  if (!draggedId || !target) return;
  const dragged = getCategoryById(draggedId);
  const targetCategory = getCategoryById(target.categoryId);
  if (!dragged || dragged.system) return;

  if (target.type === "root") {
    moveCategory(draggedId, null, Number.isFinite(target.order) ? target.order : getChildren(null).length);
    return;
  }

  if (!targetCategory) return;

  if (target.type === "nest") {
    if (dragged.parentId !== null || targetCategory.parentId !== null) return;
    moveCategory(draggedId, targetCategory.id, getChildren(targetCategory.id).length);
    state.expandedCategoryIds.add(targetCategory.id);
    return;
  }

  const parentId = targetCategory.parentId || null;
  const siblings = getChildren(parentId).filter((category) => category.id !== draggedId);
  const targetIndex = siblings.findIndex((category) => category.id === targetCategory.id);
  const insertIndex = target.type === "before" ? targetIndex : targetIndex + 1;
  moveCategory(draggedId, parentId, insertIndex);
}
