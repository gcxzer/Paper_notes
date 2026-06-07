function memoryTargetLabel(target = state.memoryTarget) {
  return target === "memory" ? "Project memory" : "User profile";
}

function memoryTargetPlaceholder(target = state.memoryTarget) {
  return target === "memory"
    ? "Add a stable project convention or environment fact"
    : "Add a durable user preference";
}

function memoryTargetHint(target = state.memoryTarget) {
  return target === "memory"
    ? "Project facts apply to this workspace."
    : "User preferences apply across chats.";
}

function currentMemoryEntries() {
  return state.memoryEntries.filter((entry) => entry.target === state.memoryTarget);
}

function normalizeMemoryEntries(entries) {
  return (Array.isArray(entries) ? entries : []).map((entry) => ({
    id: normalizeText(entry.id),
    target: normalizeText(entry.target),
    index: Number(entry.index) || 0,
    content: normalizeText(entry.content),
    charCount: Number(entry.charCount) || normalizeText(entry.content).length
  })).filter((entry) => entry.id && entry.target && entry.content);
}

function setMemoryError(message = "") {
  elements.memoryError.textContent = message;
  elements.memoryError.hidden = !message;
}

function renderMemoryDialog() {
  if (!elements.memoryDialog) return;
  const entries = currentMemoryEntries();
  const editingEntry = state.memoryEntries.find((entry) => entry.id === state.memoryEditingId);

  elements.memoryTabs.forEach((tab) => {
    const active = tab.dataset.memoryTarget === state.memoryTarget;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });

  elements.memoryListTitle.textContent = memoryTargetLabel();
  elements.memoryCount.textContent = `${entries.length} saved`;
  elements.memoryContentLabel.textContent = editingEntry ? "Edit memory" : "New memory";
  if (elements.memoryComposerHint) {
    elements.memoryComposerHint.textContent = editingEntry ? "Update the saved fact." : memoryTargetHint();
  }
  elements.memoryContentInput.placeholder = memoryTargetPlaceholder();
  elements.saveMemoryEntry.textContent = editingEntry ? "Save" : "Add";
  elements.cancelMemoryEdit.hidden = !editingEntry;

  if (state.memoryLoading) {
    elements.memoryList.innerHTML = `<p class="memory-empty">Loading memory...</p>`;
    return;
  }

  if (!entries.length) {
    elements.memoryList.innerHTML = `
      <div class="memory-empty">
        <strong>No saved memories</strong>
        <span>Add one above when there is a durable preference or project fact.</span>
      </div>
    `;
    return;
  }

  elements.memoryList.innerHTML = entries.map((entry) => `
    <article class="memory-item${entry.id === state.memoryEditingId ? " is-editing" : ""}" data-memory-id="${escapeHtml(entry.id)}">
      <p title="${escapeHtml(entry.content)}">${escapeHtml(entry.content)}</p>
      <div class="memory-item-actions">
        <button class="toolbar-button" type="button" data-memory-edit="${escapeHtml(entry.id)}">Edit</button>
        <button class="toolbar-button toolbar-button-danger" type="button" data-memory-delete="${escapeHtml(entry.id)}">Delete</button>
      </div>
    </article>
  `).join("");
}

async function loadMemoryEntries() {
  state.memoryLoading = true;
  renderMemoryDialog();
  try {
    const payload = await fetchJson("/api/memory");
    state.memoryEntries = normalizeMemoryEntries(payload.entries);
  } catch (error) {
    setMemoryError(error.message || "Could not load memory.");
    console.error(error);
  } finally {
    state.memoryLoading = false;
    renderMemoryDialog();
  }
}

async function openMemoryDialog() {
  closeSettingsMenu();
  state.memoryEditingId = "";
  setMemoryError("");
  elements.memoryContentInput.value = "";
  elements.memoryDialog.showModal();
  renderMemoryDialog();
  await loadMemoryEntries();
  elements.memoryContentInput.focus();
}

function closeMemoryDialog() {
  state.memoryEditingId = "";
  setMemoryError("");
  elements.memoryDialog.close();
  clearSettingsPanelUrl();
}

function startMemoryEdit(id) {
  const entry = state.memoryEntries.find((item) => item.id === id);
  if (!entry) return;
  state.memoryTarget = entry.target;
  state.memoryEditingId = entry.id;
  elements.memoryContentInput.value = entry.content;
  setMemoryError("");
  renderMemoryDialog();
  elements.memoryContentInput.focus();
  elements.memoryContentInput.select();
}

function cancelMemoryEdit() {
  state.memoryEditingId = "";
  elements.memoryContentInput.value = "";
  setMemoryError("");
  renderMemoryDialog();
}

async function saveMemoryEntry() {
  const content = normalizeText(elements.memoryContentInput.value);
  if (!content) {
    setMemoryError("Memory cannot be empty.");
    return false;
  }

  const editingEntry = state.memoryEntries.find((entry) => entry.id === state.memoryEditingId);
  const body = editingEntry
    ? {
        action: "update",
        target: editingEntry.target,
        id: editingEntry.id,
        index: editingEntry.index,
        oldText: editingEntry.content,
        content
      }
    : {
        action: "add",
        target: state.memoryTarget,
        content
      };

  elements.saveMemoryEntry.disabled = true;
  try {
    const payload = await fetchJson("/api/memory", { method: "POST", body });
    state.memoryEntries = normalizeMemoryEntries(payload.entries);
    state.memoryEditingId = "";
    elements.memoryContentInput.value = "";
    setMemoryError("");
    renderMemoryDialog();
    return true;
  } catch (error) {
    setMemoryError(error.message || "Could not save memory.");
    console.error(error);
    return false;
  } finally {
    elements.saveMemoryEntry.disabled = false;
  }
}

async function saveMemoryDialog() {
  const hasDraft = Boolean(normalizeText(elements.memoryContentInput.value));
  if (state.memoryEditingId || hasDraft) {
    const saved = await saveMemoryEntry();
    if (!saved) return;
  }
  closeMemoryDialog();
}

async function deleteMemoryEntry(id) {
  const entry = state.memoryEntries.find((item) => item.id === id);
  if (!entry) return;

  try {
    const payload = await fetchJson("/api/memory", {
      method: "POST",
      body: {
        action: "delete",
        target: entry.target,
        id: entry.id,
        index: entry.index,
        oldText: entry.content
      }
    });
    state.memoryEntries = normalizeMemoryEntries(payload.entries);
    if (state.memoryEditingId === id) {
      state.memoryEditingId = "";
      elements.memoryContentInput.value = "";
    }
    setMemoryError("");
    renderMemoryDialog();
  } catch (error) {
    setMemoryError(error.message || "Could not delete memory.");
    console.error(error);
  }
}
