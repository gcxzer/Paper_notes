const STORAGE_KEY = "paper-notes-library-v12";
const FILE_DB_NAME = "paper-notes-files-v1";
const FILE_STORE_NAME = "paper-files";
const READER_SPLIT_KEY = "paper-notes-reader-split-v1";
const ALL_CATEGORY_ID = "all";
const UNCATEGORIZED_ID = "uncategorized";

const elements = {
  layout: document.querySelector("#readerLayout"),
  error: document.querySelector("#readerError"),
  title: document.querySelector("#readerTitle"),
  kicker: document.querySelector("#readerKicker"),
  pdfFrame: document.querySelector("#pdfFrame"),
  notePage: document.querySelector("#notePage"),
  resizer: document.querySelector("#readerResizer")
};

const splitState = {
  dragging: false,
  minPdfWidth: 280,
  minNoteWidth: 360
};

function normalizeText(value) {
  return String(value || "").trim();
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
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
    href: normalizeText(note.href),
    htmlHref: normalizeText(note.htmlHref),
    pdfStorageKey: normalizeText(note.pdfStorageKey),
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

function showError() {
  elements.layout.hidden = true;
  elements.error.hidden = false;
  elements.title.textContent = "Paper not found";
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function readSplitPercent() {
  const value = Number(localStorage.getItem(READER_SPLIT_KEY));
  if (!Number.isFinite(value)) return 55;
  return clamp(value, 25, 75);
}

function setSplitPercent(percent) {
  const nextPercent = clamp(percent, 25, 75);
  document.documentElement.style.setProperty("--pdf-pane-width", `${nextPercent}%`);
  localStorage.setItem(READER_SPLIT_KEY, String(nextPercent));
}

function updateSplitFromClientX(clientX) {
  const rect = elements.layout.getBoundingClientRect();
  const maxPdfWidth = rect.width - splitState.minNoteWidth - 10;
  const pdfWidth = clamp(clientX - rect.left, splitState.minPdfWidth, maxPdfWidth);
  setSplitPercent((pdfWidth / rect.width) * 100);
}

function initializeResizer() {
  setSplitPercent(readSplitPercent());
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
  const collectionPath = getCollectionPath(library, note.categoryId);
  const storedFile = await readPaperFile(note.pdfStorageKey || note.id).catch((error) => {
    console.warn("Failed to read stored paper file.", error);
    return null;
  });
  const pdfHref = storedFile?.pdfBlob ? URL.createObjectURL(storedFile.pdfBlob) : note.href || "#";
  const generatedNoteBody = await fetchGeneratedNoteBody(note) || extractGeneratedNoteBody(storedFile?.noteHtml);

  elements.title.textContent = note.title;
  elements.kicker.textContent = collectionPath;
  elements.pdfFrame.src = pdfHref;
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
}

async function initialize() {
  initializeResizer();
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
