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
  if (normalizedProvider === "codex-oauth") {
    const thinkMode = currentGptThinkMode(currentReaderModel(), normalizedProvider);
    return thinkMode.enabled
      ? { effort: thinkMode.effort, summary: "auto" }
      : { effort: "none", summary: "none" };
  }
  if (providerSupportsGptThinkMode(normalizedProvider)) {
    const thinkMode = currentGptThinkMode(currentReaderModel(), normalizedProvider);
    return {
      use_responses_api: true,
      output_version: "responses/v1",
      reasoning: thinkMode.enabled
        ? { effort: thinkMode.effort, summary: "auto" }
        : { effort: "none" },
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
      .then(() => {
        setReaderChatError("");
        showCodeCopyFeedback(codeCopyButton);
      })
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
      .then(() => {
        setReaderChatError("");
        showCopyFeedback(copyButton);
      })
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
    const nextExpanded = !expanded;
    const summaryKey = normalizeText(summary?.dataset.runSummaryKey);
    if (summaryKey) {
      const nextOpen = { ...(readerState.runSummaryOpen || {}) };
      if (nextExpanded) {
        nextOpen[summaryKey] = true;
      } else {
        delete nextOpen[summaryKey];
      }
      readerState.runSummaryOpen = nextOpen;
    }
    runSummaryToggle.setAttribute("aria-expanded", nextExpanded ? "true" : "false");
    if (body) body.hidden = !nextExpanded;
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
