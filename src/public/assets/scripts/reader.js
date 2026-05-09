const pdfjsLib = globalThis.pdfjsLib;

if (pdfjsLib) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "node_modules/pdfjs-dist/build/pdf.worker.js";
}

const STORAGE_KEY = "paper-notes-library-v14";
const FILE_DB_NAME = "paper-notes-files-v1";
const FILE_STORE_NAME = "paper-files";
const READER_SPLIT_KEY = "paper-notes-reader-split-v1";
const ANNOTATION_SIDEBAR_KEY = "paper-notes-annotation-sidebar-v1";
const HTML_PANE_KEY = "paper-notes-html-pane-v1";
const ASK_PANE_KEY = "paper-notes-ask-pane-v1";
const ASK_WIDTH_KEY = "paper-notes-ask-width-v1";
const HTML_ZOOM_KEY = "paper-notes-html-zoom-v1";
const PDF_SCROLL_KEY = "paper-notes-pdf-scroll-v1";
const NOTE_SCROLL_KEY = "paper-notes-note-scroll-v1";
const CHAT_SESSION_STORE_KEY = "paper-notes-agent-session-by-note-v1";
const ALL_CATEGORY_ID = "all";
const UNCATEGORIZED_ID = "uncategorized";
const PDF_MIN_SCALE = 0.7;
const PDF_MAX_SCALE = 4;
const PDF_SCALE_STEP = 0.1;
const GENERIC_AGENT_ERROR = "I could not reach the assistant. Check that the local server is running and try again.";
const SENSITIVE_AGENT_ERROR_PATTERN = /(SSL validation failed|bedrock-agentcore|harnessArn|arn:aws|amazonaws\.com|InvokeHarness|AgentCore|AWS SSO|botocore|boto3|ValidationException|AccessDeniedException|runtimeClientError|\[Errno\s+\d+\]|No such file or directory)/i;

const elements = {
  layout: document.querySelector("#readerLayout"),
  error: document.querySelector("#readerError"),
  title: document.querySelector("#readerTitle"),
  kicker: document.querySelector("#readerKicker"),
  pdfViewer: document.querySelector("#pdfViewer"),
  notePane: document.querySelector(".note-pane"),
  askPane: document.querySelector("#askPane"),
  notePage: document.querySelector("#notePage"),
  resizer: document.querySelector("#readerResizer"),
  askResizer: document.querySelector("#askResizer"),
  annotationStatus: document.querySelector("#annotationStatus"),
  annotationList: document.querySelector("#annotationList"),
  annotationCount: document.querySelector("#annotationCount"),
  annotationSidebarToolbarToggle: document.querySelector("#annotationSidebarToolbarToggle"),
  annotationSidebarToggle: document.querySelector("#annotationSidebarToggle"),
  pdfBody: document.querySelector(".pdf-body"),
  htmlPaneToggle: document.querySelector("#htmlPaneToggle"),
  askPaneToggle: document.querySelector("#askPaneToggle"),
  closeAskPane: document.querySelector("#closeAskPane"),
  chatSessionMenuButton: document.querySelector("#chatSessionMenuButton"),
  chatSessionPopover: document.querySelector("#chatSessionPopover"),
  newChatSession: document.querySelector("#newChatSession"),
  exportChatSession: document.querySelector("#exportChatSession"),
  toggleChatSessionTrash: document.querySelector("#toggleChatSessionTrash"),
  chatSessionSearch: document.querySelector("#chatSessionSearch"),
  chatSessionList: document.querySelector("#chatSessionList"),
  readerChatForm: document.querySelector("#readerChatForm"),
  readerChatMessages: document.querySelector("#readerChatMessages"),
  readerChatInput: document.querySelector("#readerChatInput"),
  readerChatError: document.querySelector("#readerChatError"),
  sendReaderChat: document.querySelector("#sendReaderChat"),
  clearReaderChat: document.querySelector("#clearReaderChat"),
  htmlZoomIn: document.querySelector("#htmlZoomIn"),
  htmlZoomOut: document.querySelector("#htmlZoomOut"),
  htmlZoomLabel: document.querySelector("#htmlZoomLabel"),
  zoomIn: document.querySelector("#zoomIn"),
  zoomOut: document.querySelector("#zoomOut"),
  zoomLabel: document.querySelector("#zoomLabel"),
  pdfPageInput: document.querySelector("#pdfPageInput"),
  pdfPageTotal: document.querySelector("#pdfPageTotal"),
  annotationUndo: document.querySelector("#annotationUndo"),
  annotationRedo: document.querySelector("#annotationRedo"),
  pdfLinkReturn: document.querySelector("#pdfLinkReturn"),
  pdfLinkBack: document.querySelector("#pdfLinkBack"),
  pdfLinkDismiss: document.querySelector("#pdfLinkDismiss"),
  modeButtons: Array.from(document.querySelectorAll("[data-pdf-mode]")),
  colorButtons: Array.from(document.querySelectorAll("[data-pdf-color]"))
};

const splitState = {
  dragging: false,
  askDragging: false,
  minPdfWidth: 280,
  minNoteWidth: 320,
  minAskWidth: 320
};

const pdfState = {
  document: null,
  noteId: "",
  url: "",
  mode: "pan",
  color: "yellow",
  scale: 2.15,
  renderToken: 0,
  annotations: [],
  historyPast: [],
  historyFuture: [],
  historyLimit: 80,
  suppressScrollSave: false,
  scrollSaveTimer: 0,
  suppressNoteScrollSave: false,
  noteScrollSaveTimer: 0,
  saveTimer: 0,
  openEditor: null,
  selectedAnnotationId: "",
  linkReturnPosition: null
};

const readerState = {
  library: null,
  note: null,
  chatSessionId: "",
  chatSessions: [],
  chatSessionsLoading: false,
  chatSessionMenuOpen: false,
  chatSessionTrashOpen: false,
  chatSessionQuery: "",
  confirmingDeleteSessionId: "",
  renamingSessionId: "",
  chatMessages: [],
  chatProgress: null,
  chatProgressTimer: 0,
  chatProgressRequestId: "",
  chatPending: false
};

const PDF_ANNOTATION_TYPES = new Set(["highlight", "underline", "area", "note"]);
const PDF_COLORS = {
  yellow: { label: "Yellow", hex: "#f2c94c", rgb: "242, 201, 76" },
  green: { label: "Green", hex: "#70c787", rgb: "112, 199, 135" },
  blue: { label: "Blue", hex: "#6aa9ff", rgb: "106, 169, 255" },
  red: { label: "Red", hex: "#ff7a7a", rgb: "255, 122, 122" },
  purple: { label: "Purple", hex: "#b996ff", rgb: "185, 150, 255" }
};
const PDF_NOTE_MARKER_SIZE = 24;

function normalizeText(value) {
  return String(value || "").trim();
}

function sanitizeVisibleAgentError(value) {
  const text = normalizeText(value);
  if (!text) return GENERIC_AGENT_ERROR;
  return SENSITIVE_AGENT_ERROR_PATTERN.test(text) ? GENERIC_AGENT_ERROR : text;
}

function sanitizeChatProgressDetail(value) {
  const text = normalizeText(value);
  if (!text) return "";
  return SENSITIVE_AGENT_ERROR_PATTERN.test(text) ? "The assistant hit a connection issue." : text;
}

function normalizeResourceHref(value) {
  const href = normalizeText(value);
  if (!href) return "";
  if (href.startsWith("resources/")) return href;
  if (href.startsWith("Papers/") || href.startsWith("Paper-html/") || href.startsWith("Paper-annotations/")) {
    return `resources/${href}`;
  }
  return href;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getApiUrl(path) {
  return window.location.protocol === "file:"
    ? `http://localhost:4173${path}`
    : path;
}

function createRequestId(prefix = "reader-chat") {
  if (globalThis.crypto?.randomUUID) return `${prefix}-${globalThis.crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function readChatSessionStore() {
  try {
    const raw = localStorage.getItem(CHAT_SESSION_STORE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (error) {
    console.warn("Failed to read chat session selection.", error);
    return {};
  }
}

function writeChatSessionStore(store) {
  try {
    localStorage.setItem(CHAT_SESSION_STORE_KEY, JSON.stringify(store || {}));
  } catch (error) {
    console.warn("Failed to save chat session selection.", error);
  }
}

function currentChatNoteId() {
  return normalizeText(readerState.note?.id || pdfState.noteId);
}

function storedChatSessionId(noteId = currentChatNoteId()) {
  if (!noteId) return "";
  return normalizeText(readChatSessionStore()[noteId]);
}

function setStoredChatSessionId(sessionId, noteId = currentChatNoteId()) {
  if (!noteId) return;
  const store = readChatSessionStore();
  if (sessionId) {
    store[noteId] = sessionId;
  } else {
    delete store[noteId];
  }
  writeChatSessionStore(store);
}

function setCurrentChatSessionId(sessionId) {
  readerState.chatSessionId = normalizeText(sessionId);
  setStoredChatSessionId(readerState.chatSessionId);
  renderChatSessionControls();
}

function getChatSessionId() {
  return readerState.chatSessionId;
}

function sanitizeLibrary(rawLibrary) {
  const raw = rawLibrary && typeof rawLibrary === "object" ? rawLibrary : {};
  const categories = Array.isArray(raw.categories) ? raw.categories.map((category, index) => ({
    id: normalizeText(category.id),
    name: normalizeText(category.name) || "Untitled",
    parentId: normalizeText(category.parentId) || null,
    order: Number.isFinite(category.order) ? Number(category.order) : index,
    system: Boolean(category.system)
  })).filter((category) => category.id) : [];

  const notes = Array.isArray(raw.notes) ? raw.notes.map((note) => ({
    id: normalizeText(note.id),
    title: normalizeText(note.title) || "Untitled Paper",
    href: normalizeResourceHref(note.href),
    htmlHref: normalizeResourceHref(note.htmlHref),
    pdfStorageKey: normalizeText(note.pdfStorageKey),
    pdfS3Key: normalizeText(note.pdfS3Key),
    noteS3Key: normalizeText(note.noteS3Key),
    annotationS3Key: normalizeText(note.annotationS3Key),
    kbPaperS3Key: normalizeText(note.kbPaperS3Key),
    kbNoteS3Key: normalizeText(note.kbNoteS3Key),
    kbAnnotationsS3Key: normalizeText(note.kbAnnotationsS3Key),
    kbMetadataS3Key: normalizeText(note.kbMetadataS3Key),
    kbSyncStatus: normalizeText(note.kbSyncStatus),
    kbIngestionJobId: normalizeText(note.kbIngestionJobId),
    kbSyncError: normalizeText(note.kbSyncError),
    date: normalizeText(note.date),
    categoryId: normalizeText(note.categoryId) || UNCATEGORIZED_ID,
    summary: normalizeText(note.summary)
  })).filter((note) => note.id) : [];

  return { categories, notes };
}

function readLibraryFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return sanitizeLibrary(JSON.parse(raw));
  } catch (error) {
    console.warn("Failed to read local library.", error);
    return null;
  }
}

async function readDefaultLibrary() {
  const baseUrl = window.location.protocol === "file:" ? "http://localhost:4173/" : "";
  const response = await fetch(`${baseUrl}notes.json?t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Unable to load notes.json (${response.status})`);
  return sanitizeLibrary(await response.json());
}

function openFileDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(FILE_DB_NAME, 1);

    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(FILE_STORE_NAME)) {
        database.createObjectStore(FILE_STORE_NAME, { keyPath: "id" });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function readPaperFile(id) {
  if (!id) return null;
  const database = await openFileDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(FILE_STORE_NAME, "readonly");
    const request = transaction.objectStore(FILE_STORE_NAME).get(id);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => database.close();
  });
}

function getCategoryById(library, categoryId) {
  return library.categories.find((category) => category.id === categoryId) || null;
}

function getCollectionPath(library, categoryId) {
  const category = getCategoryById(library, categoryId);
  if (!category) return "Uncategorized";
  if (!category.parentId || category.id === ALL_CATEGORY_ID) return category.name;
  const parent = getCategoryById(library, category.parentId);
  return parent ? `${parent.name} / ${category.name}` : category.name;
}

function updateCurrentNote(nextNote) {
  if (!nextNote?.id) return;
  readerState.note = { ...(readerState.note || {}), ...nextNote };
  if (readerState.library?.notes) {
    const index = readerState.library.notes.findIndex((entry) => entry.id === nextNote.id);
    if (index >= 0) {
      readerState.library.notes[index] = { ...readerState.library.notes[index], ...nextNote };
    }
  }
}

function showError() {
  elements.layout.hidden = true;
  elements.error.hidden = false;
  elements.title.textContent = "Paper not found";
}

function setAnnotationStatus(text) {
  if (elements.annotationStatus) elements.annotationStatus.textContent = text;
}

function annotationColor(annotation) {
  return PDF_COLORS[annotation.color] || PDF_COLORS.yellow;
}

function applyAnnotationColor(element, annotation) {
  const color = annotationColor(annotation);
  element.style.setProperty("--annotation-color", color.hex);
  element.style.setProperty("--annotation-rgb", color.rgb);
  element.style.setProperty("--annotation-bg", color.hex);
}

function annotationTypeLabel(type) {
  return {
    highlight: "Highlight",
    underline: "Underline",
    area: "Area",
    note: "Note"
  }[type] || "Annotation";
}

function renderAnnotationColorButtons(activeColor) {
  return Object.entries(PDF_COLORS).map(([key, color]) => `
    <button
      class="annotation-editor-color${key === activeColor ? " is-active" : ""}"
      type="button"
      data-editor-color="${key}"
      style="background-color: ${color.hex}; --annotation-color: ${color.hex}; --annotation-rgb: ${color.rgb};"
      aria-label="${color.label}"
    ></button>
  `).join("");
}

function setAnnotationSidebarCollapsed(collapsed) {
  elements.pdfBody?.classList.toggle("is-annotation-sidebar-collapsed", collapsed);
  elements.annotationSidebarToggle?.setAttribute("aria-expanded", String(!collapsed));
  elements.annotationSidebarToolbarToggle?.classList.toggle("is-active", !collapsed);
  elements.annotationSidebarToolbarToggle?.setAttribute("aria-expanded", String(!collapsed));
  localStorage.setItem(ANNOTATION_SIDEBAR_KEY, collapsed ? "collapsed" : "open");
}

function initializeAnnotationSidebar() {
  setAnnotationSidebarCollapsed(localStorage.getItem(ANNOTATION_SIDEBAR_KEY) === "collapsed");
  elements.annotationSidebarToolbarToggle?.addEventListener("click", () => {
    setAnnotationSidebarCollapsed(!elements.pdfBody?.classList.contains("is-annotation-sidebar-collapsed"));
  });
  elements.annotationSidebarToggle?.addEventListener("click", () => setAnnotationSidebarCollapsed(true));
}

function setHtmlPaneVisible(visible) {
  elements.layout?.classList.toggle("is-html-pane-hidden", !visible);
  elements.htmlPaneToggle?.classList.toggle("is-active", visible);
  elements.htmlPaneToggle?.setAttribute("aria-expanded", String(visible));
  localStorage.setItem(HTML_PANE_KEY, visible ? "shown" : "hidden");
  requestAnimationFrame(() => {
    setAskWidth(readAskWidth());
    setSplitPercent(readSplitPercent());
  });
}

function initializeHtmlPaneToggle() {
  setHtmlPaneVisible(localStorage.getItem(HTML_PANE_KEY) !== "hidden");
  elements.htmlPaneToggle?.addEventListener("click", () => {
    setHtmlPaneVisible(elements.layout?.classList.contains("is-html-pane-hidden"));
  });
}

function setAskPaneVisible(visible) {
  elements.layout?.classList.toggle("is-ask-pane-hidden", !visible);
  elements.askPaneToggle?.classList.toggle("is-active", visible);
  elements.askPaneToggle?.setAttribute("aria-expanded", String(visible));
  localStorage.setItem(ASK_PANE_KEY, visible ? "shown" : "hidden");
  if (visible) {
    renderReaderChatMessages();
    requestAnimationFrame(() => {
      setAskWidth(readAskWidth());
      elements.readerChatInput?.focus();
    });
  }
  requestAnimationFrame(() => {
    setAskWidth(readAskWidth());
    setSplitPercent(readSplitPercent());
  });
}

function initializeAskPaneToggle() {
  setAskPaneVisible(localStorage.getItem(ASK_PANE_KEY) === "shown");
  elements.askPaneToggle?.addEventListener("click", () => {
    setAskPaneVisible(elements.layout?.classList.contains("is-ask-pane-hidden"));
  });
  elements.closeAskPane?.addEventListener("click", () => setAskPaneVisible(false));
}

function normalizeChatMessage(message) {
  const role = message?.role === "user" ? "user" : "assistant";
  const text = normalizeText(message?.text);
  const error = Boolean(message?.error) || (role === "assistant" && SENSITIVE_AGENT_ERROR_PATTERN.test(text));
  return {
    role,
    text: role === "assistant" && error ? sanitizeVisibleAgentError(text) : text,
    error,
    sources: normalizeChatSources(message?.sources),
    noteEdit: normalizeNoteEditDraft(message?.noteEdit)
  };
}

function normalizeNoteEditDraft(rawEdit) {
  if (!rawEdit || typeof rawEdit !== "object") return null;
  const replacementHtml = String(rawEdit.replacementHtml || "").trim();
  const noteId = normalizeText(rawEdit.noteId);
  if (!replacementHtml || !noteId) return null;
  return {
    id: normalizeText(rawEdit.id) || `note-edit-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    noteId,
    summary: normalizeText(rawEdit.summary) || "Prepared a note edit draft.",
    replacementHtml,
    applied: Boolean(rawEdit.applied)
  };
}

function normalizeChatSources(rawSources) {
  if (!Array.isArray(rawSources)) return [];
  return rawSources.slice(0, 12).map((source) => {
    const raw = typeof source === "string" ? { uri: source } : source;
    if (!raw || typeof raw !== "object") return null;
    const page = Number(raw.page);
    return {
      type: normalizeText(raw.type) || "source",
      label: normalizeText(raw.label),
      uri: normalizeText(raw.uri),
      s3Key: normalizeText(raw.s3Key),
      noteId: normalizeText(raw.noteId),
      page: Number.isFinite(page) && page > 0 ? Math.round(page) : null,
      excerpt: normalizeText(raw.excerpt)
    };
  }).filter((source) => source && (source.label || source.uri || source.excerpt));
}

function noteForChatSource(source) {
  if (!readerState.library?.notes) return readerState.note;
  if (source.noteId) {
    const byId = readerState.library.notes.find((note) => note.id === source.noteId);
    if (byId) return byId;
  }
  const locator = source.s3Key || source.uri;
  if (locator) {
    const byKey = readerState.library.notes.find((note) => (
      [note.kbPaperS3Key, note.kbNoteS3Key, note.kbAnnotationsS3Key, note.kbMetadataS3Key]
        .some((key) => key && locator.includes(key))
    ));
    if (byKey) return byKey;
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

function renderNoteEditDraft(noteEdit) {
  if (!noteEdit) return "";
  return `
    <div class="ask-note-edit" data-note-edit-id="${escapeHtml(noteEdit.id)}">
      <div class="ask-note-edit-copy">
        <strong>Note edit draft</strong>
        <span>${escapeHtml(noteEdit.summary)}</span>
      </div>
      <div class="ask-note-edit-actions">
        <button class="ask-note-edit-apply" type="button" data-note-edit-apply="${escapeHtml(noteEdit.id)}"${noteEdit.applied ? " disabled" : ""}>${noteEdit.applied ? "Applied" : "Apply to note"}</button>
        <button class="ask-note-edit-discard" type="button" data-note-edit-discard="${escapeHtml(noteEdit.id)}"${noteEdit.applied ? " hidden" : ""}>Discard</button>
      </div>
      <p class="ask-note-edit-hint">This only changes the local HTML note.</p>
    </div>
  `;
}

function normalizeChatProgress(progress) {
  if (!progress || typeof progress !== "object") return null;
  const events = Array.isArray(progress.events)
    ? progress.events.map((event) => ({
      stage: normalizeText(event?.stage),
      detail: sanitizeChatProgressDetail(event?.detail),
      at: normalizeText(event?.at)
    })).filter((event) => event.detail)
    : [];
  return {
    status: normalizeText(progress.status) || "running",
    stage: normalizeText(progress.stage) || "working",
    detail: sanitizeChatProgressDetail(progress.detail) || "Working...",
    events
  };
}

function renderChatProgress() {
  const progress = normalizeChatProgress(readerState.chatProgress);
  if (!readerState.chatPending || !progress) return "";
  const events = progress.events.length ? progress.events : [{ stage: progress.stage, detail: progress.detail }];
  return `
    <div class="ask-message ask-message-assistant ask-message-progress">
      <div class="ask-message-stack">
        <div class="ask-progress-card" role="status" aria-live="polite">
          <div class="ask-progress-header">
            <span class="ask-progress-spinner" aria-hidden="true"></span>
            <strong>${escapeHtml(progress.detail)}</strong>
          </div>
          <ol class="ask-progress-steps">
            ${events.slice(-5).map((event, index, visibleEvents) => `
              <li class="${index === visibleEvents.length - 1 ? "is-current" : "is-done"}">
                <span>${escapeHtml(event.detail)}</span>
              </li>
            `).join("")}
          </ol>
        </div>
      </div>
    </div>
  `;
}

function renderReaderChatMessages() {
  if (!elements.readerChatMessages) return;
  if (!readerState.chatMessages.length && !readerState.chatPending) {
    elements.readerChatMessages.innerHTML = "";
    return;
  }

  const messagesHtml = readerState.chatMessages.map((rawMessage) => {
    const message = normalizeChatMessage(rawMessage);
    const sourcesHtml = message.role === "assistant" ? renderChatSources(message.sources) : "";
    const noteEditHtml = message.role === "assistant" ? renderNoteEditDraft(message.noteEdit) : "";
    return `
    <div class="ask-message ask-message-${message.role}${message.error ? " ask-message-error" : ""}">
      <div class="ask-message-stack">
        <div class="ask-bubble">${escapeHtml(message.text).replace(/\n/g, "<br>")}</div>
        ${sourcesHtml}
        ${noteEditHtml}
      </div>
    </div>
  `;
  }).join("");
  elements.readerChatMessages.innerHTML = `${messagesHtml}${renderChatProgress()}`;
  elements.readerChatMessages.scrollTop = elements.readerChatMessages.scrollHeight;
}

function findChatNoteEdit(editId) {
  for (const message of readerState.chatMessages) {
    const noteEdit = normalizeNoteEditDraft(message.noteEdit);
    if (noteEdit?.id === editId) return message.noteEdit;
  }
  return null;
}

function markChatNoteEditApplied(editId) {
  readerState.chatMessages.forEach((message) => {
    if (message.noteEdit?.id === editId) {
      message.noteEdit.applied = true;
    }
  });
}

function discardChatNoteEdit(editId) {
  readerState.chatMessages.forEach((message) => {
    if (message.noteEdit?.id === editId) {
      message.noteEdit = null;
    }
  });
  renderReaderChatMessages();
}

async function applyChatNoteEdit(editId) {
  const noteEdit = normalizeNoteEditDraft(findChatNoteEdit(editId));
  if (!noteEdit || noteEdit.applied) return;
  setReaderChatError("");
  try {
    const response = await fetch(getApiUrl("/api/apply-note-edit"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        noteId: noteEdit.noteId,
        replacementHtml: noteEdit.replacementHtml
      })
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.error || `Could not apply note edit (${response.status})`);
    }
    const noteBody = elements.notePage?.querySelector(".note-body");
    if (noteBody && typeof payload.noteBodyHtml === "string") {
      noteBody.innerHTML = payload.noteBodyHtml;
      if (typeof window.buildNoteMenu === "function") window.buildNoteMenu(elements.notePage);
      mountReaderNoteMenu();
    }
    if (payload.note) updateCurrentNote(payload.note);
    markChatNoteEditApplied(editId);
    renderReaderChatMessages();
  } catch (error) {
    console.warn("Failed to apply note edit.", error);
    setReaderChatError(error.message || "Could not apply note edit.");
  }
}

function handleNoteEditDraftClick(event) {
  const applyButton = event.target.closest("[data-note-edit-apply]");
  if (applyButton) {
    event.preventDefault();
    applyChatNoteEdit(applyButton.dataset.noteEditApply);
    return;
  }
  const discardButton = event.target.closest("[data-note-edit-discard]");
  if (discardButton) {
    event.preventDefault();
    discardChatNoteEdit(discardButton.dataset.noteEditDiscard);
  }
}

function activateChatSource(source) {
  if (source.type === "note") {
    setHtmlPaneVisible(true);
    elements.notePane?.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (source.type === "pdf" || source.type === "annotation") {
    if (source.type === "annotation") setAnnotationSidebarCollapsed(false);
    if (source.page) scrollToPdfPage(source.page, "smooth");
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


function setReaderChatError(message = "") {
  if (!elements.readerChatError) return;
  elements.readerChatError.textContent = message ? sanitizeVisibleAgentError(message) : "";
  elements.readerChatError.hidden = !message;
}

function setReaderChatPending(pending) {
  readerState.chatPending = pending;
  if (elements.readerChatInput) elements.readerChatInput.disabled = pending;
  if (elements.sendReaderChat) {
    elements.sendReaderChat.disabled = pending;
    elements.sendReaderChat.textContent = pending ? "Sending" : "Send";
  }
}

function setReaderChatProgress(progress) {
  readerState.chatProgress = normalizeChatProgress(progress);
  renderReaderChatMessages();
}

function clearReaderChatProgress() {
  readerState.chatProgress = null;
  readerState.chatProgressRequestId = "";
  if (readerState.chatProgressTimer) {
    clearInterval(readerState.chatProgressTimer);
    readerState.chatProgressTimer = 0;
  }
}

async function fetchReaderChatProgress(requestId) {
  if (!requestId || readerState.chatProgressRequestId !== requestId) return;
  try {
    const response = await fetch(getApiUrl(`/api/chat-progress?requestId=${encodeURIComponent(requestId)}&t=${Date.now()}`), {
      cache: "no-store"
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload || payload.status === "unknown") return;
    setReaderChatProgress(payload);
    if (payload.status === "complete" || payload.status === "failed") {
      if (readerState.chatProgressTimer) {
        clearInterval(readerState.chatProgressTimer);
        readerState.chatProgressTimer = 0;
      }
    }
  } catch (error) {
    console.warn("Failed to read chat progress.", error);
  }
}

function startReaderChatProgress(requestId) {
  clearReaderChatProgress();
  readerState.chatProgressRequestId = requestId;
  setReaderChatProgress({
    requestId,
    status: "running",
    stage: "sending",
    detail: "Sending your question to Paper Notes Agent.",
    events: [{ stage: "sending", detail: "Sending your question to Paper Notes Agent." }]
  });
  readerState.chatProgressTimer = window.setInterval(() => {
    fetchReaderChatProgress(requestId);
  }, 850);
}

function readerChatContext() {
  const note = readerState.note;
  const position = currentPdfScrollPosition();
  return {
    selectedNoteId: note?.id || "",
    selectedNoteTitle: note?.title || "",
    selectedCategoryName: readerState.library && note ? getCollectionPath(readerState.library, note.categoryId) : "",
    currentPdfPage: position?.page || ""
  };
}

function formatChatSessionTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function chatSessionMatchesQuery(session) {
  const query = normalizeText(readerState.chatSessionQuery).toLowerCase();
  if (!query) return true;
  return [
    session.title,
    session.lastMessagePreview,
    formatChatSessionTime(session.updatedAt)
  ].some((value) => normalizeText(value).toLowerCase().includes(query));
}

function renderChatSessionControls() {
  if (elements.exportChatSession) {
    elements.exportChatSession.disabled = !readerState.chatSessionId || readerState.chatSessionTrashOpen;
  }
  if (elements.newChatSession) elements.newChatSession.disabled = readerState.chatSessionTrashOpen;
  if (elements.toggleChatSessionTrash) {
    elements.toggleChatSessionTrash.classList.toggle("is-active", readerState.chatSessionTrashOpen);
    elements.toggleChatSessionTrash.textContent = readerState.chatSessionTrashOpen ? "Back" : "Trash";
    elements.toggleChatSessionTrash.setAttribute("aria-pressed", String(readerState.chatSessionTrashOpen));
  }
  if (elements.chatSessionSearch && elements.chatSessionSearch.value !== readerState.chatSessionQuery) {
    elements.chatSessionSearch.value = readerState.chatSessionQuery;
  }
  if (elements.chatSessionSearch) {
    elements.chatSessionSearch.placeholder = readerState.chatSessionTrashOpen ? "Search trash" : "Search sessions";
  }
}

function renderChatSessionList() {
  if (!elements.chatSessionList) return;
  elements.chatSessionList.innerHTML = "";
  renderChatSessionControls();

  if (readerState.chatSessionsLoading) {
    elements.chatSessionList.innerHTML = `<p class="ask-session-empty">Loading sessions...</p>`;
    return;
  }

  if (!readerState.chatSessions.length) {
    elements.chatSessionList.innerHTML = `<p class="ask-session-empty">${readerState.chatSessionTrashOpen ? "Trash is empty" : "No sessions yet"}</p>`;
    return;
  }

  const visibleSessions = readerState.chatSessions.filter(chatSessionMatchesQuery);
  if (!visibleSessions.length) {
    elements.chatSessionList.innerHTML = `<p class="ask-session-empty">${readerState.chatSessionTrashOpen ? "No matching trashed sessions" : "No matching sessions"}</p>`;
    return;
  }

  visibleSessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = "ask-session-row";
    row.classList.toggle("is-trashed", readerState.chatSessionTrashOpen);
    row.classList.toggle("is-active", session.id === readerState.chatSessionId);
    row.classList.toggle("is-delete-confirming", session.id === readerState.confirmingDeleteSessionId);

    if (session.id === readerState.renamingSessionId) {
      const form = document.createElement("form");
      form.className = "ask-session-rename-form";
      form.innerHTML = `
        <input type="text" maxlength="80" value="${escapeHtml(session.title || "New chat")}" aria-label="Session name">
        <div class="ask-session-row-actions">
          <button class="ask-session-mini ask-session-save" type="submit">Save</button>
          <button class="ask-session-mini" type="button" data-cancel-rename>Cancel</button>
        </div>
      `;
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        renameReaderChatSession(session.id, form.querySelector("input")?.value);
      });
      form.querySelector("[data-cancel-rename]")?.addEventListener("click", () => {
        readerState.renamingSessionId = "";
        renderChatSessionList();
      });
      row.appendChild(form);
      elements.chatSessionList.appendChild(row);
      form.querySelector("input")?.focus();
      form.querySelector("input")?.select();
      return;
    }

    const sessionButton = document.createElement("button");
    sessionButton.className = "ask-session-item";
    sessionButton.type = "button";
    sessionButton.dataset.sessionId = session.id;
    sessionButton.disabled = readerState.chatSessionTrashOpen;
    sessionButton.innerHTML = `
      <span class="ask-session-title">${escapeHtml(session.title || "New chat")}</span>
      <span class="ask-session-meta">${escapeHtml(readerState.chatSessionTrashOpen ? `Moved ${formatChatSessionTime(session.trashedAt || session.updatedAt)}` : formatChatSessionTime(session.updatedAt))}</span>
    `;
    if (!readerState.chatSessionTrashOpen) {
      sessionButton.addEventListener("click", () => loadReaderChatSession(session.id));
    }

    const rowActions = document.createElement("div");
    rowActions.className = "ask-session-row-actions";

    if (readerState.chatSessionTrashOpen) {
      const restoreButton = document.createElement("button");
      restoreButton.className = "ask-session-mini ask-session-restore";
      restoreButton.type = "button";
      restoreButton.textContent = "Restore";
      restoreButton.setAttribute("aria-label", `Restore ${session.title || "chat session"}`);
      restoreButton.addEventListener("click", (event) => {
        event.stopPropagation();
        restoreReaderChatSession(session.id);
      });

      const permanentDeleteButton = document.createElement("button");
      permanentDeleteButton.className = "ask-session-mini ask-session-delete";
      permanentDeleteButton.type = "button";
      permanentDeleteButton.textContent = session.id === readerState.confirmingDeleteSessionId ? "Confirm" : "Delete";
      permanentDeleteButton.setAttribute("aria-label", `Permanently delete ${session.title || "chat session"}`);
      permanentDeleteButton.addEventListener("click", (event) => {
        event.stopPropagation();
        if (readerState.confirmingDeleteSessionId === session.id) {
          permanentlyDeleteReaderChatSession(session.id);
          return;
        }
        readerState.confirmingDeleteSessionId = session.id;
        readerState.renamingSessionId = "";
        renderChatSessionList();
      });

      rowActions.append(restoreButton, permanentDeleteButton);
      row.append(sessionButton, rowActions);
      elements.chatSessionList.appendChild(row);
      return;
    }

    const renameButton = document.createElement("button");
    renameButton.className = "ask-session-mini";
    renameButton.type = "button";
    renameButton.textContent = "Rename";
    renameButton.addEventListener("click", (event) => {
      event.stopPropagation();
      readerState.renamingSessionId = session.id;
      readerState.confirmingDeleteSessionId = "";
      renderChatSessionList();
    });

    const deleteButton = document.createElement("button");
    deleteButton.className = "ask-session-mini ask-session-delete";
    deleteButton.type = "button";
    deleteButton.textContent = session.id === readerState.confirmingDeleteSessionId ? "Move" : "Trash";
    deleteButton.setAttribute("aria-label", `Move ${session.title || "chat session"} to Trash`);
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      if (readerState.confirmingDeleteSessionId === session.id) {
        trashReaderChatSession(session.id);
        return;
      }
      readerState.confirmingDeleteSessionId = session.id;
      readerState.renamingSessionId = "";
      renderChatSessionList();
    });

    rowActions.append(renameButton, deleteButton);
    row.append(sessionButton, rowActions);
    elements.chatSessionList.appendChild(row);
  });
}

function setChatSessionMenuOpen(open) {
  readerState.chatSessionMenuOpen = open;
  if (elements.chatSessionPopover) elements.chatSessionPopover.hidden = !open;
  elements.chatSessionMenuButton?.setAttribute("aria-expanded", String(open));
  if (open) {
    renderChatSessionList();
    requestAnimationFrame(() => elements.chatSessionSearch?.focus());
  } else {
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
  }
}

async function fetchReaderChatSessions({ silent = false } = {}) {
  const noteId = currentChatNoteId();
  if (!noteId) {
    readerState.chatSessions = [];
    renderChatSessionList();
    return [];
  }

  if (!silent) {
    readerState.chatSessionsLoading = true;
    renderChatSessionList();
  }

  try {
    const trashParam = readerState.chatSessionTrashOpen ? "&trashed=1" : "";
    const response = await fetch(getApiUrl(`/api/chat-sessions?noteId=${encodeURIComponent(noteId)}${trashParam}&t=${Date.now()}`), {
      cache: "no-store"
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.error || `Could not load sessions (${response.status})`);
    readerState.chatSessions = Array.isArray(payload?.sessions) ? payload.sessions : [];
    return readerState.chatSessions;
  } catch (error) {
    console.warn("Failed to load chat sessions.", error);
    if (!silent) setReaderChatError(error.message || "Could not load chat sessions.");
    readerState.chatSessions = [];
    return [];
  } finally {
    readerState.chatSessionsLoading = false;
    renderChatSessionList();
  }
}

function clearCurrentReaderChatSession() {
  readerState.chatMessages = [];
  setCurrentChatSessionId("");
  renderReaderChatMessages();
  setReaderChatError("");
}

async function loadReaderChatSession(sessionId, { closeMenu = true, refreshList = false } = {}) {
  const nextSessionId = normalizeText(sessionId);
  if (!nextSessionId) {
    clearCurrentReaderChatSession();
    return;
  }

  try {
    const response = await fetch(getApiUrl(`/api/chat-sessions/${encodeURIComponent(nextSessionId)}?t=${Date.now()}`), {
      cache: "no-store"
    });
    const session = await response.json().catch(() => null);
    if (!response.ok || !session?.id) throw new Error(`Could not load session (${response.status})`);
    setCurrentChatSessionId(session.id);
    readerState.chatMessages = Array.isArray(session.messages) ? session.messages.map(normalizeChatMessage) : [];
    setReaderChatError("");
    renderReaderChatMessages();
    if (closeMenu) setChatSessionMenuOpen(false);
    if (refreshList) await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    console.warn("Failed to load chat session.", error);
    setReaderChatError(error.message || "Could not load chat session.");
  }
}

async function createReaderChatSession() {
  const noteId = currentChatNoteId();
  if (!noteId) return;
  try {
    readerState.chatSessionTrashOpen = false;
    const response = await fetch(getApiUrl("/api/chat-sessions"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ noteId })
    });
    const session = await response.json().catch(() => null);
    if (!response.ok || !session?.id) throw new Error(`Could not create session (${response.status})`);
    setCurrentChatSessionId(session.id);
    readerState.chatMessages = [];
    readerState.chatSessionQuery = "";
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    setReaderChatError("");
    renderReaderChatMessages();
    await fetchReaderChatSessions({ silent: true });
    setChatSessionMenuOpen(false);
    elements.readerChatInput?.focus();
  } catch (error) {
    console.warn("Failed to create chat session.", error);
    setReaderChatError(error.message || "Could not create chat session.");
  }
}

async function renameReaderChatSession(sessionId, title) {
  const nextTitle = normalizeText(title);
  if (!sessionId || !nextTitle) return;
  try {
    const response = await fetch(getApiUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: nextTitle })
    });
    const session = await response.json().catch(() => null);
    if (!response.ok || !session?.id) throw new Error(`Could not rename session (${response.status})`);
    readerState.renamingSessionId = "";
    readerState.confirmingDeleteSessionId = "";
    await fetchReaderChatSessions({ silent: true });
    renderChatSessionList();
  } catch (error) {
    console.warn("Failed to rename chat session.", error);
    setReaderChatError(error.message || "Could not rename chat session.");
  }
}

function exportCurrentReaderChatSession() {
  const sessionId = getChatSessionId();
  if (!sessionId) return;
  const link = document.createElement("a");
  link.href = getApiUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}/export`);
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setChatSessionMenuOpen(false);
}

async function trashReaderChatSession(sessionId) {
  const deletingCurrentSession = sessionId === readerState.chatSessionId;
  try {
    const response = await fetch(getApiUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}`), {
      method: "DELETE"
    });
    if (!response.ok) throw new Error(`Could not move session to Trash (${response.status})`);
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    const sessions = await fetchReaderChatSessions({ silent: true });
    if (deletingCurrentSession) {
      if (sessions[0]?.id) {
        await loadReaderChatSession(sessions[0].id, { closeMenu: false });
      } else {
        clearCurrentReaderChatSession();
      }
    }
    renderChatSessionList();
  } catch (error) {
    console.warn("Failed to move chat session to Trash.", error);
    setReaderChatError(error.message || "Could not move chat session to Trash.");
  }
}

async function restoreReaderChatSession(sessionId) {
  try {
    const response = await fetch(getApiUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}/restore`), {
      method: "POST"
    });
    const session = await response.json().catch(() => null);
    if (!response.ok || !session?.id) throw new Error(`Could not restore session (${response.status})`);
    readerState.chatSessionTrashOpen = false;
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    await fetchReaderChatSessions({ silent: true });
    await loadReaderChatSession(session.id, { closeMenu: false });
    renderChatSessionList();
  } catch (error) {
    console.warn("Failed to restore chat session.", error);
    setReaderChatError(error.message || "Could not restore chat session.");
  }
}

async function permanentlyDeleteReaderChatSession(sessionId) {
  try {
    const response = await fetch(getApiUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}/permanent`), {
      method: "DELETE"
    });
    if (!response.ok) throw new Error(`Could not permanently delete session (${response.status})`);
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    await fetchReaderChatSessions({ silent: true });
    renderChatSessionList();
  } catch (error) {
    console.warn("Failed to permanently delete chat session.", error);
    setReaderChatError(error.message || "Could not permanently delete chat session.");
  }
}

async function initializeReaderChatSessions() {
  const sessions = await fetchReaderChatSessions({ silent: true });
  const latestSession = sessions[0];
  if (latestSession?.id) {
    await loadReaderChatSession(latestSession.id, { closeMenu: false });
  } else {
    clearCurrentReaderChatSession();
  }
}

async function sendReaderChatMessage() {
  const text = normalizeText(elements.readerChatInput?.value);
  if (!text || readerState.chatPending) return;
  const requestId = createRequestId();

  elements.readerChatInput.value = "";
  setReaderChatError("");
  readerState.chatMessages.push({ role: "user", text });
  renderReaderChatMessages();
  setReaderChatPending(true);
  startReaderChatProgress(requestId);

  let payload = null;
  try {
    const response = await fetch(getApiUrl("/api/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        requestId,
        message: text,
        sessionId: getChatSessionId(),
        context: readerChatContext()
      })
    });
    payload = await response.json().catch(() => null);

    if (payload?.sessionId) {
      setCurrentChatSessionId(payload.sessionId);
    }

    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.error || `Agent request failed (${response.status})`);
    }

    readerState.chatMessages.push({
      role: "assistant",
      text: normalizeText(payload.answer) || "No answer returned.",
      sources: normalizeChatSources(payload.sources),
      noteEdit: normalizeNoteEditDraft(payload.noteEdit)
    });
    void fetchReaderChatSessions({ silent: true });
  } catch (error) {
    if (payload?.sessionId) setCurrentChatSessionId(payload.sessionId);
    setReaderChatError(GENERIC_AGENT_ERROR);
    readerState.chatMessages.push({
      role: "assistant",
      text: GENERIC_AGENT_ERROR,
      error: true
    });
    void fetchReaderChatSessions({ silent: true });
  } finally {
    clearReaderChatProgress();
    renderReaderChatMessages();
    setReaderChatPending(false);
    elements.readerChatInput?.focus();
  }
}

function initializeReaderChat() {
  renderReaderChatMessages();
  elements.readerChatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    sendReaderChatMessage();
  });
  elements.readerChatMessages?.addEventListener("click", handleChatSourceClick);
  elements.readerChatMessages?.addEventListener("click", handleNoteEditDraftClick);
  elements.chatSessionMenuButton?.addEventListener("click", () => {
    setChatSessionMenuOpen(!readerState.chatSessionMenuOpen);
  });
  elements.newChatSession?.addEventListener("click", createReaderChatSession);
  elements.exportChatSession?.addEventListener("click", exportCurrentReaderChatSession);
  elements.toggleChatSessionTrash?.addEventListener("click", async () => {
    readerState.chatSessionTrashOpen = !readerState.chatSessionTrashOpen;
    readerState.chatSessionQuery = "";
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    await fetchReaderChatSessions({ silent: false });
  });
  elements.chatSessionSearch?.addEventListener("input", (event) => {
    readerState.chatSessionQuery = event.target.value;
    readerState.confirmingDeleteSessionId = "";
    renderChatSessionList();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!readerState.chatSessionMenuOpen) return;
    if (elements.chatSessionPopover?.contains(event.target) || elements.chatSessionMenuButton?.contains(event.target)) return;
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    setChatSessionMenuOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && readerState.chatSessionMenuOpen) setChatSessionMenuOpen(false);
  });
}

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

  elements.resizer.addEventListener("pointerdown", (event) => {
    if (window.matchMedia("(max-width: 900px)").matches) return;
    splitState.dragging = true;
    elements.resizer.setPointerCapture(event.pointerId);
    document.body.classList.add("is-resizing-reader");
    updateSplitFromClientX(event.clientX);
  });

  elements.resizer.addEventListener("pointermove", (event) => {
    if (!splitState.dragging) return;
    updateSplitFromClientX(event.clientX);
  });

  elements.resizer.addEventListener("pointerup", (event) => {
    splitState.dragging = false;
    elements.resizer.releasePointerCapture(event.pointerId);
    document.body.classList.remove("is-resizing-reader");
  });

  elements.resizer.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -2 : 2;
    setSplitPercent(readSplitPercent() + delta);
  });

  if (!elements.askResizer) return;

  elements.askResizer.addEventListener("pointerdown", (event) => {
    if (window.matchMedia("(max-width: 900px)").matches) return;
    if (elements.layout?.classList.contains("is-ask-pane-hidden")) return;
    splitState.askDragging = true;
    elements.askResizer.setPointerCapture(event.pointerId);
    document.body.classList.add("is-resizing-reader");
    updateAskWidthFromClientX(event.clientX);
  });

  elements.askResizer.addEventListener("pointermove", (event) => {
    if (!splitState.askDragging) return;
    updateAskWidthFromClientX(event.clientX);
  });

  elements.askResizer.addEventListener("pointerup", (event) => {
    splitState.askDragging = false;
    elements.askResizer.releasePointerCapture(event.pointerId);
    document.body.classList.remove("is-resizing-reader");
  });

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

  const viewerBox = viewer.getBoundingClientRect();
  const anchorOffset = pdfScrollAnchorOffset();
  const anchorY = viewerBox.top + anchorOffset;
  let bestPage = null;
  let bestDistance = Number.POSITIVE_INFINITY;

  pages.forEach((pageElement) => {
    const rect = pageElement.getBoundingClientRect();
    const distance = rect.top <= anchorY && rect.bottom >= anchorY
      ? 0
      : Math.min(Math.abs(rect.top - anchorY), Math.abs(rect.bottom - anchorY));
    if (distance < bestDistance) {
      bestDistance = distance;
      bestPage = { element: pageElement, rect };
    }
  });

  if (!bestPage) return null;
  return {
    page: Number(bestPage.element.dataset.page) || 1,
    offset: clamp((anchorY - bestPage.rect.top) / Math.max(1, bestPage.rect.height), 0, 1),
    scrollTop: viewer.scrollTop,
    scale: pdfState.scale,
    updatedAt: Date.now()
  };
}

function storedPdfScrollPosition() {
  if (!pdfState.noteId) return null;
  return readPdfScrollStore()[pdfState.noteId] || null;
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
  if (pdfState.suppressScrollSave) return;
  updatePdfPageControl();
  window.clearTimeout(pdfState.scrollSaveTimer);
  pdfState.scrollSaveTimer = window.setTimeout(persistPdfScrollPosition, 120);
}

function pdfScrollTopFromPosition(position) {
  const viewer = elements.pdfViewer;
  if (!viewer || !position) return null;
  const pageElement = viewer.querySelector(`.pdf-page[data-page="${Number(position.page) || 1}"]`);
  if (!pageElement) {
    return Number.isFinite(position.scrollTop) ? position.scrollTop : null;
  }

  const viewerBox = viewer.getBoundingClientRect();
  const pageBox = pageElement.getBoundingClientRect();
  const anchorOffset = pdfScrollAnchorOffset();
  const pageOffset = clamp(Number(position.offset) || 0, 0, 1) * pageBox.height;
  return viewer.scrollTop + pageBox.top - viewerBox.top + pageOffset - anchorOffset;
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
  const viewerBox = viewer.getBoundingClientRect();
  const pageBox = pageElement.getBoundingClientRect();
  viewer.scrollTo({
    top: viewer.scrollTop + pageBox.top - viewerBox.top,
    behavior
  });
  updatePdfPageControl(targetPage);
  return true;
}

function restorePdfScrollPosition(position) {
  scrollToPdfPosition(position, "auto");
}

function finishPdfScrollRestore(position) {
  restorePdfScrollPosition(position);
  updatePdfPageControl();
  window.requestAnimationFrame(() => {
    restorePdfScrollPosition(position);
    updatePdfPageControl();
    window.setTimeout(() => {
      pdfState.suppressScrollSave = false;
      persistPdfScrollPosition();
      updatePdfPageControl();
    }, 80);
  });
}

function initializePdfScrollPersistence() {
  elements.pdfViewer?.addEventListener("scroll", schedulePersistPdfScrollPosition, { passive: true });
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
  scrollToPdfPage(rawPage, "smooth");
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
      applyRectStyle(item, rect, box);
      applyAnnotationColor(item, annotation);
      item.dataset.annotationId = annotation.id;
      item.title = annotationSummary(annotation);
      item.setAttribute("aria-label", item.title);
      item.addEventListener("pointerdown", (event) => {
        event.stopPropagation();
      });
      item.addEventListener("click", (event) => {
        event.stopPropagation();
        openAnnotationEditor(annotation, pageElement);
      });
      overlay.appendChild(item);
    });
  });
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

function openAnnotationEditor(annotation, pageElement, options = {}) {
  closeNoteEditor();
  pdfState.selectedAnnotationId = annotation.id;
  renderAnnotationList();
  const overlay = pageElement.querySelector(".pdf-annotation-layer");
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!overlay || !canvas) return;

  const box = { width: canvas.clientWidth, height: canvas.clientHeight };
  const editor = document.createElement("form");
  editor.className = "pdf-annotation-editor";
  editor.tabIndex = -1;
  editor.dataset.annotationId = annotation.id;
  applyAnnotationColor(editor, annotation);
  editor.style.left = `${clamp((annotation.x + annotation.w) * box.width + 10, 10, box.width - 270)}px`;
  editor.style.top = `${clamp(annotation.y * box.height, 10, box.height - 190)}px`;
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
    scheduleSaveAnnotations();
    closeNoteEditor();
    renderAllAnnotations();
  });
  pageElement.appendChild(editor);
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

function jumpToAnnotation(annotationId) {
  const annotation = pdfState.annotations.find((entry) => entry.id === annotationId);
  if (!annotation) return;
  pdfState.selectedAnnotationId = annotation.id;
  renderAllAnnotations();
  const pageElement = elements.pdfViewer.querySelector(`[data-page="${annotation.page}"]`);
  if (!pageElement) return;
  pageElement.scrollIntoView({ block: "center", behavior: "smooth" });
  window.setTimeout(() => openAnnotationEditor(annotation, pageElement), 180);
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

function groupTextItemsByLine(items) {
  const lines = [];
  items
    .sort((a, b) => a.rect.top - b.rect.top || a.rect.left - b.rect.left)
    .forEach((item) => {
      const center = (item.rect.top + item.rect.bottom) / 2;
      const threshold = Math.max(4, item.rect.height * 0.55);
      let line = lines.find((entry) => Math.abs(entry.center - center) <= threshold);
      if (!line) {
        line = { center, items: [] };
        lines.push(line);
      }
      line.items.push(item);
      line.center = line.items.reduce((sum, entry) => sum + ((entry.rect.top + entry.rect.bottom) / 2), 0) / line.items.length;
    });
  return lines;
}

function lineBoundsFromItems(items) {
  return {
    left: Math.min(...items.map((item) => item.rect.left)),
    right: Math.max(...items.map((item) => item.rect.right)),
    top: Math.min(...items.map((item) => item.rect.top)),
    bottom: Math.max(...items.map((item) => item.rect.bottom))
  };
}

function lineRectsFromClientRects(clientRects, pageBox, type) {
  const items = clientRects
    .map((rect) => clampClientRectToPage(rect, pageBox))
    .filter((rect) => rect.width > 1 && rect.height > 1);

  return groupTextItemsByLine(items.map((rect) => ({ rect }))).map((line) => {
    const { left, right, top, bottom } = lineBoundsFromItems(line.items);
    const lineHeight = Math.max(1, bottom - top);
    const underlineHeight = Math.max(2, lineHeight * 0.13);
    const visualTop = type === "underline" ? bottom - underlineHeight : top + lineHeight * 0.08;
    const visualHeight = type === "underline" ? underlineHeight : lineHeight * 0.84;
    return normalizeAnnotationRect({
      x: (left - pageBox.left) / pageBox.width,
      y: (visualTop - pageBox.top) / pageBox.height,
      w: (right - left) / pageBox.width,
      h: visualHeight / pageBox.height
    });
  }).filter((rect) => rect.w >= 0.004 && rect.h >= 0.001);
}

function selectionClientRectsForPage(pageElement) {
  const selection = window.getSelection();
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  const textLayer = pageElement.querySelector(".textLayer");
  if (!selection || selection.isCollapsed || !canvas || !textLayer) return [];

  const pageBox = canvas.getBoundingClientRect();
  const layerBox = textLayer.getBoundingClientRect();
  const clientRects = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    if (!textLayer.contains(range.commonAncestorContainer) && !range.intersectsNode(textLayer)) continue;
    Array.from(range.getClientRects())
      .filter((rect) => rectsIntersect(rect, layerBox) && rectsIntersect(rect, pageBox))
      .forEach((rect) => clientRects.push(rect));
  }
  return clientRects;
}

function selectedLineRectsForPage(pageElement, type) {
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!canvas) return [];
  const pageBox = canvas.getBoundingClientRect();
  const clientRects = selectionClientRectsForPage(pageElement);
  return lineRectsFromClientRects(clientRects, pageBox, type);
}

function horizontalOverlap(a, b) {
  return Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
}

function verticalOverlap(a, b) {
  return Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
}

function sliceSpanTextByRect(span, selectionRect) {
  const text = span.textContent || "";
  const spanRect = span.getBoundingClientRect();
  if (!text || spanRect.width <= 0) return "";
  const left = clamp(Math.max(selectionRect.left, spanRect.left) - spanRect.left, 0, spanRect.width);
  const right = clamp(Math.min(selectionRect.right, spanRect.right) - spanRect.left, 0, spanRect.width);
  if (right <= left) return "";

  const style = getComputedStyle(span);
  const canvas = sliceSpanTextByRect.canvas || (sliceSpanTextByRect.canvas = document.createElement("canvas"));
  const context = canvas.getContext("2d");
  context.font = style.font || `${style.fontSize} ${style.fontFamily}`;

  const totalMeasured = Math.max(0.001, context.measureText(text).width);
  const positions = [0];
  let measured = 0;
  Array.from(text).forEach((char) => {
    measured += context.measureText(char).width;
    positions.push((measured / totalMeasured) * spanRect.width);
  });

  let startIndex = 0;
  let endIndex = text.length;
  for (let index = 0; index < text.length; index += 1) {
    const center = (positions[index] + positions[index + 1]) / 2;
    if (center >= left) {
      startIndex = index;
      break;
    }
  }
  for (let index = text.length - 1; index >= 0; index -= 1) {
    const center = (positions[index] + positions[index + 1]) / 2;
    if (center <= right) {
      endIndex = index + 1;
      break;
    }
  }
  return text.slice(startIndex, endIndex);
}

function textFromSelectionForPage(pageElement) {
  const clientRects = selectionClientRectsForPage(pageElement);
  if (!clientRects.length) return "";

  const spans = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
    .map((span) => ({ span, text: span.textContent || "", rect: span.getBoundingClientRect() }))
    .filter((entry) => normalizeText(entry.text) && entry.rect.width > 0 && entry.rect.height > 0);

  const lines = groupTextItemsByLine(clientRects.map((rect) => ({ rect })));
  const lineTexts = lines.map((line) => {
    const lineRect = lineBoundsFromItems(line.items);
    return spans
      .filter((entry) => {
        const vOverlap = verticalOverlap(entry.rect, lineRect);
        const hOverlap = horizontalOverlap(entry.rect, lineRect);
        return hOverlap > 1 && vOverlap >= Math.min(entry.rect.height, lineRect.bottom - lineRect.top) * 0.35;
      })
      .sort((a, b) => a.rect.left - b.rect.left)
      .map((entry) => sliceSpanTextByRect(entry.span, lineRect))
      .join("");
  });
  return normalizeCopiedPdfText(lineTexts.join("\n"));
}

function addNoteAnnotation(event, pageElement) {
  const point = normalizedPointer(event, pageElement);
  const box = pageViewportBox(pageElement);
  const noteWidth = PDF_NOTE_MARKER_SIZE / Math.max(1, box.width);
  const noteHeight = PDF_NOTE_MARKER_SIZE / Math.max(1, box.height);
  const annotation = normalizeAnnotation({
    id: `note-${Date.now().toString(36)}`,
    type: "note",
    page: Number(pageElement.dataset.page),
    x: clamp(point.x - noteWidth / 2, 0, 1 - noteWidth),
    y: clamp(point.y - noteHeight / 2, 0, 1 - noteHeight),
    w: noteWidth,
    h: noteHeight,
    color: pdfState.color,
    text: "",
    comment: ""
  });
  pushAnnotationHistory();
  pdfState.annotations.push(annotation);
  scheduleSaveAnnotations();
  renderAnnotationsForPage(pageElement);
  openAnnotationEditor(annotation, pageElement, { focusComment: true });
}

function finishSelectionAnnotation(pageElement, type) {
  window.setTimeout(() => {
    const rects = selectedLineRectsForPage(pageElement, type);
    if (!rects.length) return;
    const bounds = annotationBounds(rects);
    const selectedText = textFromSelectionForPage(pageElement);
    const annotation = normalizeAnnotation({
      id: `${type}-${Date.now().toString(36)}`,
      type,
      page: Number(pageElement.dataset.page),
      ...bounds,
      rects,
      color: pdfState.color,
      quote: selectedText,
      text: "",
      comment: ""
    });
    if (annotation.w < 0.01 || annotation.h < 0.001) return;
    pushAnnotationHistory();
    pdfState.annotations.push(annotation);
    window.getSelection()?.removeAllRanges();
    scheduleSaveAnnotations();
    renderAnnotationsForPage(pageElement);
  }, 0);
}

function isPdfLinkAnnotation(annotation) {
  return annotation?.subtype === "Link" || annotation?.annotationType === pdfjsLib?.AnnotationType?.LINK;
}

function normalizePdfLinkAnnotation(annotation, viewport) {
  if (!isPdfLinkAnnotation(annotation) || !Array.isArray(annotation.rect)) return null;
  const rect = viewport.convertToViewportRectangle(annotation.rect);
  const left = Math.min(rect[0], rect[2]);
  const top = Math.min(rect[1], rect[3]);
  const right = Math.max(rect[0], rect[2]);
  const bottom = Math.max(rect[1], rect[3]);
  const link = {
    rect: normalizeAnnotationRect({
      x: left / viewport.width,
      y: top / viewport.height,
      w: (right - left) / viewport.width,
      h: (bottom - top) / viewport.height
    }),
    url: normalizeText(annotation.url || annotation.unsafeUrl),
    dest: annotation.dest || null,
    action: normalizeText(annotation.action),
    title: normalizeText(annotation.title || annotation.contents)
  };
  if (!link.url && !link.dest && !link.action) return null;
  return link.rect.w > 0 && link.rect.h > 0 ? link : null;
}

async function pdfLinkAnnotationsForPage(page, viewport) {
  try {
    const annotations = await page.getAnnotations({ intent: "display" });
    return annotations
      .map((annotation) => normalizePdfLinkAnnotation(annotation, viewport))
      .filter(Boolean);
  } catch (error) {
    console.warn("Failed to read PDF links.", error);
    return [];
  }
}

function pdfLinkAtPoint(event, pageElement) {
  if (pdfState.mode !== "pan") return null;
  if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return null;
  const links = pageElement._pdfLinks || [];
  if (!links.length) return null;
  const point = normalizedPointer(event, pageElement);
  return links.find((link) => {
    const rect = link.rect;
    return point.x >= rect.x && point.x <= rect.x + rect.w && point.y >= rect.y && point.y <= rect.y + rect.h;
  }) || null;
}

function targetPageElement(pageNumber) {
  return elements.pdfViewer?.querySelector(`.pdf-page[data-page="${pageNumber}"]`) || null;
}

async function pageNumberFromDestination(destination) {
  if (!Array.isArray(destination) || !pdfState.document) return 1;
  const pageRef = destination[0];
  if (typeof pageRef === "number") return pageRef + 1;
  try {
    return (await pdfState.document.getPageIndex(pageRef)) + 1;
  } catch (error) {
    console.warn("Failed to resolve PDF destination page.", error);
    return 1;
  }
}

function showPdfLinkBackButton(position) {
  if (!position || !elements.pdfLinkReturn) return;
  pdfState.linkReturnPosition = position;
  elements.pdfLinkReturn.hidden = false;
}

function hidePdfLinkBackButton() {
  pdfState.linkReturnPosition = null;
  if (elements.pdfLinkReturn) elements.pdfLinkReturn.hidden = true;
}

function returnFromPdfLink() {
  if (!pdfState.linkReturnPosition) return;
  scrollToPdfPosition(pdfState.linkReturnPosition, "smooth");
  hidePdfLinkBackButton();
}

function destinationTopValue(destination) {
  if (!Array.isArray(destination)) return null;
  const mode = typeof destination[1] === "string" ? destination[1] : destination[1]?.name;
  const value = {
    XYZ: destination[3],
    FitH: destination[2],
    FitBH: destination[2],
    FitR: destination[5]
  }[mode] ?? null;
  if (value == null) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function sectionNumberFromDestination(destinationName) {
  const match = normalizeText(destinationName).match(/^section\.([A-Za-z0-9.]+)$/);
  return match ? match[1] : "";
}

function lineTextFromItems(items) {
  return normalizeText(items
    .slice()
    .sort((a, b) => a.rect.left - b.rect.left)
    .map((item) => item.text || item.span?.textContent || "")
    .join("")
    .replace(/\s+/g, " "));
}

function sectionHeadingPattern(sectionNumber) {
  const pieces = normalizeText(sectionNumber).split(".").map(escapeRegExp);
  return new RegExp(`^${pieces.join("\\s*\\.\\s*")}(?:\\s|$|[.)])`);
}

function pdfTextLineBounds(pageElement) {
  const pageBox = pageElement.getBoundingClientRect();
  const spans = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
    .map((span) => ({ span, rect: span.getBoundingClientRect(), text: span.textContent || "" }))
    .filter((entry) => normalizeText(entry.text) && entry.rect.width > 0 && entry.rect.height > 0);
  return groupTextItemsByLine(spans).map((line) => {
    const bounds = lineBoundsFromItems(line.items);
    const localTop = bounds.top - pageBox.top;
    const localBottom = bounds.bottom - pageBox.top;
    return {
      ...bounds,
      localTop,
      localBottom,
      localCenter: (localTop + localBottom) / 2,
      localHeight: Math.max(1, localBottom - localTop),
      text: lineTextFromItems(line.items)
    };
  }).filter((line) => normalizeText(line.text))
    .sort((a, b) => a.localTop - b.localTop || a.left - b.left);
}

function pdfTargetLineBounds(pageElement, y, options = {}) {
  if (!Number.isFinite(y)) return null;
  const lineBounds = pdfTextLineBounds(pageElement);
  if (!lineBounds.length) return null;

  const sectionNumber = normalizeText(options.sectionNumber);
  if (sectionNumber) {
    const headingPattern = sectionHeadingPattern(sectionNumber);
    const sectionLine = lineBounds.find((bounds) => (
      bounds.localTop >= y - 20
      && bounds.localTop <= y + 260
      && headingPattern.test(bounds.text)
    ));
    if (sectionLine) return sectionLine;
  }

  const insideLine = lineBounds.find((bounds) => (
    y >= bounds.localTop + Math.min(8, bounds.localHeight * 0.25)
    && y <= bounds.localBottom - Math.min(2, bounds.localHeight * 0.08)
  ));
  const belowLine = lineBounds
    .filter((bounds) => bounds.localTop >= y - Math.max(6, bounds.localHeight * 0.2))
    .sort((a, b) => a.localTop - b.localTop)[0];
  const nearestLine = lineBounds
    .slice()
    .sort((a, b) => Math.abs(a.localCenter - y) - Math.abs(b.localCenter - y))[0];
  return insideLine || belowLine || nearestLine || null;
}

function pdfTargetScrollY(pageElement, y, options = {}) {
  if (!Number.isFinite(y)) return y;
  if (!normalizeText(options.sectionNumber)) return y;
  const targetLine = pdfTargetLineBounds(pageElement, y, options);
  return targetLine ? Math.max(0, targetLine.localTop - 18) : y;
}

function pdfTargetHighlightRect(pageElement, y, options = {}) {
  const pageBox = pageElement.getBoundingClientRect();
  const bestLine = pdfTargetLineBounds(pageElement, y, options);

  if (!bestLine) {
    return {
      left: pageBox.width * 0.06,
      top: Math.max(0, Number.isFinite(y) ? y - 18 : pageBox.height * 0.06),
      width: pageBox.width * 0.88,
      height: Math.max(38, pageBox.height * 0.045)
    };
  }

  return {
    left: Math.max(0, bestLine.left - pageBox.left - 8),
    top: Math.max(0, bestLine.top - pageBox.top - 6),
    width: Math.min(pageBox.width, bestLine.right - bestLine.left + 16),
    height: Math.max(30, bestLine.bottom - bestLine.top + 12)
  };
}

function flashPdfJumpTarget(pageElement, y = null, options = {}) {
  if (!pageElement) return;
  pageElement.querySelectorAll(".pdf-link-target-flash").forEach((element) => element.remove());
  const rect = pdfTargetHighlightRect(pageElement, y, options);
  const marker = document.createElement("div");
  marker.className = "pdf-link-target-flash";
  marker.style.left = `${rect.left}px`;
  marker.style.top = `${rect.top}px`;
  marker.style.width = `${rect.width}px`;
  marker.style.height = `${rect.height}px`;
  pageElement.appendChild(marker);
  window.setTimeout(() => marker.remove(), 2600);
}

async function scrollToPdfDestination(rawDestination) {
  if (!rawDestination || !pdfState.document) return false;
  const destinationName = typeof rawDestination === "string" ? rawDestination : "";
  const targetOptions = {
    destinationName,
    sectionNumber: sectionNumberFromDestination(destinationName)
  };
  const destination = typeof rawDestination === "string"
    ? await pdfState.document.getDestination(rawDestination)
    : rawDestination;
  if (!Array.isArray(destination)) return false;

  const pageNumber = await pageNumberFromDestination(destination);
  const pageElement = targetPageElement(pageNumber);
  if (!pageElement) return false;

  const topValue = destinationTopValue(destination);
  if (!Number.isFinite(topValue)) {
    pageElement.scrollIntoView({ block: "start", behavior: "smooth" });
    window.setTimeout(() => flashPdfJumpTarget(pageElement), 280);
    return true;
  }

  const page = await pdfState.document.getPage(pageNumber);
  const viewport = page.getViewport({ scale: pdfState.scale });
  const [, y] = viewport.convertToViewportPoint(0, topValue);
  const scrollY = pdfTargetScrollY(pageElement, y, targetOptions);
  const viewerBox = elements.pdfViewer.getBoundingClientRect();
  const pageBox = pageElement.getBoundingClientRect();
  elements.pdfViewer.scrollTo({
    top: elements.pdfViewer.scrollTop + pageBox.top - viewerBox.top + scrollY - pdfScrollAnchorOffset(),
    behavior: "smooth"
  });
  window.setTimeout(() => flashPdfJumpTarget(pageElement, y, targetOptions), 280);
  return true;
}

function scrollToPdfNamedAction(action) {
  const pageCount = Number(pdfState.document?.numPages || pdfState.document?._pdfInfo?.numPages || 0);
  const currentPage = currentPdfScrollPosition()?.page || 1;
  const actions = {
    FirstPage: 1,
    LastPage: pageCount,
    NextPage: Math.min(pageCount, currentPage + 1),
    PrevPage: Math.max(1, currentPage - 1)
  };
  const pageNumber = actions[action];
  if (!pageNumber) return false;
  const pageElement = targetPageElement(pageNumber);
  pageElement?.scrollIntoView({ block: "start", behavior: "smooth" });
  window.setTimeout(() => flashPdfJumpTarget(pageElement), 280);
  return true;
}

async function activatePdfLink(link) {
  if (link.url) {
    window.open(link.url, "_blank", "noopener,noreferrer");
    return;
  }
  if (link.dest) {
    const returnPosition = currentPdfScrollPosition();
    const didNavigate = await scrollToPdfDestination(link.dest);
    if (didNavigate) showPdfLinkBackButton(returnPosition);
    return;
  }
  if (link.action) {
    const returnPosition = currentPdfScrollPosition();
    if (scrollToPdfNamedAction(link.action)) showPdfLinkBackButton(returnPosition);
  }
}

function handlePdfLinkClick(event) {
  if (normalizeText(window.getSelection()?.toString())) return;
  const link = pdfLinkAtPoint(event, event.currentTarget);
  if (!link) return;
  event.preventDefault();
  event.stopPropagation();
  activatePdfLink(link);
}

function handlePdfLinkPointerMove(event) {
  const link = pdfLinkAtPoint(event, event.currentTarget);
  event.currentTarget.classList.toggle("is-over-pdf-link", Boolean(link));
}

function wirePageAnnotationEvents(pageElement) {
  pageElement.addEventListener("click", handlePdfLinkClick);
  pageElement.addEventListener("pointermove", handlePdfLinkPointerMove);
  pageElement.addEventListener("pointerleave", () => pageElement.classList.remove("is-over-pdf-link"));
  pageElement.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || pdfState.mode === "pan") return;
    if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return;
    if (pdfState.mode === "note") {
      event.preventDefault();
      addNoteAnnotation(event, pageElement);
    }
  });
  pageElement.addEventListener("pointerup", (event) => {
    if (!["highlight", "underline"].includes(pdfState.mode)) return;
    if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return;
    finishSelectionAnnotation(pageElement, pdfState.mode);
  });
}

function normalizeCopiedPdfText(text) {
  return String(text || "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]*\n[ \t]*/g, "\n")
    .replace(/([A-Za-z0-9,.;:)%])\n([A-Za-z0-9(])/g, "$1 $2")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function median(values) {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!sorted.length) return 0;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function textLayerLines(textLayer) {
  const spans = Array.from(textLayer.querySelectorAll("span[role='presentation']"))
    .map((span) => ({ span, text: span.textContent || "", rect: span.getBoundingClientRect() }))
    .filter((entry) => normalizeText(entry.text) && entry.rect.width > 0 && entry.rect.height > 0);

  return groupTextItemsByLine(spans).map((line) => {
    const items = line.items
      .filter((item) => item.span)
      .sort((a, b) => a.rect.left - b.rect.left);
    const bounds = lineBoundsFromItems(items);
    return {
      ...bounds,
      height: Math.max(1, bounds.bottom - bounds.top),
      width: Math.max(1, bounds.right - bounds.left),
      items,
      text: items.map((item) => item.text).join("")
    };
  }).filter((line) => normalizeText(line.text));
}

function selectSpanRange(firstSpan, lastSpan) {
  const firstNode = firstSpan?.firstChild;
  const lastNode = lastSpan?.firstChild;
  if (!firstNode || !lastNode) return false;
  const range = document.createRange();
  range.setStart(firstNode, 0);
  range.setEnd(lastNode, lastNode.textContent.length);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  return true;
}

function selectTextLayerLines(lines) {
  const firstSpan = lines.at(0)?.items.at(0)?.span;
  const lastSpan = lines.at(-1)?.items.at(-1)?.span;
  return selectSpanRange(firstSpan, lastSpan);
}

function findTextLayerLineIndex(lines, targetSpan, event) {
  const spanIndex = lines.findIndex((line) => line.items.some((item) => item.span === targetSpan));
  if (spanIndex !== -1) return spanIndex;
  const y = event.clientY;
  let bestIndex = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  lines.forEach((line, index) => {
    const center = (line.top + line.bottom) / 2;
    const distance = Math.abs(center - y);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function lineGap(previousLine, nextLine) {
  return Math.max(0, nextLine.top - previousLine.bottom);
}

function shouldJoinParagraphLine(previousLine, nextLine, typicalGap) {
  const gap = lineGap(previousLine, nextLine);
  const averageHeight = (previousLine.height + nextLine.height) / 2;
  const heightRatio = Math.max(previousLine.height, nextLine.height) / Math.max(1, Math.min(previousLine.height, nextLine.height));
  const overlap = horizontalOverlap(previousLine, nextLine) / Math.max(1, Math.min(previousLine.width, nextLine.width));
  const maxGap = Math.max(averageHeight * 0.92, typicalGap * 2.2, 8);
  return gap <= maxGap && overlap >= 0.35 && heightRatio <= 1.45;
}

function paragraphLinesAround(lines, lineIndex) {
  const gaps = lines.slice(1).map((line, index) => lineGap(lines[index], line));
  const typicalGap = median(gaps) || 0;
  let start = lineIndex;
  let end = lineIndex;

  while (start > 0 && shouldJoinParagraphLine(lines[start - 1], lines[start], typicalGap)) {
    start -= 1;
  }
  while (end < lines.length - 1 && shouldJoinParagraphLine(lines[end], lines[end + 1], typicalGap)) {
    end += 1;
  }
  return lines.slice(start, end + 1);
}

function handleTextLayerMultiClick(event) {
  if (event.button !== 0 || event.detail < 3) return;
  const textLayer = event.currentTarget;
  const targetSpan = event.target.closest("span[role='presentation']");
  if (!targetSpan || !textLayer.contains(targetSpan)) return;

  const lines = textLayerLines(textLayer);
  const lineIndex = findTextLayerLineIndex(lines, targetSpan, event);
  if (lineIndex < 0) return;

  event.preventDefault();
  const selectedLines = event.detail >= 4 ? paragraphLinesAround(lines, lineIndex) : [lines[lineIndex]];
  selectTextLayerLines(selectedLines);
}

function measuredTextWidth(text, fontSize, fontFamily) {
  const canvas = measuredTextWidth.canvas || (measuredTextWidth.canvas = document.createElement("canvas"));
  const context = canvas.getContext("2d");
  context.font = `${fontSize}px ${fontFamily}`;
  return Math.max(0.001, context.measureText(text).width);
}

function textChunksFromGlyphs(glyphs) {
  const chunks = [];
  let advance = 0;
  let chunk = null;

  const flush = () => {
    if (!chunk || !chunk.text) return;
    chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
    chunks.push(chunk);
    chunk = null;
  };

  glyphs.forEach((entry) => {
    if (typeof entry === "number") {
      if (entry <= -100 && chunk?.text) {
        chunk.text += " ";
        advance += -entry;
        chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
        flush();
        return;
      }
      advance += -entry;
      return;
    }
    const text = String(entry?.unicode || "");
    if (!text) {
      advance += Number(entry?.width) || 0;
      return;
    }
    if (!chunk) chunk = { text: "", startUnits: advance, widthUnits: 0 };
    chunk.text += text;
    advance += Number(entry.width) || 0;
    chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
    if (entry.isSpace || /\s$/.test(text)) flush();
  });
  flush();

  return { chunks, advanceUnits: advance };
}

function appendTextLayerChunk(container, viewport, matrix, fontSize, fontFamily, chunk) {
  const offset = chunk.startUnits * fontSize / 1000;
  const x = matrix[4] + matrix[0] * offset;
  const y = matrix[5] + matrix[1] * offset;
  const transform = [
    matrix[0] * fontSize,
    matrix[1] * fontSize,
    matrix[2] * fontSize,
    matrix[3] * fontSize,
    x,
    y
  ];
  const tx = pdfjsLib.Util.transform(viewport.transform, transform);
  const angle = Math.atan2(tx[1], tx[0]);
  const fontHeight = Math.hypot(tx[2], tx[3]);
  const fontAscent = fontHeight * 0.8;
  const measuredWidth = measuredTextWidth(chunk.text, fontHeight, fontFamily);
  const targetWidth = Math.max(0.001, chunk.widthUnits * Math.hypot(tx[0], tx[1]) / 1000);
  const span = document.createElement("span");
  span.textContent = chunk.text;
  span.setAttribute("role", "presentation");
  span.style.left = `${tx[4]}px`;
  span.style.top = `${tx[5] - fontAscent}px`;
  span.style.width = `${measuredWidth}px`;
  span.style.fontSize = `${fontHeight}px`;
  span.style.fontFamily = fontFamily;
  span.style.transform = `${Math.abs(angle) > 0.001 ? `rotate(${angle}rad) ` : ""}scaleX(${targetWidth / measuredWidth})`;
  span.style.transformOrigin = "0% 0%";
  container.appendChild(span);
}

async function renderOperatorTextLayer(page, textContent, viewport, container) {
  const opList = await page.getOperatorList();
  const ops = pdfjsLib.OPS || {};
  let fontSize = 10;
  let fontFamily = "sans-serif";
  let textMatrix = [1, 0, 0, 1, 0, 0];
  let lineMatrix = [1, 0, 0, 1, 0, 0];

  opList.fnArray.forEach((fn, index) => {
    const args = opList.argsArray[index];
    if (fn === ops.setFont) {
      fontSize = Number(args?.[1]) || fontSize;
      fontFamily = textContent.styles?.[args?.[0]]?.fontFamily || "sans-serif";
      return;
    }
    if (fn === ops.setTextMatrix) {
      textMatrix = Array.isArray(args) ? args.slice(0, 6).map(Number) : textMatrix;
      lineMatrix = textMatrix.slice();
      return;
    }
    if (fn === ops.moveText) {
      const dx = Number(args?.[0]) || 0;
      const dy = Number(args?.[1]) || 0;
      lineMatrix = lineMatrix.slice();
      lineMatrix[4] += dx;
      lineMatrix[5] += dy;
      textMatrix = lineMatrix.slice();
      return;
    }
    if (fn !== ops.showText) return;
    const glyphs = Array.isArray(args?.[0]) ? args[0] : [];
    const { chunks, advanceUnits } = textChunksFromGlyphs(glyphs);
    chunks.forEach((chunk) => appendTextLayerChunk(container, viewport, textMatrix, fontSize, fontFamily, chunk));
    const advance = advanceUnits * fontSize / 1000;
    textMatrix = textMatrix.slice();
    textMatrix[4] += textMatrix[0] * advance;
    textMatrix[5] += textMatrix[1] * advance;
  });
}

async function renderSelectableTextLayer(page, textContent, viewport, container) {
  container.addEventListener("click", handleTextLayerMultiClick);
  container.addEventListener("copy", (event) => {
    const pageElement = container.closest(".pdf-page");
    const selectionText = pageElement ? textFromSelectionForPage(pageElement) : window.getSelection()?.toString() || "";
    const normalized = normalizeCopiedPdfText(selectionText);
    if (!normalized) return;
    event.preventDefault();
    event.clipboardData?.setData("text/plain", normalized);
  });

  try {
    await renderOperatorTextLayer(page, textContent, viewport, container);
    if (container.querySelector("span[role='presentation']")) return;
  } catch (error) {
    console.warn("Precise text layer failed, falling back to PDF.js text layer.", error);
  }

  const task = pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container,
    viewport
  });
  await task.promise;
}

async function renderPdfPage(pageNumber, renderToken, scale, target = elements.pdfViewer, options = {}) {
  const page = await pdfState.document.getPage(pageNumber);
  if (renderToken !== pdfState.renderToken) return false;
  const viewport = page.getViewport({ scale });
  const outputScale = Math.min(window.devicePixelRatio || 1, 3);
  const pageElement = document.createElement("section");
  const canvas = document.createElement("canvas");
  const textLayer = document.createElement("div");
  const overlay = document.createElement("div");
  const context = canvas.getContext("2d");

  pageElement.className = "pdf-page";
  pageElement.dataset.page = String(pageNumber);
  canvas.className = "pdf-page-canvas";
  textLayer.className = "textLayer pdf-text-layer";
  overlay.className = "pdf-annotation-layer";
  pageElement._pdfLinks = await pdfLinkAnnotationsForPage(page, viewport);
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  textLayer.style.width = `${viewport.width}px`;
  textLayer.style.height = `${viewport.height}px`;
  textLayer.style.setProperty("--scale-factor", String(viewport.scale));
  pageElement.style.width = `${viewport.width}px`;
  pageElement.style.height = `${viewport.height}px`;

  pageElement.append(canvas, textLayer, overlay);
  if (renderToken !== pdfState.renderToken) return false;
  target.appendChild(pageElement);
  wirePageAnnotationEvents(pageElement);
  const renderTask = page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0]
  }).promise;
  const textContent = await page.getTextContent();
  if (renderToken !== pdfState.renderToken) {
    pageElement.remove();
    return false;
  }
  await renderSelectableTextLayer(page, textContent, viewport, textLayer);
  await renderTask;
  if (renderToken !== pdfState.renderToken) {
    pageElement.remove();
    return false;
  }
  if (options.renderAnnotations !== false) {
    renderAnnotationsForPage(pageElement);
  }
  return true;
}

async function renderPdf() {
  if (!pdfState.document) return;
  const positionToRestore = currentPdfScrollPosition() || storedPdfScrollPosition();
  const renderToken = pdfState.renderToken + 1;
  const scale = pdfState.scale;
  const hasRenderedPages = Boolean(elements.pdfViewer.querySelector(".pdf-page"));
  const renderTarget = hasRenderedPages ? document.createDocumentFragment() : elements.pdfViewer;
  pdfState.renderToken = renderToken;
  pdfState.suppressScrollSave = true;
  if (!hasRenderedPages) elements.pdfViewer.innerHTML = "";
  if (elements.zoomLabel) elements.zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  const pageCount = pdfPageCount();
  updatePdfPageControl();
  if (!pageCount) {
    pdfState.suppressScrollSave = false;
    throw new Error("PDF loaded, but page count was unavailable.");
  }
  try {
    for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
      const rendered = await renderPdfPage(pageNumber, renderToken, scale, renderTarget, {
        renderAnnotations: !hasRenderedPages
      });
      if (!rendered || renderToken !== pdfState.renderToken) {
        pdfState.suppressScrollSave = false;
        return;
      }
    }
  } catch (error) {
    pdfState.suppressScrollSave = false;
    throw error;
  }
  if (hasRenderedPages) {
    elements.pdfViewer.replaceChildren(...Array.from(renderTarget.childNodes));
    elements.pdfViewer.querySelectorAll(".pdf-page").forEach(renderAnnotationsForPage);
  }
  finishPdfScrollRestore(positionToRestore);
}

async function loadPdf(pdfHref, noteId) {
  pdfState.noteId = noteId;
  pdfState.url = pdfHref;
  hidePdfLinkBackButton();
  pdfState.annotations = await readAnnotations(noteId);
  resetAnnotationHistory();
  setAnnotationStatus(pdfState.annotations.length ? "Annotations loaded" : "No annotations yet");
  renderAnnotationList();
  setPdfLoading("Fetching PDF...");
  try {
    const response = await fetch(pdfHref, { cache: "no-store" });
    if (!response.ok) throw new Error(`PDF request failed (${response.status})`);
    const pdfData = new Uint8Array(await response.arrayBuffer());
    setPdfLoading("Decoding PDF...");
    pdfState.document = await pdfjsLib.getDocument({
      data: pdfData,
      standardFontDataUrl: "node_modules/pdfjs-dist/standard_fonts/",
      disableAutoFetch: true,
      disableStream: true
    }).promise;
    setPdfLoading("Rendering pages...");
    await renderPdf();
  } catch (error) {
    console.error(error);
    showPdfError(error);
  }
}

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
  elements.zoomIn?.addEventListener("click", async () => {
    pdfState.scale = clamp(pdfState.scale + PDF_SCALE_STEP, PDF_MIN_SCALE, PDF_MAX_SCALE);
    await renderPdf();
  });
  elements.zoomOut?.addEventListener("click", async () => {
    pdfState.scale = clamp(pdfState.scale - PDF_SCALE_STEP, PDF_MIN_SCALE, PDF_MAX_SCALE);
    await renderPdf();
  });
  initializePdfPageControl();
  setPdfMode("pan");
  setPdfColor("yellow");
  updateAnnotationHistoryButtons();
}

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

async function renderReader(library, note) {
  readerState.library = library;
  readerState.note = note;
  const collectionPath = getCollectionPath(library, note.categoryId);
  const notePositionToRestore = storedNoteScrollPosition(note.id);
  const storedFile = await readPaperFile(note.pdfStorageKey || note.id).catch((error) => {
    console.warn("Failed to read stored paper file.", error);
    return null;
  });
  const pdfHref = storedFile?.pdfBlob ? URL.createObjectURL(storedFile.pdfBlob) : note.href || "#";
  const generatedNoteBody = await fetchGeneratedNoteBody(note) || extractGeneratedNoteBody(storedFile?.noteHtml);

  elements.title.textContent = note.title;
  elements.kicker.textContent = collectionPath;
  await initializeReaderChatSessions();
  await loadPdf(pdfHref, note.id);
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

async function initialize() {
  if (window.location.protocol === "file:") {
    showStartupError("Open http://localhost:4173 instead of opening reader.html directly.");
    return;
  }
  if (!pdfjsLib) {
    showStartupError("PDF.js did not load. Refresh the page or restart the local server.");
    return;
  }
  initializeResizer();
  initializeAnnotationSidebar();
  initializeHtmlPaneToggle();
  initializeAskPaneToggle();
  initializeReaderChat();
  initializeHtmlZoom();
  initializePdfTools();
  initializePdfScrollPersistence();
  initializeNoteScrollPersistence();
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
