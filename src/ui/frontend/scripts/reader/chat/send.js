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
  if (activeSessionId) {
    rememberActiveChatRun(activeSessionId, requestId, text);
    scheduleReaderChatRecoveryPoll({ sessionId: activeSessionId, requestId, latestUserText: text });
  }
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
          rememberActiveChatRun(startedSessionId, requestId, text);
          scheduleReaderChatRecoveryPoll({ sessionId: startedSessionId, requestId, latestUserText: text });
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
    const shouldMergeFinalProgress = Boolean(payload.cancelled || payload.error || !payload.completed);
    const finalProgress = shouldMergeFinalProgress
      ? normalizeChatProgress(readerState.chatProgressBySession[sessionRunKey])
      : null;
    setCurrentChatSessionId(payload.sessionId || session?.id || activeSessionId || requestSessionId);
    readerState.chatMessages = attachRunTraceFallback(
      normalizeApiChatMessages(payload.messages),
      payload,
      runStartedAtMs,
      finalProgress
    );
    if (!readerState.chatMessages.length && payload.message) {
      readerState.chatMessages = attachRunTraceFallback([
        { role: "user", text },
        normalizeApiChatMessage(payload.message)
      ].filter(Boolean), payload, runStartedAtMs, finalProgress);
    }
    setReaderChatError(payload.error && !payload.completed ? payload.error : "");
    const runChangedHtmlNote = Boolean(readerState.htmlNoteWriteRunsBySession[sessionRunKey]);
    if (runChangedHtmlNote || chatPayloadChangesHtmlNote(payload) || chatPayloadWritesHtmlNote(payload)) {
      scheduleReaderNoteRefresh();
    }
    if (chatPayloadChangesAnnotations(payload)) {
      await refreshAnnotationsFromServer({ preserveOpenEditor: true });
    }
    await fetchReaderChatSessions({ silent: true });
  } catch (error) {
    if (error?.name === "AbortError") {
      detachedByAbort = true;
      if (activeSessionId) rememberActiveChatRun(activeSessionId, requestId, text);
      return;
    }
    if (readerState.chatProgressRequestIdsBySession[sessionRunKey] !== requestId) return;
    if (isCurrentChatSessionRunKey(sessionRunKey) && await recoverReaderChatFromSession({
      sessionId: activeSessionId || requestSessionId,
      latestUserText: text
    })) return;
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
    delete readerState.htmlNoteWriteRunsBySession[sessionRunKey];
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
