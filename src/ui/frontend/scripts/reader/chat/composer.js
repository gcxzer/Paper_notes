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

function normalizeReaderRuntimeSettings(payload) {
  return {
    docker: Boolean(payload?.docker),
    dockerLocalFileMessage: normalizeText(payload?.dockerLocalFileMessage)
      || "Docker mode cannot open files in the host desktop. Put the file under .paper-notes/media/uploads, then use that Paper Notes media path from the app."
  };
}

async function loadReaderRuntimeSettings() {
  if (readerState.runtimeSettings) return readerState.runtimeSettings;
  if (readerState.runtimeSettingsLoading) {
    while (readerState.runtimeSettingsLoading) {
      await new Promise((resolve) => window.setTimeout(resolve, 30));
    }
    return readerState.runtimeSettings || normalizeReaderRuntimeSettings(null);
  }
  readerState.runtimeSettingsLoading = true;
  try {
    readerState.runtimeSettings = normalizeReaderRuntimeSettings(await fetchAgentJson("/api/runtime"));
  } catch (error) {
    console.warn("Could not load reader runtime settings.", error);
    readerState.runtimeSettings = normalizeReaderRuntimeSettings(null);
  } finally {
    readerState.runtimeSettingsLoading = false;
  }
  return readerState.runtimeSettings;
}

async function shouldBlockLocalFileImportForDocker(source) {
  if (normalizeText(source || "local") !== "local") return false;
  const runtimeSettings = await loadReaderRuntimeSettings();
  if (!runtimeSettings.docker) return false;
  setReaderChatError(runtimeSettings.dockerLocalFileMessage);
  if (elements.readerAttachmentInput) elements.readerAttachmentInput.value = "";
  renderAttachmentTray();
  renderReaderToolControls();
  return true;
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

async function handleReaderAttachmentFiles(files, { source = "local" } = {}) {
  let selectedFiles = Array.from(files || []).filter(isSupportedAttachmentFile);
  if (!selectedFiles.length) return;
  if (await shouldBlockLocalFileImportForDocker(source)) return;
  const imageFiles = selectedFiles.filter(isImageFile);
  let blockedImageMessage = "";
  if (imageFiles.length && !activeProviderSupportsImageInput()) {
    blockedImageMessage = activeProviderImageInputUnsupportedMessage();
    selectedFiles = selectedFiles.filter((file) => !isImageFile(file));
    setReaderChatError(blockedImageMessage);
    if (!selectedFiles.length) {
      if (elements.readerAttachmentInput) elements.readerAttachmentInput.value = "";
      renderAttachmentTray();
      renderReaderToolControls();
      return;
    }
  }
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
    setReaderChatError(blockedImageMessage || "");
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

function handleReaderImageFiles(files, options = {}) {
  return handleReaderAttachmentFiles(files, options);
}

function currentPdfPageCanvasForScreenshot() {
  const page = Number(currentPdfScrollPosition()?.page) || 1;
  const pageElement = elements.pdfViewer?.querySelector(`.pdf-page[data-page="${page}"]`)
    || elements.pdfViewer?.querySelector(".pdf-page");
  const canvas = pageElement?.querySelector(".pdf-page-canvas");
  return { page: Number(pageElement?.dataset?.page) || page, canvas };
}

function canvasToPngBlob(canvas) {
  return new Promise((resolve, reject) => {
    if (!canvas || !canvas.width || !canvas.height) {
      reject(new Error("No rendered PDF page is available to capture."));
      return;
    }
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("Could not capture the current PDF page."));
    }, "image/png");
  });
}

function screenshotFileName(page) {
  const title = normalizeText(readerState.note?.title || "paper")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "paper";
  return `${title}-page-${Number(page) || 1}.png`;
}

async function addCurrentPdfPageScreenshot() {
  if (!activeProviderSupportsImageInput()) {
    setReaderChatError(activeProviderImageInputUnsupportedMessage());
    closeReaderToolMenu();
    return;
  }
  const { page, canvas } = currentPdfPageCanvasForScreenshot();
  const blob = await canvasToPngBlob(canvas);
  const file = new File([blob], screenshotFileName(page), { type: "image/png" });
  closeReaderToolMenu();
  await handleReaderAttachmentFiles([file], { source: "generated" });
  elements.readerChatInput?.focus();
}

function handleAttachmentTrayClick(event) {
  const selectedTextRemove = event.target.closest("[data-selected-text-remove]");
  if (selectedTextRemove) {
    event.preventDefault();
    clearReaderSelectedPdfText({ clearNativeSelection: true });
    return;
  }

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

function selectedPdfPagesForChatContext() {
  if (typeof selectedPdfPages === "function") return selectedPdfPages();
  const selection = window.getSelection?.();
  if (!selection || selection.isCollapsed || !elements.pdfViewer) return [];
  return Array.from(elements.pdfViewer.querySelectorAll(".pdf-page")).filter((pageElement) => {
    const textLayer = pageElement.querySelector(".textLayer");
    if (!textLayer) return false;
    for (let index = 0; index < selection.rangeCount; index += 1) {
      const range = selection.getRangeAt(index);
      try {
        if (range.intersectsNode(textLayer)) return true;
      } catch (error) {
        // A page can detach while PDF.js rerenders; ignore that transient state.
      }
    }
    return false;
  });
}

function normalizeReaderSelectedPdfText(text) {
  const normalized = typeof normalizeCopiedPdfText === "function"
    ? normalizeCopiedPdfText(text)
    : normalizeText(text);
  return normalizeText(normalized).slice(0, 4000);
}

function currentReaderSelectedPdfText() {
  return normalizeReaderSelectedPdfText(readerState.selectedPdfText);
}

function captureReaderPdfSelectionRanges() {
  const selection = window.getSelection?.();
  if (!selection || selection.isCollapsed || !selectedPdfPagesForChatContext().length) {
    readerState.selectedPdfRanges = [];
    return [];
  }
  const ranges = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    try {
      ranges.push(selection.getRangeAt(index).cloneRange());
    } catch (error) {
      // Ignore ranges that disappear during PDF rerender or browser selection churn.
    }
  }
  readerState.selectedPdfRanges = ranges;
  return ranges;
}

function restoreReaderPdfSelectionRanges() {
  const ranges = Array.isArray(readerState.selectedPdfRanges) ? readerState.selectedPdfRanges : [];
  if (!ranges.length) return false;
  const selection = window.getSelection?.();
  if (!selection) return false;
  try {
    selection.removeAllRanges();
    ranges.forEach((range) => selection.addRange(range.cloneRange()));
    if (typeof schedulePdfSelectionOverlayRender === "function") schedulePdfSelectionOverlayRender();
    return true;
  } catch (error) {
    readerState.selectedPdfRanges = [];
    return false;
  }
}

function renderSavedReaderPdfSelectionOverlay() {
  if (typeof renderPdfSelectionOverlaysFromRanges !== "function") return false;
  return renderPdfSelectionOverlaysFromRanges(readerState.selectedPdfRanges);
}

function isEditableAskPaneTarget(target) {
  const element = target?.nodeType === Node.ELEMENT_NODE ? target : target?.parentElement;
  return Boolean(element?.closest?.("input, textarea, [contenteditable='true'], [contenteditable='']"));
}

function isSelectedTextRemoveTarget(target) {
  const element = target?.nodeType === Node.ELEMENT_NODE ? target : target?.parentElement;
  return Boolean(element?.closest?.("[data-selected-text-remove]"));
}

function setReaderSelectedPdfText(text, page = "") {
  const normalized = normalizeReaderSelectedPdfText(text);
  if (!normalized) return false;
  const normalizedPage = normalizeText(page);
  const changed = normalized !== readerState.selectedPdfText || normalizedPage !== readerState.selectedPdfPage;
  readerState.selectedPdfText = normalized;
  readerState.selectedPdfPage = normalizedPage;
  captureReaderPdfSelectionRanges();
  if (changed) renderAttachmentTray();
  return true;
}

function selectedPdfTextContextFromState() {
  const text = currentReaderSelectedPdfText();
  if (!text) return null;
  return {
    type: "selected_text",
    text,
    page: normalizeText(readerState.selectedPdfPage),
    wordCount: text.split(/\s+/).filter(Boolean).length
  };
}

function snapshotReaderSelectedPdfTextForSubmit() {
  readerState.pendingSelectedTextContext = selectedPdfTextContextFromState();
}

function clearReaderSelectedPdfText({ clearNativeSelection = false } = {}) {
  readerState.selectedPdfText = "";
  readerState.selectedPdfPage = "";
  readerState.selectedPdfRanges = [];
  readerState.selectedPdfPointerRegion = "";
  readerState.preservePdfSelectionUntil = 0;
  if (clearNativeSelection) {
    window.getSelection?.()?.removeAllRanges?.();
    if (typeof clearPdfSelectionOverlays === "function") clearPdfSelectionOverlays();
  }
  renderAttachmentTray();
}

function handleReaderSelectedPdfPointerDown(event) {
  if (!currentReaderSelectedPdfText()) return;
  if (isSelectedTextRemoveTarget(event.target)) return;
  if (!elements.askPane?.contains(event.target)) {
    readerState.selectedPdfPointerRegion = "outside";
    clearReaderSelectedPdfText({ clearNativeSelection: true });
    return;
  }

  readerState.selectedPdfPointerRegion = "ask";
  if (isEditableAskPaneTarget(event.target)) {
    readerState.preservePdfSelectionUntil = 0;
    window.requestAnimationFrame(renderSavedReaderPdfSelectionOverlay);
    return;
  }
  captureReaderPdfSelectionRanges();
  readerState.preservePdfSelectionUntil = Date.now() + 700;
  window.requestAnimationFrame(() => {
    if (Date.now() <= readerState.preservePdfSelectionUntil) restoreReaderPdfSelectionRanges();
  });
}

function shouldRestoreReaderPdfSelection() {
  if (isEditableAskPaneTarget(document.activeElement)) return false;
  return currentReaderSelectedPdfText()
    && Date.now() <= Number(readerState.preservePdfSelectionUntil || 0)
    && Array.isArray(readerState.selectedPdfRanges)
    && readerState.selectedPdfRanges.length > 0;
}

function refreshReaderSelectedPdfTextFromSelection() {
  const pages = selectedPdfPagesForChatContext();
  if (!pages.length) {
    if (shouldRestoreReaderPdfSelection() && restoreReaderPdfSelectionRanges()) return true;
    if (readerState.selectedPdfPointerRegion === "ask" && currentReaderSelectedPdfText()) {
      renderSavedReaderPdfSelectionOverlay();
      return true;
    }
    clearReaderSelectedPdfText();
    return false;
  }
  const text = typeof textFromPdfSelection === "function"
    ? textFromPdfSelection()
    : window.getSelection?.()?.toString() || "";
  const page = normalizeText(pages[0]?.dataset?.page);
  return setReaderSelectedPdfText(text, page);
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
  if (!activeProviderSupportsImageInput()) {
    setReaderChatError(activeProviderImageInputUnsupportedMessage());
    return;
  }
  handleReaderAttachmentFiles(files, { source: "clipboard" });
}

function renderReaderChatComposerState() {
  const currentPending = isChatSessionPending();
  const progress = normalizeChatProgress(currentChatProgress());
  const cancelling = currentPending && normalizeText(progress?.status) === "cancelling";
  if (elements.readerChatInput) elements.readerChatInput.disabled = currentPending;
  if (elements.readerToolMenuButton) elements.readerToolMenuButton.disabled = currentPending;
  if (elements.sendReaderChat) {
    const label = cancelling ? "Cancelling" : currentPending ? "Cancel" : "Send";
    const iconName = currentPending ? "stop" : "send";
    elements.sendReaderChat.disabled = cancelling;
    elements.sendReaderChat.innerHTML = `<span class="ask-send-icon" aria-hidden="true">${renderAskToolSvg(iconName, 18)}</span>`;
    elements.sendReaderChat.setAttribute("aria-label", label);
    elements.sendReaderChat.title = label;
    elements.sendReaderChat.classList.toggle("is-cancel", currentPending);
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
  const normalized = mergeReaderChatProgress(readerState.chatProgressBySession[runKey], progress);
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

function mergeReaderChatProgress(previousProgress, nextProgress) {
  const next = normalizeChatProgress(nextProgress);
  if (!next) return null;
  const previous = normalizeChatProgress(previousProgress);
  if (!previous) return next;
  if (previous.requestId && next.requestId && previous.requestId !== next.requestId) return next;
  return {
    ...next,
    requestId: next.requestId || previous.requestId,
    events: mergeProgressItems(previous.events, next.events, progressEventKey),
    visibleEvents: mergeProgressItems(previous.visibleEvents, next.visibleEvents, progressVisibleEventKey),
    workTrace: mergeProgressWorkTrace(previous.workTrace, next.workTrace, next.status)
  };
}

function mergeProgressItems(previousItems, nextItems, keyForItem) {
  const output = [];
  const seen = new Set();
  for (const item of [...(previousItems || []), ...(nextItems || [])]) {
    const key = keyForItem(item);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    output.push(item);
  }
  return output;
}

function progressEventKey(event) {
  const data = event?.data && typeof event.data === "object" ? JSON.stringify(event.data) : "";
  return [normalizeText(event?.type || event?.stage), sanitizeChatProgressDetail(event?.detail || event?.message), normalizeText(event?.at), data].join("\n");
}

function progressVisibleEventKey(event) {
  return [normalizeText(event?.stage), sanitizeChatProgressDetail(event?.detail), normalizeText(event?.at)].join("\n");
}

function mergeProgressWorkTrace(previousTrace, nextTrace, status = "running") {
  const previous = normalizeWorkTrace(previousTrace);
  const next = normalizeWorkTrace(nextTrace);
  const items = mergeProgressItems(previous?.items || [], next?.items || [], progressWorkTraceKey);
  if (!items.length) return null;
  return { status: normalizeText(next?.status || previous?.status || status) || "running", items };
}

function progressWorkTraceKey(item) {
  return [normalizeText(item?.type), normalizeText(item?.source), sanitizeChatProgressDetail(item?.text || item?.detail)].join("\n");
}

function appendProgressStatusWorkTrace(progress, text) {
  const normalized = normalizeChatProgress(progress) || {
    status: "running",
    events: [],
    workTrace: { status: "running", items: [] }
  };
  const detail = sanitizeChatProgressDetail(text);
  if (!detail) return normalized;
  const trace = mergeProgressWorkTrace(normalized.workTrace, {
    status: normalized.status,
    items: [{ type: "status", text: detail, at: new Date().toISOString(), source: "system" }]
  }, normalized.status) || { status: normalized.status, items: [] };
  return { ...normalized, workTrace: trace };
}

function finalizeReaderChatProgress(progress, { text = "Agent run stopped.", error = false } = {}) {
  const normalized = normalizeChatProgress(progress);
  if (!normalized) return;
  const trace = runTraceFromProgress(normalized);
  const draft = latestReaderStreamingAssistantMessage() || ensureReaderStreamingAssistantMessage();
  draft.streaming = false;
  if (!normalizeText(draft.text)) draft.text = text;
  draft.error = Boolean(error);
  if (trace) draft.runTrace = trace;
  if (normalized.workTrace?.items?.length) draft.workTrace = normalized.workTrace;
  flushReaderStreamingRender();
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
    const currentProgress = normalizeChatProgress(readerState.chatProgressBySession[runKey]) || normalizeChatProgress(progress);
    if (isTerminalChatProgressStatus(currentProgress?.status)) {
      if (readerState.chatProgressTimersBySession[runKey]) {
        clearInterval(readerState.chatProgressTimersBySession[runKey]);
        delete readerState.chatProgressTimersBySession[runKey];
      }
      delete readerState.chatAbortControllersBySession[runKey];
      const terminalStatus = normalizeText(currentProgress.status);
      if (isCurrentChatSessionRunKey(runKey) && ["cancelled", "failed", "stopped"].includes(terminalStatus)) {
        const finalProgress = appendProgressStatusWorkTrace(currentProgress, currentProgress.detail || "Agent run stopped.");
        finalizeReaderChatProgress(finalProgress, {
          text: terminalStatus === "cancelled" ? "Agent run cancelled." : currentProgress.detail || "Agent run stopped.",
          error: terminalStatus === "failed"
        });
      }
      setReaderChatPending(false, runKey);
      if (normalizeText(sessionId) && sessionId !== "__draft_chat_session__") {
        forgetActiveChatRun(sessionId);
        if (isCurrentChatSessionRunKey(runKey) && !["cancelled", "failed", "stopped"].includes(terminalStatus)) {
          await loadReaderChatSession(sessionId, { closeMenu: false, refreshList: true });
        } else {
          await fetchReaderChatSessions({ silent: true });
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

function appendReaderChatProgressWorkTrace(data, runKey = chatSessionRunKey(), eventType = "") {
  const text = normalizeText(data?.text || data?.delta);
  if (!text) return;
  const itemType = normalizeText(data?.traceType || data?.trace_type) || "summary";
  const source = normalizeText(data?.source) || "provider";
  const isDelta = normalizeText(eventType) === "work_trace_delta" || Boolean(normalizeText(data?.delta));
  const progress = normalizeChatProgress(readerState.chatProgressBySession[runKey]) || {
    requestId: readerState.chatProgressRequestIdsBySession[runKey],
    status: "running",
    stage: "thinking",
    detail: "Thinking with local paper context...",
    events: [],
    workTrace: { status: "running", items: [] },
  };
  const trace = normalizeWorkTrace(progress.workTrace) || { status: progress.status || "running", items: [] };
  const canMerge = canMergeStreamingWorkTraceType(itemType);
  const exactDuplicate = () => trace.items.some((item) => (
    item.type === itemType
    && item.source === source
    && sanitizeChatProgressDetail(item.text || item.detail) === text
  ));
  if (isDelta) {
    const last = trace.items[trace.items.length - 1];
    if (canMerge && last && last.type === itemType && last.source === source && (
      text.startsWith(normalizeText(last.text)) || normalizeText(last.text).startsWith(text)
    )) {
      last.text = text;
    } else if (!exactDuplicate()) {
      trace.items.push({
        type: itemType,
        text,
        source,
        complete: false,
      });
    }
  } else {
    const last = trace.items[trace.items.length - 1];
    if (canMerge && last && last.type === itemType && last.source === source && (
      text.startsWith(normalizeText(last.text)) || normalizeText(last.text).startsWith(text)
    )) {
      last.text = text.length >= normalizeText(last.text).length ? text : normalizeText(last.text);
      last.complete = true;
    } else if (!exactDuplicate()) {
      trace.items.push({
        type: itemType,
        text,
        source,
        complete: true,
      });
    }
  }
  progress.workTrace = trace;
  setReaderChatProgress(progress, runKey);
}

async function cancelReaderChatRequest() {
  const runKey = chatSessionRunKey();
  const sessionId = getChatSessionId();
  const requestId = readerState.chatProgressRequestIdsBySession[runKey];
  if (!requestId) return;
  const progress = normalizeChatProgress(readerState.chatProgressBySession[runKey]) || { events: [] };
  if (normalizeText(progress.status) === "cancelling") return;
  readerState.chatAbortControllersBySession[runKey]?.abort();
  delete readerState.chatAbortControllersBySession[runKey];
  if (readerState.chatProgressTimersBySession[runKey]) {
    clearInterval(readerState.chatProgressTimersBySession[runKey]);
    delete readerState.chatProgressTimersBySession[runKey];
  }
  const cancellingProgress = normalizeChatProgress({
    ...appendProgressStatusWorkTrace(progress, "Cancelling agent run."),
    requestId,
    status: "cancelling",
    stage: "cancelling",
    detail: "Cancelling agent run.",
    events: [
      ...progress.events,
      { stage: "cancelling", detail: "Cancelling agent run." }
    ]
  });
  readerState.chatProgressBySession[runKey] = cancellingProgress;
  setReaderChatPending(true, runKey);

  try {
    const cancelResult = await fetchAgentJson("/api/chat/cancel", {
      method: "POST",
      body: {
        requestId,
        sessionId,
        reason: "reader_cancelled"
      }
    });
    rememberActiveChatRun(sessionId, requestId);
    readerState.chatProgressRequestIdsBySession[runKey] = requestId;
    if (normalizeText(cancelResult?.status) === "cancelling") {
      setReaderChatPending(true, runKey);
      if (!readerState.chatProgressTimersBySession[runKey]) {
        readerState.chatProgressTimersBySession[runKey] = setInterval(() => fetchReaderChatProgress(requestId, sessionId), 800);
      }
    } else {
      const cancelledProgress = normalizeChatProgress({
        ...appendProgressStatusWorkTrace(cancellingProgress, "Agent run cancelled."),
        status: "cancelled",
        stage: "cancelled",
        detail: "Agent run cancelled.",
        events: [
          ...cancellingProgress.events,
          { stage: "cancelled", detail: "Agent run cancelled." }
        ]
      });
      finalizeReaderChatProgress(cancelledProgress, { text: "Agent run cancelled." });
      readerState.chatProgressBySession[runKey] = cancelledProgress;
      clearReaderChatProgress(runKey);
      setReaderChatPending(false, runKey);
      if (sessionId) forgetActiveChatRun(sessionId);
      renderReaderChatMessages();
    }
    window.setTimeout(() => {
      fetchReaderChatProgress(requestId, sessionId).catch((error) => {
        console.warn("Failed to refresh cancelled chat progress.", error);
      });
    }, 250);
  } catch (error) {
    clearReaderChatProgress(runKey);
    setReaderChatPending(false, runKey);
    renderReaderChatMessages();
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
  } finally {
    elements.readerChatInput?.focus();
  }
}

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
  const percent = Math.min(100, Math.max(0, status.percentFull ?? status.estimatedPercent ?? 0));
  const provider = currentReaderProvider();
  const model = currentReaderModel();
  const providerName = providerDisplayName(status.provider || provider);
  const modelLabel = modelDisplayLabel(status.model || model, status.provider || provider, "label") || status.model || model || "Model";
  const tokenLine = `${formatTokenCount(status.tokensUsed)} / ${formatTokenCount(status.contextLength)} context used`;
  const estimatedLine = status.estimatedRequestTokens
    ? `Estimated request: ${formatTokenCount(status.estimatedRequestTokens)} tokens`
    : "Estimated request: unavailable";
  const estimatedKnownTokens = Math.max(0, status.messageTokens + status.instructionTokens + status.toolSchemaTokens);
  const estimatedOverheadTokens = Math.max(0, status.estimatedRequestTokens - estimatedKnownTokens);
  const estimatedParts = [
    status.messageTokens ? `Messages ${formatTokenCount(status.messageTokens)}` : "",
    status.instructionTokens ? `Instructions ${formatTokenCount(status.instructionTokens)}` : "",
    status.toolSchemaTokens ? `Tools ${formatTokenCount(status.toolSchemaTokens)}` : "",
    estimatedOverheadTokens ? `Overhead ${formatTokenCount(estimatedOverheadTokens)}` : ""
  ].filter(Boolean).join(" · ");
  const sessionId = getChatSessionId();
  const canCompact = Boolean(sessionId && status.compactionEnabled && !readerState.contextCompacting);
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
    elements.readerContextButton.classList.remove("is-warning");
    elements.readerContextButton.classList.remove("is-full");
    elements.readerContextButton.title = `${percent}% full · ${tokenLine} · ${estimatedLine}`;
    elements.readerContextButton.setAttribute("aria-expanded", String(readerState.contextPopoverOpen));
  }

  if (!elements.readerContextPopover) return;
  elements.readerContextPopover.hidden = !readerState.contextPopoverOpen;
  if (!readerState.contextPopoverOpen) return;
  elements.readerContextPopover.innerHTML = `
    <div class="ask-context-title">Context window</div>
    <div class="ask-context-percent">${escapeHtml(readerState.contextStatusLoading ? "Checking..." : `${percent}% full`)}</div>
    <div class="ask-context-tokens">${escapeHtml(tokenLine)}</div>
    <div class="ask-context-estimate">${escapeHtml(estimatedLine)}</div>
    ${estimatedParts ? `<div class="ask-context-estimate-detail">${escapeHtml(estimatedParts)}</div>` : ""}
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
    readerState.contextCompactStatus = payload?.compressed ? "Context compacted." : "Nothing to compact yet.";
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
