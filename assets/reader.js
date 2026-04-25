const pdfjsLib = globalThis.pdfjsLib;

if (pdfjsLib) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "node_modules/pdfjs-dist/build/pdf.worker.js";
}

const STORAGE_KEY = "paper-notes-library-v14";
const FILE_DB_NAME = "paper-notes-files-v1";
const FILE_STORE_NAME = "paper-files";
const READER_SPLIT_KEY = "paper-notes-reader-split-v1";
const ANNOTATION_SIDEBAR_KEY = "paper-notes-annotation-sidebar-v1";
const HTML_PANE_KEY = "paper-notes-html-pane-v1";
const HTML_ZOOM_KEY = "paper-notes-html-zoom-v1";
const ALL_CATEGORY_ID = "all";
const UNCATEGORIZED_ID = "uncategorized";

const elements = {
  layout: document.querySelector("#readerLayout"),
  error: document.querySelector("#readerError"),
  title: document.querySelector("#readerTitle"),
  kicker: document.querySelector("#readerKicker"),
  pdfViewer: document.querySelector("#pdfViewer"),
  notePane: document.querySelector(".note-pane"),
  notePage: document.querySelector("#notePage"),
  resizer: document.querySelector("#readerResizer"),
  annotationStatus: document.querySelector("#annotationStatus"),
  annotationList: document.querySelector("#annotationList"),
  annotationCount: document.querySelector("#annotationCount"),
  annotationSidebarToolbarToggle: document.querySelector("#annotationSidebarToolbarToggle"),
  annotationSidebarToggle: document.querySelector("#annotationSidebarToggle"),
  pdfBody: document.querySelector(".pdf-body"),
  htmlPaneToggle: document.querySelector("#htmlPaneToggle"),
  htmlZoomIn: document.querySelector("#htmlZoomIn"),
  htmlZoomOut: document.querySelector("#htmlZoomOut"),
  htmlZoomLabel: document.querySelector("#htmlZoomLabel"),
  zoomIn: document.querySelector("#zoomIn"),
  zoomOut: document.querySelector("#zoomOut"),
  zoomLabel: document.querySelector("#zoomLabel"),
  modeButtons: Array.from(document.querySelectorAll("[data-pdf-mode]")),
  colorButtons: Array.from(document.querySelectorAll("[data-pdf-color]"))
};

const splitState = {
  dragging: false,
  minPdfWidth: 280,
  minNoteWidth: 360
};

const pdfState = {
  document: null,
  noteId: "",
  url: "",
  mode: "pan",
  color: "yellow",
  scale: 2.15,
  renderToken: 0,
  annotations: [],
  saveTimer: 0,
  openEditor: null,
  selectedAnnotationId: ""
};

const PDF_ANNOTATION_TYPES = new Set(["highlight", "underline", "area", "note"]);
const PDF_COLORS = {
  yellow: { label: "Yellow", hex: "#f2c94c", rgb: "242, 201, 76" },
  green: { label: "Green", hex: "#70c787", rgb: "112, 199, 135" },
  blue: { label: "Blue", hex: "#6aa9ff", rgb: "106, 169, 255" },
  red: { label: "Red", hex: "#ff7a7a", rgb: "255, 122, 122" },
  purple: { label: "Purple", hex: "#b996ff", rgb: "185, 150, 255" }
};

function normalizeText(value) {
  return String(value || "").trim();
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function sanitizeLibrary(rawLibrary) {
  const raw = rawLibrary && typeof rawLibrary === "object" ? rawLibrary : {};
  const categories = Array.isArray(raw.categories) ? raw.categories.map((category, index) => ({
    id: normalizeText(category.id),
    name: normalizeText(category.name) || "Untitled",
    parentId: normalizeText(category.parentId) || null,
    order: Number.isFinite(category.order) ? Number(category.order) : index,
    system: Boolean(category.system)
  })).filter((category) => category.id) : [];

  const notes = Array.isArray(raw.notes) ? raw.notes.map((note) => ({
    id: normalizeText(note.id),
    title: normalizeText(note.title) || "Untitled Paper",
    href: normalizeText(note.href),
    htmlHref: normalizeText(note.htmlHref),
    pdfStorageKey: normalizeText(note.pdfStorageKey),
    date: normalizeText(note.date),
    categoryId: normalizeText(note.categoryId) || UNCATEGORIZED_ID,
    summary: normalizeText(note.summary)
  })).filter((note) => note.id) : [];

  return { categories, notes };
}

function readLibraryFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return sanitizeLibrary(JSON.parse(raw));
  } catch (error) {
    console.warn("Failed to read local library.", error);
    return null;
  }
}

async function readDefaultLibrary() {
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

async function readPaperFile(id) {
  if (!id) return null;
  const database = await openFileDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(FILE_STORE_NAME, "readonly");
    const request = transaction.objectStore(FILE_STORE_NAME).get(id);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => database.close();
  });
}

function getCategoryById(library, categoryId) {
  return library.categories.find((category) => category.id === categoryId) || null;
}

function getCollectionPath(library, categoryId) {
  const category = getCategoryById(library, categoryId);
  if (!category) return "Uncategorized";
  if (!category.parentId || category.id === ALL_CATEGORY_ID) return category.name;
  const parent = getCategoryById(library, category.parentId);
  return parent ? `${parent.name} / ${category.name}` : category.name;
}

function showError() {
  elements.layout.hidden = true;
  elements.error.hidden = false;
  elements.title.textContent = "Paper not found";
}

function setAnnotationStatus(text) {
  if (elements.annotationStatus) elements.annotationStatus.textContent = text;
}

function annotationColor(annotation) {
  return PDF_COLORS[annotation.color] || PDF_COLORS.yellow;
}

function applyAnnotationColor(element, annotation) {
  const color = annotationColor(annotation);
  element.style.setProperty("--annotation-color", color.hex);
  element.style.setProperty("--annotation-rgb", color.rgb);
  element.style.setProperty("--annotation-bg", color.hex);
}

function annotationTypeLabel(type) {
  return {
    highlight: "Highlight",
    underline: "Underline",
    area: "Area",
    note: "Note"
  }[type] || "Annotation";
}

function renderAnnotationColorButtons(activeColor) {
  return Object.entries(PDF_COLORS).map(([key, color]) => `
    <button
      class="annotation-editor-color${key === activeColor ? " is-active" : ""}"
      type="button"
      data-editor-color="${key}"
      style="background-color: ${color.hex}; --annotation-color: ${color.hex}; --annotation-rgb: ${color.rgb};"
      aria-label="${color.label}"
    ></button>
  `).join("");
}

function setAnnotationSidebarCollapsed(collapsed) {
  elements.pdfBody?.classList.toggle("is-annotation-sidebar-collapsed", collapsed);
  elements.annotationSidebarToggle?.setAttribute("aria-expanded", String(!collapsed));
  elements.annotationSidebarToolbarToggle?.classList.toggle("is-active", !collapsed);
  elements.annotationSidebarToolbarToggle?.setAttribute("aria-expanded", String(!collapsed));
  localStorage.setItem(ANNOTATION_SIDEBAR_KEY, collapsed ? "collapsed" : "open");
}

function initializeAnnotationSidebar() {
  setAnnotationSidebarCollapsed(localStorage.getItem(ANNOTATION_SIDEBAR_KEY) === "collapsed");
  elements.annotationSidebarToolbarToggle?.addEventListener("click", () => {
    setAnnotationSidebarCollapsed(!elements.pdfBody?.classList.contains("is-annotation-sidebar-collapsed"));
  });
  elements.annotationSidebarToggle?.addEventListener("click", () => setAnnotationSidebarCollapsed(true));
}

function setHtmlPaneVisible(visible) {
  elements.layout?.classList.toggle("is-html-pane-hidden", !visible);
  elements.htmlPaneToggle?.classList.toggle("is-active", visible);
  elements.htmlPaneToggle?.setAttribute("aria-expanded", String(visible));
  localStorage.setItem(HTML_PANE_KEY, visible ? "shown" : "hidden");
}

function initializeHtmlPaneToggle() {
  setHtmlPaneVisible(localStorage.getItem(HTML_PANE_KEY) !== "hidden");
  elements.htmlPaneToggle?.addEventListener("click", () => {
    setHtmlPaneVisible(elements.layout?.classList.contains("is-html-pane-hidden"));
  });
}

function readHtmlZoom() {
  const value = Number(localStorage.getItem(HTML_ZOOM_KEY));
  if (!Number.isFinite(value)) return 1;
  return clamp(value, 0.7, 1.8);
}

function setHtmlZoom(value) {
  const nextZoom = Math.round(clamp(value, 0.7, 1.8) * 10) / 10;
  elements.notePane?.style.setProperty("--html-zoom", String(nextZoom));
  if (elements.htmlZoomLabel) elements.htmlZoomLabel.textContent = `${Math.round(nextZoom * 100)}%`;
  localStorage.setItem(HTML_ZOOM_KEY, String(nextZoom));
}

function initializeHtmlZoom() {
  setHtmlZoom(readHtmlZoom());
  elements.htmlZoomIn?.addEventListener("click", () => setHtmlZoom(readHtmlZoom() + 0.1));
  elements.htmlZoomOut?.addEventListener("click", () => setHtmlZoom(readHtmlZoom() - 0.1));
}

function showPdfError(error) {
  const message = error?.message || "Could not load PDF.";
  if (elements.pdfViewer) {
    elements.pdfViewer.innerHTML = `
      <div class="pdf-loading pdf-error">
        <strong>Could not load PDF.</strong>
        <span>${escapeHtml(message)}</span>
      </div>
    `;
  }
  setAnnotationStatus("PDF failed to load");
}

function setPdfLoading(text) {
  if (!elements.pdfViewer) return;
  elements.pdfViewer.innerHTML = `<div class="pdf-loading">${escapeHtml(text)}</div>`;
}

function showStartupError(message) {
  if (elements.title) elements.title.textContent = "Reader setup needed";
  if (elements.kicker) elements.kicker.textContent = "Paper";
  showPdfError(new Error(message));
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function readSplitPercent() {
  const value = Number(localStorage.getItem(READER_SPLIT_KEY));
  if (!Number.isFinite(value)) return 55;
  return clamp(value, 25, 75);
}

function setSplitPercent(percent) {
  const nextPercent = clamp(percent, 25, 75);
  document.documentElement.style.setProperty("--pdf-pane-width", `${nextPercent}%`);
  localStorage.setItem(READER_SPLIT_KEY, String(nextPercent));
}

function updateSplitFromClientX(clientX) {
  const rect = elements.layout.getBoundingClientRect();
  const maxPdfWidth = rect.width - splitState.minNoteWidth - 10;
  const pdfWidth = clamp(clientX - rect.left, splitState.minPdfWidth, maxPdfWidth);
  setSplitPercent((pdfWidth / rect.width) * 100);
}

function initializeResizer() {
  setSplitPercent(readSplitPercent());
  if (!elements.resizer) return;

  elements.resizer.addEventListener("pointerdown", (event) => {
    if (window.matchMedia("(max-width: 900px)").matches) return;
    splitState.dragging = true;
    elements.resizer.setPointerCapture(event.pointerId);
    document.body.classList.add("is-resizing-reader");
    updateSplitFromClientX(event.clientX);
  });

  elements.resizer.addEventListener("pointermove", (event) => {
    if (!splitState.dragging) return;
    updateSplitFromClientX(event.clientX);
  });

  elements.resizer.addEventListener("pointerup", (event) => {
    splitState.dragging = false;
    elements.resizer.releasePointerCapture(event.pointerId);
    document.body.classList.remove("is-resizing-reader");
  });

  elements.resizer.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -2 : 2;
    setSplitPercent(readSplitPercent() + delta);
  });
}

function setPdfMode(mode) {
  pdfState.mode = mode;
  elements.pdfViewer?.classList.toggle("is-annotating", mode !== "pan");
  elements.pdfViewer?.classList.toggle("is-text-annotating", ["highlight", "underline"].includes(mode));
  elements.pdfViewer?.classList.toggle("is-note-annotating", mode === "note");
  elements.modeButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.pdfMode === mode);
  });
}

function setPdfColor(color) {
  pdfState.color = PDF_COLORS[color] ? color : "yellow";
  elements.colorButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.pdfColor === pdfState.color);
  });
}

function normalizeAnnotation(annotation) {
  const rawType = normalizeText(annotation.type);
  const type = PDF_ANNOTATION_TYPES.has(rawType) ? rawType : "highlight";
  const comment = normalizeText(annotation.comment);
  const quote = normalizeText(annotation.quote);
  const rects = normalizeAnnotationRects(annotation);
  const bounds = rects.length ? annotationBounds(rects) : {
    x: Number(annotation.x) || 0,
    y: Number(annotation.y) || 0,
    w: Number(annotation.w) || 0,
    h: Number(annotation.h) || 0
  };
  return {
    id: normalizeText(annotation.id) || `annotation-${Date.now().toString(36)}`,
    type,
    page: Number(annotation.page) || 1,
    x: bounds.x,
    y: bounds.y,
    w: bounds.w,
    h: bounds.h,
    rects,
    color: PDF_COLORS[annotation.color] ? annotation.color : "yellow",
    text: comment,
    comment,
    quote,
    createdAt: normalizeText(annotation.createdAt) || new Date().toISOString()
  };
}

function normalizeAnnotationRect(rect) {
  const x = clamp(Number(rect?.x) || 0, 0, 1);
  const y = clamp(Number(rect?.y) || 0, 0, 1);
  const w = clamp(Number(rect?.w) || 0, 0, 1 - x);
  const h = clamp(Number(rect?.h) || 0, 0, 1 - y);
  return { x, y, w, h };
}

function normalizeAnnotationRects(annotation) {
  const rawRects = Array.isArray(annotation.rects) ? annotation.rects : [];
  const rects = rawRects.map(normalizeAnnotationRect)
    .filter((rect) => rect.w >= 0.001 && rect.h >= 0.001);
  if (rects.length) return rects;
  const fallback = normalizeAnnotationRect(annotation);
  return fallback.w >= 0.001 && fallback.h >= 0.001 ? [fallback] : [];
}

function annotationBounds(rects) {
  const left = Math.min(...rects.map((rect) => rect.x));
  const top = Math.min(...rects.map((rect) => rect.y));
  const right = Math.max(...rects.map((rect) => rect.x + rect.w));
  const bottom = Math.max(...rects.map((rect) => rect.y + rect.h));
  return {
    x: left,
    y: top,
    w: right - left,
    h: bottom - top
  };
}

async function readAnnotations(noteId) {
  if (!noteId || window.location.protocol === "file:") return [];
  try {
    const response = await fetch(`/api/annotations?noteId=${encodeURIComponent(noteId)}&t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) return [];
    const body = await response.json();
    return Array.isArray(body.annotations) ? body.annotations.map(normalizeAnnotation) : [];
  } catch (error) {
    console.warn("Failed to read annotations.", error);
    return [];
  }
}

function scheduleSaveAnnotations() {
  window.clearTimeout(pdfState.saveTimer);
  setAnnotationStatus("Saving annotations...");
  renderAnnotationList();
  pdfState.saveTimer = window.setTimeout(saveAnnotations, 300);
}

async function saveAnnotations() {
  if (!pdfState.noteId || window.location.protocol === "file:") {
    setAnnotationStatus("Run the local server to save annotations");
    return;
  }
  try {
    const response = await fetch("/api/annotations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        noteId: pdfState.noteId,
        annotations: pdfState.annotations
      })
    });
    if (!response.ok) throw new Error(`Save failed (${response.status})`);
    setAnnotationStatus("Annotations saved");
    renderAnnotationList();
  } catch (error) {
    console.warn("Failed to save annotations.", error);
    setAnnotationStatus("Could not save annotations");
  }
}

function annotationSummary(annotation) {
  const comment = normalizeText(annotation.comment);
  if (comment) return comment;
  const quote = normalizeText(annotation.quote);
  if (quote) return quote;
  if (annotation.type === "note") return "Empty note";
  return `${annotationTypeLabel(annotation.type)} on page ${annotation.page}`;
}

function renderAnnotationList() {
  if (!elements.annotationList) return;
  const sorted = [...pdfState.annotations].sort((a, b) => a.page - b.page || a.y - b.y || a.x - b.x);
  if (elements.annotationCount) elements.annotationCount.textContent = String(sorted.length);
  if (!sorted.length) {
    elements.annotationList.innerHTML = `
      <div class="annotation-empty">
        <strong>No annotations yet</strong>
        <span>Use Highlight, Underline, or Note on the PDF.</span>
      </div>
    `;
    return;
  }
  elements.annotationList.innerHTML = "";
  sorted.forEach((annotation) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "annotation-card";
    card.dataset.annotationId = annotation.id;
    card.classList.toggle("is-selected", annotation.id === pdfState.selectedAnnotationId);
    applyAnnotationColor(card, annotation);
    card.innerHTML = `
      <span class="annotation-card-strip" aria-hidden="true"></span>
      <span class="annotation-card-main">
        <span class="annotation-card-meta">${annotationTypeLabel(annotation.type)} · Page ${annotation.page}</span>
        <span class="annotation-card-text">${escapeHtml(annotationSummary(annotation))}</span>
      </span>
    `;
    card.addEventListener("click", () => jumpToAnnotation(annotation.id));
    elements.annotationList.appendChild(card);
  });
}

function pageViewportBox(pageElement) {
  return pageElement.querySelector(".pdf-page-canvas").getBoundingClientRect();
}

function rectStyle(rect, box) {
  return {
    left: `${rect.x * box.width}px`,
    top: `${rect.y * box.height}px`,
    width: `${rect.w * box.width}px`,
    height: `${rect.h * box.height}px`
  };
}

function applyRectStyle(element, rect, box) {
  const style = rectStyle(rect, box);
  element.style.left = style.left;
  element.style.top = style.top;
  element.style.width = style.width;
  element.style.height = style.height;
}

function renderAnnotationsForPage(pageElement) {
  const page = Number(pageElement.dataset.page);
  const overlay = pageElement.querySelector(".pdf-annotation-layer");
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!overlay || !canvas) return;

  const box = { width: canvas.clientWidth, height: canvas.clientHeight };
  overlay.innerHTML = "";
  pdfState.annotations.filter((annotation) => annotation.page === page).forEach((annotation) => {
    const rects = annotation.rects?.length ? annotation.rects : [annotation];
    rects.forEach((rect) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = `pdf-annotation pdf-annotation-${annotation.type}`;
      item.classList.toggle("is-selected", annotation.id === pdfState.selectedAnnotationId);
      applyRectStyle(item, rect, box);
      applyAnnotationColor(item, annotation);
      item.dataset.annotationId = annotation.id;
      item.title = annotationSummary(annotation);
      item.setAttribute("aria-label", item.title);
      item.addEventListener("pointerdown", (event) => {
        event.stopPropagation();
      });
      item.addEventListener("click", (event) => {
        event.stopPropagation();
        openAnnotationEditor(annotation, pageElement);
      });
      overlay.appendChild(item);
    });
  });
}

function closeNoteEditor() {
  pdfState.openEditor?.remove();
  pdfState.openEditor = null;
}

function openAnnotationEditor(annotation, pageElement) {
  closeNoteEditor();
  pdfState.selectedAnnotationId = annotation.id;
  renderAnnotationList();
  const overlay = pageElement.querySelector(".pdf-annotation-layer");
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!overlay || !canvas) return;

  const box = { width: canvas.clientWidth, height: canvas.clientHeight };
  const editor = document.createElement("form");
  editor.className = "pdf-annotation-editor";
  applyAnnotationColor(editor, annotation);
  editor.style.left = `${clamp((annotation.x + annotation.w) * box.width + 10, 10, box.width - 270)}px`;
  editor.style.top = `${clamp(annotation.y * box.height, 10, box.height - 190)}px`;
  editor.innerHTML = `
    <div class="pdf-annotation-editor-title">
      <span>${annotationTypeLabel(annotation.type)}</span>
      <small>Page ${annotation.page}</small>
    </div>
    <div class="annotation-editor-colors" aria-label="Annotation color">
      ${renderAnnotationColorButtons(annotation.color)}
    </div>
    <textarea aria-label="Annotation comment" placeholder="Add a comment...">${escapeHtml(annotation.comment || "")}</textarea>
    <div class="pdf-annotation-editor-actions">
      <button type="button" data-annotation-delete>Delete</button>
      <button type="submit">Save</button>
    </div>
  `;
  editor.addEventListener("pointerdown", (event) => event.stopPropagation());
  editor.querySelectorAll("[data-editor-color]").forEach((button) => {
    button.addEventListener("click", () => {
      annotation.color = button.dataset.editorColor || "yellow";
      applyAnnotationColor(editor, annotation);
      editor.querySelectorAll("[data-editor-color]").forEach((entry) => {
        entry.classList.toggle("is-active", entry === button);
      });
      overlay.querySelectorAll(`.pdf-annotation[data-annotation-id="${annotation.id}"]`)
        .forEach((marker) => applyAnnotationColor(marker, annotation));
      scheduleSaveAnnotations();
    });
  });
  editor.addEventListener("submit", (event) => {
    event.preventDefault();
    annotation.comment = editor.querySelector("textarea").value.trim();
    annotation.text = annotation.comment;
    scheduleSaveAnnotations();
    closeNoteEditor();
    renderAllAnnotations();
  });
  editor.querySelector("[data-annotation-delete]").addEventListener("click", () => {
    pdfState.annotations = pdfState.annotations.filter((entry) => entry.id !== annotation.id);
    pdfState.selectedAnnotationId = "";
    scheduleSaveAnnotations();
    closeNoteEditor();
    renderAllAnnotations();
  });
  pageElement.appendChild(editor);
  pdfState.openEditor = editor;
  editor.querySelector("textarea").focus();
}

function renderAllAnnotations() {
  closeNoteEditor();
  elements.pdfViewer.querySelectorAll(".pdf-page").forEach(renderAnnotationsForPage);
  renderAnnotationList();
}

function jumpToAnnotation(annotationId) {
  const annotation = pdfState.annotations.find((entry) => entry.id === annotationId);
  if (!annotation) return;
  pdfState.selectedAnnotationId = annotation.id;
  renderAllAnnotations();
  const pageElement = elements.pdfViewer.querySelector(`[data-page="${annotation.page}"]`);
  if (!pageElement) return;
  pageElement.scrollIntoView({ block: "center", behavior: "smooth" });
  window.setTimeout(() => openAnnotationEditor(annotation, pageElement), 180);
}

function normalizedPointer(event, pageElement) {
  const box = pageViewportBox(pageElement);
  return {
    x: clamp((event.clientX - box.left) / box.width, 0, 1),
    y: clamp((event.clientY - box.top) / box.height, 0, 1)
  };
}

function rectsIntersect(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function clampClientRectToPage(rect, pageBox) {
  const left = clamp(rect.left, pageBox.left, pageBox.right);
  const right = clamp(rect.right, pageBox.left, pageBox.right);
  const top = clamp(rect.top, pageBox.top, pageBox.bottom);
  const bottom = clamp(rect.bottom, pageBox.top, pageBox.bottom);
  return { left, right, top, bottom, width: right - left, height: bottom - top };
}

function groupTextItemsByLine(items) {
  const lines = [];
  items
    .sort((a, b) => a.rect.top - b.rect.top || a.rect.left - b.rect.left)
    .forEach((item) => {
      const center = (item.rect.top + item.rect.bottom) / 2;
      const threshold = Math.max(4, item.rect.height * 0.55);
      let line = lines.find((entry) => Math.abs(entry.center - center) <= threshold);
      if (!line) {
        line = { center, items: [] };
        lines.push(line);
      }
      line.items.push(item);
      line.center = line.items.reduce((sum, entry) => sum + ((entry.rect.top + entry.rect.bottom) / 2), 0) / line.items.length;
    });
  return lines;
}

function lineRectsFromClientRects(clientRects, pageBox, type) {
  const items = clientRects
    .map((rect) => clampClientRectToPage(rect, pageBox))
    .filter((rect) => rect.width > 1 && rect.height > 1);

  return groupTextItemsByLine(items.map((rect) => ({ rect }))).map((line) => {
    const left = Math.min(...line.items.map((item) => item.rect.left));
    const right = Math.max(...line.items.map((item) => item.rect.right));
    const top = Math.min(...line.items.map((item) => item.rect.top));
    const bottom = Math.max(...line.items.map((item) => item.rect.bottom));
    const lineHeight = Math.max(1, bottom - top);
    const underlineHeight = Math.max(2, lineHeight * 0.13);
    const visualTop = type === "underline" ? bottom - underlineHeight : top + lineHeight * 0.08;
    const visualHeight = type === "underline" ? underlineHeight : lineHeight * 0.84;
    return normalizeAnnotationRect({
      x: (left - pageBox.left) / pageBox.width,
      y: (visualTop - pageBox.top) / pageBox.height,
      w: (right - left) / pageBox.width,
      h: visualHeight / pageBox.height
    });
  }).filter((rect) => rect.w >= 0.004 && rect.h >= 0.001);
}

function selectionClientRectsForPage(pageElement) {
  const selection = window.getSelection();
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  const textLayer = pageElement.querySelector(".textLayer");
  if (!selection || selection.isCollapsed || !canvas || !textLayer) return [];

  const pageBox = canvas.getBoundingClientRect();
  const layerBox = textLayer.getBoundingClientRect();
  const clientRects = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    if (!textLayer.contains(range.commonAncestorContainer) && !range.intersectsNode(textLayer)) continue;
    Array.from(range.getClientRects())
      .filter((rect) => rectsIntersect(rect, layerBox) && rectsIntersect(rect, pageBox))
      .forEach((rect) => clientRects.push(rect));
  }
  return clientRects;
}

function selectedLineRectsForPage(pageElement, type) {
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!canvas) return [];
  const pageBox = canvas.getBoundingClientRect();
  const clientRects = selectionClientRectsForPage(pageElement);
  return lineRectsFromClientRects(clientRects, pageBox, type);
}

function horizontalOverlap(a, b) {
  return Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
}

function verticalOverlap(a, b) {
  return Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
}

function sliceSpanTextByRect(span, selectionRect) {
  const text = span.textContent || "";
  const spanRect = span.getBoundingClientRect();
  if (!text || spanRect.width <= 0) return "";
  const left = clamp(Math.max(selectionRect.left, spanRect.left) - spanRect.left, 0, spanRect.width);
  const right = clamp(Math.min(selectionRect.right, spanRect.right) - spanRect.left, 0, spanRect.width);
  if (right <= left) return "";

  const style = getComputedStyle(span);
  const canvas = sliceSpanTextByRect.canvas || (sliceSpanTextByRect.canvas = document.createElement("canvas"));
  const context = canvas.getContext("2d");
  context.font = style.font || `${style.fontSize} ${style.fontFamily}`;

  const totalMeasured = Math.max(0.001, context.measureText(text).width);
  const positions = [0];
  let measured = 0;
  Array.from(text).forEach((char) => {
    measured += context.measureText(char).width;
    positions.push((measured / totalMeasured) * spanRect.width);
  });

  let startIndex = 0;
  let endIndex = text.length;
  for (let index = 0; index < text.length; index += 1) {
    const center = (positions[index] + positions[index + 1]) / 2;
    if (center >= left) {
      startIndex = index;
      break;
    }
  }
  for (let index = text.length - 1; index >= 0; index -= 1) {
    const center = (positions[index] + positions[index + 1]) / 2;
    if (center <= right) {
      endIndex = index + 1;
      break;
    }
  }
  return text.slice(startIndex, endIndex);
}

function textFromSelectionForPage(pageElement) {
  const clientRects = selectionClientRectsForPage(pageElement);
  if (!clientRects.length) return "";

  const spans = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
    .map((span) => ({ span, text: span.textContent || "", rect: span.getBoundingClientRect() }))
    .filter((entry) => normalizeText(entry.text) && entry.rect.width > 0 && entry.rect.height > 0);

  const lines = groupTextItemsByLine(clientRects.map((rect) => ({ rect })));
  const lineTexts = lines.map((line) => {
    const lineRect = {
      left: Math.min(...line.items.map((item) => item.rect.left)),
      right: Math.max(...line.items.map((item) => item.rect.right)),
      top: Math.min(...line.items.map((item) => item.rect.top)),
      bottom: Math.max(...line.items.map((item) => item.rect.bottom))
    };
    return spans
      .filter((entry) => {
        const vOverlap = verticalOverlap(entry.rect, lineRect);
        const hOverlap = horizontalOverlap(entry.rect, lineRect);
        return hOverlap > 1 && vOverlap >= Math.min(entry.rect.height, lineRect.bottom - lineRect.top) * 0.35;
      })
      .sort((a, b) => a.rect.left - b.rect.left)
      .map((entry) => sliceSpanTextByRect(entry.span, lineRect))
      .join("");
  });
  return normalizeCopiedPdfText(lineTexts.join("\n"));
}

function addNoteAnnotation(event, pageElement) {
  const point = normalizedPointer(event, pageElement);
  const annotation = normalizeAnnotation({
    id: `note-${Date.now().toString(36)}`,
    type: "note",
    page: Number(pageElement.dataset.page),
    x: point.x,
    y: point.y,
    w: 0.035,
    h: 0.035,
    color: pdfState.color,
    text: "",
    comment: ""
  });
  pdfState.annotations.push(annotation);
  scheduleSaveAnnotations();
  renderAnnotationsForPage(pageElement);
  openAnnotationEditor(annotation, pageElement);
}

function finishSelectionAnnotation(pageElement, type) {
  window.setTimeout(() => {
    const rects = selectedLineRectsForPage(pageElement, type);
    if (!rects.length) return;
    const bounds = annotationBounds(rects);
    const selectedText = textFromSelectionForPage(pageElement);
    const annotation = normalizeAnnotation({
      id: `${type}-${Date.now().toString(36)}`,
      type,
      page: Number(pageElement.dataset.page),
      ...bounds,
      rects,
      color: pdfState.color,
      quote: selectedText,
      text: "",
      comment: ""
    });
    if (annotation.w < 0.01 || annotation.h < 0.001) return;
    pdfState.annotations.push(annotation);
    window.getSelection()?.removeAllRanges();
    scheduleSaveAnnotations();
    renderAnnotationsForPage(pageElement);
  }, 0);
}

function wirePageAnnotationEvents(pageElement) {
  pageElement.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || pdfState.mode === "pan") return;
    if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return;
    if (pdfState.mode === "note") {
      event.preventDefault();
      addNoteAnnotation(event, pageElement);
    }
  });
  pageElement.addEventListener("pointerup", (event) => {
    if (!["highlight", "underline"].includes(pdfState.mode)) return;
    if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return;
    finishSelectionAnnotation(pageElement, pdfState.mode);
  });
}

function normalizeCopiedPdfText(text) {
  return String(text || "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]*\n[ \t]*/g, "\n")
    .replace(/([A-Za-z0-9,.;:)%])\n([A-Za-z0-9(])/g, "$1 $2")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function measuredTextWidth(text, fontSize, fontFamily) {
  const canvas = measuredTextWidth.canvas || (measuredTextWidth.canvas = document.createElement("canvas"));
  const context = canvas.getContext("2d");
  context.font = `${fontSize}px ${fontFamily}`;
  return Math.max(0.001, context.measureText(text).width);
}

function textChunksFromGlyphs(glyphs) {
  const chunks = [];
  let advance = 0;
  let chunk = null;

  const flush = () => {
    if (!chunk || !chunk.text) return;
    chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
    chunks.push(chunk);
    chunk = null;
  };

  glyphs.forEach((entry) => {
    if (typeof entry === "number") {
      if (entry <= -100 && chunk?.text) {
        chunk.text += " ";
        advance += -entry;
        chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
        flush();
        return;
      }
      advance += -entry;
      return;
    }
    const text = String(entry?.unicode || "");
    if (!text) {
      advance += Number(entry?.width) || 0;
      return;
    }
    if (!chunk) chunk = { text: "", startUnits: advance, widthUnits: 0 };
    chunk.text += text;
    advance += Number(entry.width) || 0;
    chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
    if (entry.isSpace || /\s$/.test(text)) flush();
  });
  flush();

  return { chunks, advanceUnits: advance };
}

function appendTextLayerChunk(container, viewport, matrix, fontSize, fontFamily, chunk) {
  const offset = chunk.startUnits * fontSize / 1000;
  const x = matrix[4] + matrix[0] * offset;
  const y = matrix[5] + matrix[1] * offset;
  const transform = [
    matrix[0] * fontSize,
    matrix[1] * fontSize,
    matrix[2] * fontSize,
    matrix[3] * fontSize,
    x,
    y
  ];
  const tx = pdfjsLib.Util.transform(viewport.transform, transform);
  const angle = Math.atan2(tx[1], tx[0]);
  const fontHeight = Math.hypot(tx[2], tx[3]);
  const fontAscent = fontHeight * 0.8;
  const measuredWidth = measuredTextWidth(chunk.text, fontHeight, fontFamily);
  const targetWidth = Math.max(0.001, chunk.widthUnits * Math.hypot(tx[0], tx[1]) / 1000);
  const span = document.createElement("span");
  span.textContent = chunk.text;
  span.setAttribute("role", "presentation");
  span.style.left = `${tx[4]}px`;
  span.style.top = `${tx[5] - fontAscent}px`;
  span.style.width = `${measuredWidth}px`;
  span.style.fontSize = `${fontHeight}px`;
  span.style.fontFamily = fontFamily;
  span.style.transform = `${Math.abs(angle) > 0.001 ? `rotate(${angle}rad) ` : ""}scaleX(${targetWidth / measuredWidth})`;
  span.style.transformOrigin = "0% 0%";
  container.appendChild(span);
}

async function renderOperatorTextLayer(page, textContent, viewport, container) {
  const opList = await page.getOperatorList();
  const ops = pdfjsLib.OPS || {};
  let fontSize = 10;
  let fontFamily = "sans-serif";
  let textMatrix = [1, 0, 0, 1, 0, 0];
  let lineMatrix = [1, 0, 0, 1, 0, 0];

  opList.fnArray.forEach((fn, index) => {
    const args = opList.argsArray[index];
    if (fn === ops.setFont) {
      fontSize = Number(args?.[1]) || fontSize;
      fontFamily = textContent.styles?.[args?.[0]]?.fontFamily || "sans-serif";
      return;
    }
    if (fn === ops.setTextMatrix) {
      textMatrix = Array.isArray(args) ? args.slice(0, 6).map(Number) : textMatrix;
      lineMatrix = textMatrix.slice();
      return;
    }
    if (fn === ops.moveText) {
      const dx = Number(args?.[0]) || 0;
      const dy = Number(args?.[1]) || 0;
      lineMatrix = lineMatrix.slice();
      lineMatrix[4] += dx;
      lineMatrix[5] += dy;
      textMatrix = lineMatrix.slice();
      return;
    }
    if (fn !== ops.showText) return;
    const glyphs = Array.isArray(args?.[0]) ? args[0] : [];
    const { chunks, advanceUnits } = textChunksFromGlyphs(glyphs);
    chunks.forEach((chunk) => appendTextLayerChunk(container, viewport, textMatrix, fontSize, fontFamily, chunk));
    const advance = advanceUnits * fontSize / 1000;
    textMatrix = textMatrix.slice();
    textMatrix[4] += textMatrix[0] * advance;
    textMatrix[5] += textMatrix[1] * advance;
  });
}

async function renderSelectableTextLayer(page, textContent, viewport, container) {
  container.addEventListener("copy", (event) => {
    const pageElement = container.closest(".pdf-page");
    const selectionText = pageElement ? textFromSelectionForPage(pageElement) : window.getSelection()?.toString() || "";
    const normalized = normalizeCopiedPdfText(selectionText);
    if (!normalized) return;
    event.preventDefault();
    event.clipboardData?.setData("text/plain", normalized);
  });

  try {
    await renderOperatorTextLayer(page, textContent, viewport, container);
    if (container.querySelector("span[role='presentation']")) return;
  } catch (error) {
    console.warn("Precise text layer failed, falling back to PDF.js text layer.", error);
  }

  const task = pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container,
    viewport
  });
  await task.promise;
}

async function renderPdfPage(pageNumber, renderToken, scale) {
  const page = await pdfState.document.getPage(pageNumber);
  if (renderToken !== pdfState.renderToken) return false;
  const viewport = page.getViewport({ scale });
  const outputScale = Math.min(window.devicePixelRatio || 1, 3);
  const pageElement = document.createElement("section");
  const canvas = document.createElement("canvas");
  const textLayer = document.createElement("div");
  const overlay = document.createElement("div");
  const context = canvas.getContext("2d");

  pageElement.className = "pdf-page";
  pageElement.dataset.page = String(pageNumber);
  canvas.className = "pdf-page-canvas";
  textLayer.className = "textLayer pdf-text-layer";
  overlay.className = "pdf-annotation-layer";
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  textLayer.style.width = `${viewport.width}px`;
  textLayer.style.height = `${viewport.height}px`;
  textLayer.style.setProperty("--scale-factor", String(viewport.scale));
  pageElement.style.width = `${viewport.width}px`;
  pageElement.style.height = `${viewport.height}px`;

  pageElement.append(canvas, textLayer, overlay);
  if (renderToken !== pdfState.renderToken) return false;
  elements.pdfViewer.appendChild(pageElement);
  wirePageAnnotationEvents(pageElement);
  const renderTask = page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0]
  }).promise;
  const textContent = await page.getTextContent();
  if (renderToken !== pdfState.renderToken) {
    pageElement.remove();
    return false;
  }
  await renderSelectableTextLayer(page, textContent, viewport, textLayer);
  await renderTask;
  if (renderToken !== pdfState.renderToken) {
    pageElement.remove();
    return false;
  }
  renderAnnotationsForPage(pageElement);
  return true;
}

async function renderPdf() {
  if (!pdfState.document) return;
  const renderToken = pdfState.renderToken + 1;
  const scale = pdfState.scale;
  pdfState.renderToken = renderToken;
  elements.pdfViewer.innerHTML = "";
  if (elements.zoomLabel) elements.zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  const pageCount = Number(pdfState.document.numPages || pdfState.document._pdfInfo?.numPages || 0);
  if (!pageCount) {
    throw new Error("PDF loaded, but page count was unavailable.");
  }
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    const rendered = await renderPdfPage(pageNumber, renderToken, scale);
    if (!rendered || renderToken !== pdfState.renderToken) return;
  }
}

async function loadPdf(pdfHref, noteId) {
  pdfState.noteId = noteId;
  pdfState.url = pdfHref;
  pdfState.annotations = await readAnnotations(noteId);
  setAnnotationStatus(pdfState.annotations.length ? "Annotations loaded" : "No annotations yet");
  renderAnnotationList();
  setPdfLoading("Fetching PDF...");
  try {
    const response = await fetch(pdfHref, { cache: "no-store" });
    if (!response.ok) throw new Error(`PDF request failed (${response.status})`);
    const pdfData = new Uint8Array(await response.arrayBuffer());
    setPdfLoading("Decoding PDF...");
    pdfState.document = await pdfjsLib.getDocument({
      data: pdfData,
      standardFontDataUrl: "node_modules/pdfjs-dist/standard_fonts/",
      disableAutoFetch: true,
      disableStream: true
    }).promise;
    setPdfLoading("Rendering pages...");
    await renderPdf();
  } catch (error) {
    console.error(error);
    showPdfError(error);
  }
}

function initializePdfTools() {
  elements.colorButtons.forEach((button) => {
    const color = PDF_COLORS[button.dataset.pdfColor];
    if (!color) return;
    button.style.backgroundColor = color.hex;
    button.style.setProperty("--swatch", color.hex);
  });
  elements.modeButtons.forEach((button) => {
    button.addEventListener("click", () => setPdfMode(button.dataset.pdfMode || "pan"));
  });
  elements.colorButtons.forEach((button) => {
    button.addEventListener("click", () => setPdfColor(button.dataset.pdfColor || "yellow"));
  });
  elements.zoomIn?.addEventListener("click", async () => {
    pdfState.scale = clamp(pdfState.scale + 0.1, 0.7, 2.2);
    await renderPdf();
  });
  elements.zoomOut?.addEventListener("click", async () => {
    pdfState.scale = clamp(pdfState.scale - 0.1, 0.7, 2.2);
    await renderPdf();
  });
  setPdfMode("pan");
  setPdfColor("yellow");
}

function renderSection(title, body = "") {
  const content = body
    ? `<p>${escapeHtml(body)}</p>`
    : `<div class="note-placeholder" aria-hidden="true"></div>`;
  return `
    <section class="note-section">
      <h2>${title}</h2>
      ${content}
    </section>
  `;
}

function absolutizeEmbeddedAssetUrls(root, baseHref) {
  if (!root || !baseHref) return;
  root.querySelectorAll("img[src], video[src], audio[src], source[src]").forEach((element) => {
    const value = element.getAttribute("src");
    if (!value || value.startsWith("#") || /^[a-z][a-z0-9+.-]*:/i.test(value)) return;
    element.setAttribute("src", new URL(value, baseHref).href);
  });
}

function extractGeneratedNoteBody(html, baseHref = window.location.href) {
  if (!html) return "";
  const documentBody = new DOMParser().parseFromString(html, "text/html");
  const note = documentBody.querySelector("main.note") || documentBody.body;
  absolutizeEmbeddedAssetUrls(note, baseHref);
  return note ? note.innerHTML : "";
}

function mountReaderNoteMenu() {
  const existingMenu = elements.notePane?.querySelector(":scope > .note-menu");
  existingMenu?.remove();
  const menu = elements.notePage?.querySelector(".note-menu");
  if (!menu || !elements.notePane) return;
  menu.classList.add("reader-note-menu");
  elements.notePane.insertBefore(menu, elements.notePage);
}

async function fetchGeneratedNoteBody(note) {
  if (!note.htmlHref) return "";
  try {
    const baseUrl = window.location.protocol === "file:" ? "http://localhost:4173/" : "";
    const separator = note.htmlHref.includes("?") ? "&" : "?";
    const noteUrl = new URL(note.htmlHref, baseUrl || window.location.href);
    const response = await fetch(`${noteUrl.href}${separator}t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) return "";
    return extractGeneratedNoteBody(await response.text(), noteUrl.href);
  } catch (error) {
    console.warn("Failed to load generated HTML note.", error);
    return "";
  }
}

async function renderReader(library, note) {
  const collectionPath = getCollectionPath(library, note.categoryId);
  const storedFile = await readPaperFile(note.pdfStorageKey || note.id).catch((error) => {
    console.warn("Failed to read stored paper file.", error);
    return null;
  });
  const pdfHref = storedFile?.pdfBlob ? URL.createObjectURL(storedFile.pdfBlob) : note.href || "#";
  const generatedNoteBody = await fetchGeneratedNoteBody(note) || extractGeneratedNoteBody(storedFile?.noteHtml);

  elements.title.textContent = note.title;
  elements.kicker.textContent = collectionPath;
  await loadPdf(pdfHref, note.id);
  elements.notePage.innerHTML = generatedNoteBody || `
    <header class="note-section">
      <p class="note-eyebrow">Paper Note</p>
      <h1>${escapeHtml(note.title)}</h1>
      <p class="note-meta">${escapeHtml([note.date, collectionPath].filter(Boolean).join(" · "))}</p>
    </header>
    ${renderSection("TL;DR", note.summary)}
    ${renderSection("Problem")}
    ${renderSection("Method")}
    ${renderSection("Experiments")}
    ${renderSection("Questions")}
  `;
  if (typeof window.buildNoteMenu === "function") window.buildNoteMenu(elements.notePage);
  mountReaderNoteMenu();
}

async function initialize() {
  if (window.location.protocol === "file:") {
    showStartupError("Open http://localhost:4173 instead of opening reader.html directly.");
    return;
  }
  if (!pdfjsLib) {
    showStartupError("PDF.js did not load. Refresh the page or restart the local server.");
    return;
  }
  initializeResizer();
  initializeAnnotationSidebar();
  initializeHtmlPaneToggle();
  initializeHtmlZoom();
  initializePdfTools();
  const noteId = new URLSearchParams(window.location.search).get("id");
  if (!noteId) {
    showError();
    return;
  }

  try {
    const library = await readDefaultLibrary().catch(() => readLibraryFromStorage());
    const note = library.notes.find((entry) => entry.id === noteId);
    if (!note) {
      showError();
      return;
    }
    await renderReader(library, note);
  } catch (error) {
    console.error(error);
    showError();
  }
}

initialize();
