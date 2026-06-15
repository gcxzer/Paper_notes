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
    readerState.chatRecoveryTimersBySession,
    readerState.htmlNoteWriteRunsBySession
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
