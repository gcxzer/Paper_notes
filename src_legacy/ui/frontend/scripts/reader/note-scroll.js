function readNoteScrollStore() {
  try {
    const raw = localStorage.getItem(NOTE_SCROLL_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (error) {
    console.warn("Failed to read note scroll position.", error);
    return {};
  }
}

function writeNoteScrollStore(store) {
  try {
    localStorage.setItem(NOTE_SCROLL_KEY, JSON.stringify(store));
  } catch (error) {
    console.warn("Failed to save note scroll position.", error);
  }
}

function noteScrollAnchorOffset() {
  const pane = elements.notePane;
  if (!pane) return 0;
  return Math.round(clamp(pane.clientHeight * 0.16, 56, 150));
}

function noteScrollAnchorElements() {
  if (!elements.notePage) return [];
  return Array.from(elements.notePage.querySelectorAll("h1, h2, h3, h4, p, li, figure, img, table, pre, blockquote"))
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
}

function currentNoteScrollPosition() {
  const pane = elements.notePane;
  if (!pane || !pdfState.noteId) return null;
  const maxScroll = Math.max(0, pane.scrollHeight - pane.clientHeight);
  const paneBox = pane.getBoundingClientRect();
  const anchorOffset = noteScrollAnchorOffset();
  const anchorY = paneBox.top + anchorOffset;
  const anchors = noteScrollAnchorElements();
  let bestAnchor = null;
  let bestDistance = Number.POSITIVE_INFINITY;

  anchors.forEach((element, index) => {
    const rect = element.getBoundingClientRect();
    const distance = rect.top <= anchorY && rect.bottom >= anchorY
      ? 0
      : Math.min(Math.abs(rect.top - anchorY), Math.abs(rect.bottom - anchorY));
    if (distance < bestDistance) {
      bestDistance = distance;
      bestAnchor = { element, index, rect };
    }
  });

  return {
    scrollTop: pane.scrollTop,
    ratio: maxScroll ? pane.scrollTop / maxScroll : 0,
    anchorId: bestAnchor?.element.id || "",
    anchorIndex: bestAnchor?.index ?? -1,
    anchorOffset: bestAnchor ? clamp((anchorY - bestAnchor.rect.top) / Math.max(1, bestAnchor.rect.height), 0, 1) : 0,
    updatedAt: Date.now()
  };
}

function storedNoteScrollPosition(noteId = pdfState.noteId) {
  if (!noteId) return null;
  return readNoteScrollStore()[noteId] || null;
}

function persistNoteScrollPosition() {
  if (pdfState.suppressNoteScrollSave) return;
  const position = currentNoteScrollPosition();
  if (!position || !pdfState.noteId) return;
  const store = readNoteScrollStore();
  store[pdfState.noteId] = position;
  writeNoteScrollStore(store);
}

function schedulePersistNoteScrollPosition() {
  if (pdfState.suppressNoteScrollSave) return;
  window.clearTimeout(pdfState.noteScrollSaveTimer);
  pdfState.noteScrollSaveTimer = window.setTimeout(persistNoteScrollPosition, 120);
}

function restoreNoteScrollPosition(position) {
  const pane = elements.notePane;
  if (!pane || !position) return;
  const maxScroll = Math.max(0, pane.scrollHeight - pane.clientHeight);
  const paneBox = pane.getBoundingClientRect();
  const anchorOffset = noteScrollAnchorOffset();
  const anchors = noteScrollAnchorElements();
  let target = Number(position.scrollTop);
  if (!Number.isFinite(target)) {
    target = Number.isFinite(position.ratio) ? position.ratio * maxScroll : 0;
  }

  const idAnchor = position.anchorId ? document.getElementById(position.anchorId) : null;
  const anchor = idAnchor && elements.notePage?.contains(idAnchor)
    ? idAnchor
    : anchors[Number(position.anchorIndex)];
  if (anchor) {
    const rect = anchor.getBoundingClientRect();
    const elementOffset = clamp(Number(position.anchorOffset) || 0, 0, 1) * rect.height;
    target = pane.scrollTop + rect.top - paneBox.top + elementOffset - anchorOffset;
  }

  pane.scrollTop = clamp(target, 0, maxScroll);
}

function finishNoteScrollRestore(position) {
  const pane = elements.notePane;
  if (!pane) return;
  if (!position) {
    pane.scrollTop = 0;
    pdfState.suppressNoteScrollSave = false;
    return;
  }

  restoreNoteScrollPosition(position);
  elements.notePage?.querySelectorAll("img").forEach((image) => {
    if (!image.complete) {
      image.addEventListener("load", () => restoreNoteScrollPosition(position), { once: true });
    }
  });
  window.requestAnimationFrame(() => {
    restoreNoteScrollPosition(position);
    window.setTimeout(() => restoreNoteScrollPosition(position), 140);
    window.setTimeout(() => {
      restoreNoteScrollPosition(position);
      pdfState.suppressNoteScrollSave = false;
      persistNoteScrollPosition();
    }, 520);
  });
}

function initializeNoteScrollPersistence() {
  elements.notePane?.addEventListener("scroll", schedulePersistNoteScrollPosition, { passive: true });
  window.addEventListener("beforeunload", persistNoteScrollPosition);
}
