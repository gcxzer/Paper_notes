function noteForChatSource(source) {
  if (!readerState.library?.notes) return readerState.note;
  if (source.noteId) {
    const byId = readerState.library.notes.find((note) => note.id === source.noteId);
    if (byId) return byId;
  }
  const locator = source.uri;
  if (locator) {
    const byHref = readerState.library.notes.find((note) => (
      [note.href, note.htmlHref].some((href) => href && locator.includes(href))
    ));
    if (byHref) return byHref;
  }
  return readerState.note;
}

function annotationKindFromSource(source) {
  const match = source.excerpt.match(/###\s+([A-Za-z]+)/);
  return match ? match[1].toLowerCase() : "annotation";
}

function chatSourceLabel(source) {
  if (source.label) return source.label;
  const note = noteForChatSource(source);
  const title = note?.title || "Paper";
  const page = source.page ? ` page ${source.page}` : "";
  if (source.type === "pdf") return `PDF: ${title}${page}`;
  if (source.type === "note") return `Note: ${title} note.html`;
  if (source.type === "annotation") return `Annotation:${page || ""} ${annotationKindFromSource(source)}`.replace("  ", " ").trim();
  return source.uri || "Source";
}

function renderChatSources(sources) {
  if (!sources.length) return "";
  return `
    <div class="ask-sources" aria-label="Sources">
      ${sources.map((source) => `
        <button
          class="ask-source"
          type="button"
          data-source-type="${escapeHtml(source.type)}"
          data-source-page="${source.page || ""}"
          data-source-uri="${escapeHtml(encodeURIComponent(source.uri))}"
          data-source-note-id="${escapeHtml(source.noteId)}"
          title="${escapeHtml(source.excerpt || source.uri || chatSourceLabel(source))}"
        >${escapeHtml(chatSourceLabel(source))}</button>
      `).join("")}
    </div>
  `;
}

function activateChatSource(source) {
  if (source.type === "note") {
    setHtmlPaneVisible(true);
    elements.notePane?.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (source.type === "pdf" || source.type === "annotation") {
    if (source.type === "annotation") setAnnotationSidebarCollapsed(false);
    if (source.page) scrollToPdfPage(source.page, "auto");
  }
}

function handleChatSourceClick(event) {
  const button = event.target.closest(".ask-source");
  if (!button) return;
  event.preventDefault();
  activateChatSource({
    type: normalizeText(button.dataset.sourceType) || "source",
    page: Number(button.dataset.sourcePage) || null,
    uri: decodeURIComponent(button.dataset.sourceUri || ""),
    noteId: normalizeText(button.dataset.sourceNoteId)
  });
}
