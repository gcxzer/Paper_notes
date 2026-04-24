const STORAGE_KEY = "paper-notes-library-v13";
const EXPANDED_KEY = "paper-notes-expanded-v1";
const LAYOUT_KEY = "paper-notes-layout-v1";
const SORT_KEY = "paper-notes-sort-v1";
const FILE_DB_NAME = "paper-notes-files-v1";
const FILE_STORE_NAME = "paper-files";
const ALL_CATEGORY_ID = "all";
const UNCATEGORIZED_ID = "uncategorized";
const LEGACY_STORAGE_KEYS = ["paper-notes-library-v5", "paper-notes-library-v6", "paper-notes-library-v7", "paper-notes-library-v8", "paper-notes-library-v9", "paper-notes-library-v10", "paper-notes-library-v11", "paper-notes-library-v12"];

LEGACY_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));

const DEFAULT_LIBRARY = {
  categories: [
    { id: ALL_CATEGORY_ID, name: "All Notes", parentId: null, order: 0, system: true },
    { id: UNCATEGORIZED_ID, name: "Uncategorized", parentId: null, order: 1, system: true }
  ],
  notes: []
};

const state = {
  library: null,
  activeCategoryId: ALL_CATEGORY_ID,
  selectedNoteId: null,
  query: "",
  pendingCategoryId: null,
  pendingParentId: null,
  pendingRenameNoteId: null,
  confirmAction: null,
  contextCategoryId: null,
  draggedCategoryId: null,
  dragTarget: null,
  pdfObjectUrls: new Map(),
  sortMode: localStorage.getItem(SORT_KEY) || "date-desc",
  expandedCategoryIds: new Set(),
  panelWidths: {
    sidebar: 320,
    details: 320
  },
  dataSource: "default"
};

const summarySaveTimers = new Map();

const elements = {
  body: document.body,
  sidebarSection: document.querySelector("#sidebarSection"),
  categoryList: document.querySelector("#categoryList"),
  notesGrid: document.querySelector("#notesGrid"),
  libraryStatus: document.querySelector("#libraryStatus"),
  searchInput: document.querySelector("#searchInput"),
  emptyState: document.querySelector("#emptyState"),
  newCategoryButton: document.querySelector("#newCategoryButton"),
  detailsPanel: document.querySelector("#detailsPanel"),
  detailsCard: document.querySelector("#detailsCard"),
  leftResizer: document.querySelector("#leftResizer"),
  rightResizer: document.querySelector("#rightResizer"),
  contentTitle: document.querySelector("#contentTitle"),
  contentKicker: document.querySelector("#contentKicker"),
  addPdfButton: document.querySelector("#addPdfButton"),
  pdfInput: document.querySelector("#pdfInput"),
  sortButton: document.querySelector("#sortButton"),
  sortMenu: document.querySelector("#sortMenu"),
  contextMenu: document.querySelector("#contextMenu"),
  categoryDialog: document.querySelector("#categoryDialog"),
  categoryForm: document.querySelector("#categoryForm"),
  categoryDialogEyebrow: document.querySelector("#categoryDialogEyebrow"),
  categoryDialogTitle: document.querySelector("#categoryDialogTitle"),
  categoryNameInput: document.querySelector("#categoryNameInput"),
  categoryDialogError: document.querySelector("#categoryDialogError"),
  closeCategoryDialog: document.querySelector("#closeCategoryDialog"),
  cancelCategoryDialog: document.querySelector("#cancelCategoryDialog"),
  confirmDialog: document.querySelector("#confirmDialog"),
  confirmDialogTitle: document.querySelector("#confirmDialogTitle"),
  confirmDialogBody: document.querySelector("#confirmDialogBody"),
  confirmDialogAction: document.querySelector("#confirmDialogAction"),
  closeConfirmDialog: document.querySelector("#closeConfirmDialog"),
  cancelConfirmDialog: document.querySelector("#cancelConfirmDialog"),
  renameNoteDialog: document.querySelector("#renameNoteDialog"),
  renameNoteForm: document.querySelector("#renameNoteForm"),
  renameNoteInput: document.querySelector("#renameNoteInput"),
  renameNoteError: document.querySelector("#renameNoteError"),
  closeRenameNoteDialog: document.querySelector("#closeRenameNoteDialog"),
  cancelRenameNoteDialog: document.querySelector("#cancelRenameNoteDialog"),
  messageDialog: document.querySelector("#messageDialog"),
  messageDialogEyebrow: document.querySelector("#messageDialogEyebrow"),
  messageDialogTitle: document.querySelector("#messageDialogTitle"),
  messageDialogBody: document.querySelector("#messageDialogBody"),
  messageDialogAction: document.querySelector("#messageDialogAction"),
  closeMessageDialog: document.querySelector("#closeMessageDialog")
};

function cloneLibrary(library) {
  return JSON.parse(JSON.stringify(library));
}

function uniqueId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeText(value) {
  return String(value || "").trim();
}

function normalizeTags(value) {
  if (!Array.isArray(value)) return [];
  return value.map((tag) => normalizeText(tag)).filter(Boolean);
}

function readExpandedState() {
  try {
    const raw = localStorage.getItem(EXPANDED_KEY);
    if (!raw) return new Set();
    const values = JSON.parse(raw);
    return new Set(Array.isArray(values) ? values : []);
  } catch (error) {
    console.warn("Failed to read expanded state.", error);
    return new Set();
  }
}

function saveExpandedState() {
  localStorage.setItem(EXPANDED_KEY, JSON.stringify([...state.expandedCategoryIds]));
}

function readLayoutState() {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return { sidebar: 320, details: 320 };
    const parsed = JSON.parse(raw);
    return {
      sidebar: Number(parsed.sidebar) || 320,
      details: Number(parsed.details) || 320
    };
  } catch (error) {
    console.warn("Failed to read layout state.", error);
    return { sidebar: 320, details: 320 };
  }
}

function saveLayoutState() {
  localStorage.setItem(LAYOUT_KEY, JSON.stringify(state.panelWidths));
}

function sanitizeLibrary(rawLibrary) {
  const raw = rawLibrary && typeof rawLibrary === "object" ? rawLibrary : {};
  const rawCategories = Array.isArray(raw.categories) ? raw.categories : [];
  const categoryMap = new Map();

  rawCategories.forEach((category, index) => {
    const id = normalizeText(category.id) || uniqueId("category");
    if (categoryMap.has(id)) return;
    categoryMap.set(id, {
      id,
      name: normalizeText(category.name) || "Untitled",
      parentId: normalizeText(category.parentId) || null,
      order: Number.isFinite(category.order) ? Number(category.order) : index,
      system: Boolean(category.system)
    });
  });

  categoryMap.set(ALL_CATEGORY_ID, {
    id: ALL_CATEGORY_ID,
    name: "All Notes",
    parentId: null,
    order: 0,
    system: true
  });
  categoryMap.set(UNCATEGORIZED_ID, {
    id: UNCATEGORIZED_ID,
    name: "Uncategorized",
    parentId: null,
    order: 1,
    system: true
  });

  const categories = Array.from(categoryMap.values()).map((category) => {
    if (category.id === ALL_CATEGORY_ID) return { ...category, parentId: null, order: 0 };
    if (category.id === UNCATEGORIZED_ID) return { ...category, parentId: null, order: 1 };
    return category;
  });

  const validIds = new Set(categories.map((category) => category.id));
  categories.forEach((category) => {
    if (category.parentId && !validIds.has(category.parentId)) category.parentId = null;
    if (category.parentId === ALL_CATEGORY_ID || category.parentId === UNCATEGORIZED_ID) category.parentId = null;
  });

  const topLevelIds = new Set(categories.filter((category) => category.parentId === null).map((category) => category.id));
  categories.forEach((category) => {
    if (category.parentId && !topLevelIds.has(category.parentId)) category.parentId = null;
  });

  const childMap = new Map();
  categories.forEach((category) => {
    const key = category.parentId || "root";
    if (!childMap.has(key)) childMap.set(key, []);
    childMap.get(key).push(category);
  });

  childMap.forEach((group) => {
    group.sort((left, right) => left.order - right.order || left.name.localeCompare(right.name));
    group.forEach((category, index) => {
      if (category.parentId === null) {
        if (category.id === ALL_CATEGORY_ID) category.order = 0;
        else if (category.id === UNCATEGORIZED_ID) category.order = 1;
        else category.order = Math.max(index, 2);
      } else {
        category.order = index;
      }
    });
  });

  const parentIdsWithChildren = new Set(categories.filter((category) => category.parentId).map((category) => category.parentId));
  const leafIds = new Set(categories.filter((category) => !parentIdsWithChildren.has(category.id)).map((category) => category.id));
  const rawNotes = Array.isArray(raw.notes) ? raw.notes : [];
  const notes = rawNotes.map((note, index) => {
    const requestedCategoryId = normalizeText(note.categoryId);
    return {
      id: normalizeText(note.id) || uniqueId(`note-${index + 1}`),
      title: normalizeText(note.title) || "Untitled Note",
      href: normalizeText(note.href) || "index.html",
      htmlHref: normalizeText(note.htmlHref),
      pdfStorageKey: normalizeText(note.pdfStorageKey),
      date: normalizeText(note.date) || "",
      order: Number.isFinite(Number(note.order)) ? Number(note.order) : index,
      categoryId: leafIds.has(requestedCategoryId) ? requestedCategoryId : UNCATEGORIZED_ID,
      venue: normalizeText(note.venue),
      summary: normalizeText(note.summary),
      tags: normalizeTags(note.tags)
    };
  });

  return { categories, notes };
}

function saveLibraryToStorage() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.library));
}

function readLibraryFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return sanitizeLibrary(JSON.parse(raw));
  } catch (error) {
    console.warn("Failed to read local library cache.", error);
    return null;
  }
}

async function fetchDefaultLibrary() {
  const baseUrl = window.location.protocol === "file:" ? "http://localhost:4173/" : "";
  const response = await fetch(`${baseUrl}notes.json?t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Unable to load notes.json (${response.status})`);
  return sanitizeLibrary(await response.json());
}

function openFileDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(FILE_DB_NAME, 1);

    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(FILE_STORE_NAME)) {
        database.createObjectStore(FILE_STORE_NAME, { keyPath: "id" });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function writePaperFile(record) {
  const database = await openFileDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(FILE_STORE_NAME, "readwrite");
    transaction.objectStore(FILE_STORE_NAME).put(record);
    transaction.oncomplete = () => {
      database.close();
      resolve();
    };
    transaction.onerror = () => {
      database.close();
      reject(transaction.error);
    };
  });
}

function getCategoryById(categoryId) {
  return state.library.categories.find((category) => category.id === categoryId) || null;
}

function getNoteById(noteId) {
  return state.library.notes.find((note) => note.id === noteId) || null;
}

function getChildren(parentId = null) {
  return state.library.categories
    .filter((category) => (category.parentId || null) === parentId)
    .sort((left, right) => left.order - right.order || left.name.localeCompare(right.name));
}

function hasChildren(categoryId) {
  return state.library.categories.some((category) => category.parentId === categoryId);
}

function isLeafCategory(categoryId) {
  return categoryId !== ALL_CATEGORY_ID && !hasChildren(categoryId);
}

function isCustomCategory(categoryId) {
  const category = getCategoryById(categoryId);
  return Boolean(category && !category.system);
}

function isTopLevel(categoryId) {
  const category = getCategoryById(categoryId);
  return Boolean(category && category.parentId === null);
}

function getTopLevelParent(categoryId) {
  const category = getCategoryById(categoryId);
  if (!category) return null;
  if (!category.parentId) return category;
  return getCategoryById(category.parentId);
}

function getAssignableCategories() {
  return state.library.categories
    .filter((category) => isLeafCategory(category.id))
    .sort((left, right) => left.name.localeCompare(right.name));
}

function getLeafDescendants(categoryId) {
  if (categoryId === ALL_CATEGORY_ID) return getAssignableCategories();
  if (isLeafCategory(categoryId)) return [getCategoryById(categoryId)].filter(Boolean);
  return state.library.categories.filter((category) => category.parentId === categoryId && isLeafCategory(category.id));
}

function getCategoryCount(categoryId) {
  if (categoryId === ALL_CATEGORY_ID) return state.library.notes.length;
  const validIds = new Set(getLeafDescendants(categoryId).map((category) => category.id));
  return state.library.notes.filter((note) => validIds.has(note.categoryId)).length;
}

function getVisibleNotes() {
  const query = state.query.toLowerCase();
  const visibleCategoryIds = new Set(getLeafDescendants(state.activeCategoryId).map((category) => category.id));
  const notes = state.library.notes.filter((note) => {
    if (!visibleCategoryIds.has(note.categoryId)) return false;
    const haystack = [note.title, note.date, note.summary, ...note.tags].join(" ").toLowerCase();
    return haystack.includes(query);
  });
  return sortNotes(notes);
}

function sortNotes(notes) {
  return [...notes].sort((left, right) => {
    const leftOrder = Number.isFinite(Number(left.order)) ? Number(left.order) : state.library.notes.indexOf(left);
    const rightOrder = Number.isFinite(Number(right.order)) ? Number(right.order) : state.library.notes.indexOf(right);
    if (state.sortMode === "date-asc") {
      return (left.date || "").localeCompare(right.date || "") || leftOrder - rightOrder || left.title.localeCompare(right.title);
    }
    if (state.sortMode === "title-asc") {
      return left.title.localeCompare(right.title) || (right.date || "").localeCompare(left.date || "");
    }
    return (right.date || "").localeCompare(left.date || "") || leftOrder - rightOrder || left.title.localeCompare(right.title);
  });
}

function getSortLabel() {
  if (state.sortMode === "date-asc") return "Oldest";
  if (state.sortMode === "title-asc") return "Title";
  return "Newest";
}

function getTodayLabel() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function getPdfTitle(file) {
  return file.name.replace(/\.pdf$/i, "").replace(/[-_]+/g, " ").trim() || "Untitled PDF";
}

function slugifyFileName(value) {
  const slug = normalizeText(value)
    .replace(/[\\/:*?"<>|#%{}^~[\]`]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return slug || "Untitled Paper";
}

function getPaperHref(file) {
  return `Papers/${encodeURIComponent(file.name)}`;
}

function getPaperHtmlHref(title) {
  return `Paper-html/${encodeURIComponent(`${slugifyFileName(title)}.html`)}`;
}

function getApiUrl(path) {
  return window.location.protocol === "file:"
    ? `http://localhost:4173${path}`
    : path;
}

function resolveNoteHref(note) {
  return state.pdfObjectUrls.get(note.id) || note.href;
}

function getReaderHref(note) {
  return `reader.html?id=${encodeURIComponent(note.id)}`;
}

function getDefaultImportCategoryId() {
  if (isLeafCategory(state.activeCategoryId)) return state.activeCategoryId;
  const leaves = getLeafDescendants(state.activeCategoryId);
  return leaves[0]?.id || UNCATEGORIZED_ID;
}

function getSelectedCategory() {
  return getCategoryById(state.activeCategoryId) || getCategoryById(ALL_CATEGORY_ID);
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function createPaperNoteHtml({ title, date, fileName }) {
  const safeTitle = escapeHtml(title);
  const safeDate = escapeHtml(date);
  const safeFileName = escapeHtml(fileName);

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${safeTitle}</title>
  <script src="../assets/theme.js"></script>
  <link rel="stylesheet" href="../assets/note.css">
</head>
<body>
  <main class="note">
    <header class="note-section">
      <p class="eyebrow note-eyebrow">Paper Note</p>
      <h1>${safeTitle}</h1>
      <p class="meta note-meta">${safeDate} · ${safeFileName}</p>
    </header>

    <div class="note-workspace">
      <aside class="note-menu" aria-label="Note sections">
        <nav data-note-menu></nav>
      </aside>

      <section class="note-body"></section>
    </div>
  </main>
  <script src="../assets/note.js"></script>
</body>
</html>`;
}

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

async function saveNoteSummaryToServer(noteId, summary) {
  const response = await fetch(getApiUrl("/api/update-note-summary"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: noteId, summary })
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Summary save failed (${response.status})`);
  }
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
      console.warn("Could not sync summary to notes.json.", error);
    });
  }, 400));
}

async function renameNote(noteId, nextTitle) {
  const note = getNoteById(noteId);
  if (!note) return;

  const cleanTitle = normalizeText(nextTitle);
  if (!cleanTitle || cleanTitle === note.title) return;

  const response = await fetch(getApiUrl("/api/rename-note"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: note.id, title: cleanTitle })
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Rename failed (${response.status})`);
  }

  const updatedNote = await response.json();
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
  const response = await fetch(getApiUrl("/api/import-pdf"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      fileName: file.name,
      mimeType: file.type || "application/pdf",
      dataBase64: await readFileAsBase64(file),
      categoryId
    })
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Import failed (${response.status})`);
  }

  return response.json();
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

function closeContextMenu() {
  state.contextCategoryId = null;
  elements.contextMenu.hidden = true;
  elements.contextMenu.innerHTML = "";
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
  if (!node) return null;
  const categoryId = node.dataset.treeNodeId;
  const category = getCategoryById(categoryId);
  if (!category || category.system || category.id === state.draggedCategoryId) return null;

  const rect = node.getBoundingClientRect();
  const offset = event.clientY - rect.top;
  const topZone = rect.height * 0.25;
  const bottomZone = rect.height * 0.75;

  if (offset < topZone) return { type: "before", categoryId };
  if (offset > bottomZone) return { type: "after", categoryId };
  if (category.parentId === null) return { type: "nest", categoryId };
  return { type: "after", categoryId };
}

function applyDropTarget(draggedId, target) {
  if (!draggedId || !target) return;
  const dragged = getCategoryById(draggedId);
  const targetCategory = getCategoryById(target.categoryId);
  if (!dragged || !targetCategory || dragged.system) return;

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
});

elements.categoryList.addEventListener("dragover", (event) => {
  if (!state.draggedCategoryId) return;
  const target = getDropTargetFromEvent(event);
  if (!target) return;
  event.preventDefault();
  state.dragTarget = target;
  renderCategories();
});

elements.categoryList.addEventListener("drop", (event) => {
  if (!state.draggedCategoryId) return;
  event.preventDefault();
  if (state.dragTarget) applyDropTarget(state.draggedCategoryId, state.dragTarget);
  state.draggedCategoryId = null;
  state.dragTarget = null;
  renderApp();
});

elements.categoryList.addEventListener("dragend", () => {
  state.draggedCategoryId = null;
  state.dragTarget = null;
  renderCategories();
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
  if (!event.target.closest(".sort-control")) {
    elements.sortMenu.hidden = true;
    elements.sortButton.setAttribute("aria-expanded", "false");
  }
});

elements.searchInput.addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  syncSelectedNote();
  renderStatus();
  renderNotes();
  renderDetails();
});

elements.newCategoryButton.addEventListener("click", () => {
  openCategoryDialog("create");
});

elements.addPdfButton.addEventListener("click", () => {
  elements.pdfInput.click();
});

elements.pdfInput.addEventListener("change", async (event) => {
  try {
    await importPdfFiles(event.target.files);
  } catch (error) {
    showMessageDialog({
      eyebrow: "Import PDF",
      title: "Could not import this PDF",
      body: "Please start the local server with npm start, then open http://localhost:4173."
    });
    console.error(error);
  }
  elements.pdfInput.value = "";
});

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
elements.notesGrid.addEventListener("click", (event) => {
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
elements.closeMessageDialog.addEventListener("click", closeMessageDialog);
elements.messageDialogAction.addEventListener("click", closeMessageDialog);

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
