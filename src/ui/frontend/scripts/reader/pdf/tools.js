function initializePdfTools() {
  elements.colorButtons.forEach((button) => {
    const color = PDF_COLORS[button.dataset.pdfColor];
    if (!color) return;
    button.style.backgroundColor = color.hex;
    button.style.setProperty("--swatch", color.hex);
  });
  elements.modeButtons.forEach((button) => {
    button.addEventListener("click", () => togglePdfMode(button.dataset.pdfMode || "pan"));
  });
  elements.colorButtons.forEach((button) => {
    button.addEventListener("click", () => setPdfColor(button.dataset.pdfColor || "yellow"));
  });
  elements.annotationUndo?.addEventListener("click", undoAnnotationChange);
  elements.annotationRedo?.addEventListener("click", redoAnnotationChange);
  elements.pdfLinkBack?.addEventListener("click", returnFromPdfLink);
  elements.pdfLinkDismiss?.addEventListener("click", hidePdfLinkBackButton);
  document.addEventListener("keydown", handleAnnotationKeyboard);
  document.addEventListener("pointerdown", handleAnnotationEditorOutsidePointer, true);
  document.addEventListener("selectionchange", () => {
    schedulePdfSelectionOverlayRender();
    if (typeof refreshReaderSelectedPdfTextFromSelection === "function") {
      window.requestAnimationFrame(refreshReaderSelectedPdfTextFromSelection);
    }
  });
  window.addEventListener("resize", schedulePdfSelectionOverlayRender);
  elements.pdfViewer?.addEventListener("scroll", schedulePdfSelectionOverlayRender, { passive: true });
  elements.zoomIn?.addEventListener("click", async () => {
    pdfState.scale = clamp(Math.round((pdfState.scale + PDF_SCALE_STEP) * 100) / 100, PDF_MIN_SCALE, PDF_MAX_SCALE);
    persistPdfScale();
    await renderPdf();
  });
  elements.zoomOut?.addEventListener("click", async () => {
    pdfState.scale = clamp(Math.round((pdfState.scale - PDF_SCALE_STEP) * 100) / 100, PDF_MIN_SCALE, PDF_MAX_SCALE);
    persistPdfScale();
    await renderPdf();
  });
  initializePdfPageControl();
  setPdfMode("pan");
  setPdfColor("yellow");
  updateAnnotationHistoryButtons();
}
