const pdfjsLib = globalThis.pdfjsLib;

if (pdfjsLib) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "node_modules/pdfjs-dist/build/pdf.worker.js";
}

const STORAGE_KEY = "paper-notes-library-v12";
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
  scale: 1.15,
  annotations: [],
  saveTimer: 0,
  drag: null,
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
  const comment = normalizeText(annotation.comment || annotation.text);
  return {
    id: normalizeText(annotation.id) || `annotation-${Date.now().toString(36)}`,
    type,
    page: Number(annotation.page) || 1,
    x: Number(annotation.x) || 0,
    y: Number(annotation.y) || 0,
    w: Number(annotation.w) || 0,
    h: Number(annotation.h) || 0,
    color: PDF_COLORS[annotation.color] ? annotation.color : "yellow",
    text: comment,
    comment,
    createdAt: normalizeText(annotation.createdAt) || new Date().toISOString()
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
  const comment = normalizeText(annotation.comment || annotation.text);
  if (comment) return comment;
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
        <span>Use Highlight, Underline, Area, or Note on the PDF.</span>
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

function annotationStyle(annotation, box) {
  return {
    left: `${annotation.x * box.width}px`,
    top: `${annotation.y * box.height}px`,
    width: `${annotation.w * box.width}px`,
    height: `${annotation.h * box.height}px`
  };
}

function renderAnnotationsForPage(pageElement) {
  const page = Number(pageElement.dataset.page);
  const overlay = pageElement.querySelector(".pdf-annotation-layer");
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!overlay || !canvas) return;

  const box = { width: canvas.clientWidth, height: canvas.clientHeight };
  overlay.innerHTML = "";
  pdfState.annotations.filter((annotation) => annotation.page === page).forEach((annotation) => {
    const item = document.createElement("button");
    const style = annotationStyle(annotation, box);
    item.type = "button";
    item.className = `pdf-annotation pdf-annotation-${annotation.type}`;
    item.classList.toggle("is-selected", annotation.id === pdfState.selectedAnnotationId);
    item.style.left = style.left;
    item.style.top = style.top;
    item.style.width = style.width;
    item.style.height = style.height;
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
    <textarea aria-label="Annotation comment" placeholder="Add a comment...">${escapeHtml(annotation.comment || annotation.text || "")}</textarea>
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
      const marker = Array.from(overlay.querySelectorAll(".pdf-annotation"))
        .find((entry) => entry.dataset.annotationId === annotation.id);
      if (marker) applyAnnotationColor(marker, annotation);
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
  overlay.appendChild(editor);
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

function startBoxAnnotation(event, pageElement) {
  const point = normalizedPointer(event, pageElement);
  const overlay = pageElement.querySelector(".pdf-annotation-layer");
  const preview = document.createElement("div");
  preview.className = `pdf-annotation-draft pdf-annotation-draft-${pdfState.mode}`;
  applyAnnotationColor(preview, { color: pdfState.color });
  overlay.appendChild(preview);
  pdfState.drag = {
    pageElement,
    type: pdfState.mode,
    start: point,
    current: point,
    preview
  };
  pageElement.setPointerCapture(event.pointerId);
}

function updateBoxAnnotation(event) {
  if (!pdfState.drag) return;
  const { pageElement, start, preview, type } = pdfState.drag;
  const current = normalizedPointer(event, pageElement);
  pdfState.drag.current = current;
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  const box = { width: canvas.clientWidth, height: canvas.clientHeight };
  const annotation = {
    x: Math.min(start.x, current.x),
    y: Math.min(start.y, current.y),
    w: Math.abs(current.x - start.x),
    h: Math.abs(current.y - start.y)
  };
  if (type === "underline") {
    annotation.y = Math.max(start.y, current.y) - 0.004;
    annotation.h = 0.008;
  }
  const style = annotationStyle(annotation, box);
  preview.style.left = style.left;
  preview.style.top = style.top;
  preview.style.width = style.width;
  preview.style.height = style.height;
}

function finishBoxAnnotation() {
  if (!pdfState.drag) return;
  const { pageElement, start, current, preview, type } = pdfState.drag;
  preview.remove();
  pdfState.drag = null;
  const x = Math.min(start.x, current.x);
  const w = Math.abs(current.x - start.x);
  const y = type === "underline" ? Math.max(start.y, current.y) - 0.004 : Math.min(start.y, current.y);
  const h = type === "underline" ? 0.008 : Math.abs(current.y - start.y);

  const annotation = normalizeAnnotation({
    id: `${type}-${Date.now().toString(36)}`,
    type,
    page: Number(pageElement.dataset.page),
    x,
    y,
    w,
    h,
    color: pdfState.color,
    comment: ""
  });
  if (annotation.w < 0.01 || (type !== "underline" && annotation.h < 0.006)) return;
  pdfState.annotations.push(annotation);
  scheduleSaveAnnotations();
  renderAnnotationsForPage(pageElement);
}

function wirePageAnnotationEvents(pageElement) {
  pageElement.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || pdfState.mode === "pan") return;
    if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return;
    event.preventDefault();
    if (pdfState.mode === "note") addNoteAnnotation(event, pageElement);
    if (["highlight", "underline"].includes(pdfState.mode)) startBoxAnnotation(event, pageElement);
  });
  pageElement.addEventListener("pointermove", updateBoxAnnotation);
  pageElement.addEventListener("pointerup", finishBoxAnnotation);
  pageElement.addEventListener("pointercancel", finishBoxAnnotation);
}

async function renderPdfPage(pageNumber) {
  const page = await pdfState.document.getPage(pageNumber);
  const viewport = page.getViewport({ scale: pdfState.scale });
  const outputScale = Math.min(window.devicePixelRatio || 1, 3);
  const pageElement = document.createElement("section");
  const canvas = document.createElement("canvas");
  const overlay = document.createElement("div");
  const context = canvas.getContext("2d");

  pageElement.className = "pdf-page";
  pageElement.dataset.page = String(pageNumber);
  canvas.className = "pdf-page-canvas";
  overlay.className = "pdf-annotation-layer";
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  pageElement.style.width = `${viewport.width}px`;
  pageElement.style.height = `${viewport.height}px`;

  pageElement.append(canvas, overlay);
  elements.pdfViewer.appendChild(pageElement);
  wirePageAnnotationEvents(pageElement);
  await page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0]
  }).promise;
  renderAnnotationsForPage(pageElement);
}

async function renderPdf() {
  if (!pdfState.document) return;
  elements.pdfViewer.innerHTML = "";
  if (elements.zoomLabel) elements.zoomLabel.textContent = `${Math.round(pdfState.scale * 100)}%`;
  const pageCount = Number(pdfState.document.numPages || pdfState.document._pdfInfo?.numPages || 0);
  if (!pageCount) {
    throw new Error("PDF loaded, but page count was unavailable.");
  }
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    await renderPdfPage(pageNumber);
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
