function applyPanelWidths() {
  document.documentElement.style.setProperty("--sidebar-width", `${state.panelWidths.sidebar}px`);
  document.documentElement.style.setProperty("--details-width", `${state.panelWidths.details}px`);
}

function renderIcon(name, label = "", className = "", size = 18) {
  return window.renderPaperIcon
    ? window.renderPaperIcon(name, { label, className, size })
    : "";
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
        ${childCategories.length ? `<button class="tree-toggle${expanded ? " is-expanded" : ""}" type="button" data-toggle-category-id="${category.id}" aria-label="Toggle sub-collections"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 4l4 4-4 4"/></svg></button>` : `<span class="tree-spacer"></span>`}
        <button class="category-button${active ? " is-active" : ""}" type="button" data-category-id="${category.id}">
          <span class="category-text">
            <strong>${category.name}</strong>
          </span>
          <span class="category-count">${getCategoryCount(category.id)}</span>
        </button>
        ${!category.system ? `<button class="category-more" type="button" data-menu-category-id="${category.id}" aria-label="Collection options">${renderIcon("more-horizontal", "", "", 16)}</button>` : ""}
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
  elements.sortButton.innerHTML = `<span>Sort: ${escapeHtml(getSortLabel())}</span>${renderIcon("chevron-down", "", "", 15)}`;
  elements.sortMenu.querySelectorAll("[data-sort-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.sortMode === state.sortMode);
  });
}

function renderStatus() {
  const notes = getVisibleNotes();
  const category = getSelectedCategory();
  const activeTags = getActiveTagFilters();
  const label = category ? category.name : "All Notes";
  elements.libraryStatus.innerHTML = `
    <span class="library-status-count">${notes.length} notes in ${escapeHtml(label)}</span>
    ${activeTags.length ? `
      <span class="library-status-tags" aria-label="Active tag filters">
        ${activeTags.map((tag) => `
          <span class="library-status-tag">
            <span>#${escapeHtml(tag)}</span>
            <button type="button" data-remove-tag-filter="${escapeHtml(tag)}" aria-label="Remove tag filter ${escapeHtml(tag)}">${renderIcon("x", "", "", 14)}</button>
          </span>
        `).join("")}
      </span>
    ` : ""}
  `;
  elements.emptyState.hidden = Boolean(notes.length);
  elements.emptyState.innerHTML = notes.length ? "" : renderEmptyState(category, label);
}

function renderEmptyState(category, label) {
  const hasQuery = Boolean(state.query);
  const activeTags = getActiveTagFilters();
  const hasTagFilter = Boolean(activeTags.length);
  const isAllNotes = !category || category.id === ALL_CATEGORY_ID;
  const title = hasQuery
    ? "No matching notes"
    : hasTagFilter
      ? `No papers tagged ${activeTags.map((tag) => `#${tag}`).join(" ")}`
    : isAllNotes
      ? "Start your paper library"
      : `No notes in ${label}`;
  const body = hasQuery
    ? "Try another search, or clear the filter to see everything in this collection."
    : hasTagFilter
      ? "Pick another tag or clear this tag search to return to the full library."
    : isAllNotes
      ? "Import a PDF or paste a paper link. Once it lands here, you can read, annotate, and ask questions beside the paper."
      : "Bring a paper into this collection now, or move notes here later from their details panel.";

  return `
    <div class="library-empty-card">
      <div class="library-empty-art" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <div class="library-empty-copy">
        <p class="library-empty-kicker">${hasQuery ? "Search" : "Library"}</p>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(body)}</p>
      </div>
      ${hasQuery ? "" : `
        <div class="library-empty-actions">
          <button class="toolbar-button" type="button" data-empty-import-action="local">${renderIcon("file-text", "", "", 16)}<span>Import PDF</span></button>
          <button class="toolbar-button" type="button" data-empty-import-action="url">${renderIcon("external-link", "", "", 16)}<span>Paste link</span></button>
        </div>
      `}
    </div>
  `;
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
    const noteTitle = escapeHtml(note.title);
    const noteId = escapeHtml(note.id);
    const readerHref = escapeHtml(getReaderHref(note));
    const venue = normalizeText(note.venue);
    return `
      <article class="note-card${note.id === state.selectedNoteId ? " is-selected" : ""}" data-note-id="${noteId}" draggable="true">
        <div class="note-card-icon" aria-hidden="true">${renderIcon("file-text", "", "", 20)}</div>
        <div class="note-card-main">
          <div class="meta note-card-meta">
            <span>${renderIcon("calendar", "", "", 13)}${escapeHtml(note.date || "No date")}</span>
            <span>${renderIcon("folder", "", "", 13)}${escapeHtml(detailLabel)}</span>
            ${venue ? `<span>${escapeHtml(venue)}</span>` : ""}
          </div>
          <h3>${noteTitle}</h3>
          ${renderNoteCardTags(note)}
        </div>
        <span class="note-card-actions-inline" aria-label="Paper actions">
          <a class="note-open note-open-primary" href="${readerHref}" aria-label="Open ${noteTitle}" title="Open">${renderIcon("book-open", "", "", 16)}<span class="note-action-label">Open</span></a>
          <button class="note-open" type="button" data-rename-note-id="${noteId}" aria-label="Rename ${noteTitle}" title="Rename">${renderIcon("edit-3", "", "", 16)}<span class="note-action-label">Rename</span></button>
          <button class="note-open note-open-danger" type="button" data-delete-note-id="${noteId}" aria-label="Delete ${noteTitle}" title="Delete">${renderIcon("trash-2", "", "", 16)}<span class="note-action-label">Delete</span></button>
        </span>
      </article>
    `;
  }).join("");
}

function renderNoteCardTags(note) {
  const tags = Array.isArray(note?.tags) ? note.tags.filter(Boolean) : [];
  if (!tags.length) return "";
  return `
    <div class="note-card-tags" aria-label="Tags">
      ${tags.map((tag) => `<span class="note-card-tag">${renderIcon("tag", "", "", 12)}${escapeHtml(tag)}</span>`).join("")}
    </div>
  `;
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
  const noteTitle = escapeHtml(note.title);
  elements.detailsPanel.hidden = false;
  elements.rightResizer.hidden = false;
  elements.detailsCard.innerHTML = `
    <div>
      <div class="content-kicker">Paper</div>
      <h3>${noteTitle}</h3>
      <div class="details-meta">
        <span>${renderIcon("calendar", "", "", 13)}${escapeHtml(note.date || "No date")}</span>
        ${note.venue ? `<span>${escapeHtml(note.venue)}</span>` : ""}
      </div>
      <div class="note-card-actions">
        <a class="toolbar-button toolbar-button-primary" href="${escapeHtml(getReaderHref(note))}">${renderIcon("book-open", "", "", 16)}<span>Open Note</span></a>
        ${note.href ? `<a class="toolbar-button" href="${escapeHtml(note.href)}" target="_blank" rel="noopener">${renderIcon("file-text", "", "", 16)}<span>Open PDF</span></a>` : ""}
        ${note.htmlHref ? `<a class="toolbar-button" href="${escapeHtml(note.htmlHref)}" target="_blank" rel="noopener">${renderIcon("external-link", "", "", 16)}<span>Open HTML</span></a>` : ""}
      </div>
    </div>
    <div class="details-row details-tags-row">
      <div class="details-row-heading">
        <strong>${renderIcon("tags", "", "", 15)}<span>Tags</span></strong>
        <button class="details-tag-add" type="button" data-open-tag-dialog="${escapeHtml(note.id)}">${renderIcon("plus", "", "", 14)}<span>Add</span></button>
      </div>
      ${tags.length ? `
        <div class="details-tags" aria-label="Paper tags">
          ${tags.map((tag) => `
            <span class="details-tag${getActiveTagFilters().includes(tag) ? " is-filter-active" : ""}">
              <button
                class="details-tag-filter"
                type="button"
                data-filter-tag="${escapeHtml(tag)}"
                aria-label="Show papers tagged ${escapeHtml(tag)}"
                title="Show papers with this tag"
              >${escapeHtml(tag)}</button>
              <button
                class="details-tag-remove"
                type="button"
                data-remove-tag-note="${escapeHtml(note.id)}"
                data-remove-tag="${escapeHtml(tag)}"
                aria-label="Remove ${escapeHtml(tag)} tag"
                title="Remove tag"
              >${renderIcon("x", "", "", 12)}</button>
            </span>
          `).join("")}
        </div>
      ` : `<p class="details-tags-empty">No tags yet</p>`}
    </div>
    <div class="details-row">
      <strong>${renderIcon("sticky-note", "", "", 15)}<span>Summary</span></strong>
      <textarea class="details-summary-input" data-summary-note-id="${note.id}" rows="6" placeholder="Write a short summary...">${escapeHtml(note.summary)}</textarea>
    </div>
    <div class="details-row">
      <strong>${renderIcon("folder", "", "", 15)}<span>Collection</span></strong>
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

function openConfirmDialog({ eyebrow = "Confirm", title, body, action, actionLabel = "Delete", danger = true }) {
  state.confirmAction = action;
  elements.confirmDialogEyebrow.textContent = eyebrow;
  elements.confirmDialogTitle.textContent = title;
  elements.confirmDialogBody.textContent = body;
  elements.confirmDialogAction.textContent = actionLabel;
  elements.confirmDialogAction.classList.toggle("toolbar-button-danger", danger);
  elements.confirmDialogAction.classList.toggle("toolbar-button-primary", !danger);
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
