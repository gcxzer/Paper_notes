function normalizeText(value) {
  return MODEL.normalizeText(value);
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
  return MODEL.normalizeResourceHref(value);
}

function escapeHtml(value) {
  return MODEL.escapeHtml(value);
}

function getApiUrl(path) {
  return MODEL.getApiUrl(path);
}

function createRequestId(prefix = "reader-chat") {
  if (globalThis.crypto?.randomUUID) return `${prefix}-${globalThis.crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function copyTextWithSelectionFallback(value) {
  const textarea = document.createElement("textarea");
  const activeElement = document.activeElement;
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-1000px";
  textarea.style.left = "-1000px";
  textarea.style.width = "1px";
  textarea.style.height = "1px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus({ preventScroll: true });
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    textarea.remove();
    if (activeElement && typeof activeElement.focus === "function") {
      try {
        activeElement.focus({ preventScroll: true });
      } catch (_error) {
        activeElement.focus();
      }
    }
  }
  if (!copied) throw new Error("Clipboard copy failed.");
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value) return;
  let clipboardError = null;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch (error) {
      clipboardError = error;
    }
  }
  try {
    copyTextWithSelectionFallback(value);
  } catch (error) {
    if (clipboardError && typeof error === "object" && error) {
      error.cause = clipboardError;
    }
    throw error;
  }
}

function normalizeClipboardPlainText(value) {
  return String(value || "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function elementChildIndex(element) {
  if (!element?.parentElement) return 0;
  return Array.from(element.parentElement.children).filter((child) => child.tagName === element.tagName).indexOf(element);
}

function listItemMarkerForCopy(item, context = null) {
  const queuedMarker = context?.listItemMarkers?.shift?.();
  if (queuedMarker) return queuedMarker;
  const list = item?.parentElement;
  if (!list || list.tagName !== "OL") return "- ";
  const value = Number(item.getAttribute("value"));
  if (Number.isFinite(value) && value > 0) return `${value}. `;
  const start = Number(list.getAttribute("start"));
  const base = Number.isFinite(start) && start > 0 ? start : 1;
  return `${base + elementChildIndex(item)}. `;
}

function serializeCopiedListItem(item, context = null) {
  const pieces = [];
  item.childNodes.forEach((child) => {
    if (child.nodeType === Node.ELEMENT_NODE && ["OL", "UL"].includes(child.tagName)) return;
    pieces.push(serializeCopiedSelectionNode(child, context));
  });
  const text = normalizeClipboardPlainText(pieces.join(""));
  return text ? `${listItemMarkerForCopy(item, context)}${text}` : "";
}

function serializeCopiedSelectionNode(node, context = null) {
  if (!node) return "";
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || "";
  if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return "";
  if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
    return Array.from(node.childNodes).map((child) => serializeCopiedSelectionNode(child, context)).join("");
  }

  const tag = node.tagName;
  if (tag === "BR") return "\n";
  if (tag === "OL" || tag === "UL") {
    return Array.from(node.children)
      .filter((child) => child.tagName === "LI")
      .map((child) => serializeCopiedListItem(child, context))
      .filter(Boolean)
      .join("\n") + "\n";
  }
  if (tag === "LI") return `${serializeCopiedListItem(node, context)}\n`;
  const text = Array.from(node.childNodes).map((child) => serializeCopiedSelectionNode(child, context)).join("");
  if (["P", "DIV", "SECTION", "ARTICLE", "BLOCKQUOTE", "PRE", "H1", "H2", "H3", "H4", "H5", "H6"].includes(tag)) {
    return `${text}\n`;
  }
  if (tag === "TR") return `${text}\n`;
  if (tag === "TD" || tag === "TH") return `${text}\t`;
  return text;
}

function elementFromSelectionNode(node) {
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
}

function listItemMarkerFromOriginalItem(item) {
  const list = item?.parentElement;
  if (!list || list.tagName !== "OL") return "- ";
  const value = Number(item.getAttribute("value"));
  if (Number.isFinite(value) && value > 0) return `${value}. `;
  const start = Number(list.getAttribute("start"));
  const base = Number.isFinite(start) && start > 0 ? start : 1;
  return `${base + elementChildIndex(item)}. `;
}

function copiedSelectionContext(range) {
  const root = elementFromSelectionNode(range.commonAncestorContainer);
  const list = root?.closest?.("ol, ul") || root?.querySelector?.("ol, ul") || null;
  const items = list
    ? Array.from(list.children).filter((child) => child.tagName === "LI" && range.intersectsNode(child))
    : [];
  return {
    listItemMarkers: items.map(listItemMarkerFromOriginalItem)
  };
}

function copiedSelectionTextWithListMarkers(selection) {
  if (!selection || selection.rangeCount <= 0 || selection.isCollapsed) return "";
  const chunks = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    chunks.push(serializeCopiedSelectionNode(range.cloneContents(), copiedSelectionContext(range)));
  }
  return normalizeClipboardPlainText(chunks.join("\n"));
}

function scopedSelectionRange(range, container) {
  if (!range || !container || !range.intersectsNode(container)) return null;
  const scoped = range.cloneRange();
  if (!container.contains(range.startContainer)) {
    scoped.setStart(container, 0);
  }
  if (!container.contains(range.endContainer)) {
    scoped.setEnd(container, container.childNodes.length);
  }
  return scoped;
}

function copiedSelectionTextWithinContainer(selection, container) {
  if (!container || !selection || selection.rangeCount <= 0 || selection.isCollapsed) return "";
  const chunks = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = scopedSelectionRange(selection.getRangeAt(index), container);
    if (!range) continue;
    chunks.push(serializeCopiedSelectionNode(range.cloneContents(), copiedSelectionContext(range)));
  }
  return normalizeClipboardPlainText(chunks.join("\n"));
}

function handleRichTextCopy(event) {
  if (event.defaultPrevented || event.target?.closest?.("input, textarea, [contenteditable='true']")) return;
  const selection = window.getSelection();
  const container = event.currentTarget?.nodeType === Node.ELEMENT_NODE ? event.currentTarget : null;
  const text = container
    ? copiedSelectionTextWithinContainer(selection, container)
    : copiedSelectionTextWithListMarkers(selection);
  if (!text || !event.clipboardData) return;
  event.preventDefault();
  event.clipboardData.setData("text/plain", text);
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

function addReaderActionMenuOption(menu, {
  className = "",
  text = "",
  html = "",
  ariaLabel = "",
  dataset = {},
  onClick = () => {},
}) {
  const button = document.createElement("button");
  button.className = `ask-session-menu-option ${className}`.trim();
  button.type = "button";
  if (html) {
    button.innerHTML = html;
  } else {
    button.textContent = text;
  }
  if (ariaLabel) button.setAttribute("aria-label", ariaLabel);
  Object.entries(dataset || {}).forEach(([key, value]) => {
    button.dataset[key] = normalizeText(value);
  });
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  menu.appendChild(button);
  return button;
}

function positionReaderActionMenu(menu, row, {
  popover,
  buttonSelector,
  gap = 8,
  maxHeight = 0,
} = {}) {
  if (!popover || !row) return;
  const popoverRect = popover.getBoundingClientRect();
  const rowRect = row.getBoundingClientRect();
  const buttonRect = row.querySelector(buttonSelector)?.getBoundingClientRect() || rowRect;
  if (maxHeight) {
    menu.style.maxHeight = `${Math.round(maxHeight)}px`;
  }
  const menuRect = menu.getBoundingClientRect();
  const left = Math.max(
    8,
    Math.min(
      buttonRect.left - popoverRect.left - menuRect.width - gap,
      popoverRect.width - menuRect.width - 8
    )
  );
  const top = Math.max(
    8,
    Math.min(
      rowRect.top - popoverRect.top,
      popoverRect.height - menuRect.height - 8
    )
  );
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
  menu.style.visibility = "";
}

class AgentRequestError extends Error {
  constructor(message, { status = 0, code = "", payload = null } = {}) {
    super(message);
    this.name = "AgentRequestError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

async function fetchAgentJson(path, { method = "GET", body = null } = {}) {
  const options = {
    method,
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  };
  const response = await fetch(getApiUrl(path), options);
  if (!response.ok) {
    throw await readAgentError(response);
  }
  return response.json();
}

async function fetchAgentEventStream(path, { body, onEvent, signal } = {}) {
  const response = await fetch(getApiUrl(path), {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    signal
  });
  if (!response.ok) {
    throw await readAgentError(response);
  }
  if (!response.body || typeof response.body.getReader !== "function") {
    throw new AgentRequestError("Streaming is not supported by this browser.", { code: "stream_unsupported" });
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

async function readAgentError(response) {
  try {
    const payload = await response.clone().json();
    return new AgentRequestError(
      normalizeText(payload?.error) || `Agent request failed (${response.status})`,
      {
        status: response.status,
        code: normalizeText(payload?.code),
        payload
      }
    );
  } catch (error) {
    const text = await response.text().catch(() => "");
    return new AgentRequestError(
      normalizeText(text) || `Agent request failed (${response.status})`,
      { status: response.status }
    );
  }
}

function normalizeReaderChatSession(rawSession) {
  const id = normalizeText(rawSession?.id || rawSession?.sessionId);
  if (!id) return null;
  const metadata = rawSession?.metadata && typeof rawSession.metadata === "object" && !Array.isArray(rawSession.metadata)
    ? rawSession.metadata
    : {};
  const state = ["active", "archived", "trashed"].includes(normalizeText(rawSession?.state))
    ? normalizeText(rawSession.state)
    : rawSession?.trashed
      ? "trashed"
      : rawSession?.archived
        ? "archived"
        : "active";
  return {
    id,
    title: normalizeText(rawSession?.title) || "New chat",
    noteId: normalizeText(rawSession?.noteId),
    originNoteId: normalizeText(rawSession?.originNoteId || metadata.originNoteId || metadata.origin_note_id || rawSession?.noteId),
    originNoteTitle: normalizeText(rawSession?.originNoteTitle || rawSession?.noteTitle || rawSession?.note_title || metadata.originNoteTitle || metadata.origin_note_title || metadata.noteTitle || metadata.note_title),
    currentNoteId: normalizeText(rawSession?.currentNoteId || metadata.currentNoteId || metadata.current_note_id),
    currentNoteTitle: normalizeText(rawSession?.currentNoteTitle || metadata.currentNoteTitle || metadata.current_note_title || rawSession?.noteTitle || rawSession?.note_title || metadata.noteTitle || metadata.note_title),
    projectId: normalizeText(rawSession?.projectId || rawSession?.project_id || metadata.projectId || metadata.project_id),
    projectName: normalizeText(rawSession?.projectName || rawSession?.project_name || metadata.projectName || metadata.project_name),
    provider: normalizeProviderName(rawSession?.provider),
    model: normalizeText(rawSession?.model),
    deepSeekThinkMode: normalizeText(metadata.deepseekThinkMode || metadata.deepseek_think_mode),
    gptThinkMode: normalizeText(metadata.gptThinkMode || metadata.gpt_think_mode),
    updatedAt: normalizeText(rawSession?.updatedAt || rawSession?.createdAt),
    createdAt: normalizeText(rawSession?.createdAt),
    archivedAt: normalizeText(rawSession?.archivedAt || metadata.archivedAt || metadata.archived_at),
    trashedAt: normalizeText(rawSession?.trashedAt),
    lastMessagePreview: normalizeText(rawSession?.lastMessagePreview),
    messageCount: Number(rawSession?.messageCount) || 0,
    activeRun: normalizeActiveChatRun(rawSession?.activeRun || metadata.activeRun || metadata.active_run),
    state,
    archived: state === "archived",
    trashed: state === "trashed"
  };
}

function normalizeActiveChatRun(rawRun) {
  if (!rawRun || typeof rawRun !== "object" || Array.isArray(rawRun)) return null;
  const requestId = normalizeText(rawRun.requestId || rawRun.request_id);
  const status = normalizeText(rawRun.status || "running").toLowerCase();
  if (!requestId || !["pending", "running", "starting"].includes(status)) return null;
  const rawProgress = rawRun.progress && typeof rawRun.progress === "object" ? rawRun.progress : null;
  const progress = typeof normalizeChatProgress === "function"
    ? normalizeChatProgress(rawProgress)
    : rawProgress;
  return {
    requestId,
    status,
    startedAt: normalizeText(rawRun.startedAt || rawRun.started_at),
    noteId: normalizeText(rawRun.noteId || rawRun.note_id),
    provider: normalizeProviderName(rawRun.provider),
    model: normalizeText(rawRun.model),
    message: normalizeText(rawRun.message || rawRun.latestUserText || rawRun.latest_user_text),
    progress
  };
}

function normalizeReaderChatSessions(rawSessions) {
  return (Array.isArray(rawSessions) ? rawSessions : [])
    .map(normalizeReaderChatSession)
    .filter(Boolean);
}

function upsertReaderChatSession(rawSession) {
  const session = normalizeReaderChatSession(rawSession);
  if (!session) return null;
  if (session.id === getChatSessionId()) {
    readerState.currentChatSession = session;
  }
  const index = readerState.chatSessions.findIndex((item) => item.id === session.id);
  if (index >= 0) {
    readerState.chatSessions[index] = session;
  } else {
    readerState.chatSessions.unshift(session);
  }
  return session;
}

function normalizeToolActivity(rawItems) {
  if (!Array.isArray(rawItems)) return [];
  const seenSnapshotIds = new Set();
  return rawItems.map((raw) => {
    if (!raw || typeof raw !== "object") return null;
    const changedFiles = Array.isArray(raw.changedFiles)
      ? raw.changedFiles.map((file) => ({
        path: normalizeText(file?.path),
        beforeBytes: Math.max(0, Math.round(Number(file?.beforeBytes) || 0)),
        afterBytes: Math.max(0, Math.round(Number(file?.afterBytes) || 0))
      })).filter((file) => file.path)
      : [];
    return {
      name: normalizeText(raw.name) || "tool",
      sessionId: normalizeText(raw.sessionId),
      noteId: normalizeText(raw.noteId || raw.note_id),
      snapshotId: normalizeText(raw.snapshotId),
      heading: normalizeText(raw.heading),
      position: normalizeText(raw.position),
      addedHeadings: (Array.isArray(raw.addedHeadings)
        ? raw.addedHeadings
        : Array.isArray(raw.added_headings) ? raw.added_headings : [])
        .map(normalizeText)
        .filter(Boolean),
      undoable: Boolean(raw.undoable),
      writeMode: normalizeWriteToolMode(raw.writeMode || raw.write_mode),
      message: normalizeText(raw.message),
      toolMessage: normalizeText(raw.toolMessage || raw.tool_message),
      summary: normalizeText(raw.summary),
      changed: raw.changed !== false,
      changedFiles
    };
  }).filter((item) => {
    if (!item || !item.changedFiles.length) return false;
    if (!item.snapshotId) return true;
    if (seenSnapshotIds.has(item.snapshotId)) return false;
    seenSnapshotIds.add(item.snapshotId);
    return true;
  });
}

function normalizeWriteToolMode(value) {
  const mode = normalizeText(value).toLowerCase();
  return ["auto", "warn", "ask", "readonly"].includes(mode) ? mode : "auto";
}

function writeToolModeLabel(mode) {
  const normalized = normalizeWriteToolMode(mode);
  if (normalized === "warn") return "Warn";
  if (normalized === "ask") return "Ask";
  if (normalized === "readonly") return "Read-only";
  return "Auto";
}

function normalizeToolSettings(payload) {
  const globalAccess = normalizeText(payload?.globalAccess || "default").toLowerCase() === "full_access"
    ? "full_access"
    : "default";
  const tools = (Array.isArray(payload?.tools) ? payload.tools : []).map((tool) => ({
    name: normalizeText(tool.name),
    enabled: tool.enabled !== false,
    access: normalizeText(tool.access || "inherit").toLowerCase(),
    mutating: Boolean(tool.mutating),
    readOnly: Boolean(tool.readOnly || tool.read_only)
  })).filter((tool) => tool.name);
  const builtInTools = (Array.isArray(payload?.builtInTools) ? payload.builtInTools : []).map((tool) => ({
    name: normalizeText(tool.name),
    enabled: tool.enabled !== false,
  })).filter((tool) => tool.name);
  const customTools = (Array.isArray(payload?.customTools) ? payload.customTools : []).map((tool) => ({
    name: normalizeText(tool.name),
    enabled: tool.enabled !== false,
  })).filter((tool) => tool.name);
  const disabledTools = Array.isArray(payload?.disabledTools)
    ? payload.disabledTools.map(normalizeText).filter(Boolean)
    : tools.filter((tool) => !tool.enabled || tool.access === "disabled").map((tool) => tool.name);
  const disabledToolsets = Array.isArray(payload?.disabledToolsets)
    ? payload.disabledToolsets.map(normalizeText).filter(Boolean)
    : tools.filter((tool) => !tool.enabled || tool.access === "disabled").map((tool) => tool.name);
  const enabledToolsets = Array.isArray(payload?.enabledToolsets)
    ? payload.enabledToolsets.map(normalizeText).filter(Boolean)
    : customTools.filter((tool) => tool.enabled).map((tool) => tool.name);
  const webSearchProviders = normalizeReaderWebSearchProviders(payload?.webSearchProviders || payload?.web_search_providers);
  const toolWriteModes = {};
  const rawWriteModes = payload?.toolWriteModes && typeof payload.toolWriteModes === "object"
    ? payload.toolWriteModes
    : {};
  Object.entries(rawWriteModes).forEach(([name, mode]) => {
    const normalizedName = normalizeText(name);
    const normalizedMode = normalizeWriteToolMode(mode);
    if (normalizedName) toolWriteModes[normalizedName] = normalizedMode;
  });
  return {
    globalAccess,
    defaultWriteMode: globalAccess === "full_access" ? "auto" : "ask",
    disabledTools,
    disabledToolsets,
    enabledToolsets,
    toolWriteModes,
    webSearchProviders,
    nativeWebSearchEnabled: Boolean(
      payload?.nativeWebSearchEnabled
      || builtInTools.some((tool) => tool.name === "native_web_search" && tool.enabled)
    )
  };
}

function normalizeReaderWebSearchProviders(raw) {
  const providers = raw && typeof raw === "object" ? raw : {};
  const nativeRaw = providers.native_provider || providers.nativeProvider || {};
  const customRaw = providers.custom_provider || providers.customProvider || {};
  const enabledEntry = (value) => ({
    enabled: Boolean(value && typeof value === "object" && value.enabled)
  });
  return {
    native_provider: {
      openaiCodex: enabledEntry(nativeRaw.openaiCodex || nativeRaw.openai_codex),
      openaiAPIKey: enabledEntry(nativeRaw.openaiAPIKey || nativeRaw.openai_api_key),
    },
    custom_provider: {
      Tavily: enabledEntry(customRaw.Tavily || customRaw.tavily),
      Brave: enabledEntry(customRaw.Brave || customRaw.brave || customRaw.braveSearch),
    }
  };
}

function readerToolSettingsPayload() {
  const settings = readerState.toolSettings || normalizeToolSettings({});
  const enabledToolsets = settings.enabledToolsets?.length ? ["default", ...settings.enabledToolsets] : [];
  const nativeSearchEnabled = readerNativeWebSearchEnabledForCurrentProvider(settings);
  const disabledTools = [...(settings.disabledTools || [])];
  if (nativeSearchEnabled && !disabledTools.includes("web_search")) {
    disabledTools.push("web_search");
  }
  return {
    enabledToolsets,
    disabledToolsets: settings.disabledToolsets,
    disabledTools,
    toolWriteModes: settings.toolWriteModes,
    requestOptions: {
      _paper_notes_native_web_search: nativeSearchEnabled
    }
  };
}

function readerNativeWebSearchEnabledForCurrentProvider(settings) {
  const provider = currentReaderProvider();
  const capabilities = modelCapabilitiesFor(provider, currentReaderModel());
  if (!capabilities.supportsWebSearch) {
    return false;
  }
  const native = settings?.webSearchProviders?.native_provider || {};
  const customSearchEnabled = readerCustomWebSearchEnabled(settings);
  if (provider === "codex-oauth") {
    return Boolean(native.openaiCodex?.enabled || settings?.nativeWebSearchEnabled);
  }
  if (provider === "openai") {
    return Boolean(native.openaiAPIKey?.enabled || settings?.nativeWebSearchEnabled || !customSearchEnabled);
  }
  return false;
}

function readerCustomWebSearchEnabled(settings) {
  const custom = settings?.webSearchProviders?.custom_provider || {};
  return Boolean(custom.Tavily?.enabled || custom.Brave?.enabled);
}

function readerGenerationPayload() {
  return generationPayloadForRequest({
    type: readerState.generationMode,
    format: readerState.fileGenerationFormat,
  });
}

function normalizeGenerationRequest(raw) {
  if (!raw || typeof raw !== "object") return null;
  const normalizedType = normalizeText(raw.type).toLowerCase();
  if (normalizedType === "file") {
    return {
      type: "file",
      format: normalizeFileGenerationFormat(raw.format)
    };
  }
  if (normalizedType === "image") {
    return { type: "image", format: "image" };
  }
  const fileGeneration = raw.fileGeneration || raw.file_generation;
  if (fileGeneration?.enabled) {
    return {
      type: "file",
      format: normalizeFileGenerationFormat(fileGeneration.format)
    };
  }
  const imageGeneration = raw.imageGeneration || raw.image_generation;
  if (imageGeneration?.enabled) {
    return { type: "image", format: "image" };
  }
  return null;
}

function generationPayloadFromRequest(generation) {
  return generationPayloadForRequest(normalizeGenerationRequest(generation));
}

function generationPayloadForRequest(normalized) {
  if (!normalized) return {};
  if (normalized.type === "image") {
    return {
      imageGeneration: {
        enabled: true,
        size: "1024x1024",
        quality: "auto",
        format: "png"
      }
    };
  }
  if (normalized.type === "file") {
    return {
      fileGeneration: {
        enabled: true,
        format: normalizeFileGenerationFormat(normalized.format)
      }
    };
  }
  return {};
}

function generationRequestLabel(generation, attachments = []) {
  if (!generation) return "";
  if (generation.type === "image") {
    const imageCount = normalizeAttachmentArtifacts(attachments).filter((attachment) => attachment.kind === "image").length;
    return imageCount > 0 ? `Generate image · ${imageCount} images` : "Generate image";
  }
  if (generation.type === "file") return `Generate file · ${fileGenerationFormatLabel(generation.format)}`;
  return "";
}

function normalizeSelectedTextContext(raw) {
  if (!raw || typeof raw !== "object") return null;
  const text = normalizeText(raw.text || raw.selectionText || raw.selection_text).slice(0, 4000);
  if (!text) return null;
  const words = text.split(/\s+/).filter(Boolean).length;
  return {
    type: "selected_text",
    text,
    page: normalizeText(raw.page || raw.currentPage || raw.current_page),
    wordCount: Number(raw.wordCount || raw.word_count || words || 0) || 0
  };
}

function writeStoredWriteToolMode(mode) {
  const normalized = normalizeWriteToolMode(mode);
  try {
    localStorage.setItem(WRITE_TOOL_MODE_KEY, normalized);
  } catch (error) {
    console.warn("Failed to save write tool mode.", error);
  }
  return normalized;
}

function readStoredReaderModelSelection() {
  try {
    const parsed = JSON.parse(localStorage.getItem(READER_MODEL_SELECTION_KEY) || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const provider = normalizeProviderName(parsed.provider);
    const model = normalizeText(parsed.model);
    return provider && model ? { provider, model } : {};
  } catch (error) {
    return {};
  }
}

function writeStoredReaderModelSelection(provider, model) {
  const normalizedProvider = normalizeProviderName(provider);
  const normalizedModel = normalizeText(model);
  if (!normalizedProvider || !normalizedModel) return {};
  const selection = { provider: normalizedProvider, model: normalizedModel };
  try {
    localStorage.setItem(READER_MODEL_SELECTION_KEY, JSON.stringify(selection));
  } catch (error) {
    console.warn("Failed to save reader model selection.", error);
  }
  return selection;
}

function normalizeDeepSeekThinkMode(rawMode) {
  const mode = normalizeText(rawMode).toLowerCase();
  if (!mode || mode === "off" || mode === "none" || mode === "false") return { enabled: false, effort: "high" };
  const effort = ["high", "max"].includes(mode) ? mode : "high";
  return { enabled: true, effort };
}

function readStoredDeepSeekThinkMode() {
  try {
    return normalizeDeepSeekThinkMode(localStorage.getItem(DEEPSEEK_THINK_MODE_KEY) || "");
  } catch (error) {
    return { enabled: false, effort: "high" };
  }
}

function writeStoredDeepSeekThinkMode(mode) {
  const normalized = normalizeDeepSeekThinkMode(mode);
  try {
    localStorage.setItem(DEEPSEEK_THINK_MODE_KEY, normalized.enabled ? normalized.effort : "off");
  } catch (error) {
    console.warn("Failed to save DeepSeek think mode.", error);
  }
  return normalized;
}

function currentDeepSeekThinkMode() {
  const sessionMode = normalizeText(currentReaderSession()?.deepSeekThinkMode);
  if (sessionMode) return normalizeDeepSeekThinkMode(sessionMode);
  return normalizeDeepSeekThinkMode(readerState.deepSeekThinkMode?.enabled ? readerState.deepSeekThinkMode.effort : "off");
}

function normalizeGptThinkMode(rawMode, model = "", provider = "") {
  const mode = normalizeText(rawMode).toLowerCase();
  if (!mode || mode === "off" || mode === "none" || mode === "false") {
    const selectedProvider = normalizeProviderName(provider);
    const selectedModel = normalizeText(model);
    return !selectedProvider || !selectedModel || gptReasoningOffSupported(selectedProvider, selectedModel)
      ? { enabled: false, effort: "medium" }
      : { enabled: true, effort: "low" };
  }
  const effort = ["low", "medium", "high", "xhigh"].includes(mode) ? mode : "medium";
  return { enabled: true, effort };
}

function readStoredGptThinkMode(model = "", provider = "") {
  try {
    return normalizeGptThinkMode(localStorage.getItem(GPT_THINK_MODE_KEY) || "", model, provider);
  } catch (error) {
    return { enabled: false, effort: "medium" };
  }
}

function writeStoredGptThinkMode(mode, model = currentReaderModel(), provider = currentReaderProvider()) {
  const normalized = normalizeGptThinkMode(mode, model, provider);
  try {
    localStorage.setItem(GPT_THINK_MODE_KEY, normalized.enabled ? normalized.effort : "off");
  } catch (error) {
    console.warn("Failed to save GPT think mode.", error);
  }
  return normalized;
}

function providerSupportsGptThinkMode(provider) {
  const normalized = normalizeProviderName(provider);
  return normalized === "openai" || normalized === "codex-oauth";
}

function currentGptThinkMode(model = currentReaderModel(), provider = currentReaderProvider()) {
  const sessionMode = normalizeText(currentReaderSession()?.gptThinkMode);
  if (sessionMode) return normalizeGptThinkMode(sessionMode, model, provider);
  return normalizeGptThinkMode(readerState.gptThinkMode?.enabled ? readerState.gptThinkMode.effort : "off", model, provider);
}

function syncReaderThinkModesFromStorage() {
  readerState.deepSeekThinkMode = readStoredDeepSeekThinkMode();
  readerState.gptThinkMode = readStoredGptThinkMode(currentReaderModel(), currentReaderProvider());
}

syncReaderThinkModesFromStorage();

function normalizeApiChatContentText(value) {
  if (typeof value === "string") return normalizeText(value);
  if (Array.isArray(value)) {
    return value
      .map(normalizeApiChatContentText)
      .filter(Boolean)
      .join("\n")
      .trim();
  }
  if (!value || typeof value !== "object") return normalizeText(value);

  const nested = value.text ?? value.content ?? value.input_text ?? value.output_text;
  if (nested !== undefined) return normalizeApiChatContentText(nested);
  return "";
}

function normalizeApiChatMessageText(rawMessage) {
  const text = normalizeApiChatContentText(rawMessage?.text);
  return text || normalizeApiChatContentText(rawMessage?.content);
}

function normalizeApiChatMessage(rawMessage) {
  const role = rawMessage?.role === "user" ? "user" : rawMessage?.role === "assistant" ? "assistant" : rawMessage?.role === "divider" ? "divider" : "";
  if (!role) return null;
  const toolCalls = Array.isArray(rawMessage?.tool_calls)
    ? rawMessage.tool_calls
    : Array.isArray(rawMessage?.toolCalls)
      ? rawMessage.toolCalls
      : [];
  if (role === "assistant" && toolCalls.length) return null;
  const text = normalizeApiChatMessageText(rawMessage);
  const attachments = normalizeImageArtifacts(rawMessage?.attachments);
  const artifacts = normalizeImageArtifacts(rawMessage?.artifacts);
  const toolActivity = normalizeToolActivity(rawMessage?.toolActivity);
  const generation = normalizeGenerationRequest(rawMessage?.metadata?.generation);
  const selectedTextContext = normalizeSelectedTextContext(rawMessage?.metadata?.selectedTextContext || rawMessage?.selectedTextContext);
  const runTrace = normalizeRunTrace(rawMessage?.runTrace);
  const workTrace = normalizeWorkTrace(rawMessage?.workTrace);
  if (role === "divider") {
    return {
      role,
      text,
      markerType: normalizeText(rawMessage?.metadata?.type),
      focus: normalizeText(rawMessage?.metadata?.focus),
      warning: normalizeText(rawMessage?.metadata?.warning)
    };
  }
  if (!text && role === "assistant" && !artifacts.length && !toolActivity.length && !runTrace && !workTrace) return null;
  return {
    role,
    text,
    error: Boolean(rawMessage?.error),
    generation,
    selectedTextContext,
    attachments,
    artifacts,
    sources: rawMessage?.sources,
    toolActivity,
    runTrace,
    workTrace
  };
}

function normalizeApiChatMessages(rawMessages) {
  return (Array.isArray(rawMessages) ? rawMessages : [])
    .map(normalizeApiChatMessage)
    .filter(Boolean);
}

function normalizeContextStatus(payload) {
  const raw = payload?.context && typeof payload.context === "object" ? payload.context : (payload || {});
  const contextLength = Math.max(0, Math.round(Number(raw.contextLength || raw.contextWindow || raw.context_length || raw.context_window) || 0));
  const tokensUsed = Math.max(0, Math.round(Number(
    raw.tokensUsed
    || raw.estimatedTokens
    || raw.requestTokens
    || raw.estimatedRequestTokens
    || raw.tokens_used
    || raw.estimated_tokens
  ) || 0));
  const estimatedRequestTokens = Math.max(0, Math.round(Number(raw.estimatedRequestTokens || raw.estimated_request_tokens || tokensUsed) || 0));
  const percentFullRaw = raw.percentFull ?? raw.percent_full ?? (contextLength ? Math.round((tokensUsed / contextLength) * 100) : 0);
  const thresholdTokens = Math.max(0, Math.round(Number(raw.thresholdTokens || raw.compactionTriggerTokens || raw.threshold_tokens || raw.compaction_trigger_tokens) || 0));
  const thresholdPercentRaw = raw.thresholdPercent ?? raw.threshold_percent ?? (contextLength && thresholdTokens ? Math.round((thresholdTokens / contextLength) * 100) : 0);
  const compressionCount = Math.max(0, Math.round(Number(raw.compressionCount || raw.compression_count) || 0));
  return {
    sessionId: normalizeText(raw.sessionId || raw.session_id),
    provider: normalizeProviderName(raw.provider) || currentReaderProvider(),
    model: normalizeText(raw.model) || currentReaderModel(),
    contextLength,
    tokensUsed,
    estimatedRequestTokens,
    actualInputTokens: Math.max(0, Math.round(Number(raw.actualInputTokens || raw.actual_input_tokens) || 0)),
    estimatedPercent: Math.min(100, Math.max(0, Math.round(Number(percentFullRaw) || 0))),
    actualUsageAvailable: Boolean(raw.actualUsageAvailable ?? raw.actual_usage_available),
    usageUpdatedAt: normalizeText(raw.usageUpdatedAt || raw.usage_updated_at),
    usageRequestId: normalizeText(raw.usageRequestId || raw.usage_request_id),
    messageTokens: Math.max(0, Math.round(Number(raw.messageTokens || raw.message_tokens) || 0)),
    instructionTokens: Math.max(0, Math.round(Number(raw.instructionTokens || raw.instruction_tokens) || 0)),
    toolSchemaTokens: Math.max(0, Math.round(Number(raw.toolSchemaTokens || raw.toolTokens || raw.tool_schema_tokens || raw.tool_tokens) || 0)),
    thresholdTokens,
    percentFull: Math.min(100, Math.max(0, Math.round(Number(percentFullRaw) || 0))),
    thresholdPercent: Math.min(100, Math.max(0, Math.round(Number(thresholdPercentRaw) || 0))),
    messageCount: Math.max(0, Math.round(Number(raw.messageCount || raw.message_count) || 0)),
    compactionEnabled: Boolean(raw.compactionEnabled ?? raw.compaction_enabled),
    compactionReady: Boolean(raw.compactionReady ?? raw.compaction_ready),
    compressionCount,
    lastCompressedAt: normalizeText(raw.lastCompressedAt || raw.last_compressed_at),
    summaryAvailable: Boolean(raw.summaryAvailable ?? raw.summary_available ?? compressionCount),
    lastCompressionError: normalizeText(raw.lastCompressionError || raw.last_compression_error),
    fallbackUsed: Boolean(raw.fallbackUsed ?? raw.fallback_used)
  };
}

function formatTokenCount(value) {
  const count = Math.max(0, Math.round(Number(value) || 0));
  if (count >= 1_000_000) {
    const rounded = count / 1_000_000;
    return `${rounded >= 10 ? Math.round(rounded) : rounded.toFixed(1)}m`;
  }
  if (count >= 1000) {
    const rounded = count / 1000;
    return `${rounded >= 10 ? Math.round(rounded) : rounded.toFixed(1)}k`;
  }
  return String(count);
}

function hasAssistantResponseAfterLatestUser(messages, { normalizeMessage = null } = {}) {
  const normalizedMessages = Array.isArray(messages) ? messages : [];
  const lastUserIndex = normalizedMessages.reduce((latest, message, index) => (
    message?.role === "user" ? index : latest
  ), -1);
  return normalizedMessages.slice(Math.max(0, lastUserIndex + 1)).some((message) => {
    const normalized = typeof normalizeMessage === "function" ? normalizeMessage(message) : message;
    return normalized?.role === "assistant" && normalizeApiChatMessageText(normalized) && !normalized.error;
  });
}

function isCodexProvider(provider) {
  return normalizeProviderName(provider) === "codex-oauth";
}

function fallbackProviderDisplayName(provider) {
  const normalized = normalizeText(provider);
  if (normalized === "codex-oauth") return "Codex OAuth";
  if (normalized === "openai") return "OpenAI API key";
  return normalized || "Provider";
}

function normalizeProviderName(value) {
  const provider = normalizeText(value);
  if (!provider) return "";
  if (provider === "codex" || provider === "openai-codex" || provider === "codex-oauth") {
    return "codex-oauth";
  }
  if (provider === "openai" || provider === "openai-api-key") return "openai";
  const catalog = readerState?.modelCatalog;
  const profile = catalog?.providers?.find((item) => item.name === provider || item.aliases?.includes(provider));
  return profile?.name || provider;
}

function normalizeModelOption(rawOption) {
  const value = normalizeText(rawOption?.value || rawOption?.model || rawOption?.id || rawOption);
  if (!value) return null;
  const label = normalizeText(rawOption?.label) || value;
  const shortLabel = normalizeText(rawOption?.shortLabel || rawOption?.short_label) || label;
  const description = normalizeText(rawOption?.description || rawOption?.detail);
  const hasCapabilities = rawOption
    && typeof rawOption === "object"
    && Object.prototype.hasOwnProperty.call(rawOption, "capabilities");
  return {
    value,
    label,
    shortLabel,
    description,
    detail: description,
    capabilities: hasCapabilities ? normalizeModelCapabilities(rawOption.capabilities) : null
  };
}

function normalizeModelCapabilities(rawCapabilities) {
  const raw = rawCapabilities && typeof rawCapabilities === "object" ? rawCapabilities : {};
  return {
    supportsTools: raw.supportsTools !== false,
    supportsVision: Boolean(raw.supportsVision),
    supportsImageGeneration: Boolean(raw.supportsImageGeneration),
    supportsWebSearch: Boolean(raw.supportsWebSearch),
    supportsReasoningOff: raw.supportsReasoningOff !== false,
    contextWindow: Math.max(0, Math.round(Number(raw.contextWindow) || 0)),
    imageInputMode: normalizeText(raw.imageInputMode)
  };
}

function normalizeModelProvider(rawProvider) {
  const name = normalizeProviderName(rawProvider?.name || rawProvider?.provider);
  if (!name) return null;
  const aliases = Array.isArray(rawProvider?.aliases)
    ? rawProvider.aliases.map(normalizeText).filter(Boolean)
    : [];
  const models = (Array.isArray(rawProvider?.models) ? rawProvider.models : [])
    .map(normalizeModelOption)
    .filter(Boolean);
  const defaultModel = normalizeText(rawProvider?.defaultModel || rawProvider?.default_model);
  const selectedModel = normalizeText(rawProvider?.selectedModel || rawProvider?.model);
  return {
    name,
    aliases,
    displayName: normalizeText(rawProvider?.displayName || rawProvider?.display_name) || fallbackProviderDisplayName(name),
    authType: normalizeText(rawProvider?.authType || rawProvider?.auth_type),
    description: normalizeText(rawProvider?.description),
    defaultModel,
    configured: Boolean(rawProvider?.configured),
    ready: Boolean(rawProvider?.ready),
    model: selectedModel,
    selectedModel,
    modelSource: normalizeText(rawProvider?.modelSource || rawProvider?.model_source || "profile"),
    capabilities: normalizeModelCapabilities(rawProvider?.capabilities),
    models
  };
}

function normalizeReaderModelCatalog(payload) {
  const providers = (Array.isArray(payload?.providers) ? payload.providers : [])
    .map(normalizeModelProvider)
    .filter(Boolean);
  const requestedDefault = normalizeProviderName(payload?.defaultProvider || payload?.provider);
  const defaultProvider = providers.some((profile) => profile.name === requestedDefault)
    ? requestedDefault
    : providers.find((profile) => profile.configured)?.name || providers[0]?.name || requestedDefault || "openai";
  return {
    defaultProvider,
    defaultModel: normalizeText(payload?.defaultModel || payload?.model),
    modelConnectionConfigured: Boolean(payload?.modelConnectionConfigured || payload?.configured),
    codexAuth: payload && Object.prototype.hasOwnProperty.call(payload, "codexAuth")
      ? normalizeReaderCodexAuth(payload.codexAuth)
      : null,
    providers
  };
}

function normalizeReaderCodexAuth(payload) {
  const auth = payload && typeof payload === "object" ? payload : {};
  return {
    loggedIn: Boolean(auth.loggedIn),
    authMode: normalizeText(auth.authMode || ""),
    planType: normalizeText(auth.planType || ""),
    accountId: normalizeText(auth.accountId || ""),
    accountEmail: normalizeText(auth.accountEmail || ""),
    lastRefresh: normalizeText(auth.lastRefresh || ""),
    authStorePath: normalizeText(auth.authStorePath || "")
  };
}

function normalizeReaderAiSettings(payload) {
  const provider = normalizeProviderName(payload?.provider) || "openai";
  return {
    provider,
    model: normalizeText(payload?.model),
    modelSource: normalizeText(payload?.modelSource || "missing"),
    configured: Boolean(payload?.configured),
    ready: Boolean(payload?.ready),
    codexAuth: normalizeReaderCodexAuth(payload?.codexAuth)
  };
}

function currentReaderSession() {
  const sessionId = getChatSessionId();
  if (!sessionId) return null;
  const listedSession = readerState.chatSessions.find((session) => session.id === sessionId);
  if (listedSession) {
    readerState.currentChatSession = listedSession;
    return listedSession;
  }
  return readerState.currentChatSession?.id === sessionId ? readerState.currentChatSession : null;
}

function currentReaderModelCatalog() {
  return readerState.modelCatalog || normalizeReaderModelCatalog({});
}

function modelProvidersForMenu() {
  const catalog = currentReaderModelCatalog();
  const configuredProviders = catalog.providers.filter((profile) => profile.configured);
  if (configuredProviders.length) return configuredProviders;
  if (catalog.providers.length) return [];
  const settings = readerState.aiSettings || normalizeReaderAiSettings({});
  return [
    {
      name: "openai",
      displayName: "OpenAI API key",
      aliases: [],
      configured: settings.provider === "openai" && settings.configured,
      ready: settings.provider === "openai" && settings.ready,
      model: settings.provider === "openai" ? settings.model : "",
      selectedModel: settings.provider === "openai" ? settings.model : "",
      modelSource: settings.modelSource || "missing",
      defaultModel: "",
      models: []
    },
    {
      name: "codex-oauth",
      displayName: "Codex OAuth",
      aliases: ["codex", "openai-codex"],
      configured: settings.provider === "codex-oauth" && settings.configured,
      ready: settings.provider === "codex-oauth" && settings.ready,
      model: settings.provider === "codex-oauth" ? settings.model : "",
      selectedModel: settings.provider === "codex-oauth" ? settings.model : "",
      modelSource: settings.modelSource || "missing",
      defaultModel: "",
      models: []
    }
  ].filter((profile) => profile.configured);
}

function providerProfileFor(provider) {
  const normalized = normalizeProviderName(provider) || normalizeProviderName(currentReaderModelCatalog().defaultProvider) || "openai";
  const menuProfile = modelProvidersForMenu().find((profile) => profile.name === normalized || profile.aliases?.includes(normalized));
  if (menuProfile) return menuProfile;
  const catalogProfile = currentReaderModelCatalog().providers.find(
    (profile) => profile.name === normalized || profile.aliases?.includes(normalized)
  );
  return catalogProfile?.configured ? catalogProfile : null;
}

function modelOptionsForProvider(provider, selectedModel = "") {
  const selected = normalizeText(selectedModel);
  const profile = providerProfileFor(provider);
  const options = (profile?.models || []).map((option) => ({ ...option }));
  const ensureOption = (value, label = "", description = "") => {
    const normalized = normalizeText(value);
    if (!normalized || options.some((option) => option.value === normalized)) return;
    options.push({
      value: normalized,
      label: normalizeText(label) || normalized,
      shortLabel: normalizeText(label) || normalized,
      description: normalizeText(description),
      detail: normalizeText(description)
    });
  };
  ensureOption(normalizeText(profile?.model || profile?.defaultModel), "", "Provider default");
  if (providerAllowsSavedModel(provider, selected, options)) {
    ensureOption(selected, "", "Current saved model");
  }
  return options;
}

function providerAllowsSavedModel(provider, model, options = null) {
  const selected = normalizeText(model);
  if (!selected) return false;
  const normalizedProvider = normalizeProviderName(provider);
  const catalogOptions = options || (providerProfileFor(provider)?.models || []);
  if (catalogOptions.some((option) => option.value === selected)) return true;
  return normalizedProvider !== "codex-oauth";
}

function defaultModelForProvider(provider) {
  const profile = providerProfileFor(provider);
  return normalizeText(profile?.model || profile?.defaultModel) || modelOptionsForProvider(provider)[0]?.value || "";
}

function currentReaderModel() {
  const activeSessionId = getChatSessionId();
  const sessionModel = normalizeText(currentReaderSession()?.model);
  const provider = currentReaderProvider();
  if (sessionModel) return sessionModel;
  if (activeSessionId) {
    return defaultModelForProvider(provider)
      || (normalizeProviderName(readerState.aiSettings?.provider) === provider ? normalizeText(readerState.aiSettings?.model) : "");
  }
  if (normalizeProviderName(readerState.pendingChatProvider) === provider) {
    const pendingModel = normalizeText(readerState.pendingChatModel);
    if (providerAllowsSavedModel(provider, pendingModel)) return pendingModel;
  }
  const stored = readStoredReaderModelSelection();
  if (normalizeProviderName(stored.provider) === provider && normalizeText(stored.model)) {
    const storedModel = normalizeText(stored.model);
    if (providerAllowsSavedModel(provider, storedModel)) return storedModel;
  }
  return defaultModelForProvider(provider)
    || (normalizeProviderName(readerState.aiSettings?.provider) === provider ? normalizeText(readerState.aiSettings?.model) : "");
}

function currentReaderProvider() {
  const activeSessionId = getChatSessionId();
  const sessionProvider = normalizeProviderName(currentReaderSession()?.provider);
  if (sessionProvider) return sessionProvider;
  if (activeSessionId) {
    return normalizeProviderName(currentReaderModelCatalog().defaultProvider)
      || normalizeProviderName(readerState.aiSettings?.provider)
      || "openai";
  }
  const stored = readStoredReaderModelSelection();
  const storedProvider = normalizeProviderName(stored.provider);
  return normalizeProviderName(readerState.pendingChatProvider)
    || (storedProvider && providerProfileFor(storedProvider) ? storedProvider : "")
    || normalizeProviderName(currentReaderModelCatalog().defaultProvider)
    || normalizeProviderName(readerState.aiSettings?.provider)
    || "openai";
}

function activeReaderModelProvider() {
  return normalizeProviderName(readerState.modelDraftProvider) || currentReaderProvider();
}

function providerDisplayName(provider) {
  return normalizeText(providerProfileFor(provider)?.displayName) || fallbackProviderDisplayName(provider);
}

function modelDisplayLabel(model, provider, field = "label") {
  const selected = normalizeText(model);
  const option = modelOptionsForProvider(provider, selected).find((item) => item.value === selected);
  return normalizeText(option?.[field] || selected);
}

function modelCapabilitiesFor(provider, model) {
  const profile = providerProfileFor(provider);
  const selected = normalizeText(model);
  const option = modelOptionsForProvider(provider, selected).find((item) => item.value === selected);
  return option?.capabilities || profile?.capabilities || normalizeModelCapabilities({});
}

function gptReasoningOffSupported(provider, model = currentReaderModel()) {
  return Boolean(modelCapabilitiesFor(provider, model).supportsReasoningOff);
}

function activeProviderSupportsImageArtifacts() {
  const provider = currentReaderProvider();
  const profile = providerProfileFor(provider);
  const model = currentReaderModel();
  const capabilities = modelCapabilitiesFor(provider, currentReaderModel());
  const settings = readerState.aiSettings || normalizeReaderAiSettings({});
  const configured = Boolean(
    profile?.configured
    || (normalizeProviderName(settings.provider) === provider && settings.configured)
  );
  if (!configured) return false;
  if (provider === "codex-oauth") {
    return normalizeText(model).toLowerCase() !== "gpt-5.3-codex-spark";
  }
  return Boolean(capabilities.supportsImageGeneration);
}

function activeProviderImageGenerationUnsupportedMessage() {
  if (normalizeProviderName(currentReaderProvider()) === "codex-oauth") {
    const label = modelDisplayLabel(currentReaderModel(), currentReaderProvider(), "label") || currentReaderModel();
    return `${label || "This Codex model"} does not support image generation.`;
  }
  return "Image generation needs a connected Codex OAuth or OpenAI API key provider.";
}

function activeProviderSupportsImageInput() {
  const capabilities = modelCapabilitiesFor(currentReaderProvider(), currentReaderModel());
  return Boolean(capabilities.supportsVision && capabilities.imageInputMode !== "unsupported");
}

function activeProviderImageInputUnsupportedMessage() {
  if (normalizeProviderName(currentReaderProvider()) === "deepseek") {
    return "DeepSeek does not support image input. Files can still be attached.";
  }
  return "The selected model does not support image input. Files can still be attached.";
}

function modelSourceLabel(source) {
  const normalized = normalizeText(source);
  const labels = {
    default: "default",
    environment: "environment",
    local: "local settings",
    ".env.local": ".env.local",
    ".env": ".env",
    profile: "profile",
    selected: "selected",
    session: "session",
    missing: "not set"
  };
  return labels[normalized] || normalized || "not set";
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

function storedChatSessionId() {
  const store = readChatSessionStore();
  return normalizeText(store.__global || store.globalSessionId || store[currentChatNoteId()]);
}

function setStoredChatSessionId(sessionId) {
  const store = readChatSessionStore();
  if (sessionId) {
    store.__global = sessionId;
    store.globalSessionId = sessionId;
  } else {
    delete store.__global;
    delete store.globalSessionId;
  }
  writeChatSessionStore(store);
}

function readActiveChatRunStore() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ACTIVE_CHAT_RUN_STORE_KEY) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (error) {
    return {};
  }
}

function writeActiveChatRunStore(store) {
  try {
    localStorage.setItem(ACTIVE_CHAT_RUN_STORE_KEY, JSON.stringify(store || {}));
  } catch (error) {
    console.warn("Failed to save active chat run.", error);
  }
}

function rememberActiveChatRun(sessionId, requestId, latestUserText = "") {
  const normalizedSessionId = normalizeText(sessionId);
  const normalizedRequestId = normalizeText(requestId);
  if (!normalizedSessionId || !normalizedRequestId) return;
  const store = readActiveChatRunStore();
  store[normalizedSessionId] = {
    requestId: normalizedRequestId,
    noteId: currentChatNoteId(),
    latestUserText: normalizeText(latestUserText),
    updatedAt: new Date().toISOString()
  };
  writeActiveChatRunStore(store);
}

function forgetActiveChatRun(sessionId) {
  const normalizedSessionId = normalizeText(sessionId);
  if (!normalizedSessionId) return;
  const store = readActiveChatRunStore();
  delete store[normalizedSessionId];
  writeActiveChatRunStore(store);
}

function activeChatRunForSession(sessionId = getChatSessionId()) {
  const normalizedSessionId = normalizeText(sessionId);
  if (!normalizedSessionId) return null;
  const entry = readActiveChatRunStore()[normalizedSessionId];
  const requestId = normalizeText(entry?.requestId);
  if (requestId && normalizeText(entry?.noteId) === currentChatNoteId()) {
    return {
      sessionId: normalizedSessionId,
      requestId,
      latestUserText: normalizeText(entry?.latestUserText)
    };
  }
  const session = readerState.currentChatSession?.id === normalizedSessionId
    ? readerState.currentChatSession
    : readerState.chatSessions.find((item) => item?.id === normalizedSessionId);
  const activeRun = normalizeActiveChatRun(session?.activeRun);
  if (!activeRun) return null;
  if (activeRun.noteId && activeRun.noteId !== currentChatNoteId()) return null;
  return {
    sessionId: normalizedSessionId,
    requestId: activeRun.requestId,
    latestUserText: activeRun.message,
    progress: activeRun.progress
  };
}

function migrateChatRunState(fromRunKey, toSessionId) {
  const fromKey = chatSessionRunKey(fromRunKey);
  const toKey = chatSessionRunKey(toSessionId);
  if (!toSessionId || fromKey === toKey) return toKey;
  for (const store of [
    readerState.chatPendingBySession,
    readerState.chatProgressBySession,
    readerState.chatProgressRequestIdsBySession,
    readerState.chatAbortControllersBySession,
    readerState.chatRecoveryTimersBySession
  ]) {
    if (Object.prototype.hasOwnProperty.call(store, fromKey)) {
      store[toKey] = store[fromKey];
      delete store[fromKey];
    }
  }
  syncCurrentChatRunState();
  return toKey;
}

function setCurrentChatSessionId(sessionId) {
  const previousSessionId = readerState.chatSessionId;
  readerState.chatSessionId = normalizeText(sessionId);
  if (readerState.chatSessionId !== previousSessionId) {
    readerState.contextStatus = null;
    readerState.contextCompactStatus = "";
  }
  if (!readerState.chatSessionId) {
    readerState.currentChatSession = null;
  } else {
    const listedSession = readerState.chatSessions.find((session) => session.id === readerState.chatSessionId);
    if (listedSession) readerState.currentChatSession = listedSession;
  }
  setStoredChatSessionId(readerState.chatSessionId);
  syncCurrentChatRunState();
  renderReaderChatComposerState();
  renderChatSessionControls();
  renderReaderModelControls();
  if (typeof renderReaderContextControls === "function") renderReaderContextControls();
  renderReaderToolControls();
}

function getChatSessionId() {
  return readerState.chatSessionId;
}

function chatSessionRunKey(sessionId = getChatSessionId()) {
  return normalizeText(sessionId) || "__draft_chat_session__";
}

function isCurrentChatSessionRunKey(runKey) {
  return chatSessionRunKey() === chatSessionRunKey(runKey);
}

function isChatSessionPending(sessionId = getChatSessionId()) {
  return Boolean(readerState.chatPendingBySession[chatSessionRunKey(sessionId)]);
}

function currentChatProgress() {
  return readerState.chatProgressBySession[chatSessionRunKey()] || null;
}

function currentChatProgressRequestId() {
  return readerState.chatProgressRequestIdsBySession[chatSessionRunKey()] || "";
}

function syncCurrentChatRunState() {
  const runKey = chatSessionRunKey();
  readerState.chatPending = Boolean(readerState.chatPendingBySession[runKey]);
  readerState.chatProgress = readerState.chatProgressBySession[runKey] || null;
  readerState.chatProgressRequestId = readerState.chatProgressRequestIdsBySession[runKey] || "";
  readerState.chatAbortController = readerState.chatAbortControllersBySession[runKey] || null;
}
