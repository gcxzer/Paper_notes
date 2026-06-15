function selectedPdfPagesForChatContext() {
  if (typeof selectedPdfPages === "function") return selectedPdfPages();
  const selection = window.getSelection?.();
  if (!selection || selection.isCollapsed || !elements.pdfViewer) return [];
  return Array.from(elements.pdfViewer.querySelectorAll(".pdf-page")).filter((pageElement) => {
    const textLayer = pageElement.querySelector(".textLayer");
    if (!textLayer) return false;
    for (let index = 0; index < selection.rangeCount; index += 1) {
      const range = selection.getRangeAt(index);
      try {
        if (range.intersectsNode(textLayer)) return true;
      } catch (error) {
        // A page can detach while PDF.js rerenders; ignore that transient state.
      }
    }
    return false;
  });
}

function normalizeReaderSelectedPdfText(text) {
  const normalized = typeof normalizeCopiedPdfText === "function"
    ? normalizeCopiedPdfText(text)
    : normalizeText(text);
  return normalizeText(normalized).slice(0, 4000);
}

function currentReaderSelectedPdfText() {
  return normalizeReaderSelectedPdfText(readerState.selectedPdfText);
}

function captureReaderPdfSelectionRanges() {
  const selection = window.getSelection?.();
  if (!selection || selection.isCollapsed || !selectedPdfPagesForChatContext().length) {
    readerState.selectedPdfRanges = [];
    return [];
  }
  const ranges = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    try {
      ranges.push(selection.getRangeAt(index).cloneRange());
    } catch (error) {
      // Ignore ranges that disappear during PDF rerender or browser selection churn.
    }
  }
  readerState.selectedPdfRanges = ranges;
  return ranges;
}

function restoreReaderPdfSelectionRanges() {
  const ranges = Array.isArray(readerState.selectedPdfRanges) ? readerState.selectedPdfRanges : [];
  if (!ranges.length) return false;
  const selection = window.getSelection?.();
  if (!selection) return false;
  try {
    selection.removeAllRanges();
    ranges.forEach((range) => selection.addRange(range.cloneRange()));
    if (typeof schedulePdfSelectionOverlayRender === "function") schedulePdfSelectionOverlayRender();
    return true;
  } catch (error) {
    readerState.selectedPdfRanges = [];
    return false;
  }
}

function renderSavedReaderPdfSelectionOverlay() {
  if (typeof renderPdfSelectionOverlaysFromRanges !== "function") return false;
  return renderPdfSelectionOverlaysFromRanges(readerState.selectedPdfRanges);
}

function isEditableAskPaneTarget(target) {
  const element = target?.nodeType === Node.ELEMENT_NODE ? target : target?.parentElement;
  return Boolean(element?.closest?.("input, textarea, [contenteditable='true'], [contenteditable='']"));
}

function isSelectedTextRemoveTarget(target) {
  const element = target?.nodeType === Node.ELEMENT_NODE ? target : target?.parentElement;
  return Boolean(element?.closest?.("[data-selected-text-remove]"));
}

function setReaderSelectedPdfText(text, page = "") {
  const normalized = normalizeReaderSelectedPdfText(text);
  if (!normalized) return false;
  const normalizedPage = normalizeText(page);
  const changed = normalized !== readerState.selectedPdfText || normalizedPage !== readerState.selectedPdfPage;
  readerState.selectedPdfText = normalized;
  readerState.selectedPdfPage = normalizedPage;
  captureReaderPdfSelectionRanges();
  if (changed) renderAttachmentTray();
  return true;
}

function selectedPdfTextContextFromState() {
  const text = currentReaderSelectedPdfText();
  if (!text) return null;
  return {
    type: "selected_text",
    text,
    page: normalizeText(readerState.selectedPdfPage),
    wordCount: text.split(/\s+/).filter(Boolean).length
  };
}

function snapshotReaderSelectedPdfTextForSubmit() {
  readerState.pendingSelectedTextContext = selectedPdfTextContextFromState();
}

function clearReaderSelectedPdfText({ clearNativeSelection = false } = {}) {
  readerState.selectedPdfText = "";
  readerState.selectedPdfPage = "";
  readerState.selectedPdfRanges = [];
  readerState.selectedPdfPointerRegion = "";
  readerState.preservePdfSelectionUntil = 0;
  if (clearNativeSelection) {
    window.getSelection?.()?.removeAllRanges?.();
    if (typeof clearPdfSelectionOverlays === "function") clearPdfSelectionOverlays();
  }
  renderAttachmentTray();
}

function keepSelectedPdfContextWithoutNativeSelection() {
  if (!currentReaderSelectedPdfText()) return;
  readerState.selectedPdfRanges = [];
  readerState.selectedPdfPointerRegion = "ask";
  readerState.preservePdfSelectionUntil = 0;
  renderAttachmentTray();
}

function clearNativePdfSelectionOnly({ preserveSelectedText = false } = {}) {
  if (preserveSelectedText) keepSelectedPdfContextWithoutNativeSelection();
  window.getSelection?.()?.removeAllRanges?.();
  if (typeof clearPdfSelectionOverlays === "function") clearPdfSelectionOverlays();
}

function handleReaderSelectedPdfPointerDown(event) {
  const askTarget = elements.askPane?.contains(event.target);
  if (!currentReaderSelectedPdfText()) {
    if (askTarget && selectedPdfPagesForChatContext().length) clearNativePdfSelectionOnly();
    return;
  }
  if (isSelectedTextRemoveTarget(event.target)) return;
  if (!askTarget) {
    readerState.selectedPdfPointerRegion = "outside";
    clearReaderSelectedPdfText({ clearNativeSelection: true });
    return;
  }

  readerState.selectedPdfPointerRegion = "ask";
  clearNativePdfSelectionOnly({ preserveSelectedText: true });
}

function shouldRestoreReaderPdfSelection() {
  if (isEditableAskPaneTarget(document.activeElement)) return false;
  return currentReaderSelectedPdfText()
    && Date.now() <= Number(readerState.preservePdfSelectionUntil || 0)
    && Array.isArray(readerState.selectedPdfRanges)
    && readerState.selectedPdfRanges.length > 0;
}

function refreshReaderSelectedPdfTextFromSelection() {
  const pages = selectedPdfPagesForChatContext();
  if (!pages.length) {
    if (shouldRestoreReaderPdfSelection() && restoreReaderPdfSelectionRanges()) return true;
    if (readerState.selectedPdfPointerRegion === "ask" && currentReaderSelectedPdfText()) {
      if (typeof clearPdfSelectionOverlays === "function") clearPdfSelectionOverlays();
      return true;
    }
    clearReaderSelectedPdfText();
    return false;
  }
  const text = typeof textFromPdfSelection === "function"
    ? textFromPdfSelection()
    : window.getSelection?.()?.toString() || "";
  const page = normalizeText(pages[0]?.dataset?.page);
  return setReaderSelectedPdfText(text, page);
}

function imageFilesFromClipboard(event) {
  const data = event?.clipboardData;
  if (!data) return [];
  const files = Array.from(data.files || []).filter(isImageFile);
  if (files.length) return files;
  return Array.from(data.items || [])
    .filter((item) => item?.kind === "file" && String(item.type || "").startsWith("image/"))
    .map((item) => item.getAsFile?.())
    .filter(isImageFile);
}

function handleReaderImagePaste(event) {
  const files = imageFilesFromClipboard(event);
  if (!files.length) return;
  event.preventDefault();
  event.stopPropagation();
  if (!activeProviderSupportsImageInput()) {
    setReaderChatError(activeProviderImageInputUnsupportedMessage());
    return;
  }
  handleReaderAttachmentFiles(files);
}
