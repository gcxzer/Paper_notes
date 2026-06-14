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
  let selectedFiles = Array.from(files || []).filter(isSupportedAttachmentFile);
  if (!selectedFiles.length) return;
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

function handleReaderImageFiles(files) {
  return handleReaderAttachmentFiles(files);
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
  await handleReaderAttachmentFiles([file]);
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

function keepSelectedPdfContextWithoutNativeSelection() {
  if (!currentReaderSelectedPdfText()) return;
  readerState.selectedPdfRanges = [];
  readerState.selectedPdfPointerRegion = "ask";
  readerState.preservePdfSelectionUntil = 0;
  renderAttachmentTray();
}

function clearNativePdfSelectionOnly({ preserveSelectedText = false } = {}) {
  if (preserveSelectedText) keepSelectedPdfContextWithoutNativeSelection();
  window.getSelection?.()?.removeAllRanges?.();
  if (typeof clearPdfSelectionOverlays === "function") clearPdfSelectionOverlays();
}

function handleReaderSelectedPdfPointerDown(event) {
  const askTarget = elements.askPane?.contains(event.target);
  if (!currentReaderSelectedPdfText()) {
    if (askTarget && selectedPdfPagesForChatContext().length) clearNativePdfSelectionOnly();
    return;
  }
  if (isSelectedTextRemoveTarget(event.target)) return;
  if (!askTarget) {
    readerState.selectedPdfPointerRegion = "outside";
    clearReaderSelectedPdfText({ clearNativeSelection: true });
    return;
  }

  readerState.selectedPdfPointerRegion = "ask";
  clearNativePdfSelectionOnly({ preserveSelectedText: true });
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
      if (typeof clearPdfSelectionOverlays === "function") clearPdfSelectionOverlays();
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
  handleReaderAttachmentFiles(files);
}

function renderReaderChatComposerState() {
  const currentPending = isChatSessionPending();
  if (elements.readerChatInput) elements.readerChatInput.disabled = false;
  if (elements.readerToolMenuButton) elements.readerToolMenuButton.disabled = false;
  if (elements.sendReaderChat) {
    const label = currentPending ? "Stop" : "Send";
    const iconName = currentPending ? "stop" : "send";
    elements.sendReaderChat.disabled = false;
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
  const items = mergeProgressWorkTraceItems(previous?.items || [], next?.items || []);
  if (!items.length) return null;
  return { status: normalizeText(next?.status || previous?.status || status) || "running", items };
}

function progressWorkTraceKey(item) {
  const identity = typeof workTraceItemIdentity === "function" ? workTraceItemIdentity(item) : "";
  return [
    normalizeText(item?.type),
    normalizeText(item?.source),
    identity || sanitizeChatProgressDetail(item?.text || item?.detail)
  ].join("\n");
}

function mergeProgressWorkTraceItems(previousItems, nextItems) {
  const output = [];
  const indexByKey = new Map();
  for (const item of [...(previousItems || []), ...(nextItems || [])]) {
    const key = progressWorkTraceKey(item);
    if (!key.trim()) continue;
    const existingIndex = indexByKey.get(key);
    if (existingIndex === undefined) {
      indexByKey.set(key, output.length);
      output.push(item);
      continue;
    }
    const previous = output[existingIndex];
    const nextText = sanitizeChatProgressDetail(item?.text || item?.detail);
    const previousText = sanitizeChatProgressDetail(previous?.text || previous?.detail);
    output[existingIndex] = {
      ...previous,
      ...item,
      text: nextText.length >= previousText.length ? nextText : previousText,
      complete: item?.complete === true || (previous?.complete === true && item?.complete !== false),
    };
  }
  return output;
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

function clearReaderChatRecoveryPoll(sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  const timer = readerState.chatRecoveryTimersBySession[runKey];
  if (timer) window.clearTimeout(timer);
  delete readerState.chatRecoveryTimersBySession[runKey];
}

function scheduleReaderChatRecoveryPoll({ sessionId, requestId, latestUserText = "", delay = 2400 } = {}) {
  const targetSessionId = normalizeText(sessionId);
  const targetRequestId = normalizeText(requestId);
  if (!targetSessionId || !targetRequestId) return;
  const runKey = chatSessionRunKey(targetSessionId);
  clearReaderChatRecoveryPoll(runKey);
  readerState.chatRecoveryTimersBySession[runKey] = window.setTimeout(async () => {
    delete readerState.chatRecoveryTimersBySession[runKey];
    if (readerState.chatProgressRequestIdsBySession[runKey] !== targetRequestId) return;
    try {
      if (typeof recoverReaderChatFromSession === "function") {
        const recovered = await recoverReaderChatFromSession({
          sessionId: targetSessionId,
          latestUserText
        });
        if (recovered) return;
      }
    } catch (error) {
      console.debug("Could not recover pending chat run yet.", error);
    }
    if (readerState.chatProgressRequestIdsBySession[runKey] === targetRequestId) {
      scheduleReaderChatRecoveryPoll({
        sessionId: targetSessionId,
        requestId: targetRequestId,
        latestUserText,
        delay: Math.min(6000, Math.round(delay * 1.25))
      });
    }
  }, delay);
}

function clearReaderChatProgress(sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  clearReaderChatRecoveryPoll(runKey);
  delete readerState.chatProgressBySession[runKey];
  delete readerState.chatProgressRequestIdsBySession[runKey];
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

function startReaderChatProgress(requestId, sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  const startedAt = new Date().toISOString();
  const startText = "Starting agent run.";
  clearReaderChatProgress(runKey);
  readerState.chatProgressRequestIdsBySession[runKey] = requestId;
  setReaderChatProgress({
    requestId,
    status: "running",
    stage: "starting",
    detail: startText,
    visibleEvents: [{ stage: "starting", detail: startText, at: startedAt }],
    events: [],
    workTrace: {
      status: "running",
      items: [{
        type: "status",
        text: startText,
        at: startedAt,
        source: "runtime",
        complete: true
      }]
    }
  }, runKey);
}

function appendReaderChatProgressWorkTrace(data, runKey = chatSessionRunKey(), eventType = "") {
  const text = normalizeText(data?.text || data?.delta);
  if (!text) return;
  const itemType = normalizeText(data?.traceType || data?.trace_type) || "summary";
  if (isStructuredToolCallProgressText(itemType, text)) return;
  const source = normalizeText(data?.source) || "provider";
  const at = normalizeText(data?.at) || new Date().toISOString();
  const itemData = data?.data && typeof data.data === "object" ? data.data : {};
  const isDelta = normalizeText(eventType) === "work_trace_delta" || Boolean(normalizeText(data?.delta));
  const explicitComplete = itemData.statusComplete === true || itemData.complete === true
    ? true
    : itemData.statusComplete === false || itemData.complete === false
      ? false
      : null;
  const progress = normalizeChatProgress(readerState.chatProgressBySession[runKey]) || {
    requestId: readerState.chatProgressRequestIdsBySession[runKey],
    status: "running",
    stage: "thinking",
    events: [],
    workTrace: { status: "running", items: [] },
  };
  const trace = normalizeWorkTrace(progress.workTrace) || { status: progress.status || "running", items: [] };
  const canMerge = canMergeStreamingWorkTraceType(itemType);
  const itemIdentity = typeof workTraceItemIdentity === "function" ? workTraceItemIdentity({ data: itemData }) : "";
  const relatedByIdentity = () => itemIdentity
    ? trace.items.findIndex((item) => (
      item.type === itemType
      && item.source === source
      && workTraceItemIdentity(item) === itemIdentity
    ))
    : -1;
  const upsertWorkTraceItem = (complete) => {
    const relatedIndex = relatedByIdentity();
    if (relatedIndex !== -1) {
      const previous = trace.items[relatedIndex];
      const previousText = normalizeText(previous.text);
      trace.items[relatedIndex] = {
        ...previous,
        text: text.length >= previousText.length ? text : previousText,
        source,
        at,
        data: itemData,
        complete,
      };
      return;
    }
    trace.items.push({
      type: itemType,
      text,
      source,
      at,
      data: itemData,
      complete,
    });
  };
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
    } else if (itemIdentity || !exactDuplicate()) {
      upsertWorkTraceItem(explicitComplete ?? false);
    }
  } else {
    const last = trace.items[trace.items.length - 1];
    if (canMerge && last && last.type === itemType && last.source === source && (
      text.startsWith(normalizeText(last.text)) || normalizeText(last.text).startsWith(text)
    )) {
      last.text = text.length >= normalizeText(last.text).length ? text : normalizeText(last.text);
      last.complete = explicitComplete ?? true;
    } else if (itemIdentity || !exactDuplicate()) {
      upsertWorkTraceItem(explicitComplete ?? true);
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
  readerState.chatAbortControllersBySession[runKey]?.abort();
  delete readerState.chatAbortControllersBySession[runKey];

  const stoppedProgress = normalizeChatProgress({
    ...appendProgressStatusWorkTrace(progress, "Agent run stopped."),
    requestId,
    status: "stopped",
    stage: "stopped",
    detail: "Agent run stopped.",
    events: [
      ...progress.events,
      { stage: "stopped", detail: "Agent run stopped." }
    ]
  });
  finalizeReaderChatProgress(stoppedProgress, { text: "Agent run stopped." });
  readerState.chatProgressBySession[runKey] = stoppedProgress;
  clearReaderChatProgress(runKey);
  setReaderChatPending(false, runKey);
  if (sessionId) forgetActiveChatRun(sessionId);
  renderReaderChatMessages();
  elements.readerChatInput?.focus();
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
