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

function localFilePathFromHref(href) {
  const value = String(href || "").trim();
  if (!value) return "";
  if (value.startsWith("file://")) {
    try {
      return decodeURIComponent(new URL(value).pathname);
    } catch {
      return "";
    }
  }
  if (/^\/(?:Users|Volumes|Applications|opt|private|tmp|var|home)\//.test(value)) return value;
  return "";
}

function enableLocalFileLinks(root) {
  if (!root) return;
  root.querySelectorAll("a[href]").forEach((link) => {
    const path = localFilePathFromHref(link.getAttribute("href"));
    if (!path) return;
    link.dataset.localFilePath = path;
    link.setAttribute("title", `Open local file: ${path}`);
  });
}

async function handleNoteLocalFileLinkClick(event) {
  const link = event.target?.closest?.(".note-body a[data-local-file-path]");
  if (!link) return;
  const path = link.dataset.localFilePath || "";
  if (!path) return;
  event.preventDefault();
  try {
    const response = await fetch(getApiUrl("/api/open-local-file"), {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Paper-Notes-Local-Action": "open-local-file",
      },
      body: JSON.stringify({ path }),
    });
    if (!response.ok) {
      const detail = await readLocalFileOpenError(response);
      throw new Error(detail || "Could not open local file.");
    }
  } catch (error) {
    console.warn("Failed to open local file link.", error);
    showLocalFileOpenError(error);
  }
}

async function readLocalFileOpenError(response) {
  const contentType = response.headers.get("Content-Type") || "";
  if (contentType.includes("application/json")) {
    const payload = await response.json().catch(() => null);
    return payload?.error || payload?.message || "";
  }
  return response.text().catch(() => "");
}

function showLocalFileOpenError(error) {
  const message = error?.message || "Could not open local file.";
  if (typeof window.alert === "function") {
    window.alert(message);
  }
}

function extractGeneratedNoteBody(html, baseHref = window.location.href) {
  if (!html) return "";
  const documentBody = new DOMParser().parseFromString(html, "text/html");
  const note = documentBody.querySelector("main.note") || documentBody.body;
  absolutizeEmbeddedAssetUrls(note, baseHref);
  return note ? note.innerHTML : "";
}

function renderNoteMathExpression(source, displayMode = false) {
  const formula = String(source || "").trim();
  if (!formula) return null;
  const wrapper = document.createElement("span");
  wrapper.className = displayMode ? "note-math-block" : "note-math-inline";
  if (globalThis.katex?.renderToString) {
    wrapper.innerHTML = globalThis.katex.renderToString(formula, {
      displayMode,
      throwOnError: false,
      strict: "ignore",
      trust: false,
    });
  } else {
    wrapper.classList.add("note-math-fallback");
    wrapper.textContent = formula;
  }
  return wrapper;
}

function splitNoteMathSegments(text) {
  const segments = [];
  const source = String(text || "");
  const pattern = /\\\[([\s\S]*?)\\\]|\$\$([\s\S]*?)\$\$|\\\(([\s\S]*?)\\\)|(^|[^\\])\$([^\s$][^$\n]*?)\$/g;
  let cursor = 0;
  let match;
  while ((match = pattern.exec(source)) !== null) {
    const fullMatch = match[0];
    const prefix = match[4] || "";
    const start = match.index + prefix.length;
    const rawFormula = match[1] ?? match[2] ?? match[3] ?? match[5] ?? "";
    const displayMode = match[1] !== undefined || match[2] !== undefined;
    const formulaEnd = match.index + fullMatch.length;
    if (!rawFormula.trim()) continue;
    if (start > cursor) segments.push({ type: "text", value: source.slice(cursor, start) });
    segments.push({ type: "math", value: rawFormula, displayMode });
    cursor = formulaEnd;
  }
  if (!segments.length) return null;
  if (cursor < source.length) segments.push({ type: "text", value: source.slice(cursor) });
  return segments;
}

function renderMathInNote(root) {
  if (!root) return;
  const skipSelector = "script, style, textarea, pre, code, kbd, samp, .katex, .note-math-inline, .note-math-block";
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue || !/[\\$]/.test(node.nodeValue)) return NodeFilter.FILTER_REJECT;
      if (node.parentElement?.closest(skipSelector)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);
  textNodes.forEach((node) => {
    const segments = splitNoteMathSegments(node.nodeValue);
    if (!segments) return;
    const fragment = document.createDocumentFragment();
    segments.forEach((segment) => {
      if (segment.type === "text") {
        fragment.append(document.createTextNode(segment.value));
        return;
      }
      const rendered = renderNoteMathExpression(segment.value, segment.displayMode);
      if (rendered) fragment.append(rendered);
    });
    node.replaceWith(fragment);
  });
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
    const baseUrl = window.location.protocol === "file:" ? "http://localhost:8765/" : "";
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
  renderMathInNote(elements.notePage);
  enableLocalFileLinks(elements.notePage);
  elements.notePage.removeEventListener("click", handleNoteLocalFileLinkClick);
  elements.notePage.addEventListener("click", handleNoteLocalFileLinkClick);
  elements.notePage.removeEventListener("copy", handleRichTextCopy);
  elements.notePage.addEventListener("copy", handleRichTextCopy);
  if (typeof window.buildNoteMenu === "function") window.buildNoteMenu(elements.notePage);
  mountReaderNoteMenu();
  finishNoteScrollRestore(notePositionToRestore);
}

async function refreshReaderNoteBody({ preserveScroll = true } = {}) {
  const note = readerState.note;
  if (!note || !elements.notePage) return false;
  const generatedNoteBody = await fetchGeneratedNoteBody(note);
  if (!generatedNoteBody) return false;
  const scrollPosition = preserveScroll ? currentNoteScrollPosition() : null;
  const collectionPath = readerState.library ? getCollectionPath(readerState.library, note.categoryId) : "";
  renderReaderNoteBody(note, collectionPath, generatedNoteBody, scrollPosition);
  return true;
}

function scheduleReaderNoteRefresh({ delay = 180 } = {}) {
  if (!readerState.note?.htmlHref) return;
  if (readerState.noteRefreshInFlight) {
    readerState.noteRefreshQueued = true;
    return;
  }
  window.clearTimeout(readerState.noteRefreshTimer);
  readerState.noteRefreshTimer = window.setTimeout(async () => {
    readerState.noteRefreshTimer = 0;
    readerState.noteRefreshInFlight = true;
    try {
      await refreshReaderNoteBody();
    } catch (error) {
      console.warn("Failed to refresh HTML note after tool update.", error);
    } finally {
      readerState.noteRefreshInFlight = false;
      if (readerState.noteRefreshQueued) {
        readerState.noteRefreshQueued = false;
        scheduleReaderNoteRefresh({ delay: 80 });
      }
    }
  }, delay);
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
