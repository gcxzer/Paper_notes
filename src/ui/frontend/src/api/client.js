export class ApiError extends Error {
  constructor(message, { status = 0, payload = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
    ...options,
  });
  const text = await response.text();
  const payload = parseJson(text);
  if (!response.ok) {
    throw new ApiError(payload?.error || response.statusText || "Request failed", {
      status: response.status,
      payload,
    });
  }
  return payload;
}

function parseJson(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export async function fetchLibrary() {
  const payload = await request("/api/library");
  return payload.library || payload;
}

export async function importPdfFile(file, categoryId) {
  const dataBase64 = await readFileAsBase64(file);
  return request("/api/library/import/pdf", {
    method: "POST",
    body: JSON.stringify({
      fileName: file.name,
      dataBase64,
      categoryId,
    }),
  });
}

export async function importPaperUrl(url, categoryId) {
  return request("/api/library/import/url", {
    method: "POST",
    body: JSON.stringify({ url, categoryId }),
  });
}

export async function renameNote(noteId, title) {
  return request(`/api/library/notes/${encodeURIComponent(noteId)}/rename`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function updateNoteSummary(noteId, summary) {
  return request(`/api/library/notes/${encodeURIComponent(noteId)}/summary`, {
    method: "POST",
    body: JSON.stringify({ summary }),
  });
}

export async function fetchRagStatus(noteId) {
  const params = new URLSearchParams({ noteId });
  return request(`/api/rag/status?${params.toString()}`);
}

export async function fetchAgentSessions() {
  const payload = await request("/api/agent/sessions");
  return payload.sessions || [];
}

export async function fetchAgentContext(sessionId, { provider = "", model = "" } = {}) {
  const params = new URLSearchParams({ provider, model });
  const payload = await request(`/api/agent/sessions/${encodeURIComponent(sessionId)}/context?${params.toString()}`);
  return payload.context || null;
}

export async function runAgentMessage(payload) {
  return request("/api/agent/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function resourceUrl(href) {
  const value = String(href || "").trim();
  if (!value) return "";
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return value;
  return `/${value.replace(/^\/+/, "")}`;
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",").pop() : result);
    };
    reader.readAsDataURL(file);
  });
}
