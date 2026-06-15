function initializeReaderChat() {
  initializeSavedPrompts();
  initializeReaderProjects();
  renderReaderChatMessages({ preserveScrollTop: true });
  renderReaderModelControls();
  renderReaderContextControls();
  renderReaderToolControls();
  renderAttachmentTray();
  void loadReaderModelCatalog({ silent: true });
  scheduleReaderContextStatusRefresh(300);
  elements.readerChatForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (isChatSessionPending()) {
      if (event.submitter === elements.sendReaderChat) cancelReaderChatRequest();
      return;
    }
    sendReaderChatMessage().catch((error) => {
      console.error("Reader chat submit failed.", error);
      setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    });
  });
  elements.readerChatMessages?.addEventListener("click", handleChatSourceClick);
  elements.readerChatMessages?.addEventListener("click", handleChatProgressClick);
  elements.readerChatMessages?.addEventListener("click", handleReaderChatMessageAction);
  elements.readerChatMessages?.addEventListener("copy", handleRichTextCopy);
  elements.readerChatMessages?.addEventListener("dblclick", handleReaderChatMessageDoubleClick);
  elements.readerChatMessages?.addEventListener("input", handleReaderChatMessageInput);
  elements.readerChatMessages?.addEventListener("keydown", handleReaderChatMessageKeydown);
  elements.readerChatMessages?.addEventListener("submit", handleReaderChatMessageSubmit);
  elements.readerChatMessages?.addEventListener("click", (event) => {
    handleToolActivityClick(event).catch((error) => setReaderChatError(error.message || GENERIC_AGENT_ERROR));
  });
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
  document.addEventListener("pointerdown", handleReaderSelectedPdfPointerDown, true);
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
      readerState.chatProjectMenuOpen
      && !elements.readerProjectPopover?.contains(event.target)
      && !elements.readerProjectButton?.contains(event.target)
      && !event.target.closest(".ask-project-flyout")
    ) {
      closeReaderProjectMenu();
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
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (readerState.chatSessionMenuOpen) setChatSessionMenuOpen(false);
    if (readerState.chatProjectMenuOpen) closeReaderProjectMenu();
    if (readerState.modelMenuOpen) closeReaderModelMenu();
    if (readerState.contextPopoverOpen) closeReaderContextPopover();
    if (readerState.toolMenuOpen) closeReaderToolMenu();
  });
  resizeReaderChatInput();
  window.readerChatInitialized = true;
}
