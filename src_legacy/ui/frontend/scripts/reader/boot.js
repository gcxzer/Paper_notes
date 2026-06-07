async function initialize() {
  if (window.location.protocol === "file:") {
    showStartupError("Open http://localhost:4173 instead of opening reader.html directly.");
    return;
  }
  if (!pdfjsLib) {
    showStartupError("PDF.js did not load. Refresh the page or restart the local server.");
    return;
  }
  initializeAnnotationSidebar();
  initializeHtmlPaneToggle();
  initializeAskPaneToggle();
  initializeResizer();
  initializeReaderChat();
  initializeHtmlZoom();
  initializePdfTools();
  initializePdfSearch();
  initializePdfScrollPersistence();
  initializeNoteScrollPersistence();
  void loadReaderToolSettings({ silent: true });
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
