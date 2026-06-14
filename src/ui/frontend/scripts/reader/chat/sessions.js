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
    readerSessionProjectName(session),
    chatSessionPaperLabel(session),
    formatChatSessionTime(session.updatedAt)
  ].some((value) => normalizeText(value).toLowerCase().includes(query));
}

function currentChatSessionView() {
  return ["active", "archived", "trashed"].includes(readerState.chatSessionView)
    ? readerState.chatSessionView
    : "active";
}

function chatSessionViewLabel(view = currentChatSessionView()) {
  if (view === "archived") return "Archived";
  if (view === "trashed") return "Trash";
  return "Sessions";
}

function sessionNoteIdBase(value) {
  const text = normalizeText(value).toLowerCase();
  const match = text.match(/^(.*)-[a-z0-9]{3,}$/);
  return match ? match[1] : text;
}

function noteTitleForSessionNoteId(noteId) {
  const targetId = normalizeText(noteId);
  if (!targetId || !Array.isArray(readerState.library?.notes)) return "";
  const exact = readerState.library.notes.find((note) => note.id === targetId);
  if (exact?.title) return normalizeText(exact.title);
  const targetBase = sessionNoteIdBase(targetId);
  if (!targetBase) return "";
  const sibling = readerState.library.notes.find((note) => sessionNoteIdBase(note.id) === targetBase);
  return normalizeText(sibling?.title);
}

function chatSessionPaperLabel(session) {
  return normalizeText(session?.originNoteTitle || session?.currentNoteTitle)
    || noteTitleForSessionNoteId(session?.originNoteId)
    || noteTitleForSessionNoteId(session?.currentNoteId)
    || noteTitleForSessionNoteId(session?.noteId);
}

function chatSessionMetaText(session, view) {
  return view === "trashed"
    ? `Moved ${formatChatSessionTime(session.trashedAt || session.updatedAt)}`
    : view === "archived"
      ? `Archived ${formatChatSessionTime(session.archivedAt || session.updatedAt)}`
      : formatChatSessionTime(session.updatedAt);
}

function chatSessionMetaHtml(session, view) {
  const timeText = chatSessionMetaText(session, view);
  const paperLabel = chatSessionPaperLabel(session);
  const projectName = readerSessionProjectName(session);
  return `
    <span class="ask-session-meta-time">${escapeHtml(timeText)}</span>
    ${paperLabel ? `<span class="ask-session-meta-paper">· ${escapeHtml(paperLabel)}</span>` : ""}
    ${projectName ? `<span class="ask-session-meta-project">· ${escapeHtml(projectName)}</span>` : ""}
  `;
}

function clearSessionActionMenu() {
  readerState.openSessionActionMenuId = "";
}

function clearSessionRowState() {
  readerState.confirmingDeleteSessionId = "";
  readerState.renamingSessionId = "";
  readerState.assigningProjectSessionId = "";
  clearSessionActionMenu();
}

function addSessionMenuOption(menu, {
  className = "",
  text = "",
  ariaLabel = "",
  onClick = () => {},
}) {
  return addReaderActionMenuOption(menu, { className, text, ariaLabel, onClick });
}

function populateSessionActionMenu(menu, session, view) {
  if (readerState.assigningProjectSessionId === session.id) {
    menu.classList.add("ask-session-project-picker-menu");
    addSessionProjectPicker(menu, session);
    return;
  }
  menu.classList.remove("ask-session-project-picker-menu");
  if (view === "active") {
    addSessionMenuOption(menu, {
      text: "Rename",
      ariaLabel: `Rename ${session.title || "chat session"}`,
      onClick: () => {
        readerState.renamingSessionId = session.id;
        readerState.confirmingDeleteSessionId = "";
        clearSessionActionMenu();
        renderChatSessionList();
      },
    });
    addSessionMenuOption(menu, {
      className: "ask-session-project",
      text: readerSessionProjectName(session) ? `Project: ${readerSessionProjectName(session)}` : "Project...",
      ariaLabel: `Choose project for ${session.title || "chat session"}`,
      onClick: () => {
        readerState.assigningProjectSessionId = session.id;
        readerState.confirmingDeleteSessionId = "";
        renderChatSessionList();
      },
    });
    addSessionMenuOption(menu, {
      className: "ask-session-archive",
      text: "Archive",
      ariaLabel: `Archive ${session.title || "chat session"}`,
      onClick: () => archiveReaderChatSession(session.id),
    });
    addSessionMenuOption(menu, {
      className: "ask-session-delete",
      text: "Trash",
      ariaLabel: `Move ${session.title || "chat session"} to Trash`,
      onClick: () => trashReaderChatSession(session.id),
    });
  } else {
    if (view === "archived") {
      addSessionMenuOption(menu, {
        className: "ask-session-project",
        text: readerSessionProjectName(session) ? `Project: ${readerSessionProjectName(session)}` : "Project...",
        ariaLabel: `Choose project for ${session.title || "chat session"}`,
        onClick: () => {
          readerState.assigningProjectSessionId = session.id;
          readerState.confirmingDeleteSessionId = "";
          renderChatSessionList();
        },
      });
    }
    addSessionMenuOption(menu, {
      className: "ask-session-restore",
      text: "Restore",
      ariaLabel: `Restore ${session.title || "chat session"}`,
      onClick: () => restoreReaderChatSession(session.id),
    });
    if (view === "archived") {
      addSessionMenuOption(menu, {
        className: "ask-session-delete",
        text: "Trash",
        ariaLabel: `Move ${session.title || "chat session"} to Trash`,
        onClick: () => trashReaderChatSession(session.id),
      });
    } else {
      addSessionMenuOption(menu, {
        className: "ask-session-delete",
        text: readerState.confirmingDeleteSessionId === session.id ? "Confirm delete" : "Delete",
        ariaLabel: `${readerState.confirmingDeleteSessionId === session.id ? "Confirm delete" : "Permanently delete"} ${session.title || "chat session"}`,
        onClick: () => {
          if (readerState.confirmingDeleteSessionId === session.id) {
            permanentlyDeleteReaderChatSession(session.id);
            return;
          }
          readerState.confirmingDeleteSessionId = session.id;
          readerState.openSessionActionMenuId = session.id;
          readerState.renamingSessionId = "";
          renderChatSessionList();
        },
      });
    }
  }
}

function positionSessionActionMenu(menu, row) {
  const popover = elements.chatSessionPopover;
  if (!popover || !row) return;
  positionReaderActionMenu(menu, row, {
    popover,
    buttonSelector: ".ask-session-more",
    gap: 10,
    maxHeight: Math.max(96, popover.getBoundingClientRect().height - 16),
  });
}

function appendSessionFloatingActionMenu(session, row, view) {
  if (!elements.chatSessionPopover || !session || !row) return;
  const menu = document.createElement("div");
  menu.className = "ask-session-action-menu";
  menu.setAttribute("role", "menu");
  menu.style.visibility = "hidden";
  populateSessionActionMenu(menu, session, view);
  elements.chatSessionPopover.appendChild(menu);
  positionSessionActionMenu(menu, row);
}

function appendSessionActionMenu(row, session) {
  const isMenuOpen = readerState.openSessionActionMenuId === session.id;
  const menuButton = document.createElement("button");
  menuButton.className = "ask-session-more";
  menuButton.type = "button";
  menuButton.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="6.5" cy="12" r="1.9"></circle>
      <circle cx="12" cy="12" r="1.9"></circle>
      <circle cx="17.5" cy="12" r="1.9"></circle>
    </svg>
  `;
  menuButton.setAttribute("aria-label", `More actions for ${session.title || "chat session"}`);
  menuButton.setAttribute("aria-haspopup", "menu");
  menuButton.setAttribute("aria-expanded", String(isMenuOpen));
  menuButton.addEventListener("click", (event) => {
    event.stopPropagation();
    readerState.openSessionActionMenuId = isMenuOpen ? "" : session.id;
    readerState.renamingSessionId = "";
    readerState.assigningProjectSessionId = "";
    renderChatSessionList();
  });

  row.appendChild(menuButton);
}

function renderChatSessionControls() {
  const view = currentChatSessionView();
  if (elements.chatSessionPopoverTitle) {
    elements.chatSessionPopoverTitle.textContent = chatSessionViewLabel(view);
  }
  if (elements.clearTrashSessions) {
    elements.clearTrashSessions.hidden = view !== "trashed";
    elements.clearTrashSessions.disabled = readerState.chatSessionsLoading || !readerState.chatSessions.length;
  }
  if (elements.newChatSession) {
    elements.newChatSession.hidden = view !== "active";
    elements.newChatSession.disabled = readerState.chatSessionsLoading;
  }
  elements.chatSessionViewButtons?.forEach((button) => {
    const isActive = button.dataset.sessionView === view && readerState.chatSessionMenuOpen;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-expanded", String(isActive));
    button.setAttribute("aria-pressed", String(isActive));
  });
  elements.chatSessionMenuButton?.setAttribute("aria-expanded", String(readerState.chatSessionMenuOpen && view === "active"));
  elements.chatSessionTrashButton?.setAttribute("aria-expanded", String(readerState.chatSessionMenuOpen && view === "trashed"));
  elements.chatSessionArchivedButton?.setAttribute("aria-expanded", String(readerState.chatSessionMenuOpen && view === "archived"));
  if (elements.chatSessionSearch) {
    elements.chatSessionSearch.placeholder = view === "trashed"
      ? "Search trash"
      : view === "archived"
        ? "Search archived"
        : "Search sessions";
  }
  if (elements.chatSessionSearch && elements.chatSessionSearch.value !== readerState.chatSessionQuery) {
    elements.chatSessionSearch.value = readerState.chatSessionQuery;
  }
}

function openClearTrashDialog() {
  if (currentChatSessionView() !== "trashed" || !readerState.chatSessions.length) return;
  const count = readerState.chatSessions.length;
  if (elements.clearTrashMessage) {
    elements.clearTrashMessage.textContent = `Permanently delete ${count} trashed chat${count === 1 ? "" : "s"}? This cannot be undone.`;
  }
  if (elements.clearTrashDialog && !elements.clearTrashDialog.open) {
    elements.clearTrashDialog.showModal();
  }
}

function closeClearTrashDialog() {
  elements.clearTrashDialog?.close();
}

function renderChatSessionList() {
  if (!elements.chatSessionList) return;
  elements.chatSessionList.innerHTML = "";
  elements.chatSessionPopover?.querySelector(".ask-session-action-menu")?.remove();
  renderChatSessionControls();

  if (readerState.chatSessionsLoading) {
    elements.chatSessionList.innerHTML = `<p class="ask-session-empty">Loading sessions...</p>`;
    return;
  }

  if (!readerState.chatSessions.length) {
    const view = currentChatSessionView();
    elements.chatSessionList.innerHTML = `<p class="ask-session-empty">${
      view === "trashed" ? "Trash is empty" : view === "archived" ? "Archive is empty" : "No sessions yet"
    }</p>`;
    return;
  }

  const scopedSessions = readerState.chatSessions.filter(chatSessionMatchesProject);
  if (!scopedSessions.length) {
    const view = currentChatSessionView();
    const scoped = Boolean(normalizeText(readerState.chatProjectScopeId));
    elements.chatSessionList.innerHTML = `<p class="ask-session-empty">${
      scoped
        ? "No sessions in this project"
        : view === "trashed" ? "Trash is empty" : view === "archived" ? "Archive is empty" : "No sessions yet"
    }</p>`;
    return;
  }

  const visibleSessions = scopedSessions.filter(chatSessionMatchesQuery);
  if (!visibleSessions.length) {
    const view = currentChatSessionView();
    elements.chatSessionList.innerHTML = `<p class="ask-session-empty">${
      view === "trashed" ? "No matching trashed sessions" : view === "archived" ? "No matching archived sessions" : "No matching sessions"
    }</p>`;
    return;
  }

  const view = currentChatSessionView();
  let openMenuSession = null;
  let openMenuRow = null;
  visibleSessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = "ask-session-row";
    row.classList.toggle("is-trashed", view === "trashed");
    row.classList.toggle("is-archived", view === "archived");
    row.classList.toggle("is-active", session.id === readerState.chatSessionId);
    row.classList.toggle("is-delete-confirming", session.id === readerState.confirmingDeleteSessionId);
    row.classList.toggle("is-menu-open", session.id === readerState.openSessionActionMenuId);

    if (session.id === readerState.renamingSessionId) {
      const form = document.createElement("form");
      form.className = "ask-session-rename-form";
      form.innerHTML = `
        <label class="ask-session-rename-card">
          <span class="sr-only">Session name</span>
          <input type="text" maxlength="80" value="${escapeHtml(session.title || "New chat")}" aria-label="Session name">
          <button class="ask-session-save" type="submit">Save</button>
        </label>
      `;
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        renameReaderChatSession(session.id, form.querySelector("input")?.value);
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
    sessionButton.disabled = view === "trashed";
    sessionButton.innerHTML = `
      <span class="ask-session-title">${escapeHtml(session.title || "New chat")}</span>
      <span class="ask-session-meta">${chatSessionMetaHtml(session, view)}</span>
    `;
    if (view === "active") {
      sessionButton.addEventListener("click", () => loadReaderChatSession(session.id));
    } else if (view === "archived") {
      sessionButton.addEventListener("click", () => loadReaderChatSession(session.id));
    }

    row.appendChild(sessionButton);
    appendSessionActionMenu(row, session);
    elements.chatSessionList.appendChild(row);
    if (session.id === readerState.openSessionActionMenuId) {
      openMenuSession = session;
      openMenuRow = row;
    }
  });
  appendSessionFloatingActionMenu(openMenuSession, openMenuRow, view);
}

function setChatSessionMenuOpen(open, view = currentChatSessionView()) {
  if (open) {
    closeReaderProjectMenu();
    closeReaderModelMenu();
    closeReaderToolMenu();
    readerState.chatProjectScopeId = "";
  }
  if (open) readerState.chatSessionView = ["active", "archived", "trashed"].includes(view) ? view : "active";
  readerState.chatSessionMenuOpen = open;
  if (elements.chatSessionPopover) elements.chatSessionPopover.hidden = !open;
  if (open) {
    readerState.chatSessionQuery = "";
    clearSessionRowState();
    renderChatSessionList();
    void fetchReaderChatSessions({ silent: true });
    requestAnimationFrame(() => elements.chatSessionSearch?.focus());
  } else {
    clearSessionRowState();
    renderChatSessionControls();
  }
}

async function openChatSessionView(view) {
  const nextView = ["active", "archived", "trashed"].includes(view) ? view : "active";
  if (readerState.chatSessionMenuOpen && currentChatSessionView() === nextView) {
    setChatSessionMenuOpen(false);
    return;
  }
  const changedView = currentChatSessionView() !== nextView;
  readerState.chatSessionView = nextView;
  readerState.chatSessionQuery = "";
  readerState.chatProjectScopeId = "";
  clearSessionRowState();
  if (changedView) readerState.chatSessions = [];
  setChatSessionMenuOpen(true, nextView);
}

async function fetchReaderChatSessions({ silent = false } = {}) {
  readerState.chatSessionsLoading = true;
  renderChatSessionList();
  try {
    const view = currentChatSessionView();
    const query = view === "active" ? "" : `?state=${encodeURIComponent(view)}`;
    const payload = await fetchAgentJson(`/api/agent/sessions${query}`);
    const sessions = normalizeReaderChatSessions(payload.sessions).map(enrichReaderSessionProject);
    if (currentChatSessionView() !== view) {
      readerState.chatSessionsLoading = false;
      return readerState.chatSessions;
    }
    const activeSession = readerState.currentChatSession?.id === getChatSessionId()
      ? readerState.currentChatSession
      : readerState.chatSessions.find((session) => session.id === getChatSessionId());
    readerState.chatSessions = sessions.filter((session) => session.state === view);
    if (activeSession && activeSession.id === getChatSessionId()) {
      readerState.currentChatSession = activeSession;
    }
    readerState.chatSessionsLoading = false;
    renderChatSessionList();
    if (readerState.chatProjectMenuOpen) renderReaderProjectControls();
    renderReaderModelControls();
    return readerState.chatSessions;
  } catch (error) {
    readerState.chatSessionsLoading = false;
    readerState.chatSessions = [];
    if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
    if (readerState.chatProjectMenuOpen) renderReaderProjectControls();
    renderReaderModelControls();
    return [];
  }
}

function clearCurrentReaderChatSession() {
  readerState.chatMessages = [];
  readerState.chatEditingIndex = -1;
  readerState.chatEditingText = "";
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
    const payload = await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(nextSessionId)}`);
    const session = upsertReaderChatSession(payload.session);
    readerState.chatMessages = normalizeApiChatMessages(payload.session?.messages);
    readerState.chatEditingIndex = -1;
    readerState.chatEditingText = "";
    setCurrentChatSessionId(session?.id || payload.session?.id || nextSessionId);
    setReaderChatError("");
    await resumeActiveChatRunForCurrentSession();
    renderReaderChatMessages({ scrollToBottom: true });
    renderReaderModelControls();
    scheduleReaderContextStatusRefresh();
    if (refreshList) await fetchReaderChatSessions({ silent: true });
    if (closeMenu) setChatSessionMenuOpen(false);
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
  }
}

async function resumeActiveChatRunForCurrentSession() {
  const activeRun = activeChatRunForSession();
  if (!activeRun) {
    syncCurrentChatRunState();
    renderReaderChatComposerState();
    return;
  }
  if (await recoverReaderChatFromSession({
    sessionId: activeRun.sessionId,
    latestUserText: activeRun.latestUserText || ""
  })) return;
  const runKey = chatSessionRunKey(activeRun.sessionId);
  if (activeRun.progress) {
    readerState.chatProgressRequestIdsBySession[runKey] = activeRun.requestId;
    setReaderChatProgress(activeRun.progress, runKey);
  } else {
    startReaderChatProgress(activeRun.requestId, runKey);
  }
  setReaderChatPending(true, runKey);
  scheduleReaderChatRecoveryPoll({
    sessionId: activeRun.sessionId,
    requestId: activeRun.requestId,
    latestUserText: activeRun.latestUserText || "",
    delay: 1200
  });
  syncCurrentChatRunState();
  renderReaderChatComposerState();
}

async function createReaderChatSession() {
  readerState.chatSessionView = "active";
  readerState.chatSessionQuery = "";
  clearSessionRowState();
  readerState.chatMessages = [];
  setCurrentChatSessionId("");
  setReaderChatError("");
  renderReaderChatMessages();
  await fetchReaderChatSessions({ silent: true });
  setChatSessionMenuOpen(false);
  elements.readerChatInput?.focus();
}

async function clearTrashedReaderChatSessions() {
  if (currentChatSessionView() !== "trashed" || !readerState.chatSessions.length) return;
  closeClearTrashDialog();
  try {
    const sessionIds = readerState.chatSessions.map((session) => normalizeText(session.id)).filter(Boolean);
    await Promise.all(sessionIds.map((sessionId) => fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE"
    })));
    if (sessionIds.includes(getChatSessionId())) clearCurrentReaderChatSession();
    clearSessionRowState();
    setReaderChatError("");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function renameReaderChatSession(sessionId, title) {
  const nextTitle = normalizeText(title);
  if (!sessionId || !nextTitle) return;
  try {
    await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(sessionId)}/rename`, {
      method: "POST",
      body: { title: nextTitle }
    });
    clearSessionRowState();
    setReaderChatError("");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function archiveReaderChatSession(sessionId) {
  if (!sessionId) return;
  try {
    await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(sessionId)}/state`, {
      method: "POST",
      body: { state: "archived" }
    });
    if (sessionId === getChatSessionId()) clearCurrentReaderChatSession();
    clearSessionRowState();
    setReaderChatError("");
    setReaderChatNotice("Moved to Archive");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function trashReaderChatSession(sessionId) {
  if (!sessionId) return;
  try {
    await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(sessionId)}/state`, {
      method: "POST",
      body: { state: "trashed" }
    });
    if (sessionId === getChatSessionId()) clearCurrentReaderChatSession();
    clearSessionRowState();
    setReaderChatError("");
    setReaderChatNotice("Moved to Trash");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function restoreReaderChatSession(sessionId) {
  if (!sessionId) return;
  try {
    await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(sessionId)}/state`, {
      method: "POST",
      body: { state: "active" }
    });
    clearSessionRowState();
    setReaderChatError("");
    setReaderChatNotice("Restored to Sessions");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function permanentlyDeleteReaderChatSession(sessionId) {
  if (!sessionId) return;
  try {
    await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE"
    });
    if (sessionId === getChatSessionId()) clearCurrentReaderChatSession();
    clearSessionRowState();
    setReaderChatError("");
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

async function initializeReaderChatSessions() {
  const preserveOpenView = readerState.chatSessionMenuOpen && currentChatSessionView() !== "active";
  if (!preserveOpenView) {
    readerState.chatSessionView = "active";
    readerState.chatSessionQuery = "";
  }
  const sessions = await fetchReaderChatSessions({ silent: true });
  if (readerState.chatSessionMenuOpen && currentChatSessionView() !== "active") return;
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
  return hasAssistantResponseAfterLatestUser(messages);
}

async function recoverReaderChatFromSession({ sessionId = "", latestUserText = "" } = {}) {
  const targetSessionId = normalizeText(sessionId) || getChatSessionId();
  if (!targetSessionId) return false;
  try {
    const payload = await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(targetSessionId)}`);
    const messages = normalizeApiChatMessages(payload.session?.messages);
    const expectedUserText = normalizeText(latestUserText);
    if (expectedUserText) {
      const latestUser = [...messages].reverse().find((message) => message?.role === "user");
      if (normalizeText(latestUser?.text || latestUser?.content) !== expectedUserText) return false;
    }
    if (!hasCompletedAssistantAfterLatestUser(messages)) {
      const session = upsertReaderChatSession(payload.session);
      const activeRun = normalizeActiveChatRun(session?.activeRun || payload.session?.activeRun || payload.session?.metadata?.activeRun);
      if (activeRun) {
        const runKey = chatSessionRunKey(targetSessionId);
        readerState.chatProgressRequestIdsBySession[runKey] = activeRun.requestId;
        if (activeRun.progress) setReaderChatProgress(activeRun.progress, runKey);
        setReaderChatPending(true, runKey);
      }
      return false;
    }
    const session = upsertReaderChatSession(payload.session);
    const recoveredSessionId = session?.id || payload.session?.id || targetSessionId;
    setCurrentChatSessionId(recoveredSessionId);
    readerState.chatMessages = messages;
    readerState.chatEditingIndex = -1;
    readerState.chatEditingText = "";
    clearReaderChatProgress(recoveredSessionId);
    setReaderChatPending(false, recoveredSessionId);
    forgetActiveChatRun(recoveredSessionId);
    setReaderChatError("");
    renderReaderChatMessages({ scrollToBottom: true });
    renderReaderModelControls();
    scheduleReaderContextStatusRefresh();
    return true;
  } catch (error) {
    console.debug("Could not recover chat session after request error.", error);
    return false;
  }
}
