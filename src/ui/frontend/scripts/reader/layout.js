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

function readerDividerWidth() {
  const value = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--reader-resizer-width"));
  return Number.isFinite(value) ? value : 10;
}

function visibleAskPaneWidth() {
  if (!elements.askPane || elements.layout?.classList.contains("is-ask-pane-hidden")) return 0;
  return elements.askPane.getBoundingClientRect().width || 360;
}

function visibleAskDividerWidth() {
  if (!elements.askResizer || elements.layout?.classList.contains("is-ask-pane-hidden")) return 0;
  return readerDividerWidth();
}

function maxSplitPercentForLayout() {
  const rect = elements.layout?.getBoundingClientRect();
  if (!rect?.width || elements.layout?.classList.contains("is-html-pane-hidden")) return 75;
  const reservedWidth = splitState.minNoteWidth + visibleAskPaneWidth() + readerDividerWidth() + visibleAskDividerWidth();
  return clamp(((rect.width - reservedWidth) / rect.width) * 100, 25, 75);
}

function setSplitPercent(percent) {
  const nextPercent = clamp(percent, 25, maxSplitPercentForLayout());
  document.documentElement.style.setProperty("--pdf-pane-width", `${nextPercent}%`);
  elements.resizer?.setAttribute("aria-valuenow", String(Math.round(nextPercent)));
  elements.resizer?.setAttribute("aria-valuemin", "25");
  elements.resizer?.setAttribute("aria-valuemax", String(Math.round(maxSplitPercentForLayout())));
  localStorage.setItem(READER_SPLIT_KEY, String(nextPercent));
}

function updateSplitFromClientX(clientX) {
  const rect = elements.layout.getBoundingClientRect();
  const maxPdfWidth = rect.width - splitState.minNoteWidth - visibleAskPaneWidth() - readerDividerWidth() - visibleAskDividerWidth();
  const pdfWidth = clamp(clientX - rect.left, splitState.minPdfWidth, maxPdfWidth);
  setSplitPercent((pdfWidth / rect.width) * 100);
}

function readAskWidth() {
  const value = Number(localStorage.getItem(ASK_WIDTH_KEY));
  return Number.isFinite(value) ? value : 360;
}

function maxAskWidthForLayout() {
  const rect = elements.layout?.getBoundingClientRect();
  if (!rect?.width) return 560;
  const dividerWidth = readerDividerWidth();
  const htmlHidden = elements.layout?.classList.contains("is-html-pane-hidden");
  if (htmlHidden) {
    return Math.max(splitState.minAskWidth, rect.width - splitState.minPdfWidth - dividerWidth);
  }

  const pdfWidth = elements.pdfViewer?.closest(".pdf-pane")?.getBoundingClientRect().width
    || (rect.width * readSplitPercent()) / 100;
  return Math.max(splitState.minAskWidth, rect.width - pdfWidth - splitState.minNoteWidth - (dividerWidth * 2));
}

function setAskWidth(width) {
  const nextWidth = Math.round(clamp(width, splitState.minAskWidth, maxAskWidthForLayout()));
  document.documentElement.style.setProperty("--ask-pane-width", `${nextWidth}px`);
  elements.askResizer?.setAttribute("aria-valuenow", String(nextWidth));
  elements.askResizer?.setAttribute("aria-valuemin", String(splitState.minAskWidth));
  elements.askResizer?.setAttribute("aria-valuemax", String(Math.round(maxAskWidthForLayout())));
  localStorage.setItem(ASK_WIDTH_KEY, String(nextWidth));
}

function updateAskWidthFromClientX(clientX) {
  const rect = elements.layout.getBoundingClientRect();
  setAskWidth(rect.right - clientX);
}

function initializeResizer() {
  setSplitPercent(readSplitPercent());
  setAskWidth(readAskWidth());
  if (!elements.resizer) return;

  const finishMainResize = (event) => {
    if (!splitState.dragging) return;
    splitState.dragging = false;
    releasePointerCaptureSafely(elements.resizer, event?.pointerId);
    setReaderResizerActive(elements.resizer, false);
  };

  elements.resizer.addEventListener("pointerdown", (event) => {
    if (window.matchMedia("(max-width: 900px)").matches) return;
    splitState.dragging = true;
    elements.resizer.setPointerCapture(event.pointerId);
    setReaderResizerActive(elements.resizer, true);
    updateSplitFromClientX(event.clientX);
    event.preventDefault();
  });

  elements.resizer.addEventListener("pointermove", (event) => {
    if (!splitState.dragging) return;
    updateSplitFromClientX(event.clientX);
  });

  elements.resizer.addEventListener("pointerup", finishMainResize);
  elements.resizer.addEventListener("pointercancel", finishMainResize);
  elements.resizer.addEventListener("lostpointercapture", finishMainResize);

  elements.resizer.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -2 : 2;
    setSplitPercent(readSplitPercent() + delta);
  });

  if (!elements.askResizer) return;

  const finishAskResize = (event) => {
    if (!splitState.askDragging) return;
    splitState.askDragging = false;
    releasePointerCaptureSafely(elements.askResizer, event?.pointerId);
    setReaderResizerActive(elements.askResizer, false);
  };

  elements.askResizer.addEventListener("pointerdown", (event) => {
    if (window.matchMedia("(max-width: 900px)").matches) return;
    if (elements.layout?.classList.contains("is-ask-pane-hidden")) return;
    splitState.askDragging = true;
    elements.askResizer.setPointerCapture(event.pointerId);
    setReaderResizerActive(elements.askResizer, true);
    updateAskWidthFromClientX(event.clientX);
    event.preventDefault();
  });

  elements.askResizer.addEventListener("pointermove", (event) => {
    if (!splitState.askDragging) return;
    updateAskWidthFromClientX(event.clientX);
  });

  elements.askResizer.addEventListener("pointerup", finishAskResize);
  elements.askResizer.addEventListener("pointercancel", finishAskResize);
  elements.askResizer.addEventListener("lostpointercapture", finishAskResize);

  elements.askResizer.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? 24 : -24;
    setAskWidth(readAskWidth() + delta);
    setSplitPercent(readSplitPercent());
  });
}

function readPdfScrollStore() {
  try {
    const raw = localStorage.getItem(PDF_SCROLL_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (error) {
    console.warn("Failed to read PDF scroll position.", error);
    return {};
  }
}

function writePdfScrollStore(store) {
  try {
    localStorage.setItem(PDF_SCROLL_KEY, JSON.stringify(store));
  } catch (error) {
    console.warn("Failed to save PDF scroll position.", error);
  }
}

function pdfScrollAnchorOffset() {
  const viewer = elements.pdfViewer;
  if (!viewer) return 0;
  return Math.round(clamp(viewer.clientHeight * 0.18, 64, 180));
}

function pdfPageCount() {
  return Number(pdfState.document?.numPages || pdfState.document?._pdfInfo?.numPages || 0);
}

function currentPdfScrollPosition() {
  const viewer = elements.pdfViewer;
  if (!viewer || !pdfState.noteId) return null;
  const pages = Array.from(viewer.querySelectorAll(".pdf-page"));
  if (!pages.length) return null;

  const anchorOffset = pdfScrollAnchorOffset();
  const anchorTop = viewer.scrollTop + anchorOffset;
  let bestPage = null;
  let bestDistance = Number.POSITIVE_INFINITY;

  pages.forEach((pageElement) => {
    const pageTop = pageElement.offsetTop;
    const pageBottom = pageTop + pageElement.offsetHeight;
    const distance = pageTop <= anchorTop && pageBottom >= anchorTop
      ? 0
      : Math.min(Math.abs(pageTop - anchorTop), Math.abs(pageBottom - anchorTop));
    if (distance < bestDistance) {
      bestDistance = distance;
      bestPage = { element: pageElement, pageTop, pageHeight: pageElement.offsetHeight };
    }
  });

  if (!bestPage) return null;
  return {
    page: Number(bestPage.element.dataset.page) || 1,
    offset: clamp((anchorTop - bestPage.pageTop) / Math.max(1, bestPage.pageHeight), 0, 1),
    scrollTop: viewer.scrollTop,
    scale: pdfState.scale,
    updatedAt: Date.now()
  };
}

function storedPdfScrollPosition() {
  if (!pdfState.noteId) return null;
  return readPdfScrollStore()[pdfState.noteId] || null;
}

function storedPdfScale(noteId = pdfState.noteId) {
  if (!noteId) return null;
  const scale = Number(readPdfScrollStore()[noteId]?.scale);
  return Number.isFinite(scale) ? clamp(scale, PDF_MIN_SCALE, PDF_MAX_SCALE) : null;
}

function restoreStoredPdfScale(noteId = pdfState.noteId) {
  const scale = storedPdfScale(noteId);
  if (scale == null) return;
  pdfState.scale = scale;
  if (elements.zoomLabel) elements.zoomLabel.textContent = `${Math.round(scale * 100)}%`;
}

function persistPdfScale() {
  if (!pdfState.noteId) return;
  const store = readPdfScrollStore();
  store[pdfState.noteId] = {
    ...(store[pdfState.noteId] || {}),
    scale: pdfState.scale,
    updatedAt: Date.now()
  };
  writePdfScrollStore(store);
}

function persistPdfScrollPosition() {
  if (pdfState.suppressScrollSave) return;
  const position = currentPdfScrollPosition();
  if (!position || !pdfState.noteId) return;
  const store = readPdfScrollStore();
  store[pdfState.noteId] = position;
  writePdfScrollStore(store);
}

function schedulePersistPdfScrollPosition() {
  if (pdfState.suppressScrollSave) {
    capturePdfScrollRestoreOverride();
    return;
  }
  updatePdfPageControl();
  window.clearTimeout(pdfState.scrollSaveTimer);
  pdfState.scrollSaveTimer = window.setTimeout(persistPdfScrollPosition, 120);
}

function clearPendingPdfScrollRestore() {
  window.cancelAnimationFrame(pdfState.scrollRestoreFrame);
  window.clearTimeout(pdfState.scrollRestoreTimer);
  pdfState.scrollRestoreFrame = 0;
  pdfState.scrollRestoreTimer = 0;
}

function beginPdfScrollRestore() {
  clearPendingPdfScrollRestore();
  pdfState.scrollRestoreGeneration += 1;
  pdfState.scrollRestoreInterrupted = false;
  pdfState.scrollRestoreOverridePosition = null;
  return pdfState.scrollRestoreGeneration;
}

function interruptPdfScrollRestore() {
  if (!pdfState.suppressScrollSave || pdfState.scrollRestoreInterrupted) return;
  pdfState.scrollRestoreInterrupted = true;
  clearPendingPdfScrollRestore();
}

function capturePdfScrollRestoreOverride() {
  const viewer = elements.pdfViewer;
  if (!pdfState.suppressScrollSave || !viewer) return;
  const position = currentPdfScrollPosition();
  if (!position) return;
  pdfState.scrollRestoreInterrupted = true;
  pdfState.scrollRestoreOverridePosition = position;
  clearPendingPdfScrollRestore();
  updatePdfPageControl(position.page);
}

function canRestorePdfScroll(generation) {
  return generation === pdfState.scrollRestoreGeneration && !pdfState.scrollRestoreInterrupted;
}

function finalizePdfScrollRestore(generation) {
  clearPendingPdfScrollRestore();
  if (generation !== pdfState.scrollRestoreGeneration) return;
  pdfState.suppressScrollSave = false;
  pdfState.scrollRestoreOverridePosition = null;
  persistPdfScrollPosition();
  updatePdfPageControl();
}

function pdfScrollTopFromPosition(position) {
  const viewer = elements.pdfViewer;
  if (!viewer || !position) return null;
  const pageElement = viewer.querySelector(`.pdf-page[data-page="${Number(position.page) || 1}"]`);
  if (!pageElement) {
    return Number.isFinite(position.scrollTop) ? position.scrollTop : null;
  }

  const anchorOffset = pdfScrollAnchorOffset();
  const pageOffset = clamp(Number(position.offset) || 0, 0, 1) * pageElement.offsetHeight;
  return pageElement.offsetTop + pageOffset - anchorOffset;
}

function scrollToPdfPosition(position, behavior = "auto") {
  const viewer = elements.pdfViewer;
  const top = pdfScrollTopFromPosition(position);
  if (!viewer || top == null) return false;
  viewer.scrollTo({ top, behavior });
  return true;
}

function scrollToPdfPage(pageNumber, behavior = "smooth") {
  const viewer = elements.pdfViewer;
  const count = pdfPageCount();
  if (!viewer || !count) return false;
  const targetPage = clamp(Math.round(Number(pageNumber) || 1), 1, count);
  const pageElement = viewer.querySelector(`.pdf-page[data-page="${targetPage}"]`);
  if (!pageElement) return false;
  viewer.scrollTo({
    top: pageElement.offsetTop,
    behavior
  });
  if (typeof renderVisiblePdfPages === "function") {
    renderVisiblePdfPages(pdfState.renderToken, pdfState.scale);
  }
  updatePdfPageControl(targetPage);
  return true;
}

function restorePdfScrollPosition(position) {
  scrollToPdfPosition(position, "auto");
}

function finishPdfScrollRestore(position, generation = pdfState.scrollRestoreGeneration) {
  if (canRestorePdfScroll(generation)) restorePdfScrollPosition(position);
  updatePdfPageControl();
  clearPendingPdfScrollRestore();
  pdfState.scrollRestoreFrame = window.requestAnimationFrame(() => {
    pdfState.scrollRestoreFrame = 0;
    if (canRestorePdfScroll(generation)) restorePdfScrollPosition(position);
    updatePdfPageControl();
    pdfState.scrollRestoreTimer = window.setTimeout(() => {
      pdfState.scrollRestoreTimer = 0;
      finalizePdfScrollRestore(generation);
    }, 80);
  });
}

function finishPdfScrollAfterEarlyRestore(generation = pdfState.scrollRestoreGeneration) {
  updatePdfPageControl();
  clearPendingPdfScrollRestore();
  pdfState.scrollRestoreFrame = window.requestAnimationFrame(() => {
    pdfState.scrollRestoreFrame = 0;
    updatePdfPageControl();
    pdfState.scrollRestoreTimer = window.setTimeout(() => {
      pdfState.scrollRestoreTimer = 0;
      finalizePdfScrollRestore(generation);
    }, 80);
  });
}

function initializePdfScrollPersistence() {
  elements.pdfViewer?.addEventListener("scroll", schedulePersistPdfScrollPosition, { passive: true });
  elements.pdfViewer?.addEventListener("wheel", interruptPdfScrollRestore, { passive: true });
  elements.pdfViewer?.addEventListener("touchstart", interruptPdfScrollRestore, { passive: true });
  elements.pdfViewer?.addEventListener("pointerdown", interruptPdfScrollRestore, { passive: true });
  elements.pdfViewer?.addEventListener("keydown", (event) => {
    if (!["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " ", "Spacebar"].includes(event.key)) return;
    interruptPdfScrollRestore();
  });
  window.addEventListener("beforeunload", persistPdfScrollPosition);
}

function updatePdfPageControl(forcedPage = null) {
  const count = pdfPageCount();
  if (elements.pdfPageTotal) elements.pdfPageTotal.textContent = `/ ${count || 0}`;
  if (elements.pdfPageInput) {
    elements.pdfPageInput.disabled = !count;
    elements.pdfPageInput.setAttribute("aria-label", count ? `PDF page number, 1 to ${count}` : "PDF page number");
    if (count) elements.pdfPageInput.setAttribute("data-max-page", String(count));
    const position = forcedPage ? { page: forcedPage } : currentPdfScrollPosition();
    const page = clamp(Number(position?.page) || 1, 1, Math.max(1, count || 1));
    if (document.activeElement !== elements.pdfPageInput) {
      elements.pdfPageInput.value = String(page);
    }
  }
}

function commitPdfPageInput() {
  const count = pdfPageCount();
  if (!count || !elements.pdfPageInput) return;
  const rawPage = Number(elements.pdfPageInput.value.replace(/[^\d]/g, ""));
  if (!Number.isFinite(rawPage) || rawPage < 1) {
    updatePdfPageControl();
    return;
  }
  const targetPage = clamp(Math.round(rawPage), 1, count);
  const returnPosition = currentPdfScrollPosition();
  const didNavigate = scrollToPdfPage(targetPage, "auto");
  if (
    didNavigate
    && returnPosition
    && Number(returnPosition.page) !== targetPage
    && typeof showPdfLinkBackButton === "function"
  ) {
    showPdfLinkBackButton(returnPosition);
  }
}

function initializePdfPageControl() {
  if (!elements.pdfPageInput) return;
  elements.pdfPageInput.addEventListener("focus", () => {
    elements.pdfPageInput.select();
  });
  elements.pdfPageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitPdfPageInput();
      elements.pdfPageInput.blur();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      updatePdfPageControl();
      elements.pdfPageInput.blur();
    }
  });
  elements.pdfPageInput.addEventListener("blur", commitPdfPageInput);
  updatePdfPageControl();
}
