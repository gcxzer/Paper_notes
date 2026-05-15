function startReaderUserMessageEdit(index) {
  const latest = latestReaderUserMessageIndex();
  if (isChatSessionPending() || index !== latest) return;
  const message = normalizeChatMessage(readerState.chatMessages[index]);
  if (message.role !== "user") return;
  readerState.chatEditingIndex = index;
  readerState.chatEditingText = message.text;
  preserveReaderChatScrollTop(() => renderReaderChatMessages({ preserveScrollTop: true }));
  requestAnimationFrame(() => {
    const input = elements.readerChatMessages?.querySelector(`[data-user-message-edit-input="${index}"]`);
    input?.focus?.({ preventScroll: true });
    input?.setSelectionRange?.(input.value.length, input.value.length);
  });
}

function cancelReaderUserMessageEdit() {
  readerState.chatEditingIndex = -1;
  readerState.chatEditingText = "";
  preserveReaderChatScrollTop(() => renderReaderChatMessages({ preserveScrollTop: true }));
}

function readerRequestOptions() {
  const provider = currentReaderProvider();
  const normalizedProvider = normalizeProviderName(provider);
  if (providerSupportsGptThinkMode(normalizedProvider)) {
    const thinkMode = currentGptThinkMode(currentReaderModel(), normalizedProvider);
    return {
      reasoning: thinkMode.enabled
        ? { effort: thinkMode.effort, summary: "auto" }
        : { effort: "none" },
    };
  }
  if (providerSupportsGeminiThinkMode(normalizedProvider)) {
    const model = currentReaderModel();
    const thinkMode = currentGeminiThinkMode(model);
    if (model === "gemini-3-pro-preview") {
      return { thinkingConfig: { thinkingLevel: thinkMode.effort, includeThoughts: true } };
    }
    if (!thinkMode.enabled) {
      return { thinkingConfig: { thinkingLevel: "minimal" } };
    }
    return { thinkingConfig: { thinkingLevel: thinkMode.effort, includeThoughts: true } };
  }
  if (providerSupportsAnthropicThinkMode(normalizedProvider, currentReaderModel())) {
    const thinkMode = currentAnthropicThinkMode(currentReaderModel());
    if (!thinkMode.enabled) {
      return { thinking: { type: "disabled" } };
    }
    return {
      thinking: { type: "adaptive", display: "summarized" },
      output_config: { effort: thinkMode.effort },
    };
  }
  if (normalizedProvider !== "deepseek") return {};
  const thinkMode = currentDeepSeekThinkMode();
  if (!thinkMode.enabled) {
    return { thinking: { type: "disabled" } };
  }
  return {
    reasoning_effort: thinkMode.effort,
    thinking: { type: "enabled" },
  };
}

function sessionWithRequestModelSelection(rawSession, requestBody, fallbackSessionId = "") {
  const session = rawSession && typeof rawSession === "object" && !Array.isArray(rawSession)
    ? { ...rawSession }
    : {};
  const sessionId = normalizeText(session.id || session.sessionId || fallbackSessionId || requestBody?.sessionId);
  if (sessionId) {
    session.id = session.id || sessionId;
    session.sessionId = session.sessionId || sessionId;
  }
  if (!normalizeProviderName(session.provider)) session.provider = requestBody?.provider || "";
  if (!normalizeText(session.model)) session.model = requestBody?.model || "";
  return session;
}

async function saveReaderUserMessageEdit(index) {
  if (isChatSessionPending() || index !== latestReaderUserMessageIndex()) return;
  const text = normalizeText(readerState.chatEditingText);
  if (!text) {
    setReaderChatError("Message cannot be empty.");
    return;
  }
  const message = normalizeChatMessage(readerState.chatMessages[index]);
  readerState.chatEditingIndex = -1;
  readerState.chatEditingText = "";
  await sendReaderChatMessage({
    text,
    attachments: message.attachments,
    generation: message.generation,
    selectedTextContext: message.selectedTextContext,
    editLatestUserMessage: true,
    replaceFromIndex: index
  });
}

function handleReaderChatMessageInput(event) {
  const input = event.target.closest("[data-user-message-edit-input]");
  if (!input) return;
  readerState.chatEditingIndex = Number(input.dataset.userMessageEditInput);
  readerState.chatEditingText = input.value;
}

function handleReaderChatMessageKeydown(event) {
  const input = event.target.closest("[data-user-message-edit-input]");
  if (!input || event.key !== "Enter" || event.shiftKey || event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return;
  event.preventDefault();
  input.closest("[data-user-message-edit-form]")?.requestSubmit();
}

function handleReaderChatMessageSubmit(event) {
  const form = event.target.closest("[data-user-message-edit-form]");
  if (!form) return;
  event.preventDefault();
  saveReaderUserMessageEdit(Number(form.dataset.userMessageEditForm))
    .catch((error) => setReaderChatError(error.message || GENERIC_AGENT_ERROR));
}

function handleReaderChatMessageAction(event) {
  const codeCopyButton = event.target.closest("[data-code-copy]");
  if (codeCopyButton) {
    const code = decodeURIComponent(codeCopyButton.dataset.codeCopy || "");
    copyTextToClipboard(code)
      .then(() => showCodeCopyFeedback(codeCopyButton))
      .catch((error) => {
        setReaderChatError("Could not copy code.");
        console.warn("Failed to copy code block.", error);
      });
    return;
  }
  const copyButton = event.target.closest("[data-user-message-copy]");
  if (copyButton) {
    const index = Number(copyButton.dataset.userMessageCopy);
    const message = normalizeChatMessage(readerState.chatMessages[index]);
    copyTextToClipboard(message.text)
      .then(() => showCopyFeedback(copyButton))
      .catch((error) => {
        setReaderChatError("Could not copy message.");
        console.warn("Failed to copy chat message.", error);
      });
    return;
  }
  const editButton = event.target.closest("[data-user-message-edit]");
  if (editButton) {
    startReaderUserMessageEdit(Number(editButton.dataset.userMessageEdit));
    return;
  }
  const cancelButton = event.target.closest("[data-user-message-edit-cancel]");
  if (cancelButton) {
    cancelReaderUserMessageEdit();
    return;
  }
  const runSummaryToggle = event.target.closest("[data-run-summary-toggle]");
  if (runSummaryToggle) {
    const summary = runSummaryToggle.closest(".ask-run-summary");
    const body = summary?.querySelector("[data-run-summary-body]");
    const expanded = runSummaryToggle.getAttribute("aria-expanded") === "true";
    runSummaryToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
    if (body) body.hidden = expanded;
    return;
  }
  const debugButton = event.target.closest("[data-debug-run-open]");
  if (debugButton) {
    void openReaderDebugDialog(debugButton.dataset.debugRunOpen);
    return;
  }
}

function handleReaderChatMessageDoubleClick(event) {
  const image = event.target.closest("[data-image-lightbox-url]");
  if (!image) return;
  openImageLightbox(image.dataset.imageLightboxUrl, image.dataset.imageLightboxTitle || image.alt || "Generated image");
}

function openImageLightbox(url, title = "Image") {
  const src = normalizeText(url);
  if (!src) return;
  closeImageLightbox();
  const overlay = document.createElement("div");
  overlay.className = "ask-image-lightbox";
  overlay.dataset.imageLightbox = "1";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", title || "Image preview");
  overlay.innerHTML = `
    <button class="ask-image-lightbox-close" type="button" aria-label="Close image preview">×</button>
    <img src="${escapeHtml(src)}" alt="${escapeHtml(title || "Image preview")}">
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.closest(".ask-image-lightbox-close")) {
      closeImageLightbox();
    }
  });
  document.body.append(overlay);
  document.addEventListener("keydown", handleImageLightboxKeydown);
}

function closeImageLightbox() {
  document.querySelector("[data-image-lightbox]")?.remove();
  document.removeEventListener("keydown", handleImageLightboxKeydown);
}

function handleImageLightboxKeydown(event) {
  if (event.key === "Escape") closeImageLightbox();
}

function showCodeCopyFeedback(button) {
  if (!button) return;
  const previous = button.textContent;
  button.textContent = "Copied";
  button.disabled = true;
  window.setTimeout(() => {
    button.textContent = previous || "Copy";
    button.disabled = false;
  }, 2500);
}

async function submitReaderChatStream(body, {
  signal,
  getSessionRunKey = () => chatSessionRunKey(body?.sessionId),
  onStart = null
} = {}) {
  let finalPayload = null;
  let streamStarted = false;
  let streamError = null;
  try {
    await fetchAgentEventStream("/api/chat/stream", {
      body,
      signal,
      onEvent: ({ event, data }) => {
        streamStarted = true;
        if (event === "start" && typeof onStart === "function") onStart(data || {});
        const sessionRunKey = getSessionRunKey();
        if (readerState.chatProgressRequestIdsBySession[sessionRunKey] !== body.requestId) return;
        if (data?.progress) {
          setReaderChatProgress(data.progress, sessionRunKey);
        }
        if (event === "work_trace_item" || event === "work_trace_delta") {
          appendReaderChatProgressWorkTrace(data, sessionRunKey);
        }
        if (event === "model_delta") {
          if (isCurrentChatSessionRunKey(sessionRunKey)) appendReaderStreamingDelta(data?.delta);
        } else if (event === "final") {
          finalPayload = data;
        } else if (event === "error") {
          streamError = new AgentRequestError(
            normalizeText(data?.error) || GENERIC_AGENT_ERROR,
            { code: normalizeText(data?.code), payload: data }
          );
          streamError.streamStarted = streamStarted;
        }
      }
    });
  } catch (error) {
    if (!finalPayload) throw error;
    console.debug("Chat stream ended after final payload with a recoverable close error.", error);
  }
  if (finalPayload) return finalPayload;
  if (streamError) throw streamError;
  const error = new AgentRequestError("Chat stream ended before a final response.", { code: "stream_incomplete" });
  error.streamStarted = streamStarted;
  throw error;
}

function hasSuccessfulAssistantAfterLatestReaderUser(messages = readerState.chatMessages) {
  const normalizedMessages = Array.isArray(messages) ? messages : [];
  const lastUserIndex = normalizedMessages.reduce((latest, message, index) => (
    message?.role === "user" ? index : latest
  ), -1);
  return normalizedMessages.slice(Math.max(0, lastUserIndex + 1)).some((message) => {
    const normalized = normalizeChatMessage(message);
    return normalized.role === "assistant" && normalizeText(normalized.text) && !normalized.error;
  });
}

async function sendReaderChatMessage(options = {}) {
  const editing = Boolean(options.editLatestUserMessage);
  const requestSessionId = getChatSessionId();
  let activeSessionId = requestSessionId;
  let sessionRunKey = chatSessionRunKey(requestSessionId);
  const text = normalizeText(editing ? options.text : elements.readerChatInput?.value);
  const allAttachments = normalizeAttachmentArtifacts(editing ? options.attachments : readerState.chatAttachments);
  const generationPayload = editing ? generationPayloadFromRequest(options.generation) : readerGenerationPayload();
  const editedSelectedTextContext = normalizeSelectedTextContext(options.selectedTextContext);
  const pendingSelectedTextContext = normalizeSelectedTextContext(readerState.pendingSelectedTextContext);
  const selectedTextContext = editing
    ? editedSelectedTextContext
    : normalizeSelectedTextContext(selectedPdfTextContextFromState() || pendingSelectedTextContext);
  const selectedPdfText = normalizeText(selectedTextContext?.text);
  const blockedAttachments = allAttachments.filter((attachment) => (
    attachment.uploadPending || attachment.uploadError || attachment.id.startsWith("local_")
  ));
  const attachments = allAttachments.filter((attachment) => !blockedAttachments.includes(attachment));
  if ((!text && !attachments.length) || isChatSessionPending(requestSessionId) || readerState.attachmentUploadPending || readerState.imageUploadPending) return;
  if (blockedAttachments.length) {
    setReaderChatError("Remove failed attachment uploads before sending.");
    return;
  }
  if (attachments.some(isImageArtifact) && !activeProviderSupportsImageInput()) {
    setReaderChatError(activeProviderImageInputUnsupportedMessage());
    return;
  }
  if (editing && !getChatSessionId()) {
    setReaderChatError("No saved session is available to edit.");
    return;
  }
  if (!editing && generationPayload.imageGeneration?.enabled && !activeProviderSupportsImageArtifacts()) {
    readerState.generationMode = "";
    renderAttachmentTray();
    renderReaderToolControls();
    setReaderChatError(activeProviderImageGenerationUnsupportedMessage());
    return;
  }
  const requestId = createRequestId();
  const context = readerChatContext();
  if (selectedPdfText) {
    context.selectionText = selectedPdfText;
    context.selection_text = selectedPdfText;
  }

  if (!editing) {
    elements.readerChatInput.value = "";
    resizeReaderChatInput();
    attachments.forEach(revokeAttachmentPreview);
    readerState.chatAttachments = [];
    clearReaderSelectedPdfText({ clearNativeSelection: Boolean(selectedPdfText) });
    readerState.generationMode = "";
    renderAttachmentTray();
    renderReaderToolControls();
  }
  setReaderChatError("");
  if (editing) {
    const replaceFromIndex = Number.isFinite(options.replaceFromIndex) ? options.replaceFromIndex : latestReaderUserMessageIndex();
    readerState.chatMessages = readerState.chatMessages.slice(0, Math.max(0, replaceFromIndex));
  }
  const generation = normalizeGenerationRequest(generationPayload);
  readerState.chatMessages.push({ role: "user", text, attachments, generation, selectedTextContext });
  renderReaderChatMessages({ forceScrollToBottom: true });
  setReaderChatPending(true, sessionRunKey);
  startReaderChatProgress(requestId, sessionRunKey);
  const abortController = new AbortController();
  readerState.chatAbortControllersBySession[sessionRunKey] = abortController;
  syncCurrentChatRunState();
  const runStartedAtMs = Date.now();
  let updatedVisibleSession = false;
  let detachedByAbort = false;

  try {
    const deepSeekThinkModeForRequest = currentDeepSeekThinkMode();
    const providerForRequest = currentReaderProvider();
    const normalizedProviderForRequest = normalizeProviderName(providerForRequest);
    const gptThinkModeForRequest = currentGptThinkMode(currentReaderModel(), normalizedProviderForRequest);
    const geminiThinkModeForRequest = currentGeminiThinkMode(currentReaderModel());
    const anthropicThinkModeForRequest = currentAnthropicThinkMode(currentReaderModel());
    const requestBody = {
      requestId,
      message: text,
      attachments: attachments.map((attachment) => ({ id: attachment.id })),
      sessionId: activeSessionId,
      editLatestUserMessage: editing,
      provider: providerForRequest,
      model: currentReaderModel() || undefined,
      requestOptions: readerRequestOptions(),
      writeToolMode: normalizeWriteToolMode(readerState.writeToolMode),
      ...readerToolSettingsPayload(),
      ...generationPayload,
      noteId: currentChatNoteId(),
      noteTitle: readerState.note?.title || "",
      currentPage: context.currentPage,
      selectionText: context.selectionText,
      visibleAnnotations: context.visibleAnnotations,
      context,
      metadata: {
        source: "reader",
        generation: generationPayload,
        ...(selectedTextContext ? { selectedTextContext } : {}),
        deepseekThinkMode: deepSeekThinkModeForRequest.enabled ? deepSeekThinkModeForRequest.effort : "off",
        ...(providerSupportsGptThinkMode(normalizedProviderForRequest)
          ? { gptThinkMode: gptThinkModeForRequest.enabled ? gptThinkModeForRequest.effort : "off" }
          : {}),
        ...(providerSupportsGeminiThinkMode(normalizedProviderForRequest)
          ? { geminiThinkMode: geminiThinkModeForRequest.enabled ? geminiThinkModeForRequest.effort : "off" }
          : {}),
        ...(providerSupportsAnthropicThinkMode(normalizedProviderForRequest, currentReaderModel())
          ? { anthropicThinkMode: anthropicThinkModeForRequest.enabled ? anthropicThinkModeForRequest.effort : "off" }
          : {}),
      }
    };
    if (!activeSessionId) writeStoredReaderModelSelection(requestBody.provider, requestBody.model);
    let payload;
    try {
      payload = await submitReaderChatStream(requestBody, {
        signal: abortController.signal,
        getSessionRunKey: () => sessionRunKey,
        onStart: (data) => {
          const startedSessionId = normalizeText(data?.sessionId);
          if (!startedSessionId) return;
          const previousRunKey = sessionRunKey;
          activeSessionId = startedSessionId;
          requestBody.sessionId = startedSessionId;
          sessionRunKey = migrateChatRunState(previousRunKey, startedSessionId);
          const startedSession = upsertReaderChatSession(
            sessionWithRequestModelSelection(data?.session, requestBody, startedSessionId)
          );
          setCurrentChatSessionId(startedSession?.id || startedSessionId);
          rememberActiveChatRun(startedSessionId, requestId);
        }
      });
    } catch (streamError) {
      if (streamError?.name === "AbortError" && readerState.chatProgressRequestIdsBySession[sessionRunKey] !== requestId) return;
      if (!shouldFallbackToReaderJsonChat(streamError)) throw streamError;
      payload = await fetchAgentJson("/api/chat", {
        method: "POST",
        body: requestBody
      });
    }
    if (readerState.chatProgressRequestIdsBySession[sessionRunKey] !== requestId) return;
    const session = upsertReaderChatSession(
      sessionWithRequestModelSelection(payload.session, requestBody, payload.sessionId || activeSessionId || requestSessionId)
    );
    if (!isCurrentChatSessionRunKey(sessionRunKey)) {
      setReaderChatError("");
      await fetchReaderChatSessions({ silent: true });
      return;
    }
    updatedVisibleSession = true;
    flushReaderStreamingRender();
    setCurrentChatSessionId(payload.sessionId || session?.id || activeSessionId || requestSessionId);
    readerState.chatMessages = attachRunTraceFallback(
      normalizeApiChatMessages(payload.messages),
      payload,
      runStartedAtMs
    );
    if (!readerState.chatMessages.length && payload.message) {
      readerState.chatMessages = attachRunTraceFallback([
        { role: "user", text },
        normalizeApiChatMessage(payload.message)
      ].filter(Boolean), payload, runStartedAtMs);
    }
    setReaderChatError(payload.error && !payload.completed ? payload.error : "");
    await loadReaderToolSnapshots({ silent: true });
    if (chatPayloadChangesAnnotations(payload)) {
      await refreshAnnotationsFromServer({ preserveOpenEditor: true });
    }
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    if (error?.name === "AbortError") {
      detachedByAbort = true;
      if (activeSessionId) rememberActiveChatRun(activeSessionId, requestId);
      return;
    }
    if (readerState.chatProgressRequestIdsBySession[sessionRunKey] !== requestId) return;
    if (isCurrentChatSessionRunKey(sessionRunKey) && await recoverReaderChatFromSession({ sessionId: activeSessionId || requestSessionId, requestId })) return;
    if (!isCurrentChatSessionRunKey(sessionRunKey)) {
      await fetchReaderChatSessions({ silent: true });
      return;
    }
    const message = error.message || GENERIC_AGENT_ERROR;
    setReaderChatError("");
    readerState.chatMessages.push({
      role: "assistant",
      text: message,
      error: true
    });
  } finally {
    readerState.pendingSelectedTextContext = null;
    if (detachedByAbort) return;
    if (readerState.chatProgressRequestIdsBySession[sessionRunKey] === requestId) {
      const shouldUpdateVisible = updatedVisibleSession || isCurrentChatSessionRunKey(sessionRunKey);
      if (!editing && shouldUpdateVisible) {
        renderAttachmentTray();
      }
      if (readerState.chatAbortControllersBySession[sessionRunKey] === abortController) {
        delete readerState.chatAbortControllersBySession[sessionRunKey];
      }
      clearReaderChatProgress(sessionRunKey);
      setReaderChatPending(false, sessionRunKey);
      if (activeSessionId) forgetActiveChatRun(activeSessionId);
      if (shouldUpdateVisible) {
        renderReaderChatMessages({ scrollToBottom: true });
        if (hasSuccessfulAssistantAfterLatestReaderUser()) setReaderChatError("");
        scheduleReaderContextStatusRefresh();
        elements.readerChatInput?.focus();
      } else {
        await fetchReaderChatSessions({ silent: true });
      }
    } else {
      if (readerState.chatAbortControllersBySession[sessionRunKey] === abortController) {
        delete readerState.chatAbortControllersBySession[sessionRunKey];
      }
      if (isCurrentChatSessionRunKey(sessionRunKey)) renderReaderChatMessages({ scrollToBottom: true });
    }
  }
}

function initializeReaderChat() {
  initializeSavedPrompts();
  renderReaderChatMessages({ preserveScrollTop: true });
  renderReaderModelControls();
  renderReaderContextControls();
  renderReaderToolControls();
  renderAttachmentTray();
  void loadReaderModelCatalog({ silent: true });
  scheduleReaderContextStatusRefresh(300);
  elements.readerChatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    sendReaderChatMessage();
  });
  elements.readerChatMessages?.addEventListener("click", handleChatSourceClick);
  elements.readerChatMessages?.addEventListener("click", handleNoteEditDraftClick);
  elements.readerChatMessages?.addEventListener("click", handleChatProgressClick);
  elements.readerChatMessages?.addEventListener("click", handleReaderChatMessageAction);
  elements.readerChatMessages?.addEventListener("dblclick", handleReaderChatMessageDoubleClick);
  elements.readerChatMessages?.addEventListener("input", handleReaderChatMessageInput);
  elements.readerChatMessages?.addEventListener("keydown", handleReaderChatMessageKeydown);
  elements.readerChatMessages?.addEventListener("submit", handleReaderChatMessageSubmit);
  elements.readerChatMessages?.addEventListener("click", (event) => {
    handleToolActivityClick(event).catch((error) => setReaderChatError(error.message || GENERIC_AGENT_ERROR));
  });
  elements.readerCloseDebugDialog?.addEventListener("click", closeReaderDebugDialog);
  elements.readerRefreshDebugRuns?.addEventListener("click", () => {
    void loadReaderDebugRuns();
  });
  elements.readerCleanupDebugRuns?.addEventListener("click", () => {
    setReaderDebugCleanupMenuOpen(!readerState.debugCleanupMenuOpen);
  });
  elements.readerCleanupDebugMenu?.addEventListener("click", (event) => {
    const option = event.target.closest("[data-debug-cleanup-days]");
    if (!option) return;
    const days = Number(option.dataset.debugCleanupDays || 30);
    void cleanupReaderDebugRunsAction(Number.isFinite(days) ? days : 30);
  });
  elements.readerCopyDebugRun?.addEventListener("click", () => {
    void copyActiveReaderDebugRun();
  });
  elements.readerDebugRunList?.addEventListener("click", (event) => {
    const row = event.target.closest("[data-debug-run-id]");
    if (row) void loadReaderDebugRunDetail(row.dataset.debugRunId);
  });
  elements.readerDebugDialog?.addEventListener("wheel", handleReaderDebugWheel, { passive: false });
  elements.readerModelMenuButton?.addEventListener("click", () => {
    setReaderModelMenuOpen(!readerState.modelMenuOpen);
  });
  elements.readerToolMenuButton?.addEventListener("click", () => {
    setReaderToolMenuOpen(!readerState.toolMenuOpen);
  });
  elements.readerToolPopover?.addEventListener("click", handleReaderToolPopoverClick);
  elements.savedPromptForm?.addEventListener("submit", handleSavedPromptSubmit);
  elements.savedPromptTitleInput?.addEventListener("input", updateSavedPromptSubmitState);
  elements.savedPromptContentInput?.addEventListener("input", updateSavedPromptSubmitState);
  elements.savedPromptIconButton?.addEventListener("click", toggleSavedPromptIconPanel);
  elements.savedPromptIconGrid?.addEventListener("click", handleSavedPromptIconGridClick);
  elements.savedPromptIconSearch?.addEventListener("input", handleSavedPromptIconSearch);
  elements.savedPromptIconPanel?.addEventListener("click", handleSavedPromptIconPanelClick);
  elements.savedPromptToolButton?.addEventListener("click", toggleSavedPromptToolPanel);
  elements.savedPromptToolChip?.addEventListener("click", clearSavedPromptToolSelection);
  elements.savedPromptToolPanel?.addEventListener("click", handleSavedPromptToolPanelClick);
  elements.closeSavedPromptDialog?.addEventListener("click", closeSavedPromptDialog);
  elements.cancelSavedPromptDialog?.addEventListener("click", closeSavedPromptDialog);
  elements.closeSavedPromptManageDialog?.addEventListener("click", closeSavedPromptManageDialog);
  elements.cancelSavedPromptDelete?.addEventListener("click", closeSavedPromptDeleteDialog);
  elements.confirmSavedPromptDelete?.addEventListener("click", confirmSavedPromptDelete);
  elements.savedPromptManageList?.addEventListener("click", handleSavedPromptManageClick);
  elements.readerAttachmentInput?.addEventListener("change", (event) => {
    closeReaderToolMenu();
    handleReaderAttachmentFiles(event.target?.files);
  });
  elements.readerChatInput?.addEventListener("paste", handleReaderImagePaste);
  elements.readerChatInput?.addEventListener("input", resizeReaderChatInput);
  elements.askPane?.addEventListener("pointerdown", preserveReaderPdfSelectionForAskPane, true);
  elements.sendReaderChat?.addEventListener("pointerdown", snapshotReaderSelectedPdfTextForSubmit);
  elements.readerChatInput?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return;
    event.preventDefault();
    elements.readerChatForm?.requestSubmit();
  });
  elements.readerChatForm?.addEventListener("paste", handleReaderImagePaste);
  elements.readerAttachmentTray?.addEventListener("click", handleAttachmentTrayClick);
  elements.readerModelBack?.addEventListener("click", showReaderProviderMenu);
  elements.readerModelProvider?.addEventListener("click", closeReaderModelMenu);
  elements.readerContextButton?.addEventListener("click", () => {
    setReaderContextPopoverOpen(!readerState.contextPopoverOpen);
  });
  elements.readerContextPopover?.addEventListener("input", (event) => {
    if (event.target?.id === "readerContextCompactFocus") {
      readerState.contextCompactFocus = event.target.value;
    }
  });
  elements.readerContextPopover?.addEventListener("click", (event) => {
    const action = event.target?.closest?.("[data-context-action]")?.dataset?.contextAction;
    if (action === "compact") {
      compactReaderContext();
    }
  });
  elements.clearTrashSessions?.addEventListener("click", openClearTrashDialog);
  elements.newChatSession?.addEventListener("click", createReaderChatSession);
  elements.cancelClearTrash?.addEventListener("click", closeClearTrashDialog);
  elements.confirmClearTrash?.addEventListener("click", clearTrashedReaderChatSessions);
  elements.chatSessionViewButtons?.forEach((button) => {
    button.addEventListener("click", () => {
      openChatSessionView(button.dataset.sessionView);
    });
  });
  elements.chatSessionSearch?.addEventListener("input", (event) => {
    readerState.chatSessionQuery = event.target.value;
    clearSessionRowState();
    renderChatSessionList();
  });
  document.addEventListener("pointerdown", (event) => {
    if (
      readerState.chatSessionMenuOpen
      && !elements.chatSessionPopover?.contains(event.target)
      && !elements.chatSessionViewButtons?.some((button) => button.contains(event.target))
      && !elements.clearTrashDialog?.contains(event.target)
    ) {
      clearSessionRowState();
      setChatSessionMenuOpen(false);
    }
    if (
      readerState.modelMenuOpen
      && !elements.readerModelPopover?.contains(event.target)
      && !elements.readerModelMenuButton?.contains(event.target)
    ) {
      closeReaderModelMenu();
    }
    if (
      readerState.contextPopoverOpen
      && !elements.readerContextPopover?.contains(event.target)
      && !elements.readerContextButton?.contains(event.target)
    ) {
      closeReaderContextPopover();
    }
    if (
      readerState.toolMenuOpen
      && !elements.readerToolPopover?.contains(event.target)
      && !elements.readerToolMenuButton?.contains(event.target)
    ) {
      closeReaderToolMenu();
    }
    if (!event.target.closest(".debug-cleanup-control")) {
      setReaderDebugCleanupMenuOpen(false);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (readerState.chatSessionMenuOpen) setChatSessionMenuOpen(false);
    if (readerState.modelMenuOpen) closeReaderModelMenu();
    if (readerState.contextPopoverOpen) closeReaderContextPopover();
    if (readerState.toolMenuOpen) closeReaderToolMenu();
    if (readerState.debugCleanupMenuOpen) setReaderDebugCleanupMenuOpen(false);
  });
  resizeReaderChatInput();
}
