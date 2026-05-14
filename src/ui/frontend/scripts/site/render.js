function applyPanelWidths() {
  document.documentElement.style.setProperty("--sidebar-width", `${state.panelWidths.sidebar}px`);
  document.documentElement.style.setProperty("--details-width", `${state.panelWidths.details}px`);
}

function renderCategoryNode(category, level = 0) {
  const childCategories = getChildren(category.id);
  const expanded = state.expandedCategoryIds.has(category.id);
  const active = category.id === state.activeCategoryId;
  const selectedDrop = state.dragTarget && state.dragTarget.type === "nest" && state.dragTarget.categoryId === category.id;
  const beforeDrop = state.dragTarget && state.dragTarget.type === "before" && state.dragTarget.categoryId === category.id;
  const afterDrop = state.dragTarget && state.dragTarget.type === "after" && state.dragTarget.categoryId === category.id;

  return `
    <div class="tree-node tree-level-${level}${selectedDrop ? " is-drop-target" : ""}${beforeDrop ? " is-drop-before" : ""}${afterDrop ? " is-drop-after" : ""}" data-tree-node-id="${category.id}" draggable="${category.system ? "false" : "true"}">
      <div class="tree-row${active ? " is-active" : ""}">
        ${childCategories.length ? `<button class="tree-toggle${expanded ? " is-expanded" : ""}" type="button" data-toggle-category-id="${category.id}" aria-label="Toggle sub-collections">></button>` : `<span class="tree-spacer"></span>`}
        <button class="category-button${active ? " is-active" : ""}" type="button" data-category-id="${category.id}">
          <span class="category-text">
            <strong>${category.name}</strong>
          </span>
          <span class="category-count">${getCategoryCount(category.id)}</span>
        </button>
        ${!category.system ? `<button class="category-more" type="button" data-menu-category-id="${category.id}" aria-label="Collection options">...</button>` : ""}
      </div>
      ${childCategories.length && expanded ? `<div class="tree-children">${childCategories.map((child) => renderCategoryNode(child, level + 1)).join("")}</div>` : ""}
    </div>
  `;
}

function renderCategories() {
  const topLevel = getChildren(null).filter((category) => category.id !== UNCATEGORIZED_ID);
  elements.categoryList.innerHTML = topLevel.map((category) => renderCategoryNode(category, 0)).join("");
}

function renderContentHeader() {
  const category = getSelectedCategory();
  const isParent = category && hasChildren(category.id);
  elements.contentKicker.textContent = category && category.id === ALL_CATEGORY_ID
    ? "Library"
    : isParent
      ? "Collection"
      : "Sub-collection";
  elements.contentTitle.textContent = category ? category.name : "All Notes";
  elements.sortButton.textContent = `Sort: ${getSortLabel()}`;
  elements.sortMenu.querySelectorAll("[data-sort-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.sortMode === state.sortMode);
  });
}

function renderStatus() {
  const notes = getVisibleNotes();
  const category = getSelectedCategory();
  const label = category ? category.name : "All Notes";
  elements.libraryStatus.textContent = `${notes.length} notes in ${label}`;
  elements.emptyState.style.display = notes.length ? "none" : "block";
}

function syncSelectedNote() {
  const visibleNotes = getVisibleNotes();
  if (!visibleNotes.length) {
    state.selectedNoteId = null;
    return;
  }

  if (!state.selectedNoteId || !visibleNotes.some((note) => note.id === state.selectedNoteId)) {
    state.selectedNoteId = visibleNotes[0].id;
  }
}

function renderNotes() {
  const visibleNotes = getVisibleNotes();
  elements.notesGrid.innerHTML = visibleNotes.map((note) => {
    const leafCategory = getCategoryById(note.categoryId);
    const parent = leafCategory ? getTopLevelParent(leafCategory.id) : null;
    const detailLabel = parent && leafCategory && parent.id !== leafCategory.id
      ? `${parent.name} / ${leafCategory.name}`
      : leafCategory?.name || "Uncategorized";
    return `
      <article class="note-card${note.id === state.selectedNoteId ? " is-selected" : ""}" data-note-id="${note.id}">
        <div class="note-card-main">
          <div class="meta">
            <span>${note.date || "No date"}</span>
            <span>${detailLabel}</span>
          </div>
          <h3>${note.title}</h3>
        </div>
        <span class="note-card-actions-inline">
          <button class="note-open" type="button" data-rename-note-id="${note.id}">Rename</button>
          <button class="note-open note-open-danger" type="button" data-delete-note-id="${note.id}">Delete</button>
          <a class="note-open" href="${getReaderHref(note)}" aria-label="Open ${note.title}">Open</a>
        </span>
      </article>
    `;
  }).join("");
}

function renderDetails() {
  const note = getNoteById(state.selectedNoteId);
  if (!note) {
    elements.detailsPanel.hidden = true;
    elements.rightResizer.hidden = true;
    elements.detailsCard.innerHTML = "";
    return;
  }

  const allAssignable = getAssignableCategories();
  const tags = Array.isArray(note.tags) ? note.tags.filter(Boolean) : [];
  elements.detailsPanel.hidden = false;
  elements.rightResizer.hidden = false;
  elements.detailsCard.innerHTML = `
    <div>
      <div class="content-kicker">Paper</div>
      <h3>${note.title}</h3>
      <div class="details-meta">
        <span>${note.date || "No date"}</span>
      </div>
      <div class="note-card-actions">
        <a class="toolbar-button" href="${getReaderHref(note)}">Open Note</a>
        ${note.href ? `<a class="toolbar-button" href="${note.href}" target="_blank" rel="noopener">Open PDF</a>` : ""}
        ${note.htmlHref ? `<a class="toolbar-button" href="${note.htmlHref}" target="_blank" rel="noopener">Open HTML</a>` : ""}
      </div>
    </div>
    <div class="details-row details-tags-row">
      <div class="details-row-heading">
        <strong>Tags</strong>
        <button class="details-tag-add" type="button" data-open-tag-dialog="${escapeHtml(note.id)}">Add</button>
      </div>
      ${tags.length ? `
        <div class="details-tags" aria-label="Paper tags">
          ${tags.map((tag) => `
            <span class="details-tag">
              <span>${escapeHtml(tag)}</span>
              <button
                class="details-tag-remove"
                type="button"
                data-remove-tag-note="${escapeHtml(note.id)}"
                data-remove-tag="${escapeHtml(tag)}"
                aria-label="Remove ${escapeHtml(tag)} tag"
                title="Remove tag"
              >×</button>
            </span>
          `).join("")}
        </div>
      ` : `<p class="details-tags-empty">No tags yet</p>`}
    </div>
    <div class="details-row">
      <strong>Summary</strong>
      <textarea class="details-summary-input" data-summary-note-id="${note.id}" rows="6" placeholder="Write a short summary...">${escapeHtml(note.summary)}</textarea>
    </div>
    <div class="details-row">
      <strong>Collection</strong>
      <select class="note-select" data-detail-note-id="${note.id}" aria-label="Move note to collection">
        ${allAssignable.map((entry) => `
          <option value="${entry.id}"${entry.id === note.categoryId ? " selected" : ""}>${entry.parentId ? `${getCategoryById(entry.parentId)?.name} / ${entry.name}` : entry.name}</option>
        `).join("")}
      </select>
    </div>
  `;
}

function renderApp() {
  closeContextMenu();
  syncSelectedNote();
  renderCategories();
  renderContentHeader();
  renderStatus();
  renderNotes();
  renderDetails();
}

function updateLibrary(mutator) {
  mutator(state.library);
  state.library = sanitizeLibrary(state.library);
  saveLibraryToStorage();
  syncLibraryToServer(state.library);
  saveExpandedState();
  state.dataSource = "storage";
  renderApp();
}

function validateCategoryName(name, currentId = null) {
  const trimmed = normalizeText(name);
  if (!trimmed) return "Collection name cannot be empty.";
  const duplicate = state.library.categories.some((category) => (
    category.id !== currentId && category.name.toLowerCase() === trimmed.toLowerCase()
  ));
  if (duplicate) return "Collection name already exists.";
  return "";
}

function openCategoryDialog(mode, categoryId = null, parentId = null) {
  state.pendingCategoryId = categoryId;
  state.pendingParentId = parentId;
  elements.categoryDialog.dataset.mode = mode;
  elements.categoryDialogEyebrow.textContent = mode === "create-child"
    ? "Sub-collection"
    : mode === "create"
      ? "Collection"
      : "Edit Collection";
  elements.categoryDialogTitle.textContent = mode === "create-child"
    ? "New Sub-collection"
    : mode === "create"
      ? "New Collection"
      : "Rename Collection";
  elements.categoryDialogError.hidden = true;
  elements.categoryDialogError.textContent = "";
  elements.categoryNameInput.value = categoryId ? getCategoryById(categoryId)?.name || "" : "";
  elements.categoryDialog.showModal();
  elements.categoryNameInput.focus();
  elements.categoryNameInput.select();
}

function closeCategoryDialog() {
  state.pendingCategoryId = null;
  state.pendingParentId = null;
  elements.categoryDialog.close();
}

function openConfirmDialog({ title, body, action }) {
  state.confirmAction = action;
  elements.confirmDialogTitle.textContent = title;
  elements.confirmDialogBody.textContent = body;
  elements.confirmDialog.showModal();
}

function closeConfirmDialog() {
  state.confirmAction = null;
  elements.confirmDialog.close();
}

function showMessageDialog({ eyebrow = "Notice", title = "Message", body = "" }) {
  elements.messageDialogEyebrow.textContent = eyebrow;
  elements.messageDialogTitle.textContent = title;
  elements.messageDialogBody.textContent = body;
  elements.messageDialog.showModal();
}

function closeMessageDialog() {
  elements.messageDialog.close();
}
