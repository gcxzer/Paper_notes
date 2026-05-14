function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")));
    reader.addEventListener("error", () => reject(reader.error || new Error("Could not read attachment.")));
    reader.readAsDataURL(file);
  });
}

function createLocalAttachment(file) {
  const image = isImageFile(file);
  const name = normalizeText(file?.name) || (image ? `pasted-image-${Date.now()}.png` : `attachment-${Date.now()}`);
  const previewUrl = image ? URL.createObjectURL(file) : "";
  return {
    id: `local_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    kind: image ? "image" : localFileKind(file),
    source: "local",
    mimeType: normalizeText(file?.type) || mimeTypeForFileName(name),
    fileName: name,
    size: Number(file?.size) || 0,
    url: previewUrl,
    localPreviewUrl: previewUrl,
    uploadPending: true
  };
}

function revokeAttachmentPreview(attachment) {
  const previewUrl = normalizeText(attachment?.localPreviewUrl);
  if (!previewUrl || !previewUrl.startsWith("blob:")) return;
  try {
    URL.revokeObjectURL(previewUrl);
  } catch (error) {
    console.warn("Failed to revoke image preview URL.", error);
  }
}

function isImageFile(file) {
  return Boolean(file && typeof file.type === "string" && file.type.startsWith("image/"));
}

function isSupportedAttachmentFile(file) {
  return Boolean(file);
}

function mimeTypeForFileName(fileName) {
  const name = normalizeText(fileName).toLowerCase();
  if (name.endsWith(".pdf")) return "application/pdf";
  if (name.endsWith(".md") || name.endsWith(".markdown")) return "text/markdown";
  if (name.endsWith(".txt")) return "text/plain";
  if (name.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  if (name.endsWith(".pptx")) return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  if (name.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  return "";
}

function localFileKind(file) {
  const mimeType = normalizeText(file?.type || mimeTypeForFileName(file?.name)).toLowerCase();
  const name = normalizeText(file?.name).toLowerCase();
  if (mimeType === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (name.endsWith(".docx")) return "document";
  if (name.endsWith(".pptx")) return "presentation";
  if (name.endsWith(".xlsx")) return "spreadsheet";
  if (mimeType.startsWith("text/") || name.endsWith(".txt") || name.endsWith(".md") || name.endsWith(".markdown")) return "text";
  return "file";
}

async function uploadReaderAttachmentFile(file) {
  const data = await readFileAsDataUrl(file);
  const payload = await fetchAgentJson("/api/chat/attachments", {
    method: "POST",
    body: {
      data,
      fileName: file?.name || "attachment",
      mimeType: file?.type || mimeTypeForFileName(file?.name),
      sessionId: getChatSessionId(),
      requestId: createRequestId(),
      metadata: { source: "reader_upload" }
    }
  });
  return normalizeAttachmentArtifacts([payload.artifact])[0];
}

async function handleReaderAttachmentFiles(files) {
  const selectedFiles = Array.from(files || []).filter(isSupportedAttachmentFile);
  if (!selectedFiles.length) return;
  readerState.imageUploadPending = true;
  readerState.attachmentUploadPending = true;
  const localAttachments = selectedFiles.map(createLocalAttachment);
  readerState.chatAttachments.push(...localAttachments);
  renderAttachmentTray();
  renderReaderToolControls();
  try {
    for (const [index, file] of selectedFiles.entries()) {
      const localAttachment = localAttachments[index];
      const artifact = await uploadReaderAttachmentFile(file);
      const currentIndex = readerState.chatAttachments.findIndex((entry) => entry.id === localAttachment.id);
      if (currentIndex === -1) {
        revokeAttachmentPreview(localAttachment);
        continue;
      }
      if (artifact) {
        revokeAttachmentPreview(localAttachment);
        readerState.chatAttachments.splice(currentIndex, 1, artifact);
        renderAttachmentTray();
        renderReaderToolControls();
      }
    }
    setReaderChatError("");
  } catch (error) {
    for (const localAttachment of localAttachments) {
      const current = readerState.chatAttachments.find((entry) => entry.id === localAttachment.id);
      if (current) {
        current.uploadPending = false;
        current.uploadError = error.message || "Upload failed.";
      }
    }
    setReaderChatError(error.message || "Could not upload attachment.");
  } finally {
    readerState.imageUploadPending = false;
    readerState.attachmentUploadPending = false;
    if (elements.readerAttachmentInput) elements.readerAttachmentInput.value = "";
    renderAttachmentTray();
    renderReaderToolControls();
  }
}

function handleReaderImageFiles(files) {
  return handleReaderAttachmentFiles(files);
}

function handleAttachmentTrayClick(event) {
  const generationRemove = event.target.closest("[data-generation-mode-remove]");
  if (generationRemove) {
    event.preventDefault();
    clearReaderGenerationMode();
    return;
  }

  const removeButton = event.target.closest("[data-attachment-remove]");
  if (removeButton) {
    event.preventDefault();
    const targetId = normalizeText(removeButton.dataset.attachmentRemove);
    const target = readerState.chatAttachments.find((artifact) => artifact.id === targetId);
    revokeAttachmentPreview(target);
    readerState.chatAttachments = readerState.chatAttachments.filter((artifact) => artifact.id !== targetId);
    renderAttachmentTray();
    renderReaderToolControls();
    return;
  }
}

function imageFilesFromClipboard(event) {
  const data = event?.clipboardData;
  if (!data) return [];
  const files = Array.from(data.files || []).filter(isImageFile);
  if (files.length) return files;
  return Array.from(data.items || [])
    .filter((item) => item?.kind === "file" && String(item.type || "").startsWith("image/"))
    .map((item) => item.getAsFile?.())
    .filter(isImageFile);
}

function handleReaderImagePaste(event) {
  const files = imageFilesFromClipboard(event);
  if (!files.length) return;
  event.preventDefault();
  event.stopPropagation();
  handleReaderAttachmentFiles(files);
}

function renderReaderChatComposerState() {
  const currentPending = isChatSessionPending();
  if (elements.readerChatInput) elements.readerChatInput.disabled = currentPending;
  if (elements.readerToolMenuButton) elements.readerToolMenuButton.disabled = currentPending;
  if (elements.sendReaderChat) {
    elements.sendReaderChat.disabled = currentPending;
    elements.sendReaderChat.textContent = currentPending ? "Sending" : "Send";
  }
}

function setReaderChatPending(pending, sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  if (pending) {
    readerState.chatPendingBySession[runKey] = true;
  } else {
    delete readerState.chatPendingBySession[runKey];
  }
  syncCurrentChatRunState();
  renderReaderChatComposerState();
  renderReaderModelControls();
  renderReaderChatMessages({ scrollToBottom: isChatSessionPending() });
}

function setReaderChatProgress(progress, sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  const normalized = normalizeChatProgress(progress);
  if (normalized) {
    readerState.chatProgressBySession[runKey] = normalized;
  } else {
    delete readerState.chatProgressBySession[runKey];
  }
  if (isCurrentChatSessionRunKey(runKey)) {
    syncCurrentChatRunState();
    renderReaderChatMessages({ scrollToBottom: Boolean(readerState.chatPending) });
  }
}

function clearReaderChatProgress(sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  delete readerState.chatProgressBySession[runKey];
  delete readerState.chatProgressRequestIdsBySession[runKey];
  const timer = readerState.chatProgressTimersBySession[runKey];
  if (timer) {
    clearInterval(timer);
    delete readerState.chatProgressTimersBySession[runKey];
  }
  if (isCurrentChatSessionRunKey(runKey)) syncCurrentChatRunState();
}

function resizeReaderChatInput() {
  const input = elements.readerChatInput;
  if (!input) return;
  const computed = window.getComputedStyle(input);
  const maxHeight = Number.parseFloat(computed.maxHeight) || 148;
  input.style.height = "auto";
  const nextHeight = Math.min(input.scrollHeight, maxHeight);
  input.style.height = `${nextHeight}px`;
  input.classList.toggle("is-scrollable", input.scrollHeight > maxHeight + 1);
}

async function fetchReaderChatProgress(requestId, sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  if (!requestId || readerState.chatProgressRequestIdsBySession[runKey] !== requestId) return;
  try {
    const progress = await fetchAgentJson(`/api/chat/progress?id=${encodeURIComponent(requestId)}`);
    if (readerState.chatProgressRequestIdsBySession[runKey] !== requestId) return;
    if (progress.status === "unknown") return;
    setReaderChatProgress(progress, runKey);
    if (isTerminalChatProgressStatus(progress.status) && readerState.chatProgressTimersBySession[runKey]) {
      clearInterval(readerState.chatProgressTimersBySession[runKey]);
      delete readerState.chatProgressTimersBySession[runKey];
      delete readerState.chatAbortControllersBySession[runKey];
      setReaderChatPending(false, runKey);
      if (normalizeText(sessionId) && sessionId !== "__draft_chat_session__") {
        forgetActiveChatRun(sessionId);
        if (isCurrentChatSessionRunKey(runKey)) {
          await loadReaderChatSession(sessionId, { closeMenu: false, refreshList: true });
        }
      }
    }
  } catch (error) {
    console.warn("Failed to fetch chat progress.", error);
  }
}

function startReaderChatProgress(requestId, sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  clearReaderChatProgress(runKey);
  readerState.chatProgressRequestIdsBySession[runKey] = requestId;
  setReaderChatProgress({
    requestId,
    status: "running",
    stage: "thinking",
    detail: "Thinking with local paper context...",
    events: []
  }, runKey);
  readerState.chatProgressTimersBySession[runKey] = setInterval(() => fetchReaderChatProgress(requestId, runKey), 800);
  fetchReaderChatProgress(requestId, runKey);
}

async function cancelReaderChatRequest() {
  const runKey = chatSessionRunKey();
  const requestId = readerState.chatProgressRequestIdsBySession[runKey];
  if (!requestId) return;
  const progress = normalizeChatProgress(readerState.chatProgressBySession[runKey]) || { events: [] };
  readerState.chatAbortControllersBySession[runKey]?.abort();
  delete readerState.chatAbortControllersBySession[runKey];
  if (readerState.chatProgressTimersBySession[runKey]) {
    clearInterval(readerState.chatProgressTimersBySession[runKey]);
    delete readerState.chatProgressTimersBySession[runKey];
  }
  const cancelledProgress = normalizeChatProgress({
    ...progress,
    requestId,
    status: "cancelled",
    stage: "cancelled",
    detail: "Agent run cancelled.",
    events: [
      ...progress.events,
      { stage: "cancelled", detail: "Agent run cancelled." }
    ]
  });
  const cancelledTrace = runTraceFromProgress(cancelledProgress);
  if (cancelledTrace) {
    const draft = latestReaderStreamingAssistantMessage() || ensureReaderStreamingAssistantMessage();
    draft.streaming = false;
    draft.runTrace = cancelledTrace;
  }
  flushReaderStreamingRender();
  clearReaderChatProgress(runKey);
  setReaderChatPending(false, runKey);
  forgetActiveChatRun(getChatSessionId());
  renderReaderChatMessages();

  try {
    await fetchAgentJson("/api/chat/cancel", {
      method: "POST",
      body: {
        requestId,
        sessionId: getChatSessionId(),
        reason: "reader_cancelled"
      }
    });
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
  } finally {
    elements.readerChatInput?.focus();
  }
}

function readerChatContext() {
  const note = readerState.note;
  const position = currentPdfScrollPosition();
  const currentPage = position?.page || "";
  const selectionText = normalizeText(globalThis.getSelection?.().toString()).slice(0, 2000);
  return {
    selectedNoteId: note?.id || "",
    selectedNoteTitle: note?.title || "",
    selectedCategoryName: readerState.library && note ? getCollectionPath(readerState.library, note.categoryId) : "",
    currentPdfPage: currentPage,
    currentPage,
    selectionText,
    selection_text: selectionText,
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

function renderReaderContextControls() {
  const status = readerState.contextStatus || normalizeContextStatus({});
  const percent = Math.min(100, Math.max(0, status.percentFull || 0));
  const compactPercent = Math.min(100, Math.max(0, status.thresholdPercent || 0));
  const provider = currentReaderProvider();
  const model = currentReaderModel();
  const providerName = providerDisplayName(status.provider || provider);
  const modelLabel = modelDisplayLabel(status.model || model, status.provider || provider, "label") || status.model || model || "Model";
  const tokenLine = `${formatTokenCount(status.tokensUsed)} / ${formatTokenCount(status.contextLength)} tokens used`;
  const sessionId = getChatSessionId();
  const canCompact = Boolean(sessionId && status.compactionEnabled && !readerState.contextCompacting);
  const compressedLine = status.compressionCount
    ? `${status.compressionCount} compacted${status.lastCompressedAt ? ` · ${formatChatSessionTime(status.lastCompressedAt)}` : ""}`
    : "No compaction yet";
  const warningText = status.lastCompressionError
    || (status.fallbackUsed ? "Fallback marker was used during the last compaction." : "")
    || (status.compressionCount >= 2 ? "Multiple compactions can reduce context precision." : "");

  if (elements.readerContextButton) {
    elements.readerContextButton.style.setProperty("--context-percent", String(percent));
    elements.readerContextButton.classList.toggle("is-loading", readerState.contextStatusLoading);
    elements.readerContextButton.classList.toggle("is-warning", compactPercent > 0 && percent >= compactPercent);
    elements.readerContextButton.classList.toggle("is-full", percent >= 90);
    elements.readerContextButton.title = `${percent}% full · ${tokenLine}`;
    elements.readerContextButton.setAttribute("aria-expanded", String(readerState.contextPopoverOpen));
  }

  if (!elements.readerContextPopover) return;
  elements.readerContextPopover.hidden = !readerState.contextPopoverOpen;
  if (!readerState.contextPopoverOpen) return;
  elements.readerContextPopover.innerHTML = `
    <div class="ask-context-title">Context window</div>
    <div class="ask-context-percent">${escapeHtml(readerState.contextStatusLoading ? "Checking..." : `${percent}% full`)}</div>
    <div class="ask-context-tokens">${escapeHtml(tokenLine)}</div>
    <div class="ask-context-model">${escapeHtml(`${providerName} · ${modelLabel}`)}</div>
    <div class="ask-context-grid">
      <span>Threshold</span><strong>${escapeHtml(`${formatTokenCount(status.thresholdTokens)} (${status.thresholdPercent}%)`)}</strong>
      <span>Messages</span><strong>${escapeHtml(String(status.messageCount))}</strong>
      <span>Summary</span><strong>${escapeHtml(status.summaryAvailable ? "available" : "not yet")}</strong>
      <span>Compactions</span><strong>${escapeHtml(compressedLine)}</strong>
    </div>
    ${warningText ? `<div class="ask-context-warning">${escapeHtml(warningText)}</div>` : ""}
    ${readerState.contextCompactStatus ? `<div class="ask-context-status">${escapeHtml(readerState.contextCompactStatus)}</div>` : ""}
    <div class="ask-context-actions">
      <input class="ask-context-focus" id="readerContextCompactFocus" type="text" value="${escapeHtml(readerState.contextCompactFocus)}" placeholder="Focus" aria-label="Compaction focus">
      <button class="ask-context-compact" type="button" data-context-action="compact" ${canCompact ? "" : "disabled"}>${escapeHtml(readerState.contextCompacting ? "Compacting" : "Compact now")}</button>
    </div>
  `;
}

function setReaderContextPopoverOpen(open) {
  readerState.contextPopoverOpen = open;
  if (open) {
    setChatSessionMenuOpen(false);
    closeReaderModelMenu();
    closeReaderToolMenu();
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
  const params = new URLSearchParams();
  const sessionId = getChatSessionId();
  const provider = currentReaderProvider();
  const model = currentReaderModel();
  const noteId = currentChatNoteId();
  const context = readerChatContext();
  if (sessionId) params.set("sessionId", sessionId);
  if (provider) params.set("provider", provider);
  if (model) params.set("model", model);
  if (noteId) params.set("noteId", noteId);
  if (readerState.note?.title) params.set("noteTitle", readerState.note.title);
  if (context.currentPage) params.set("currentPage", String(context.currentPage));

  readerState.contextStatusLoading = true;
  renderReaderContextControls();
  try {
    const suffix = params.toString() ? `?${params.toString()}` : "";
    readerState.contextStatus = normalizeContextStatus(await fetchAgentJson(`/api/chat/context${suffix}`));
  } catch (error) {
    if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
  } finally {
    readerState.contextStatusLoading = false;
    renderReaderContextControls();
  }
}

async function compactReaderContext() {
  const sessionId = getChatSessionId();
  if (!sessionId || readerState.contextCompacting) return;
  const context = readerChatContext();
  readerState.contextCompacting = true;
  readerState.contextCompactStatus = "Compacting context...";
  renderReaderContextControls();
  try {
    const payload = await fetchAgentJson("/api/chat/compress", {
      method: "POST",
      body: {
        sessionId,
        focus: readerState.contextCompactFocus,
        provider: currentReaderProvider(),
        model: currentReaderModel(),
        noteId: currentChatNoteId(),
        noteTitle: readerState.note?.title || "",
        currentPage: context.currentPage,
        selectionText: context.selectionText,
        context
      }
    });
    readerState.contextStatus = normalizeContextStatus(payload?.context);
    readerState.contextCompactStatus = normalizeText(payload?.warning)
      || (payload?.compressed ? "Context compacted." : "Nothing to compact yet.");
    if (payload?.compressed) {
      const marker = normalizeApiChatMessage(payload?.message);
      if (marker) {
        readerState.chatMessages = [...readerState.chatMessages, marker];
        renderReaderChatMessages({ scrollToBottom: true });
      } else {
        await recoverReaderChatFromSession({ requestId: "" });
      }
    }
    setReaderChatError("");
  } catch (error) {
    readerState.contextCompactStatus = sanitizeVisibleAgentError(error.message || "Could not compact context.");
  } finally {
    readerState.contextCompacting = false;
    renderReaderContextControls();
  }
}

