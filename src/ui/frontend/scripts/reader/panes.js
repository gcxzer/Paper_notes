function sanitizeLibrary(rawLibrary) {
  const library = MODEL.sanitizeLibrary(rawLibrary);
  library.notes.forEach((note) => {
    note.title = note.title || "Untitled Paper";
  });
  return library;
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
  const response = await fetch(getApiUrl("/api/library"), { cache: "no-store" });
  if (!response.ok) throw new Error(`Unable to load library (${response.status})`);
  const payload = await response.json();
  return sanitizeLibrary(payload.library || payload);
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

function updateCurrentNote(nextNote) {
  if (!nextNote?.id) return;
  readerState.note = { ...(readerState.note || {}), ...nextNote };
  if (readerState.library?.notes) {
    const index = readerState.library.notes.findIndex((entry) => entry.id === nextNote.id);
    if (index >= 0) {
      readerState.library.notes[index] = { ...readerState.library.notes[index], ...nextNote };
    }
  }
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
  if (!collapsed) setAnnotationSidebarWidth(readAnnotationSidebarWidth(), { persist: false });
  requestAnimationFrame(() => {
    schedulePdfSelectionOverlayRender();
    updatePdfPageControl();
  });
}

function annotationSidebarMaxWidth() {
  const bodyWidth = elements.pdfBody?.clientWidth || 0;
  if (!bodyWidth) return ANNOTATION_SIDEBAR_MAX_WIDTH;
  return Math.max(
    ANNOTATION_SIDEBAR_MIN_WIDTH,
    Math.min(ANNOTATION_SIDEBAR_MAX_WIDTH, bodyWidth * 0.62)
  );
}

function readAnnotationSidebarWidth() {
  const stored = Number(localStorage.getItem(ANNOTATION_SIDEBAR_WIDTH_KEY));
  const width = Number.isFinite(stored) ? stored : ANNOTATION_SIDEBAR_DEFAULT_WIDTH;
  return clamp(width, ANNOTATION_SIDEBAR_MIN_WIDTH, annotationSidebarMaxWidth());
}

function setAnnotationSidebarWidth(width, options = {}) {
  const nextWidth = clamp(Number(width) || ANNOTATION_SIDEBAR_DEFAULT_WIDTH, ANNOTATION_SIDEBAR_MIN_WIDTH, annotationSidebarMaxWidth());
  elements.pdfBody?.style.setProperty("--annotation-sidebar-width", `${nextWidth}px`);
  elements.annotationSidebarResizer?.setAttribute("aria-valuenow", String(Math.round(nextWidth)));
  elements.annotationSidebarResizer?.setAttribute("aria-valuemin", String(ANNOTATION_SIDEBAR_MIN_WIDTH));
  elements.annotationSidebarResizer?.setAttribute("aria-valuemax", String(Math.round(annotationSidebarMaxWidth())));
  if (options.persist !== false) localStorage.setItem(ANNOTATION_SIDEBAR_WIDTH_KEY, String(Math.round(nextWidth)));
  schedulePdfSelectionOverlayRender();
  updatePdfPageControl();
}

function updateAnnotationSidebarWidthFromClientX(clientX) {
  const bodyBox = elements.pdfBody?.getBoundingClientRect();
  if (!bodyBox) return;
  setAnnotationSidebarWidth(clientX - bodyBox.left);
}

function initializeAnnotationSidebar() {
  setAnnotationSidebarWidth(readAnnotationSidebarWidth(), { persist: false });
  setAnnotationSidebarCollapsed(localStorage.getItem(ANNOTATION_SIDEBAR_KEY) === "collapsed");
  elements.annotationSidebarToolbarToggle?.addEventListener("click", () => {
    setAnnotationSidebarCollapsed(!elements.pdfBody?.classList.contains("is-annotation-sidebar-collapsed"));
  });
  elements.annotationSidebarToggle?.addEventListener("click", () => setAnnotationSidebarCollapsed(true));
  const finishAnnotationSidebarResize = (event) => {
    if (!splitState.annotationSidebarDragging) return;
    splitState.annotationSidebarDragging = false;
    releasePointerCaptureSafely(elements.annotationSidebarResizer, event?.pointerId);
    setReaderResizerActive(elements.annotationSidebarResizer, false);
  };
  elements.annotationSidebarResizer?.addEventListener("pointerdown", (event) => {
    if (elements.pdfBody?.classList.contains("is-annotation-sidebar-collapsed")) return;
    splitState.annotationSidebarDragging = true;
    elements.annotationSidebarResizer.setPointerCapture(event.pointerId);
    setReaderResizerActive(elements.annotationSidebarResizer, true);
    event.preventDefault();
  });
  elements.annotationSidebarResizer?.addEventListener("pointermove", (event) => {
    if (!splitState.annotationSidebarDragging) return;
    updateAnnotationSidebarWidthFromClientX(event.clientX);
  });
  elements.annotationSidebarResizer?.addEventListener("pointerup", finishAnnotationSidebarResize);
  elements.annotationSidebarResizer?.addEventListener("pointercancel", finishAnnotationSidebarResize);
  elements.annotationSidebarResizer?.addEventListener("lostpointercapture", finishAnnotationSidebarResize);
  elements.annotationSidebarResizer?.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -16 : 16;
    setAnnotationSidebarWidth(readAnnotationSidebarWidth() + delta);
  });
}

function setHtmlPaneVisible(visible) {
  elements.layout?.classList.toggle("is-html-pane-hidden", !visible);
  elements.htmlPaneToggle?.classList.toggle("is-active", visible);
  elements.htmlPaneToggle?.setAttribute("aria-expanded", String(visible));
  localStorage.setItem(HTML_PANE_KEY, visible ? "shown" : "hidden");
  requestAnimationFrame(() => {
    setAskWidth(readAskWidth());
    setSplitPercent(readSplitPercent());
  });
}

function initializeHtmlPaneToggle() {
  setHtmlPaneVisible(localStorage.getItem(HTML_PANE_KEY) !== "hidden");
  elements.htmlPaneToggle?.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button === 1) return;
    event.preventDefault();
    setHtmlPaneVisible(elements.layout?.classList.contains("is-html-pane-hidden"));
  });
}

function setAskPaneVisible(visible) {
  elements.layout?.classList.toggle("is-ask-pane-hidden", !visible);
  elements.askPaneToggle?.classList.toggle("is-active", visible);
  elements.askPaneToggle?.setAttribute("aria-expanded", String(visible));
  localStorage.setItem(ASK_PANE_KEY, visible ? "shown" : "hidden");
  if (visible) {
    if (typeof renderReaderChatMessages === "function") {
      renderReaderChatMessages({ scrollToBottom: true });
    }
    requestAnimationFrame(() => {
      setAskWidth(readAskWidth());
      elements.readerChatInput?.focus();
    });
  }
  requestAnimationFrame(() => {
    setAskWidth(readAskWidth());
    setSplitPercent(readSplitPercent());
  });
}

function initializeAskPaneToggle() {
  setAskPaneVisible(localStorage.getItem(ASK_PANE_KEY) === "shown");
  elements.askPaneToggle?.addEventListener("click", () => {
    setAskPaneVisible(elements.layout?.classList.contains("is-ask-pane-hidden"));
  });
  elements.closeAskPane?.addEventListener("click", () => setAskPaneVisible(false));
}
