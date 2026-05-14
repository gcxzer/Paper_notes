function renderReaderToolControls() {
  const sessionId = getChatSessionId();
  const level = normalizeToolMenuLevel(readerState.toolMenuLevel);

  if (elements.readerToolMenuButton) {
    elements.readerToolMenuButton.textContent = "+";
    elements.readerToolMenuButton.title = "Ask tools";
    elements.readerToolMenuButton.setAttribute("aria-expanded", String(readerState.toolMenuOpen));
  }

  if (elements.readerToolPopover) {
    elements.readerToolPopover.hidden = !readerState.toolMenuOpen;
  }
  if (!readerState.toolMenuOpen) return;

  if (elements.readerToolBack) {
    elements.readerToolBack.hidden = level === "root";
  }
  if (elements.readerToolTitle) {
    elements.readerToolTitle.textContent = toolMenuTitle(level);
    elements.readerToolTitle.hidden = level === "root";
  }
  if (elements.readerToolSubtitle) {
    elements.readerToolSubtitle.textContent = toolMenuSubtitle(level);
    elements.readerToolSubtitle.hidden = level === "root";
  }
  if (elements.readerToolRoot) {
    elements.readerToolRoot.hidden = level !== "root";
    if (level === "root") {
      elements.readerToolRoot.innerHTML = renderToolRootMenu();
    }
  }
  if (elements.readerToolNoteWriting) {
    elements.readerToolNoteWriting.hidden = true;
  }
  if (elements.readerToolSnapshots) {
    elements.readerToolSnapshots.hidden = level !== "snapshots";
  }
  if (elements.readerToolFileGeneration) {
    elements.readerToolFileGeneration.hidden = level !== "file_generation";
  }

  elements.readerToolPopover?.querySelectorAll("[data-tool-mode]").forEach((button) => {
    const active = normalizeWriteToolMode(button.dataset.toolMode) === normalizeWriteToolMode(readerState.writeToolMode);
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  elements.readerToolPopover?.querySelectorAll("[data-file-generation-format]").forEach((button) => {
    const active = normalizeFileGenerationFormat(button.dataset.fileGenerationFormat) === normalizeFileGenerationFormat(readerState.fileGenerationFormat);
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });

  if (elements.readerSnapshotList) {
    if (!sessionId) {
      elements.readerSnapshotList.innerHTML = `<p class="ask-session-empty">No session yet.</p>`;
    } else if (readerState.toolSnapshotsLoading) {
      elements.readerSnapshotList.innerHTML = `<p class="ask-session-empty">Loading snapshots...</p>`;
    } else if (!readerState.toolSnapshots.length) {
      elements.readerSnapshotList.innerHTML = `<p class="ask-session-empty">No write snapshots yet.</p>`;
    } else {
      elements.readerSnapshotList.innerHTML = readerState.toolSnapshots.map(renderToolSnapshotRow).join("");
    }
  }

  if (elements.readerToolStatus) {
    elements.readerToolStatus.textContent = readerState.toolSnapshotStatus;
    const statusLevel = normalizeToolMenuLevel(readerState.toolSnapshotStatusLevel);
    elements.readerToolStatus.hidden = !readerState.toolSnapshotStatus || statusLevel !== level;
  }
}

function normalizeToolMenuLevel(value) {
  const level = normalizeText(value);
  return ["root", "snapshots", "file_generation"].includes(level) ? level : "root";
}

function normalizeFileGenerationFormat(value) {
  const format = normalizeText(value).toLowerCase();
  return FILE_GENERATION_FORMATS.has(format) ? format : "markdown";
}

function fileGenerationFormatLabel(value) {
  return {
    markdown: "Markdown file",
    text: "Text file",
    json: "JSON file",
    csv: "CSV file",
    html: "HTML file"
  }[normalizeFileGenerationFormat(value)] || "Markdown file";
}

function toolMenuTitle(level) {
  if (level === "snapshots") return "Snapshots";
  if (level === "file_generation") return "Generate file";
  return "Ask tools";
}

function toolMenuSubtitle(level) {
  if (level === "snapshots") return "Undo note writes";
  if (level === "file_generation") return "Choose file format";
  return "More actions";
}

function renderToolRootMenu() {
  const imageGenerationSupported = activeProviderSupportsImageArtifacts();
  const imageGenerationTitle = imageGenerationSupported
    ? "Generate image"
    : "Image generation needs a connected Codex OAuth or OpenAI API key provider.";
  return `
    <div class="ask-tool-menu-section">
      <button class="ask-tool-menu-option" type="button" data-tool-action="attach-image">
        <span>
          <strong>Add Images & Files</strong>
        </span>
      </button>
    </div>
    <div class="ask-tool-menu-section">
      <button class="ask-tool-menu-option" type="button" data-tool-action="generate-image"${imageGenerationSupported ? "" : " disabled"} title="${escapeHtml(imageGenerationTitle)}">
        <span>
          <strong>Generate image</strong>
        </span>
      </button>
      <button class="ask-tool-menu-option" type="button" data-tool-section="file_generation">
        <span>
          <strong>Generate file</strong>
        </span>
      </button>
    </div>
  `;
}

function imageToolSummary() {
  return attachmentToolSummary();
}

function attachmentToolSummary() {
  const count = normalizeAttachmentArtifacts(readerState.chatAttachments).length;
  if (count) return `${count} attached`;
  return "Attach images or files";
}

function renderToolSnapshotRow(snapshot) {
  const files = snapshot.changedFiles.map((file) => file.path).join(", ") || "No changed files";
  const meta = [
    formatChatSessionTime(snapshot.createdAt),
    snapshot.restored ? "restored" : "",
    snapshot.failed ? "failed" : ""
  ].filter(Boolean).join(" · ");
  const actioning = readerState.toolSnapshotActionId === snapshot.snapshotId;
  const canUndo = snapshot.undoable && !snapshot.restored && !snapshot.failed;
  return `
    <div class="ask-snapshot-row">
      <div class="ask-snapshot-copy">
        <span class="ask-snapshot-title">${escapeHtml(toolDisplayName(snapshot.toolName))}</span>
        <span class="ask-snapshot-files">${escapeHtml(files)}</span>
        ${meta ? `<span class="ask-snapshot-meta">${escapeHtml(meta)}</span>` : ""}
      </div>
      <div class="ask-snapshot-buttons">
        ${canUndo ? `
          <button
            class="ask-snapshot-undo"
            type="button"
            data-tool-snapshot-undo="${escapeHtml(snapshot.snapshotId)}"
            ${actioning ? "disabled" : ""}
          >${actioning ? "Working" : "Undo"}</button>
        ` : ""}
      </div>
    </div>
  `;
}

function setReaderToolMenuOpen(open) {
  readerState.toolMenuOpen = open;
  if (open) {
    readerState.toolMenuLevel = "root";
    setChatSessionMenuOpen(false);
    closeReaderModelMenu();
    closeReaderContextPopover();
    void loadReaderToolSnapshots({ silent: true });
  }
  renderReaderToolControls();
}

function closeReaderToolMenu() {
  readerState.toolMenuOpen = false;
  readerState.toolMenuLevel = "root";
  renderReaderToolControls();
}

function showReaderToolRootMenu() {
  readerState.toolMenuLevel = "root";
  renderReaderToolControls();
}

function showReaderToolSection(section) {
  const nextLevel = normalizeToolMenuLevel(section);
  readerState.toolMenuLevel = nextLevel === "root" ? "root" : nextLevel;
  if (readerState.toolMenuLevel === "snapshots") {
    void loadReaderToolSnapshots({ silent: true });
  }
  renderReaderToolControls();
}

function setReaderGenerationMode(mode, options = {}) {
  const nextMode = ["image", "file"].includes(normalizeText(mode)) ? normalizeText(mode) : "";
  if (nextMode === "image" && !activeProviderSupportsImageArtifacts()) {
    setReaderChatError("Image generation needs a connected Codex OAuth or OpenAI API key provider.");
    closeReaderToolMenu();
    return;
  }
  readerState.generationMode = nextMode;
  if (options.format) readerState.fileGenerationFormat = normalizeFileGenerationFormat(options.format);
  renderAttachmentTray();
  renderReaderToolControls();
}

function clearReaderGenerationMode() {
  readerState.generationMode = "";
  renderAttachmentTray();
  renderReaderToolControls();
}

function setReaderWriteToolMode(mode) {
  readerState.writeToolMode = writeStoredWriteToolMode(mode);
  readerState.toolSnapshotStatus = `Write mode: ${writeToolModeLabel(readerState.writeToolMode)}`;
  readerState.toolSnapshotStatusLevel = "note_writing";
  renderReaderToolControls();
}

function markToolSnapshotConflict(snapshotId, message) {
  if (!snapshotId) return;
  readerState.toolSnapshotConflicts = {
    ...readerState.toolSnapshotConflicts,
    [snapshotId]: message || "Newer file changes detected."
  };
  renderReaderToolControls();
}

function clearToolSnapshotConflict(snapshotId) {
  if (!snapshotId || !readerState.toolSnapshotConflicts[snapshotId]) return;
  const nextConflicts = { ...readerState.toolSnapshotConflicts };
  delete nextConflicts[snapshotId];
  readerState.toolSnapshotConflicts = nextConflicts;
}

async function loadReaderToolSnapshots({ silent = false } = {}) {
  const sessionId = getChatSessionId();
  if (!sessionId) {
    readerState.toolSnapshots = [];
    readerState.toolDiffs = {};
    readerState.toolSnapshotsLoading = false;
    readerState.toolSnapshotStatus = "";
    readerState.toolSnapshotStatusLevel = "";
    renderReaderToolControls();
    return [];
  }

  readerState.toolSnapshotsLoading = true;
  renderReaderToolControls();
  try {
    const payload = await fetchAgentJson(`/api/chat/tool-snapshots?sessionId=${encodeURIComponent(sessionId)}&limit=50`);
    readerState.toolSnapshots = normalizeToolSnapshots(payload.snapshots);
    readerState.toolSnapshotStatus = "";
    readerState.toolSnapshotStatusLevel = "";
    return readerState.toolSnapshots;
  } catch (error) {
    readerState.toolSnapshots = [];
    readerState.toolSnapshotStatus = "Could not load snapshots.";
    readerState.toolSnapshotStatusLevel = "snapshots";
    if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    return [];
  } finally {
    readerState.toolSnapshotsLoading = false;
    renderReaderToolControls();
  }
}

async function respondReaderToolApproval(approvalId, action) {
  const targetApprovalId = normalizeText(approvalId);
  const targetAction = normalizeText(action);
  if (!targetApprovalId || !targetAction) return null;
  readerState.toolApprovalActionId = targetApprovalId;
  renderReaderChatMessages({ preserveScrollTop: true });
  try {
    return await fetchAgentJson("/api/chat/tool-approvals/respond", {
      method: "POST",
      body: { approvalId: targetApprovalId, action: targetAction }
    });
  } catch (error) {
    throw error;
  } finally {
    readerState.toolApprovalActionId = "";
    renderReaderChatMessages({ preserveScrollTop: true });
  }
}

async function cleanupReaderToolSnapshots() {
  const sessionId = getChatSessionId();
  if (!sessionId) return;
  readerState.toolSnapshotStatus = "Cleaning old snapshots...";
  readerState.toolSnapshotStatusLevel = "snapshots";
  renderReaderToolControls();
  try {
    const payload = await fetchAgentJson("/api/chat/tool-snapshots/cleanup", {
      method: "POST",
      body: { sessionId, keepPerSession: 20, maxAgeDays: 30 }
    });
    const status = `${Math.max(0, Number(payload.deletedCount) || 0)} old snapshots removed.`;
    await loadReaderToolSnapshots({ silent: true });
    readerState.toolSnapshotStatus = status;
    readerState.toolSnapshotStatusLevel = "snapshots";
    renderReaderToolControls();
  } catch (error) {
    readerState.toolSnapshotStatus = sanitizeVisibleAgentError(error.message || "Could not clean snapshots.");
    readerState.toolSnapshotStatusLevel = "snapshots";
    renderReaderToolControls();
  }
}

async function restoreReaderToolSnapshot(snapshotId, { sessionId = getChatSessionId(), force = false } = {}) {
  const targetSnapshotId = normalizeText(snapshotId);
  const targetSessionId = normalizeText(sessionId);
  if (!targetSnapshotId || !targetSessionId) return null;
  readerState.toolSnapshotActionId = targetSnapshotId;
  renderReaderToolControls();
  try {
    const payload = await fetchAgentJson("/api/chat/tool-undo", {
      method: "POST",
      body: { sessionId: targetSessionId, snapshotId: targetSnapshotId, force }
    });
    clearToolSnapshotConflict(targetSnapshotId);
    const status = force ? "Snapshot force-restored." : "Snapshot restored.";
    await refreshCurrentNoteAfterToolUndo();
    await loadReaderToolSnapshots({ silent: true });
    readerState.toolSnapshotStatus = status;
    readerState.toolSnapshotStatusLevel = "snapshots";
    renderReaderToolControls();
    return payload;
  } catch (error) {
    if (error?.code === "snapshot_conflict") {
      markToolSnapshotConflict(targetSnapshotId, "Newer file changes detected.");
      readerState.toolSnapshotStatus = "Restore paused. Force only if you want to overwrite newer changes.";
      readerState.toolSnapshotStatusLevel = "snapshots";
      throw error;
    }
    readerState.toolSnapshotStatus = sanitizeVisibleAgentError(error.message || "Could not restore snapshot.");
    readerState.toolSnapshotStatusLevel = "snapshots";
    throw error;
  } finally {
    readerState.toolSnapshotActionId = "";
    renderReaderToolControls();
  }
}

async function redoReaderToolSnapshot(snapshotId, { sessionId = getChatSessionId(), force = true } = {}) {
  const targetSnapshotId = normalizeText(snapshotId);
  const targetSessionId = normalizeText(sessionId);
  if (!targetSnapshotId || !targetSessionId) return null;
  readerState.toolSnapshotActionId = targetSnapshotId;
  renderReaderToolControls();
  try {
    const payload = await fetchAgentJson("/api/chat/tool-redo", {
      method: "POST",
      body: { sessionId: targetSessionId, snapshotId: targetSnapshotId, force }
    });
    clearToolSnapshotConflict(targetSnapshotId);
    await refreshCurrentNoteAfterToolUndo();
    await loadReaderToolSnapshots({ silent: true });
    readerState.toolSnapshotStatus = "Snapshot redone.";
    readerState.toolSnapshotStatusLevel = "snapshots";
    renderReaderToolControls();
    return payload;
  } catch (error) {
    readerState.toolSnapshotStatus = sanitizeVisibleAgentError(error.message || "Could not redo snapshot.");
    readerState.toolSnapshotStatusLevel = "snapshots";
    throw error;
  } finally {
    readerState.toolSnapshotActionId = "";
    renderReaderToolControls();
  }
}

function setToolUndoState(snapshotId, state) {
  const targetSnapshotId = normalizeText(snapshotId);
  if (!targetSnapshotId) return;
  readerState.toolUndoStates = {
    ...readerState.toolUndoStates,
    [targetSnapshotId]: normalizeText(state)
  };
  renderReaderChatMessages({ preserveScrollTop: true });
}

function handleReaderToolPopoverClick(event) {
  const backButton = event.target.closest("#readerToolBack");
  if (backButton) {
    event.preventDefault();
    showReaderToolRootMenu();
    return;
  }

  const sectionButton = event.target.closest("[data-tool-section]");
  if (sectionButton) {
    event.preventDefault();
    showReaderToolSection(sectionButton.dataset.toolSection);
    return;
  }

  const modeButton = event.target.closest("[data-tool-mode]");
  if (modeButton) {
    event.preventDefault();
    setReaderWriteToolMode(modeButton.dataset.toolMode);
    return;
  }

  const fileFormatButton = event.target.closest("[data-file-generation-format]");
  if (fileFormatButton) {
    event.preventDefault();
    setReaderGenerationMode("file", { format: fileFormatButton.dataset.fileGenerationFormat });
    closeReaderToolMenu();
    elements.readerChatInput?.focus();
    return;
  }

  const action = event.target.closest("[data-tool-action]")?.dataset?.toolAction;
  if (action === "refresh") {
    event.preventDefault();
    loadReaderToolSnapshots({ silent: false });
    return;
  }
  if (action === "cleanup") {
    event.preventDefault();
    cleanupReaderToolSnapshots();
    return;
  }
  if (action === "attach-image") {
    event.preventDefault();
    elements.readerAttachmentInput?.click();
    return;
  }
  if (action === "generate-image") {
    event.preventDefault();
    setReaderGenerationMode("image");
    closeReaderToolMenu();
    elements.readerChatInput?.focus();
    return;
  }

  const undoButton = event.target.closest("[data-tool-snapshot-undo]");
  if (undoButton) {
    event.preventDefault();
    restoreReaderToolSnapshot(undoButton.dataset.toolSnapshotUndo, { force: true }).catch((error) => {
      setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    });
    return;
  }
}


function setReaderChatError(message = "") {
  if (!elements.readerChatError) return;
  elements.readerChatError.textContent = message ? sanitizeVisibleAgentError(message) : "";
  elements.readerChatError.hidden = !message;
}

