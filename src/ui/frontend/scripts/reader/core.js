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
    provider: normalizeProviderName(rawSession?.provider),
    model: normalizeText(rawSession?.model),
    deepSeekThinkMode: normalizeText(metadata.deepseekThinkMode || metadata.deepseek_think_mode),
    gptThinkMode: normalizeText(metadata.gptThinkMode || metadata.gpt_think_mode),
    geminiThinkMode: normalizeText(metadata.geminiThinkMode || metadata.gemini_think_mode),
    anthropicThinkMode: normalizeText(metadata.anthropicThinkMode || metadata.anthropic_think_mode),
    updatedAt: normalizeText(rawSession?.updatedAt || rawSession?.createdAt),
    createdAt: normalizeText(rawSession?.createdAt),
    archivedAt: normalizeText(rawSession?.archivedAt || metadata.archivedAt || metadata.archived_at),
    trashedAt: normalizeText(rawSession?.trashedAt),
    lastMessagePreview: normalizeText(rawSession?.lastMessagePreview),
    messageCount: Number(rawSession?.messageCount) || 0,
    state,
    archived: state === "archived",
    trashed: state === "trashed"
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

function normalizeToolDiff(rawDiff) {
  if (!rawDiff || typeof rawDiff !== "object") return null;
  const snapshotId = normalizeText(rawDiff.snapshotId || rawDiff.snapshot_id);
  if (!snapshotId) return null;
  const files = (Array.isArray(rawDiff.files) ? rawDiff.files : [])
    .map((file) => ({
      path: normalizeText(file?.path),
      diff: normalizeText(file?.diff),
      currentMatchesSnapshot: file?.currentMatchesSnapshot !== false,
      truncated: Boolean(file?.truncated)
    }))
    .filter((file) => file.path);
  return {
    snapshotId,
    sessionId: normalizeText(rawDiff.sessionId || rawDiff.session_id),
    toolName: normalizeText(rawDiff.toolName || rawDiff.tool_name),
    files
  };
}

function normalizeToolSnapshot(rawSnapshot) {
  if (!rawSnapshot || typeof rawSnapshot !== "object") return null;
  const changedFiles = Array.isArray(rawSnapshot.changedFiles)
    ? rawSnapshot.changedFiles.map((file) => ({
      path: normalizeText(file?.path),
      beforeBytes: Math.max(0, Math.round(Number(file?.beforeBytes) || 0)),
      afterBytes: Math.max(0, Math.round(Number(file?.afterBytes) || 0))
    })).filter((file) => file.path)
    : [];
  const snapshotId = normalizeText(rawSnapshot.snapshotId || rawSnapshot.snapshot_id);
  if (!snapshotId) return null;
  return {
    snapshotId,
    sessionId: normalizeText(rawSnapshot.sessionId || rawSnapshot.session_id),
    toolName: normalizeText(rawSnapshot.toolName || rawSnapshot.tool_name || rawSnapshot.name) || "tool",
    changed: Boolean(rawSnapshot.changed),
    changedFiles,
    undoable: Boolean(rawSnapshot.undoable),
    canUndo: rawSnapshot.canUndo !== false && rawSnapshot.can_undo !== false,
    canRedo: rawSnapshot.canRedo === true || rawSnapshot.can_redo === true,
    currentMatchesAfter: rawSnapshot.currentMatchesAfter === true || rawSnapshot.current_matches_after === true,
    currentMatchesBefore: rawSnapshot.currentMatchesBefore === true || rawSnapshot.current_matches_before === true,
    restored: Boolean(rawSnapshot.restored),
    failed: Boolean(rawSnapshot.failed),
    createdAt: normalizeText(rawSnapshot.createdAt || rawSnapshot.created_at),
    arguments: rawSnapshot.arguments && typeof rawSnapshot.arguments === "object" ? rawSnapshot.arguments : {}
  };
}

function normalizeToolSnapshots(rawSnapshots) {
  return (Array.isArray(rawSnapshots) ? rawSnapshots : [])
    .map(normalizeToolSnapshot)
    .filter(Boolean);
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
      anthropic: enabledEntry(nativeRaw.anthropic || nativeRaw.Anthropic),
      gemini: enabledEntry(nativeRaw.gemini || nativeRaw.Gemini || nativeRaw.googleGemini),
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
  if (nativeSearchEnabled && !readerCustomWebSearchEnabled(settings) && !disabledTools.includes("web_search")) {
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
  if (provider === "codex-oauth") {
    return Boolean(native.openaiCodex?.enabled || settings?.nativeWebSearchEnabled);
  }
  if (provider === "openai") {
    return Boolean(native.openaiAPIKey?.enabled || settings?.nativeWebSearchEnabled);
  }
  if (provider === "anthropic") {
    return Boolean(native.anthropic?.enabled || settings?.nativeWebSearchEnabled);
  }
  if (provider === "gemini") {
    return Boolean(native.gemini?.enabled || settings?.nativeWebSearchEnabled);
  }
  return false;
}

function readerCustomWebSearchEnabled(settings) {
  const custom = settings?.webSearchProviders?.custom_provider || {};
  return Boolean(custom.Tavily?.enabled || custom.Brave?.enabled);
}

function readerGenerationPayload() {
  if (readerState.generationMode === "image") {
    return {
      imageGeneration: {
        enabled: true,
        size: "1024x1024",
        quality: "auto",
        format: "png"
      }
    };
  }
  if (readerState.generationMode === "file") {
    return {
      fileGeneration: {
        enabled: true,
        format: normalizeFileGenerationFormat(readerState.fileGenerationFormat)
      }
    };
  }
  return {};
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
  const normalized = normalizeGenerationRequest(generation);
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

function normalizeToolApproval(rawApproval) {
  if (!rawApproval || typeof rawApproval !== "object") return null;
  const approvalId = normalizeText(rawApproval.approvalId || rawApproval.approval_id || rawApproval.id);
  if (!approvalId) return null;
  return {
    approvalId,
    sessionId: normalizeText(rawApproval.sessionId || rawApproval.session_id),
    requestId: normalizeText(rawApproval.requestId || rawApproval.request_id),
    toolCallId: normalizeText(rawApproval.toolCallId || rawApproval.tool_call_id),
    toolName: normalizeText(rawApproval.toolName || rawApproval.tool_name) || "tool",
    risk: normalizeText(rawApproval.risk) || "write",
    writeMode: normalizeWriteToolMode(rawApproval.writeMode || rawApproval.write_mode),
    argumentSummary: normalizeText(rawApproval.argumentSummary || rawApproval.argument_summary),
    status: normalizeText(rawApproval.status) || "pending",
    message: normalizeText(rawApproval.message),
    createdAt: normalizeText(rawApproval.createdAt || rawApproval.created_at),
    expiresAt: normalizeText(rawApproval.expiresAt || rawApproval.expires_at)
  };
}

function pendingApprovalFromProgress(progress) {
  const normalizedProgress = normalizeChatProgress(progress);
  if (!normalizedProgress) return null;
  const pending = new Map();
  for (const event of normalizedProgress.events) {
    const approval = normalizeToolApproval(event.data);
    if (!approval) continue;
    if (event.type === "tool_approval_requested") {
      pending.set(approval.approvalId, approval);
    } else if (event.type === "tool_approval_resolved") {
      pending.delete(approval.approvalId);
    }
  }
  return Array.from(pending.values()).pop() || null;
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

function normalizeGeminiThinkMode(rawMode, model = currentReaderModel()) {
  const normalizedModel = normalizeText(model);
  const mode = normalizeText(rawMode).toLowerCase();
  if (normalizedModel === "gemini-3-pro-preview") {
    const effort = ["low", "high"].includes(mode) ? mode : "high";
    return { enabled: true, effort };
  }
  if (!mode || mode === "off" || mode === "minimal" || mode === "none" || mode === "false") {
    return { enabled: false, effort: "medium" };
  }
  const effort = ["low", "medium", "high"].includes(mode) ? mode : "medium";
  return { enabled: true, effort };
}

function readStoredGeminiThinkMode() {
  try {
    return normalizeGeminiThinkMode(localStorage.getItem(GEMINI_THINK_MODE_KEY) || "", "gemini-3-flash-preview");
  } catch (error) {
    return { enabled: false, effort: "medium" };
  }
}

function writeStoredGeminiThinkMode(mode, model = currentReaderModel()) {
  const normalized = normalizeGeminiThinkMode(mode, model);
  try {
    localStorage.setItem(GEMINI_THINK_MODE_KEY, normalized.enabled ? normalized.effort : "off");
  } catch (error) {
    console.warn("Failed to save Gemini think mode.", error);
  }
  return normalized;
}

function providerSupportsGeminiThinkMode(provider) {
  return normalizeProviderName(provider) === "gemini";
}

function currentGeminiThinkMode(model = currentReaderModel()) {
  const sessionMode = normalizeText(currentReaderSession()?.geminiThinkMode);
  if (sessionMode) return normalizeGeminiThinkMode(sessionMode, model);
  return normalizeGeminiThinkMode(readerState.geminiThinkMode?.enabled ? readerState.geminiThinkMode.effort : "off", model);
}

function anthropicThinkEffortsForModel(model = currentReaderModel()) {
  const normalizedModel = normalizeText(model);
  if (normalizedModel === "claude-opus-4-7") return ["low", "medium", "high", "xhigh", "max"];
  if (normalizedModel === "claude-sonnet-4-6") return ["low", "medium", "high", "max"];
  return [];
}

function normalizeAnthropicThinkMode(rawMode, model = currentReaderModel()) {
  const efforts = anthropicThinkEffortsForModel(model);
  const mode = normalizeText(rawMode).toLowerCase();
  if (!efforts.length || !mode || mode === "off" || mode === "none" || mode === "false") {
    return { enabled: false, effort: "medium" };
  }
  const effort = efforts.includes(mode) ? mode : "medium";
  return { enabled: true, effort };
}

function readStoredAnthropicThinkMode() {
  try {
    return normalizeAnthropicThinkMode(localStorage.getItem(ANTHROPIC_THINK_MODE_KEY) || "");
  } catch (error) {
    return { enabled: false, effort: "medium" };
  }
}

function writeStoredAnthropicThinkMode(mode, model = currentReaderModel()) {
  const normalized = normalizeAnthropicThinkMode(mode, model);
  try {
    localStorage.setItem(ANTHROPIC_THINK_MODE_KEY, normalized.enabled ? normalized.effort : "off");
  } catch (error) {
    console.warn("Failed to save Anthropic think mode.", error);
  }
  return normalized;
}

function providerSupportsAnthropicThinkMode(provider, model = currentReaderModel()) {
  return normalizeProviderName(provider) === "anthropic" && anthropicThinkEffortsForModel(model).length > 0;
}

function currentAnthropicThinkMode(model = currentReaderModel()) {
  const sessionMode = normalizeText(currentReaderSession()?.anthropicThinkMode);
  if (sessionMode) return normalizeAnthropicThinkMode(sessionMode, model);
  return normalizeAnthropicThinkMode(readerState.anthropicThinkMode?.enabled ? readerState.anthropicThinkMode.effort : "off", model);
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
  const text = normalizeText(rawMessage?.text || rawMessage?.content);
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
    noteEdit: rawMessage?.noteEdit,
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
    providers
  };
}

function normalizeReaderAiSettings(payload) {
  const provider = normalizeProviderName(payload?.provider) || "openai";
  return {
    provider,
    model: normalizeText(payload?.model),
    modelSource: normalizeText(payload?.modelSource || "missing"),
    configured: Boolean(payload?.configured),
    ready: Boolean(payload?.ready)
  };
}

function normalizeContextStatus(payload) {
  const raw = payload?.context || payload || {};
  const contextLength = Math.max(0, Math.round(Number(raw.contextLength || raw.context_length) || 0));
  const tokensUsed = Math.max(0, Math.round(Number(raw.tokensUsed || raw.requestTokens || raw.request_tokens) || 0));
  const thresholdTokens = Math.max(0, Math.round(Number(raw.thresholdTokens || raw.threshold_tokens) || 0));
  const fallbackPercent = contextLength > 0 ? Math.round((tokensUsed / contextLength) * 100) : 0;
  const fallbackThresholdPercent = contextLength > 0 ? Math.round((thresholdTokens / contextLength) * 100) : 0;
  return {
    provider: normalizeProviderName(raw.provider) || currentReaderProvider(),
    model: normalizeText(raw.model) || currentReaderModel(),
    contextLength,
    tokensUsed,
    messageTokens: Math.max(0, Math.round(Number(raw.messageTokens || raw.message_tokens) || 0)),
    instructionTokens: Math.max(0, Math.round(Number(raw.instructionTokens || raw.instruction_tokens) || 0)),
    toolSchemaTokens: Math.max(0, Math.round(Number(raw.toolSchemaTokens || raw.tool_schema_tokens) || 0)),
    thresholdTokens,
    percentFull: Math.min(100, Math.max(0, Math.round(Number(raw.percentFull || raw.percent_full) || fallbackPercent))),
    thresholdPercent: Math.min(100, Math.max(0, Math.round(Number(raw.thresholdPercent || raw.threshold_percent) || fallbackThresholdPercent))),
    messageCount: Math.max(0, Math.round(Number(raw.messageCount || raw.message_count) || 0)),
    compactionEnabled: Boolean(raw.compactionEnabled ?? raw.compaction_enabled),
    compressionCount: Math.max(0, Math.round(Number(raw.compressionCount || raw.compression_count) || 0)),
    lastCompressedAt: normalizeText(raw.lastCompressedAt || raw.last_compressed_at),
    summaryAvailable: Boolean(raw.summaryAvailable ?? raw.summary_available),
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
  if (count >= 1_000) return `${Math.round(count / 1_000)}k`;
  return String(count);
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
  if (normalizeProviderName(provider) !== "gemini" || geminiModelIsSupported(selected)) {
    ensureOption(selected, "", "Current saved model");
  }
  return options;
}

function defaultModelForProvider(provider) {
  const profile = providerProfileFor(provider);
  return normalizeText(profile?.model || profile?.defaultModel) || modelOptionsForProvider(provider)[0]?.value || "";
}

function currentReaderModel() {
  const activeSessionId = getChatSessionId();
  const sessionModel = normalizeText(currentReaderSession()?.model);
  const provider = currentReaderProvider();
  if (sessionModel) {
    if (provider === "gemini" && !geminiModelIsSupported(sessionModel)) return defaultModelForProvider(provider);
    return sessionModel;
  }
  if (activeSessionId) {
    return defaultModelForProvider(provider)
      || (normalizeProviderName(readerState.aiSettings?.provider) === provider ? normalizeText(readerState.aiSettings?.model) : "");
  }
  if (normalizeProviderName(readerState.pendingChatProvider) === provider) {
    const pendingModel = normalizeText(readerState.pendingChatModel);
    if (pendingModel && (provider !== "gemini" || geminiModelIsSupported(pendingModel))) return pendingModel;
  }
  const stored = readStoredReaderModelSelection();
  if (normalizeProviderName(stored.provider) === provider && normalizeText(stored.model)) {
    const storedModel = normalizeText(stored.model);
    if (provider !== "gemini" || geminiModelIsSupported(storedModel)) return storedModel;
  }
  return defaultModelForProvider(provider)
    || (normalizeProviderName(readerState.aiSettings?.provider) === provider ? normalizeText(readerState.aiSettings?.model) : "");
}

function geminiModelIsSupported(model) {
  return ["gemini-3-flash-preview", "gemini-3-pro-preview"].includes(normalizeText(model));
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

function rememberActiveChatRun(sessionId, requestId) {
  const normalizedSessionId = normalizeText(sessionId);
  const normalizedRequestId = normalizeText(requestId);
  if (!normalizedSessionId || !normalizedRequestId) return;
  const store = readActiveChatRunStore();
  store[normalizedSessionId] = {
    requestId: normalizedRequestId,
    noteId: currentChatNoteId(),
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
  if (!requestId || normalizeText(entry?.noteId) !== currentChatNoteId()) return null;
  return { sessionId: normalizedSessionId, requestId };
}

function migrateChatRunState(fromRunKey, toSessionId) {
  const fromKey = chatSessionRunKey(fromRunKey);
  const toKey = chatSessionRunKey(toSessionId);
  if (!toSessionId || fromKey === toKey) return toKey;
  for (const store of [
    readerState.chatPendingBySession,
    readerState.chatProgressBySession,
    readerState.chatProgressRequestIdsBySession,
    readerState.chatProgressTimersBySession,
    readerState.chatAbortControllersBySession
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
  readerState.chatSessionId = normalizeText(sessionId);
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
  renderReaderToolControls();
  if (readerState.toolMenuOpen) void loadReaderToolSnapshots({ silent: true });
  scheduleReaderContextStatusRefresh();
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
