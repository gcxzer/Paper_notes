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
  if (open) {
    closeReaderModelMenu();
    closeReaderContextPopover();
    closeReaderToolMenu();
  }
  readerState.chatSessionMenuOpen = open;
  if (elements.chatSessionPopover) elements.chatSessionPopover.hidden = !open;
  elements.chatSessionMenuButton?.setAttribute("aria-expanded", String(open));
  if (open) {
    renderChatSessionList();
    void fetchReaderChatSessions({ silent: true });
    requestAnimationFrame(() => elements.chatSessionSearch?.focus());
  } else {
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
  }
}

async function fetchReaderChatSessions({ silent = false } = {}) {
  readerState.chatSessionsLoading = true;
  renderChatSessionList();
  try {
    const query = readerState.chatSessionTrashOpen ? "?includeArchived=true" : "";
    const payload = await fetchAgentJson(`/api/chat/sessions${query}`);
    const sessions = normalizeReaderChatSessions(payload.sessions);
    readerState.chatSessions = sessions.filter((session) => (
      readerState.chatSessionTrashOpen ? session.archived : !session.archived
    ));
    readerState.chatSessionsLoading = false;
    renderChatSessionList();
    renderReaderModelControls();
    return readerState.chatSessions;
  } catch (error) {
    readerState.chatSessionsLoading = false;
    readerState.chatSessions = [];
    if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
    renderReaderModelControls();
    return [];
  }
}

function clearCurrentReaderChatSession() {
  readerState.chatMessages = [];
  readerState.chatEditingIndex = -1;
  readerState.chatEditingText = "";
  readerState.toolSnapshots = [];
  readerState.toolDiffs = {};
  readerState.toolSnapshotConflicts = {};
  setCurrentChatSessionId("");
  renderReaderChatMessages();
  renderReaderModelControls();
  renderReaderToolControls();
  setReaderChatError("");
}

async function loadReaderChatSession(sessionId, { closeMenu = true, refreshList = false } = {}) {
  const nextSessionId = normalizeText(sessionId);
  if (!nextSessionId) {
    clearCurrentReaderChatSession();
    return;
  }

  try {
    const payload = await fetchAgentJson(`/api/chat/session?id=${encodeURIComponent(nextSessionId)}`);
    const session = upsertReaderChatSession(payload.session);
    if (session?.provider && session?.model) writeStoredReaderModelSelection(session.provider, session.model);
    readerState.chatMessages = normalizeApiChatMessages(payload.session?.messages);
    readerState.chatEditingIndex = -1;
    readerState.chatEditingText = "";
    readerState.toolDiffs = {};
    setCurrentChatSessionId(session?.id || payload.session?.id || nextSessionId);
    setReaderChatError("");
    resumeActiveChatRunForCurrentSession();
    renderReaderChatMessages({ scrollToBottom: true });
    renderReaderModelControls();
    if (refreshList) await fetchReaderChatSessions({ silent: true });
    if (closeMenu) setChatSessionMenuOpen(false);
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
  }
}

function resumeActiveChatRunForCurrentSession() {
  const activeRun = activeChatRunForSession();
  if (!activeRun) {
    syncCurrentChatRunState();
    renderReaderChatComposerState();
    return;
  }
  setReaderChatPending(true, activeRun.sessionId);
  startReaderChatProgress(activeRun.requestId, activeRun.sessionId);
}

async function createReaderChatSession() {
  readerState.chatSessionTrashOpen = false;
  readerState.chatSessionQuery = "";
  readerState.confirmingDeleteSessionId = "";
  readerState.renamingSessionId = "";
  readerState.chatMessages = [];
  readerState.toolDiffs = {};
  setCurrentChatSessionId("");
  setReaderChatError("");
  renderReaderChatMessages();
  await fetchReaderChatSessions({ silent: true });
  setChatSessionMenuOpen(false);
  elements.readerChatInput?.focus();
}

async function renameReaderChatSession(sessionId, title) {
  const nextTitle = normalizeText(title);
  if (!sessionId || !nextTitle) return;
  try {
    await fetchAgentJson("/api/chat/session/rename", {
      method: "POST",
      body: { sessionId, title: nextTitle }
    });
    readerState.renamingSessionId = "";
    readerState.confirmingDeleteSessionId = "";
    setReaderChatError("");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function trashReaderChatSession(sessionId) {
  if (!sessionId) return;
  try {
    await fetchAgentJson("/api/chat/session/archive", {
      method: "POST",
      body: { sessionId, archived: true }
    });
    if (sessionId === getChatSessionId()) clearCurrentReaderChatSession();
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    setReaderChatError("");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function restoreReaderChatSession(sessionId) {
  if (!sessionId) return;
  try {
    await fetchAgentJson("/api/chat/session/archive", {
      method: "POST",
      body: { sessionId, archived: false }
    });
    readerState.chatSessionTrashOpen = false;
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    setReaderChatError("");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function permanentlyDeleteReaderChatSession(sessionId) {
  if (!sessionId) return;
  try {
    await fetchAgentJson("/api/chat/session/delete", {
      method: "POST",
      body: { sessionId }
    });
    if (sessionId === getChatSessionId()) clearCurrentReaderChatSession();
    readerState.confirmingDeleteSessionId = "";
    readerState.renamingSessionId = "";
    setReaderChatError("");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function initializeReaderChatSessions() {
  readerState.chatSessionTrashOpen = false;
  readerState.chatSessionQuery = "";
  const sessions = await fetchReaderChatSessions({ silent: true });
  const savedSessionId = storedChatSessionId();
  if (savedSessionId && sessions.some((session) => session.id === savedSessionId)) {
    await loadReaderChatSession(savedSessionId, { closeMenu: false, refreshList: false });
    return;
  }
  clearCurrentReaderChatSession();
}

function ensureReaderStreamingAssistantMessage() {
  const last = readerState.chatMessages[readerState.chatMessages.length - 1];
  if (last?.role === "assistant" && last.streaming) return last;
  const draft = { role: "assistant", text: "", streaming: true };
  readerState.chatMessages.push(draft);
  return draft;
}

function appendReaderStreamingDelta(delta) {
  const text = String(delta ?? "");
  if (!text) return;
  const draft = ensureReaderStreamingAssistantMessage();
  draft.text = `${draft.text || ""}${text}`;
  scheduleReaderStreamingRender();
}

function scheduleReaderStreamingRender() {
  if (readerState.chatStreamRenderTimer) return;
  readerState.chatStreamRenderTimer = window.setTimeout(() => {
    readerState.chatStreamRenderTimer = 0;
    renderReaderChatMessages({ scrollToBottom: true });
  }, 50);
}

function flushReaderStreamingRender() {
  if (readerState.chatStreamRenderTimer) {
    window.clearTimeout(readerState.chatStreamRenderTimer);
    readerState.chatStreamRenderTimer = 0;
  }
  renderReaderChatMessages({ scrollToBottom: true });
}

function latestReaderStreamingAssistantMessage() {
  for (let index = readerState.chatMessages.length - 1; index >= 0; index -= 1) {
    const message = readerState.chatMessages[index];
    if (message?.role === "user") return null;
    if (message?.role === "assistant" && message.streaming) return message;
  }
  return null;
}

function shouldFallbackToReaderJsonChat(error) {
  if (error?.streamStarted) return false;
  return error?.code === "stream_unsupported" || error?.status === 404 || error?.status === 405;
}

function hasCompletedAssistantAfterLatestUser(messages) {
  const normalizedMessages = Array.isArray(messages) ? messages : [];
  const lastUserIndex = normalizedMessages.reduce((latest, message, index) => (
    message?.role === "user" ? index : latest
  ), -1);
  return normalizedMessages.slice(Math.max(0, lastUserIndex + 1)).some((message) => (
    message?.role === "assistant" && normalizeText(message.text || message.content) && !message.error
  ));
}

async function readerSessionIdFromDebugRun(requestId) {
  const id = normalizeText(requestId);
  if (!id) return "";
  try {
    const payload = await fetchAgentJson(`/api/debug/runs/${encodeURIComponent(id)}`);
    const run = normalizeDebugRun(payload.run);
    return normalizeText(run?.sessionId);
  } catch (error) {
    console.debug("Could not resolve chat session from debug run.", error);
    return "";
  }
}

async function recoverReaderChatFromSession({ sessionId = "", requestId = "" } = {}) {
  const targetSessionId = normalizeText(sessionId) || getChatSessionId() || await readerSessionIdFromDebugRun(requestId);
  if (!targetSessionId) return false;
  try {
    const payload = await fetchAgentJson(`/api/chat/session?id=${encodeURIComponent(targetSessionId)}`);
    const messages = normalizeApiChatMessages(payload.session?.messages);
    if (!hasCompletedAssistantAfterLatestUser(messages)) return false;
    setCurrentChatSessionId(payload.session?.id || targetSessionId);
    upsertReaderChatSession(payload.session);
    readerState.chatMessages = messages;
    readerState.chatEditingIndex = -1;
    readerState.chatEditingText = "";
    clearReaderChatProgress(payload.session?.id || targetSessionId);
    setReaderChatError("");
    renderReaderChatMessages({ scrollToBottom: true });
    renderReaderModelControls();
    return true;
  } catch (error) {
    console.debug("Could not recover chat session after request error.", error);
    return false;
  }
}
