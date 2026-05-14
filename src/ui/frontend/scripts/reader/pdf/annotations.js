function setPdfMode(mode) {
  const nextMode = ["highlight", "underline", "note"].includes(mode) ? mode : "pan";
  pdfState.mode = nextMode;
  elements.pdfViewer?.classList.toggle("is-annotating", nextMode !== "pan");
  elements.pdfViewer?.classList.toggle("is-text-annotating", ["highlight", "underline"].includes(nextMode));
  elements.pdfViewer?.classList.toggle("is-note-annotating", nextMode === "note");
  elements.modeButtons.forEach((button) => {
    const active = button.dataset.pdfMode === nextMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function togglePdfMode(mode) {
  setPdfMode(pdfState.mode === mode ? "pan" : mode);
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

function cloneAnnotation(annotation) {
  return {
    ...annotation,
    rects: Array.isArray(annotation.rects) ? annotation.rects.map((rect) => ({ ...rect })) : []
  };
}

function cloneAnnotationSnapshot() {
  return pdfState.annotations.map(cloneAnnotation);
}

function updateAnnotationHistoryButtons() {
  if (elements.annotationUndo) elements.annotationUndo.disabled = !pdfState.historyPast.length;
  if (elements.annotationRedo) elements.annotationRedo.disabled = !pdfState.historyFuture.length;
}

function resetAnnotationHistory() {
  pdfState.historyPast = [];
  pdfState.historyFuture = [];
  updateAnnotationHistoryButtons();
}

function pushAnnotationHistory() {
  pdfState.historyPast.push(cloneAnnotationSnapshot());
  if (pdfState.historyPast.length > pdfState.historyLimit) {
    pdfState.historyPast.shift();
  }
  pdfState.historyFuture = [];
  updateAnnotationHistoryButtons();
}

function restoreAnnotationSnapshot(snapshot) {
  closeNoteEditor();
  pdfState.annotations = (Array.isArray(snapshot) ? snapshot : [])
    .map((annotation) => normalizeAnnotation(cloneAnnotation(annotation)));
  pdfState.selectedAnnotationId = "";
  clearAnnotationSelectionOutline();
  scheduleSaveAnnotations();
  renderAllAnnotations();
  updateAnnotationHistoryButtons();
}

function undoAnnotationChange() {
  if (!pdfState.historyPast.length) return;
  const currentSnapshot = cloneAnnotationSnapshot();
  const previousSnapshot = pdfState.historyPast.pop();
  pdfState.historyFuture.push(currentSnapshot);
  restoreAnnotationSnapshot(previousSnapshot);
}

function redoAnnotationChange() {
  if (!pdfState.historyFuture.length) return;
  const currentSnapshot = cloneAnnotationSnapshot();
  const nextSnapshot = pdfState.historyFuture.pop();
  pdfState.historyPast.push(currentSnapshot);
  restoreAnnotationSnapshot(nextSnapshot);
}

function editableKeyboardTarget(element) {
  return Boolean(element?.closest?.("input, textarea, select, [contenteditable='true'], [contenteditable='']"));
}

function deleteSelectedAnnotation() {
  const annotationId = pdfState.selectedAnnotationId;
  if (!annotationId || !pdfState.annotations.some((entry) => entry.id === annotationId)) return false;
  pushAnnotationHistory();
  pdfState.annotations = pdfState.annotations.filter((entry) => entry.id !== annotationId);
  pdfState.selectedAnnotationId = "";
  clearAnnotationSelectionOutline();
  closeNoteEditor();
  scheduleSaveAnnotations();
  renderAllAnnotations();
  return true;
}

function handleAnnotationKeyboard(event) {
  if (editableKeyboardTarget(event.target)) return;
  const key = event.key.toLowerCase();
  const commandKey = event.metaKey || event.ctrlKey;

  if (commandKey && key === "z") {
    event.preventDefault();
    if (event.shiftKey) {
      redoAnnotationChange();
    } else {
      undoAnnotationChange();
    }
    return;
  }

  if (!event.metaKey && !event.ctrlKey && !event.altKey && ["delete", "backspace"].includes(key)) {
    if (deleteSelectedAnnotation()) event.preventDefault();
  }
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

async function refreshAnnotationsFromServer({ preserveOpenEditor = false, statusText = "Annotations refreshed" } = {}) {
  if (!pdfState.noteId) return [];
  const openAnnotationId = preserveOpenEditor
    ? normalizeText(pdfState.openEditor?.dataset?.annotationId || pdfState.selectedAnnotationId)
    : "";
  pdfState.annotations = await readAnnotations(pdfState.noteId);
  resetAnnotationHistory();
  if (openAnnotationId && pdfState.annotations.some((entry) => entry.id === openAnnotationId)) {
    pdfState.selectedAnnotationId = openAnnotationId;
  } else {
    pdfState.selectedAnnotationId = "";
    clearAnnotationSelectionOutline();
  }
  if (statusText) {
    setAnnotationStatus(statusText);
  } else {
    renderAnnotationList();
  }
  renderAllAnnotations();
  return pdfState.annotations;
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

function annotationIdSelectorValue(annotationId) {
  return String(annotationId || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function annotationMarkerSelector(annotationId) {
  return `.pdf-annotation[data-annotation-id="${annotationIdSelectorValue(annotationId)}"]`;
}

function clearAnnotationSelectionOutline() {
  window.clearTimeout(pdfState.selectionOutlineTimer);
  pdfState.selectionOutlineTimer = 0;
  pdfState.selectionOutlineAnnotationId = "";
  elements.pdfViewer?.querySelectorAll(".pdf-annotation.is-selection-outlined")
    .forEach((element) => element.classList.remove("is-selection-outlined"));
}

function removeExpiredAnnotationSelectionOutline(annotationId) {
  if (pdfState.selectionOutlineAnnotationId !== annotationId) return;
  clearAnnotationSelectionOutline();
}

function showAnnotationSelectionOutline(annotationId) {
  if (!annotationId) return;
  clearAnnotationSelectionOutline();
  pdfState.selectionOutlineAnnotationId = annotationId;
  elements.pdfViewer?.querySelectorAll(annotationMarkerSelector(annotationId))
    .forEach((element) => element.classList.add("is-selection-outlined"));
  pdfState.selectionOutlineTimer = window.setTimeout(() => {
    removeExpiredAnnotationSelectionOutline(annotationId);
  }, 3000);
}

function renderAnnotationList() {
  if (!elements.annotationList) return;
  updateAnnotationHistoryButtons();
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
  const pageGroups = new Map();
  sorted.forEach((annotation) => {
    const page = Number(annotation.page) || 1;
    if (!pageGroups.has(page)) pageGroups.set(page, []);
    pageGroups.get(page).push(annotation);
  });

  pageGroups.forEach((annotations, page) => {
    const section = document.createElement("section");
    section.className = "annotation-page-section";
    section.setAttribute("aria-label", `Page ${page} annotations`);
    section.innerHTML = `
      <div class="annotation-page-heading">
        <span>Page ${page}</span>
        <small>${annotations.length}</small>
      </div>
    `;
    annotations.forEach((annotation) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "annotation-card";
      card.dataset.annotationId = annotation.id;
      card.classList.toggle("is-selected", annotation.id === pdfState.selectedAnnotationId);
      applyAnnotationColor(card, annotation);
      card.innerHTML = `
        <span class="annotation-card-strip" aria-hidden="true"></span>
        <span class="annotation-card-main">
          <span class="annotation-card-meta">${annotationTypeLabel(annotation.type)}</span>
          <span class="annotation-card-text">${escapeHtml(annotationSummary(annotation))}</span>
        </span>
      `;
      card.addEventListener("click", () => jumpToAnnotation(annotation.id));
      section.appendChild(card);
    });
    elements.annotationList.appendChild(section);
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

function clampAnnotationPosition(value, size) {
  return clamp(value, 0, Math.max(0, 1 - size));
}

function moveAnnotationTo(annotation, startRects, nextX, nextY) {
  const startBounds = annotationBounds(startRects);
  const deltaX = nextX - startBounds.x;
  const deltaY = nextY - startBounds.y;
  annotation.rects = startRects.map((rect) => ({
    ...rect,
    x: clampAnnotationPosition(rect.x + deltaX, rect.w),
    y: clampAnnotationPosition(rect.y + deltaY, rect.h)
  }));
  const nextBounds = annotationBounds(annotation.rects);
  annotation.x = nextBounds.x;
  annotation.y = nextBounds.y;
  annotation.w = nextBounds.w;
  annotation.h = nextBounds.h;
}

function finishNoteAnnotationDrag(event) {
  const drag = pdfState.noteDrag;
  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;
  pdfState.noteDrag = null;
  drag.item.classList.remove("is-dragging");
  releasePointerCaptureSafely(drag.item, drag.pointerId);
  window.removeEventListener("pointermove", handleNoteAnnotationDragMove, true);
  window.removeEventListener("pointerup", finishNoteAnnotationDrag, true);
  window.removeEventListener("pointercancel", finishNoteAnnotationDrag, true);

  if (!drag.moved) return;
  pdfState.noteDragSuppressClick = true;
  scheduleSaveAnnotations();
  renderAnnotationList();
  window.setTimeout(() => {
    pdfState.noteDragSuppressClick = false;
  }, 0);
}

function handleNoteAnnotationDragMove(event) {
  const drag = pdfState.noteDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  event.preventDefault();
  const distance = Math.hypot(event.clientX - drag.startClientX, event.clientY - drag.startClientY);
  if (!drag.moved && distance < 3) return;

  const annotation = pdfState.annotations.find((entry) => entry.id === drag.annotationId);
  if (!annotation) {
    finishNoteAnnotationDrag(event);
    return;
  }
  if (!drag.historyPushed) {
    pushAnnotationHistory();
    drag.historyPushed = true;
  }
  drag.moved = true;

  const box = pageViewportBox(drag.pageElement);
  const nextX = clampAnnotationPosition(
    drag.startBounds.x + ((event.clientX - drag.startClientX) / Math.max(1, box.width)),
    drag.startBounds.w
  );
  const nextY = clampAnnotationPosition(
    drag.startBounds.y + ((event.clientY - drag.startClientY) / Math.max(1, box.height)),
    drag.startBounds.h
  );
  moveAnnotationTo(annotation, drag.startRects, nextX, nextY);
  applyRectStyle(drag.item, annotationBounds(annotation.rects), { width: box.width, height: box.height });
}

function startNoteAnnotationDrag(event, annotation, pageElement, item) {
  if (event.button !== 0 || annotation.type !== "note") return;
  event.preventDefault();
  event.stopPropagation();
  pdfState.noteDragSuppressClick = false;
  saveAnnotationEditorComment();
  closeNoteEditor();
  cancelPendingAnnotationClick();
  pdfState.selectedAnnotationId = annotation.id;
  const startRects = (annotation.rects?.length ? annotation.rects : [annotation]).map((rect) => ({ ...rect }));
  pdfState.noteDrag = {
    pointerId: event.pointerId,
    annotationId: annotation.id,
    pageElement,
    item,
    startClientX: event.clientX,
    startClientY: event.clientY,
    startRects,
    startBounds: annotationBounds(startRects),
    historyPushed: false,
    moved: false
  };
  item.classList.add("is-dragging", "is-selected");
  item.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", handleNoteAnnotationDragMove, true);
  window.addEventListener("pointerup", finishNoteAnnotationDrag, true);
  window.addEventListener("pointercancel", finishNoteAnnotationDrag, true);
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
      item.classList.toggle("is-selection-outlined", annotation.id === pdfState.selectionOutlineAnnotationId);
      applyRectStyle(item, rect, box);
      applyAnnotationColor(item, annotation);
      item.dataset.annotationId = annotation.id;
      item.title = annotationSummary(annotation);
      item.setAttribute("aria-label", item.title);
      item.addEventListener("pointerdown", (event) => {
        startNoteAnnotationDrag(event, annotation, pageElement, item);
        event.stopPropagation();
      });
      item.addEventListener("click", (event) => {
        if (pdfState.noteDragSuppressClick) {
          event.preventDefault();
          event.stopPropagation();
          pdfState.noteDragSuppressClick = false;
          return;
        }
        event.stopPropagation();
        openAnnotationEditor(annotation, pageElement);
      });
      overlay.appendChild(item);
    });
  });
}

function annotationAtPagePoint(pageElement, event) {
  if (!pageElement || pdfState.mode !== "pan") return null;
  const page = Number(pageElement.dataset.page);
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!canvas) return null;
  const box = canvas.getBoundingClientRect();
  const x = (event.clientX - box.left) / Math.max(1, box.width);
  const y = (event.clientY - box.top) / Math.max(1, box.height);
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  const annotations = pdfState.annotations.filter((annotation) => annotation.page === page);
  for (let index = annotations.length - 1; index >= 0; index -= 1) {
    const annotation = annotations[index];
    const rects = annotation.rects?.length ? annotation.rects : [annotation];
    if (rects.some((rect) => annotationRectContainsPoint(annotation, rect, x, y, box))) return annotation;
  }
  return null;
}

function annotationRectContainsPoint(annotation, rect, x, y, box) {
  const xSlop = 3 / Math.max(1, box.width);
  let top = rect.y;
  let bottom = rect.y + rect.h;
  if (annotation.type === "underline") {
    const upwardSlop = Math.max(14 / Math.max(1, box.height), rect.h * 6);
    const downwardSlop = Math.max(8 / Math.max(1, box.height), rect.h * 2);
    top -= upwardSlop;
    bottom += downwardSlop;
  }
  return x >= rect.x - xSlop
    && x <= rect.x + rect.w + xSlop
    && y >= top
    && y <= bottom;
}

function cancelPendingAnnotationClick() {
  window.clearTimeout(pdfState.annotationClickTimer);
  pdfState.annotationClickTimer = 0;
}

function handlePdfAnnotationClick(event, pageElement) {
  if (event.paperNotesAnnotationClickHandled) return;
  if (event.defaultPrevented || event.button !== 0 || pdfState.mode !== "pan") return;
  const targetElement = event.target?.nodeType === Node.ELEMENT_NODE
    ? event.target
    : event.target?.parentElement;
  if (targetElement?.closest(".pdf-annotation-editor")) return;
  if (event.detail > 1) {
    cancelPendingAnnotationClick();
    return;
  }
  const annotation = annotationAtPagePoint(pageElement, event);
  if (!annotation) return;
  event.paperNotesAnnotationClickHandled = true;
  cancelPendingAnnotationClick();
  pdfState.annotationClickTimer = window.setTimeout(() => {
    pdfState.annotationClickTimer = 0;
    if (normalizeText(window.getSelection()?.toString())) return;
    const currentPageElement = elements.pdfViewer?.querySelector(`[data-page="${annotation.page}"]`);
    if (!currentPageElement) return;
    openAnnotationEditor(annotation, currentPageElement);
  }, 260);
}

function closeNoteEditor() {
  pdfState.openEditor?.remove();
  pdfState.openEditor = null;
}

function saveAnnotationEditorComment(editor = pdfState.openEditor) {
  if (!editor) return false;
  const annotation = pdfState.annotations.find((entry) => entry.id === editor.dataset.annotationId);
  const textarea = editor.querySelector("textarea");
  if (!annotation || !textarea) return false;
  const nextComment = textarea.value.trim();
  if (annotation.comment === nextComment) return false;
  pushAnnotationHistory();
  annotation.comment = nextComment;
  annotation.text = annotation.comment;
  scheduleSaveAnnotations();
  return true;
}

function closeOpenAnnotationEditor(saveComment = false) {
  const changed = saveComment ? saveAnnotationEditorComment() : false;
  closeNoteEditor();
  if (changed) renderAllAnnotations();
  return changed;
}

function handleAnnotationEditorOutsidePointer(event) {
  const editor = pdfState.openEditor;
  if (!editor || editor.contains(event.target)) return;
  closeOpenAnnotationEditor(true);
}

function rectOverlapArea(a, b) {
  const width = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
  const height = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  return width * height;
}

function positionAnnotationEditor(editor, annotation, pageElement) {
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!canvas) return;
  const box = { width: canvas.clientWidth, height: canvas.clientHeight };
  const margin = 10;
  const gap = 12;
  const editorWidth = Math.min(editor.offsetWidth || 380, Math.max(1, box.width - margin * 2));
  const editorHeight = Math.min(editor.offsetHeight || 360, Math.max(1, box.height - margin * 2));
  const rects = annotation.rects?.length ? annotation.rects : [annotation];
  const bounds = annotationBounds(rects);
  const annotationLeft = bounds.x * box.width;
  const annotationTop = bounds.y * box.height;
  const annotationRight = (bounds.x + bounds.w) * box.width;
  const annotationBottom = (bounds.y + bounds.h) * box.height;
  const annotationRects = rects.map((rect) => ({
    left: rect.x * box.width,
    top: rect.y * box.height,
    right: (rect.x + rect.w) * box.width,
    bottom: (rect.y + rect.h) * box.height
  }));
  const maxLeft = Math.max(margin, box.width - editorWidth - margin);
  const maxTop = Math.max(margin, box.height - editorHeight - margin);
  const candidates = [
    { name: "below", left: annotationLeft, top: annotationBottom + gap, preference: 0 },
    { name: "above", left: annotationLeft, top: annotationTop - editorHeight - gap, preference: 20 },
    { name: "right", left: annotationRight + gap, top: annotationTop, preference: 40 },
    { name: "left", left: annotationLeft - editorWidth - gap, top: annotationTop, preference: 50 }
  ].map((candidate) => {
    const left = clamp(candidate.left, margin, maxLeft);
    const top = clamp(candidate.top, margin, maxTop);
    const editorRect = { left, top, right: left + editorWidth, bottom: top + editorHeight };
    const overlap = annotationRects.reduce((sum, rect) => sum + rectOverlapArea(editorRect, rect), 0);
    const clampPenalty = Math.abs(left - candidate.left) + Math.abs(top - candidate.top);
    const distance = Math.hypot(left - annotationLeft, top - annotationTop);
    return {
      ...candidate,
      left,
      top,
      score: overlap * 1000 + clampPenalty * 10 + distance * 0.02 + candidate.preference
    };
  }).sort((a, b) => a.score - b.score);

  editor.dataset.placement = candidates[0]?.name || "";
  editor.style.left = `${candidates[0]?.left ?? margin}px`;
  editor.style.top = `${candidates[0]?.top ?? margin}px`;
}

function keepAnnotationEditorInView(editor) {
  const viewer = elements.pdfViewer;
  if (!viewer || !editor) return;
  const margin = 18;
  const viewerBox = viewer.getBoundingClientRect();
  const editorBox = editor.getBoundingClientRect();
  let nextScrollTop = viewer.scrollTop;
  if (editorBox.bottom > viewerBox.bottom - margin) {
    nextScrollTop += editorBox.bottom - viewerBox.bottom + margin;
  }
  if (nextScrollTop !== viewer.scrollTop) {
    viewer.scrollTop = clamp(nextScrollTop, 0, Math.max(0, viewer.scrollHeight - viewer.clientHeight));
  }
}

function openAnnotationEditor(annotation, pageElement, options = {}) {
  closeNoteEditor();
  pdfState.selectedAnnotationId = annotation.id;
  renderAnnotationList();
  const overlay = pageElement.querySelector(".pdf-annotation-layer");
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!overlay || !canvas) return;

  const editor = document.createElement("form");
  editor.className = "pdf-annotation-editor";
  editor.tabIndex = -1;
  editor.dataset.annotationId = annotation.id;
  applyAnnotationColor(editor, annotation);
  editor.style.left = "10px";
  editor.style.top = "10px";
  editor.style.visibility = "hidden";
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
      const nextColor = PDF_COLORS[button.dataset.editorColor] ? button.dataset.editorColor : "yellow";
      if (annotation.color === nextColor) return;
      pushAnnotationHistory();
      annotation.color = nextColor;
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
    saveAnnotationEditorComment(editor);
    closeNoteEditor();
    renderAllAnnotations();
  });
  editor.querySelector("[data-annotation-delete]").addEventListener("click", () => {
    pushAnnotationHistory();
    pdfState.annotations = pdfState.annotations.filter((entry) => entry.id !== annotation.id);
    pdfState.selectedAnnotationId = "";
    clearAnnotationSelectionOutline();
    scheduleSaveAnnotations();
    closeNoteEditor();
    renderAllAnnotations();
  });
  pageElement.appendChild(editor);
  positionAnnotationEditor(editor, annotation, pageElement);
  editor.style.visibility = "";
  if (options.keepInView) keepAnnotationEditorInView(editor);
  pdfState.openEditor = editor;
  if (options.focusComment) {
    editor.querySelector("textarea").focus();
  } else {
    editor.focus({ preventScroll: true });
  }
}

function renderAllAnnotations() {
  closeNoteEditor();
  elements.pdfViewer.querySelectorAll(".pdf-page").forEach(renderAnnotationsForPage);
  renderAnnotationList();
}

function scrollToAnnotation(annotation, pageElement, behavior = "auto") {
  const viewer = elements.pdfViewer;
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!viewer || !canvas) return false;
  const rects = annotation.rects?.length ? annotation.rects : [annotation];
  const bounds = annotationBounds(rects);
  const targetY = (bounds.y + bounds.h / 2) * canvas.clientHeight;
  const viewportAnchor = Math.round(clamp(viewer.clientHeight * 0.38, 120, viewer.clientHeight * 0.45));
  const maxScroll = Math.max(0, viewer.scrollHeight - viewer.clientHeight);
  viewer.scrollTo({
    top: clamp(pageElement.offsetTop + targetY - viewportAnchor, 0, maxScroll),
    behavior
  });
  if (typeof updatePdfPageControl === "function") updatePdfPageControl(annotation.page);
  return true;
}

function jumpToAnnotation(annotationId, attempt = 0) {
  const annotation = pdfState.annotations.find((entry) => entry.id === annotationId);
  if (!annotation) return;
  pdfState.selectedAnnotationId = annotation.id;
  showAnnotationSelectionOutline(annotation.id);
  renderAllAnnotations();
  const pageElement = elements.pdfViewer.querySelector(`[data-page="${annotation.page}"]`);
  if (!pageElement && attempt < 20) {
    window.setTimeout(() => jumpToAnnotation(annotationId, attempt + 1), 80);
    return;
  }
  if (!pageElement) return;
  scrollToAnnotation(annotation, pageElement);
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
