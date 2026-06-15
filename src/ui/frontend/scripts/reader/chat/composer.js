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
