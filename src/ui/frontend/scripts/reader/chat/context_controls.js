function readerChatContext() {
  const note = readerState.note;
  const position = currentPdfScrollPosition();
  const currentPage = position?.page || "";
  const selectionText = currentReaderSelectedPdfText()
    || normalizeReaderSelectedPdfText(globalThis.getSelection?.().toString()).slice(0, 2000);
  return {
    selectedNoteId: note?.id || "",
    selectedNoteTitle: note?.title || "",
    selectedCategoryName: readerState.library && note ? getCollectionPath(readerState.library, note.categoryId) : "",
    currentPdfPage: currentPage,
    currentPage,
    selectionText,
    visibleAnnotations: pdfState.annotations
      .filter((annotation) => !currentPage || annotation.page === currentPage)
      .slice(0, 12)
      .map((annotation) => ({
        id: annotation.id,
        page: annotation.page,
        comment: annotation.comment || "",
        quote: annotation.quote || ""
      }))
  };
}

function emptyReaderContextStatus() {
  return normalizeContextStatus({
    sessionId: getChatSessionId(),
    provider: currentReaderProvider(),
    model: currentReaderModel()
  });
}

function currentReaderContextStatus() {
  const sessionId = getChatSessionId();
  const status = readerState.contextStatus ? normalizeContextStatus(readerState.contextStatus) : emptyReaderContextStatus();
  if (!sessionId) return status.sessionId ? emptyReaderContextStatus() : status;
  return status.sessionId === sessionId ? status : emptyReaderContextStatus();
}

function resetReaderContextStatus({ refresh = false } = {}) {
  readerState.contextStatus = null;
  readerState.contextCompactStatus = "";
  renderReaderContextControls();
  if (refresh && getChatSessionId()) scheduleReaderContextStatusRefresh(0);
}

function renderReaderContextControls() {
  const status = currentReaderContextStatus();
  const percent = Math.min(100, Math.max(0, status.percentFull ?? status.estimatedPercent ?? 0));
  const provider = currentReaderProvider();
  const model = currentReaderModel();
  const providerName = providerDisplayName(status.provider || provider);
  const modelLabel = modelDisplayLabel(status.model || model, status.provider || provider, "label") || status.model || model || "Model";
  const tokenPair = status.contextLength ? `${formatTokenCount(status.tokensUsed)} / ${formatTokenCount(status.contextLength)}` : "";
  const contextHeadline = readerState.contextStatusLoading
    ? "Checking..."
    : `${percent}% full${tokenPair ? ` · ${tokenPair}` : ""}`;
  const contextHint = status.contextLength ? "" : "No saved chat context";
  const sessionId = getChatSessionId();
  const pending = isChatSessionPending(sessionId);
  const canCompact = Boolean(sessionId && status.compactionEnabled && !pending && !readerState.contextCompacting);
  const compactTitle = pending
    ? "Wait for current answer to finish"
    : readerState.contextCompacting
      ? "Compacting already in progress"
      : status.compactionEnabled
        ? "Compact now"
        : "Context compaction unavailable";
  const compressedLine = status.compressionCount
    ? `${status.compressionCount} compacted${status.lastCompressedAt ? ` · ${formatChatSessionTime(status.lastCompressedAt)}` : ""}`
    : "No compaction yet";
  const repeatedCompressionWarning = status.compressionCount >= 2
    ? `Session compacted ${status.compressionCount} times\nAccuracy may degrade. Consider starting a new chat.`
    : "";
  const warningText = status.lastCompressionError
    || (status.fallbackUsed ? "Fallback marker was used during the last compaction." : "")
    || repeatedCompressionWarning;

  if (elements.readerContextButton) {
    elements.readerContextButton.style.setProperty("--context-percent", String(percent));
    elements.readerContextButton.classList.toggle("is-loading", readerState.contextStatusLoading);
    elements.readerContextButton.classList.toggle("is-ready", Boolean(status.compactionReady));
    elements.readerContextButton.title = contextHint ? `${contextHeadline} · ${contextHint}` : contextHeadline;
    elements.readerContextButton.setAttribute("aria-expanded", String(readerState.contextPopoverOpen));
  }

  if (!elements.readerContextPopover) return;
  elements.readerContextPopover.hidden = !readerState.contextPopoverOpen;
  if (!readerState.contextPopoverOpen) return;
  elements.readerContextPopover.innerHTML = `
    <div class="ask-context-title">Context window</div>
    <div class="ask-context-percent">${escapeHtml(contextHeadline)}</div>
    ${contextHint ? `<div class="ask-context-tokens">${escapeHtml(contextHint)}</div>` : ""}
    <div class="ask-context-model">${escapeHtml(`${providerName} · ${modelLabel}`)}</div>
    <div class="ask-context-grid">
      <span>Messages</span><strong>${escapeHtml(String(status.messageCount))}</strong>
      <span class="ask-context-help" tabindex="0" aria-label="Shows whether earlier chat has been summarized for this session." data-tooltip="When a chat gets long, earlier messages can be summarized so the model can keep using them. This shows whether that summary exists.">Summary</span><strong>${escapeHtml(status.summaryAvailable ? "available" : "not yet")}</strong>
      <span>Compactions</span><strong>${escapeHtml(compressedLine)}</strong>
    </div>
    ${warningText ? `<div class="ask-context-warning">${escapeHtml(warningText).replace(/\n/g, "<br>")}</div>` : ""}
    ${readerState.contextCompactStatus ? `<div class="ask-context-status">${escapeHtml(readerState.contextCompactStatus)}</div>` : ""}
    <div class="ask-context-actions">
      <input class="ask-context-focus" id="readerContextCompactFocus" type="text" value="${escapeHtml(readerState.contextCompactFocus)}" placeholder="Focus" aria-label="Compaction focus">
      <button class="ask-context-compact" type="button" data-context-action="compact" title="${escapeHtml(compactTitle)}" ${canCompact ? "" : "disabled"}>${escapeHtml(readerState.contextCompacting ? "Compacting" : "Compact now")}</button>
    </div>
  `;
}

function setReaderContextPopoverOpen(open) {
  readerState.contextPopoverOpen = Boolean(open);
  if (readerState.contextPopoverOpen) {
    if (typeof setChatSessionMenuOpen === "function") setChatSessionMenuOpen(false);
    if (typeof closeReaderProjectMenu === "function") closeReaderProjectMenu();
    if (typeof closeReaderModelMenu === "function") closeReaderModelMenu();
    if (typeof closeReaderToolMenu === "function") closeReaderToolMenu();
    void loadReaderContextStatus({ silent: true });
  }
  renderReaderContextControls();
}

function closeReaderContextPopover() {
  readerState.contextPopoverOpen = false;
  renderReaderContextControls();
}

function scheduleReaderContextStatusRefresh(delay = 160) {
  if (readerState.contextRefreshTimer) {
    clearTimeout(readerState.contextRefreshTimer);
  }
  readerState.contextRefreshTimer = setTimeout(() => {
    readerState.contextRefreshTimer = 0;
    void loadReaderContextStatus({ silent: true });
  }, delay);
}

async function loadReaderContextStatus({ silent = false } = {}) {
  const sessionId = getChatSessionId();
  if (!sessionId) {
    readerState.contextStatus = normalizeContextStatus({});
    readerState.contextStatusLoading = false;
    renderReaderContextControls();
    return;
  }
  const params = new URLSearchParams();
  const provider = currentReaderProvider();
  const model = currentReaderModel();
  const noteId = currentChatNoteId();
  const context = readerChatContext();
  params.set("sessionId", sessionId);
  if (provider) params.set("provider", provider);
  if (model) params.set("model", model);
  if (noteId) params.set("noteId", noteId);
  if (readerState.note?.title) params.set("noteTitle", readerState.note.title);
  if (context.currentPage) params.set("currentPage", String(context.currentPage));

  readerState.contextStatusLoading = true;
  renderReaderContextControls();
  try {
    const payload = await fetchAgentJson(`/api/chat/context?${params.toString()}`);
    readerState.contextStatus = normalizeContextStatus(payload);
  } catch (error) {
    readerState.contextStatus = null;
    if (readerState.contextPopoverOpen) {
      readerState.contextCompactStatus = sanitizeVisibleAgentError(error.message || "Could not load context.");
    }
    if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
  } finally {
    readerState.contextStatusLoading = false;
    renderReaderContextControls();
  }
}

async function compactReaderContext() {
  const sessionId = getChatSessionId();
  if (!sessionId || isChatSessionPending(sessionId) || readerState.contextCompacting) return;
  const context = readerChatContext();
  readerState.contextCompacting = true;
  readerState.contextCompactStatus = "Compacting context...";
  renderReaderContextControls();
  renderReaderChatMessages({ scrollToBottom: true });
  try {
    const payload = await fetchAgentJson("/api/chat/compress", {
      method: "POST",
      body: {
        sessionId,
        focus: readerState.contextCompactFocus,
        provider: currentReaderProvider(),
        model: currentReaderModel(),
        requestOptions: readerRequestOptions(),
        ...readerToolSettingsPayload(),
        noteId: currentChatNoteId(),
        noteTitle: readerState.note?.title || "",
        currentPage: context.currentPage,
        selectionText: context.selectionText,
        context
      }
    });
    readerState.contextStatus = normalizeContextStatus(payload);
    readerState.contextCompactStatus = payload?.compressed ? "Context compacted." : "Nothing to compact yet.";
    if (payload?.compressed) {
      const marker = normalizeApiChatMessage(payload?.message);
      if (marker) {
        readerState.chatMessages = [...readerState.chatMessages, marker];
      } else {
        await recoverReaderChatFromSession({ sessionId });
      }
    }
    setReaderChatError("");
    if (typeof fetchReaderChatSessions === "function") await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    readerState.contextCompactStatus = sanitizeVisibleAgentError(error.message || "Could not compact context.");
  } finally {
    readerState.contextCompacting = false;
    renderReaderContextControls();
    renderReaderChatMessages({ scrollToBottom: true });
  }
}
