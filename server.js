const http = require("http");
const fs = require("fs/promises");
const path = require("path");

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 4173);
const HOST = "127.0.0.1";
const MAX_BODY_SIZE = 200 * 1024 * 1024;
const PAPERS_DIR = path.join(ROOT, "Papers");
const HTML_DIR = path.join(ROOT, "Paper-html");
const NOTES_PATH = path.join(ROOT, "notes.json");

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".pdf": "application/pdf",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml"
};

const BASE_LIBRARY = {
  categories: [
    { id: "all", name: "All Notes", parentId: null, order: 0, system: true },
    { id: "uncategorized", name: "Uncategorized", parentId: null, order: 1, system: true }
  ],
  notes: []
};

function send(response, status, body, contentType = "text/plain; charset=utf-8") {
  response.writeHead(status, {
    "Content-Type": contentType,
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,HEAD,POST,OPTIONS"
  });
  response.end(body);
}

function sendJson(response, status, body) {
  send(response, status, JSON.stringify(body, null, 2), "application/json; charset=utf-8");
}

function normalizeText(value) {
  return String(value || "").trim();
}

function getTodayLabel() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function safeFileName(fileName) {
  const ext = path.extname(fileName).toLowerCase();
  const base = path.basename(fileName, ext)
    .replace(/[\\/:*?"<>|#%{}^~[\]`]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return `${base || "Untitled Paper"}${ext || ".pdf"}`;
}

function noteTitleFromPdf(fileName) {
  return path.basename(fileName, path.extname(fileName)).replace(/[-_]+/g, " ").trim() || "Untitled PDF";
}

function noteIdFromTitle(title) {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return `pdf-${slug || Date.now()}-${Date.now().toString(36)}`;
}

function createPaperNoteHtml({ title, date, fileName }) {
  const safeTitle = escapeHtml(title);
  const safeDate = escapeHtml(date);
  const safeFileName = escapeHtml(fileName);

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${safeTitle}</title>
  <link rel="stylesheet" href="../assets/note.css">
</head>
<body>
  <main class="note">
    <header class="note-section">
      <p class="eyebrow note-eyebrow">Paper Note</p>
      <h1>${safeTitle}</h1>
      <p class="meta note-meta">${safeDate} · ${safeFileName}</p>
    </header>

    <div class="note-workspace">
      <aside class="note-menu" aria-label="Note sections">
        <nav data-note-menu></nav>
      </aside>

      <section class="note-body"></section>
    </div>
  </main>
  <script src="../assets/note.js"></script>
</body>
</html>`;
}

async function readLibrary() {
  try {
    return JSON.parse(await fs.readFile(NOTES_PATH, "utf8"));
  } catch {
    return structuredClone(BASE_LIBRARY);
  }
}

async function writeLibrary(library) {
  await fs.writeFile(NOTES_PATH, `${JSON.stringify(library, null, 2)}\n`);
}

async function readRequestBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_SIZE) {
      throw new Error("Request body is too large.");
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function handleImportPdf(request, response) {
  const body = JSON.parse(await readRequestBody(request));
  const originalName = safeFileName(body.fileName);
  if (!originalName.toLowerCase().endsWith(".pdf")) {
    send(response, 400, "Only PDF files can be imported.");
    return;
  }

  const pdfBuffer = Buffer.from(String(body.dataBase64 || ""), "base64");
  if (!pdfBuffer.length) {
    send(response, 400, "PDF file is empty.");
    return;
  }

  await fs.mkdir(PAPERS_DIR, { recursive: true });
  await fs.mkdir(HTML_DIR, { recursive: true });

  const htmlName = `${path.basename(originalName, path.extname(originalName))}.html`;
  const title = noteTitleFromPdf(originalName);
  const date = getTodayLabel();
  const note = {
    id: noteIdFromTitle(title),
    title,
    href: `Papers/${encodeURIComponent(originalName)}`,
    htmlHref: `Paper-html/${encodeURIComponent(htmlName)}`,
    pdfStorageKey: "",
    date,
    categoryId: normalizeText(body.categoryId) || "uncategorized",
    venue: "",
    summary: "",
    tags: []
  };

  await fs.writeFile(path.join(PAPERS_DIR, originalName), pdfBuffer);
  await fs.writeFile(path.join(HTML_DIR, htmlName), createPaperNoteHtml({ title, date, fileName: originalName }));

  const library = await readLibrary();
  library.categories = Array.isArray(library.categories) ? library.categories : structuredClone(BASE_LIBRARY.categories);
  library.notes = Array.isArray(library.notes) ? library.notes : [];
  library.notes = library.notes.filter((entry) => entry.href !== note.href && entry.htmlHref !== note.htmlHref);
  library.notes.push(note);
  await writeLibrary(library);

  sendJson(response, 201, note);
}

async function handleRenameNote(request, response) {
  const body = JSON.parse(await readRequestBody(request));
  const noteId = normalizeText(body.id);
  const nextTitle = normalizeText(body.title);

  if (!noteId || !nextTitle) {
    send(response, 400, "Note id and title are required.");
    return;
  }

  const library = await readLibrary();
  const note = Array.isArray(library.notes)
    ? library.notes.find((entry) => entry.id === noteId)
    : null;

  if (!note) {
    send(response, 404, "Note not found.");
    return;
  }

  note.title = nextTitle;
  await writeLibrary(library);

  if (note.htmlHref) {
    const htmlPath = path.normalize(path.join(ROOT, decodeURIComponent(note.htmlHref)));
    if (htmlPath.startsWith(HTML_DIR)) {
      try {
        const safeTitle = escapeHtml(nextTitle);
        const html = await fs.readFile(htmlPath, "utf8");
        const updatedHtml = html
          .replace(/<title>[\s\S]*?<\/title>/i, `<title>${safeTitle}</title>`)
          .replace(/<h1>[\s\S]*?<\/h1>/i, `<h1>${safeTitle}</h1>`);
        await fs.writeFile(htmlPath, updatedHtml);
      } catch (error) {
        console.warn(`Could not update note HTML title for ${noteId}:`, error.message);
      }
    }
  }

  sendJson(response, 200, note);
}

async function serveStatic(request, response) {
  const url = new URL(request.url, `http://${request.headers.host}`);
  const pathname = decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname);
  const filePath = path.normalize(path.join(ROOT, pathname));

  if (!filePath.startsWith(ROOT)) {
    send(response, 403, "Forbidden");
    return;
  }

  try {
    const data = await fs.readFile(filePath);
    const contentType = MIME_TYPES[path.extname(filePath).toLowerCase()] || "application/octet-stream";
    response.writeHead(200, {
      "Content-Type": contentType,
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Allow-Methods": "GET,HEAD,POST,OPTIONS"
    });
    response.end(data);
  } catch {
    send(response, 404, "Not found");
  }
}

const server = http.createServer(async (request, response) => {
  try {
    if (request.method === "OPTIONS") {
      send(response, 204, "");
      return;
    }

    if (request.method === "POST" && request.url === "/api/import-pdf") {
      await handleImportPdf(request, response);
      return;
    }

    if (request.method === "POST" && request.url === "/api/rename-note") {
      await handleRenameNote(request, response);
      return;
    }

    if (request.method === "GET" || request.method === "HEAD") {
      await serveStatic(request, response);
      return;
    }

    send(response, 405, "Method not allowed");
  } catch (error) {
    console.error(error);
    send(response, 500, error.message || "Server error");
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Paper Notes is running at http://localhost:${PORT}`);
});
