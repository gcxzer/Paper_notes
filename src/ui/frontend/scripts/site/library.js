function cloneLibrary(library) {
  return JSON.parse(JSON.stringify(library));
}

function uniqueId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const copyFeedbackTimers = new WeakMap();

function showCopyFeedback(button) {
  if (!button) return;
  const existingTimer = copyFeedbackTimers.get(button);
  if (existingTimer) window.clearTimeout(existingTimer);
  button.classList.add("is-copied");
  button.setAttribute("aria-label", "Copied");
  button.setAttribute("title", "Copied");
  const timer = window.setTimeout(() => {
    button.classList.remove("is-copied");
    button.setAttribute("aria-label", "Copy message");
    button.setAttribute("title", "Copy");
    copyFeedbackTimers.delete(button);
  }, 2500);
  copyFeedbackTimers.set(button, timer);
}

function normalizeText(value) {
  return MODEL.normalizeText(value);
}

function sanitizeVisibleAgentError(value) {
  const text = normalizeText(value);
  if (!text) return GENERIC_AGENT_ERROR;
  return SENSITIVE_AGENT_ERROR_PATTERN.test(text) ? GENERIC_AGENT_ERROR : text;
}

function normalizeTags(value) {
  return MODEL.normalizeTags(value);
}

function normalizeResourceHref(value) {
  return MODEL.normalizeResourceHref(value);
}

function readExpandedState() {
  try {
    const raw = localStorage.getItem(EXPANDED_KEY);
    if (!raw) return new Set();
    const values = JSON.parse(raw);
    return new Set(Array.isArray(values) ? values : []);
  } catch (error) {
    console.warn("Failed to read expanded state.", error);
    return new Set();
  }
}

function saveExpandedState() {
  localStorage.setItem(EXPANDED_KEY, JSON.stringify([...state.expandedCategoryIds]));
}

function readLayoutState() {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return { sidebar: 320, details: 320 };
    const parsed = JSON.parse(raw);
    return {
      sidebar: Number(parsed.sidebar) || 320,
      details: Number(parsed.details) || 320
    };
  } catch (error) {
    console.warn("Failed to read layout state.", error);
    return { sidebar: 320, details: 320 };
  }
}

function saveLayoutState() {
  localStorage.setItem(LAYOUT_KEY, JSON.stringify(state.panelWidths));
}

function sanitizeLibrary(rawLibrary) {
  const library = MODEL.sanitizeLibrary(rawLibrary, { uniqueId });
  library.notes.forEach((note) => {
    if (!note.href) note.href = "index.html";
  });
  return library;
}

function saveLibraryToStorage() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.library));
}

function syncLibraryToServer(library = state.library) {
  if (window.location.protocol === "file:") return Promise.resolve(null);

  const snapshot = cloneLibrary(library);
  const version = ++librarySyncVersion;
  const request = async () => {
    const response = await fetch(getApiUrl("/api/library"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(snapshot),
      keepalive: true
    });

    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || `Library save failed (${response.status})`);
    }

    return sanitizeLibrary(await response.json());
  };

  librarySyncQueue = librarySyncQueue.catch(() => null).then(request);
  librarySyncQueue.then((syncedLibrary) => {
    if (!syncedLibrary || version !== librarySyncVersion) return;
    state.library = syncedLibrary;
    saveLibraryToStorage();
    state.dataSource = "default";
    renderApp();
  }).catch((error) => {
    console.warn("Could not sync library to notes.json.", error);
  });

  return librarySyncQueue;
}

function readLibraryFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return sanitizeLibrary(JSON.parse(raw));
  } catch (error) {
    console.warn("Failed to read local library cache.", error);
    return null;
  }
}

async function fetchDefaultLibrary() {
  const baseUrl = window.location.protocol === "file:" ? "http://localhost:4173/" : "";
  const response = await fetch(`${baseUrl}notes.json?t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Unable to load notes.json (${response.status})`);
  return sanitizeLibrary(await response.json());
}

function getCategoryById(categoryId) {
  return state.library.categories.find((category) => category.id === categoryId) || null;
}

function getNoteById(noteId) {
  return state.library.notes.find((note) => note.id === noteId) || null;
}

function getChildren(parentId = null) {
  return state.library.categories
    .filter((category) => (category.parentId || null) === parentId)
    .sort((left, right) => left.order - right.order || left.name.localeCompare(right.name));
}

function hasChildren(categoryId) {
  return state.library.categories.some((category) => category.parentId === categoryId);
}

function isLeafCategory(categoryId) {
  return categoryId !== ALL_CATEGORY_ID && !hasChildren(categoryId);
}

function isCustomCategory(categoryId) {
  const category = getCategoryById(categoryId);
  return Boolean(category && !category.system);
}

function isTopLevel(categoryId) {
  const category = getCategoryById(categoryId);
  return Boolean(category && category.parentId === null);
}

function getTopLevelParent(categoryId) {
  const category = getCategoryById(categoryId);
  if (!category) return null;
  if (!category.parentId) return category;
  return getCategoryById(category.parentId);
}

function getAssignableCategories() {
  return state.library.categories
    .filter((category) => isLeafCategory(category.id))
    .sort((left, right) => left.name.localeCompare(right.name));
}

function getLeafDescendants(categoryId) {
  if (categoryId === ALL_CATEGORY_ID) return getAssignableCategories();
  if (isLeafCategory(categoryId)) return [getCategoryById(categoryId)].filter(Boolean);
  return state.library.categories.filter((category) => category.parentId === categoryId && isLeafCategory(category.id));
}

function getCategoryCount(categoryId) {
  const validIds = new Set(getLeafDescendants(categoryId).map((category) => category.id));
  return state.library.notes.filter((note) => validIds.has(note.categoryId) && noteMatchesActiveFilters(note)).length;
}

function getActiveTagFilters() {
  return normalizeTags(state.activeTagFilters);
}

function noteMatchesActiveFilters(note) {
  const query = state.query.toLowerCase();
  const activeTags = getActiveTagFilters();
  if (query && !note.title.toLowerCase().includes(query)) return false;
  if (activeTags.length) {
    const noteTags = normalizeTags(note.tags);
    if (!activeTags.every((tag) => noteTags.includes(tag))) return false;
  }
  return true;
}

function getVisibleNotes() {
  const visibleCategoryIds = new Set(getLeafDescendants(state.activeCategoryId).map((category) => category.id));
  const notes = state.library.notes.filter((note) => {
    if (!visibleCategoryIds.has(note.categoryId)) return false;
    return noteMatchesActiveFilters(note);
  });
  return sortNotes(notes);
}

function sortNotes(notes) {
  return [...notes].sort((left, right) => {
    const leftOrder = Number.isFinite(Number(left.order)) ? Number(left.order) : state.library.notes.indexOf(left);
    const rightOrder = Number.isFinite(Number(right.order)) ? Number(right.order) : state.library.notes.indexOf(right);
    if (state.sortMode === "date-asc") {
      return (left.date || "").localeCompare(right.date || "") || leftOrder - rightOrder || left.title.localeCompare(right.title);
    }
    if (state.sortMode === "title-asc") {
      return left.title.localeCompare(right.title) || (right.date || "").localeCompare(left.date || "");
    }
    return (right.date || "").localeCompare(left.date || "") || rightOrder - leftOrder || left.title.localeCompare(right.title);
  });
}

function getSortLabel() {
  if (state.sortMode === "date-asc") return "Oldest";
  if (state.sortMode === "title-asc") return "Title";
  return "Newest";
}

function getApiUrl(path) {
  return MODEL.getApiUrl(path);
}

async function fetchJson(path, { method = "GET", body = null } = {}) {
  const response = await fetch(getApiUrl(path), {
    method,
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (error) {
      payload = null;
    }
  }
  if (!response.ok) {
    const message = payload?.error || payload?.message || text || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    error.code = payload?.code || "";
    error.payload = payload;
    throw error;
  }
  return payload || {};
}

async function fetchEventStream(path, { body, onEvent }) {
  const response = await fetch(getApiUrl(path), {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  const contentType = response.headers.get("Content-Type") || "";
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch (error) {
      payload = null;
    }
    const message = payload?.error || payload?.message || text || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    error.code = payload?.code || "";
    error.payload = payload;
    throw error;
  }
  if (!response.body || typeof response.body.getReader !== "function" || !contentType.includes("text/event-stream")) {
    const error = new Error("Streaming is not supported by this browser.");
    error.code = "stream_unsupported";
    throw error;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = drainSseBuffer(buffer, onEvent);
  }
  buffer += decoder.decode();
  drainSseBuffer(`${buffer}\n\n`, onEvent);
}

function drainSseBuffer(buffer, onEvent) {
  let remaining = buffer;
  while (true) {
    const boundary = remaining.indexOf("\n\n");
    if (boundary < 0) return remaining;
    const frame = remaining.slice(0, boundary);
    remaining = remaining.slice(boundary + 2);
    const parsed = parseSseFrame(frame);
    if (parsed) onEvent(parsed);
  }
}

function parseSseFrame(frame) {
  const lines = String(frame || "").split(/\r?\n/);
  let event = "message";
  const dataLines = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = normalizeText(line.slice(6)) || "message";
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }
  if (!dataLines.length) return { event, data: {} };
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch (error) {
    return { event, data: { text: dataLines.join("\n") } };
  }
}

function resolveNoteHref(note) {
  return state.pdfObjectUrls.get(note.id) || note.href;
}

function getReaderHref(note) {
  return `reader.html?id=${encodeURIComponent(note.id)}`;
}

function getDefaultImportCategoryId() {
  if (isLeafCategory(state.activeCategoryId)) return state.activeCategoryId;
  const leaves = getLeafDescendants(state.activeCategoryId);
  return leaves[0]?.id || UNCATEGORIZED_ID;
}

function getSelectedCategory() {
  return getCategoryById(state.activeCategoryId) || getCategoryById(ALL_CATEGORY_ID);
}

function escapeHtml(value) {
  return MODEL.escapeHtml(value);
}

function safeLinkHref(rawHref) {
  const href = normalizeText(rawHref);
  if (!href) return "";
  if (/^https?:\/\//i.test(href)) {
    try {
      return new URL(href).href;
    } catch (error) {
      return "";
    }
  }
  if (/^\/?(resources|assets)\//i.test(href) || /^\/(?!api\/)[A-Za-z0-9._~/%+-]+$/i.test(href)) {
    return href;
  }
  return "";
}

function splitTrailingUrlPunctuation(url) {
  let trimmed = url;
  let trailing = "";
  while (/[.,!?;:，。！？；：、]$/.test(trimmed)) {
    trailing = trimmed.slice(-1) + trailing;
    trimmed = trimmed.slice(0, -1);
  }
  return [trimmed, trailing];
}

function renderLinkedText(text) {
  const source = normalizeText(text);
  const codeBlocks = [];
  const withCodeBlocks = source.replace(/```([A-Za-z0-9_+.-]*)[ \t]*\n([\s\S]*?)```/g, (_, language, code) => {
    const token = `@@CODEBLOCK${codeBlocks.length}@@`;
    codeBlocks.push(renderChatCodeBlock(normalizeFencedCode(code), language));
    return token;
  });
  const codeSpans = [];
  const codeSpanLabels = [];
  let html = escapeHtml(withCodeBlocks).replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `@@CODESPAN${codeSpans.length}@@`;
    codeSpans.push(`<code>${code}</code>`);
    codeSpanLabels.push(code);
    return token;
  });
  html = html.replace(/\*\*([^*\n](?:[\s\S]*?[^*\n])?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__([^_\n](?:[\s\S]*?[^_\n])?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*\*/g, "");
  html = html.replace(/__/g, "");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/(^|[^\w])_([^_\n]+?)_(?=[^\w]|$)/g, "$1<em>$2</em>");
  html = html.replace(/\[([^\]\n]{1,240})\]\(([^)\s]+)\)/g, (match, label, href) => {
    const safeHref = safeLinkHref(href);
    const linkLabel = label.replace(/@@CODESPAN(\d+)@@/g, (spanToken, index) => codeSpanLabels[Number(index)] ?? spanToken);
    return safeHref
      ? `<a href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer">${linkLabel}</a>`
      : match;
  });
  html = html.replace(/(https?:\/\/[^\s<>"'()[\]{}（）【】《》]+)/gi, (url) => {
    const [hrefCandidate, trailing] = splitTrailingUrlPunctuation(url);
    const href = safeLinkHref(hrefCandidate);
    return href
      ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${hrefCandidate}</a>${trailing}`
      : url;
  });
  codeSpans.forEach((code, index) => {
    html = html.replace(`@@CODESPAN${index}@@`, code);
  });
  html = renderChatMarkdownBlocks(html);
  codeBlocks.forEach((block, index) => {
    html = html.replace(`@@CODEBLOCK${index}@@`, block);
  });
  return html;
}

function renderChatMarkdownBlocks(html) {
  const lines = String(html || "").split(/\r?\n/);
  const output = [];
  let listType = "";
  let blockquote = [];

  const closeList = () => {
    if (!listType) return;
    output.push(`</${listType}>`);
    listType = "";
  };
  const closeBlockquote = () => {
    if (!blockquote.length) return;
    closeList();
    output.push(`<blockquote>${blockquote.join("<br>")}</blockquote>`);
    blockquote = [];
  };
  const openList = (type) => {
    closeBlockquote();
    if (listType === type) return;
    closeList();
    output.push(`<${type}>`);
    listType = type;
  };
  const closeBlocks = () => {
    closeBlockquote();
    closeList();
  };
  const tableSeparator = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const tableRow = (line) => /^\s*\|.+\|\s*$/.test(line);
  const tableCells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  const renderTable = (tableLines) => {
    const header = tableCells(tableLines[0]);
    const rows = tableLines.slice(2).map(tableCells);
    return `
      <div class="chat-table-wrap">
        <table class="chat-markdown-table">
          <thead><tr>${header.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>
          <tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody>
        </table>
      </div>
    `;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      closeBlocks();
      continue;
    }
    if (tableRow(line) && tableSeparator(lines[index + 1] || "")) {
      closeBlocks();
      const tableLines = [line, lines[index + 1].trimEnd()];
      index += 2;
      while (index < lines.length && tableRow(lines[index])) {
        tableLines.push(lines[index].trimEnd());
        index += 1;
      }
      index -= 1;
      output.push(renderTable(tableLines));
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      closeBlocks();
      const level = Math.min(6, heading[1].length);
      output.push(`<h${level}>${heading[2].trim()}</h${level}>`);
      continue;
    }
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      closeBlocks();
      output.push("<hr>");
      continue;
    }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    if (unordered) {
      openList("ul");
      output.push(`<li>${unordered[1]}</li>`);
      continue;
    }
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      openList("ol");
      output.push(`<li>${ordered[1]}</li>`);
      continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      blockquote.push(quote[1]);
      continue;
    }
    closeBlocks();
    output.push(`<p>${line}</p>`);
  }
  closeBlocks();
  return output.join("");
}

function normalizeFencedCode(code) {
  return String(code || "").replace(/^(?:[ \t]*\r?\n)+/, "").replace(/(?:\r?\n[ \t]*)+$/, "");
}

function renderChatCodeBlock(code, language = "") {
  const normalizedCode = String(code || "");
  const label = normalizeText(language);
  return `<div class="chat-code-block">${label ? `<div class="chat-code-language">${escapeHtml(label)}</div>` : ""}<pre><code>${escapeHtml(normalizedCode)}</code></pre><button class="chat-code-copy" type="button" data-code-copy="${escapeHtml(encodeURIComponent(normalizedCode))}">Copy</button></div>`;
}
