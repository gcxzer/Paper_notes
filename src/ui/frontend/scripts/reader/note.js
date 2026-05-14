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

function setHtmlPaneLink(note) {
  if (!elements.htmlPaneToggle) return;
  const htmlHref = note.htmlHref ? new URL(note.htmlHref, window.location.href).href : "#";
  elements.htmlPaneToggle.setAttribute("href", htmlHref);
  elements.htmlPaneToggle.toggleAttribute("target", Boolean(note.htmlHref));
  if (note.htmlHref) {
    elements.htmlPaneToggle.setAttribute("target", "_blank");
    elements.htmlPaneToggle.setAttribute("rel", "noopener");
    elements.htmlPaneToggle.setAttribute("title", "Open HTML note in a new tab");
  } else {
    elements.htmlPaneToggle.removeAttribute("rel");
    elements.htmlPaneToggle.removeAttribute("title");
  }
}

function renderReaderNoteBody(note, collectionPath, generatedNoteBody, notePositionToRestore) {
  pdfState.suppressNoteScrollSave = true;
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
  finishNoteScrollRestore(notePositionToRestore);
}

async function renderReader(library, note) {
  readerState.library = library;
  readerState.note = note;
  const collectionPath = getCollectionPath(library, note.categoryId);
  const notePositionToRestore = storedNoteScrollPosition(note.id);
  setHtmlPaneLink(note);
  elements.title.textContent = note.title;
  elements.kicker.textContent = collectionPath;

  const storedFilePromise = readPaperFile(note.pdfStorageKey || note.id).catch((error) => {
    console.warn("Failed to read stored paper file.", error);
    return null;
  });
  const generatedNoteBodyPromise = fetchGeneratedNoteBody(note);
  let renderedNoteBody = false;
  const renderGeneratedNoteBodyPromise = generatedNoteBodyPromise.then((generatedNoteBody) => {
    if (generatedNoteBody && !renderedNoteBody) {
      renderReaderNoteBody(note, collectionPath, generatedNoteBody, notePositionToRestore);
      renderedNoteBody = true;
    }
    return generatedNoteBody;
  });
  const storedFile = await storedFilePromise;
  const storedNoteBody = extractGeneratedNoteBody(storedFile?.noteHtml);
  if (storedNoteBody && !renderedNoteBody) {
    renderReaderNoteBody(note, collectionPath, storedNoteBody, notePositionToRestore);
    renderedNoteBody = true;
  }
  const pdfHref = storedFile?.pdfBlob ? URL.createObjectURL(storedFile.pdfBlob) : note.href || "#";
  if (!renderedNoteBody) await renderGeneratedNoteBodyPromise;
  if (!renderedNoteBody) {
    renderReaderNoteBody(note, collectionPath, "", notePositionToRestore);
  }
  await initializeReaderChatSessions();
  await loadPdf(pdfHref, note.id);
}
