function setRagSettingsError(message = "") {
  if (!elements.ragSettingsError) return;
  elements.ragSettingsError.textContent = message;
  elements.ragSettingsError.hidden = !message;
}

function ragStatusForNote(noteId) {
  return state.ragStatuses?.[noteId] || null;
}

function ragStatusTone(status) {
  if (!status) return "muted";
  if (status.error) return "error";
  if (status.ready) return "ready";
  return "missing";
}

function ragStatusLabel(status) {
  if (!status) return "Unknown";
  if (status.error) return status.error;
  if (status.ready) return "Indexed";
  const qdrantReady = Boolean(status.indexes?.qdrant?.exists);
  const bm25Ready = Boolean(status.indexes?.bm25?.exists);
  if (qdrantReady || bm25Ready) return "Partially indexed";
  return "Not indexed";
}

function ragFileName(path) {
  const text = normalizeText(path);
  if (!text) return "";
  return text.split(/[\\/]/).filter(Boolean).pop() || text;
}

function ragIndexPartLabel(status, key, label) {
  const exists = Boolean(status?.indexes?.[key]?.exists);
  return `
    <span class="rag-index-part${exists ? " is-ready" : ""}">
      <span class="rag-index-dot" aria-hidden="true"></span>
      ${escapeHtml(label)}
    </span>
  `;
}

function renderRagSettingsSummary(notes) {
  if (!elements.ragSettingsSummary) return;
  const statuses = notes.map((note) => ragStatusForNote(normalizeText(note.id))).filter(Boolean);
  const indexed = statuses.filter((status) => status.ready).length;
  const errors = statuses.filter((status) => status.error).length;
  const pending = Math.max(0, notes.length - indexed - errors);
  elements.ragSettingsSummary.innerHTML = `
    <div class="rag-summary-card is-total">
      <span>Papers</span>
      <strong>${notes.length}</strong>
    </div>
    <div class="rag-summary-card is-ready">
      <span>Indexed</span>
      <strong>${indexed}</strong>
    </div>
    <div class="rag-summary-card is-pending">
      <span>${state.ragLoading ? "Checking" : "Pending"}</span>
      <strong>${pending}</strong>
    </div>
  `;
}

function renderRagSettingsDialog() {
  if (!elements.ragSettingsList) return;
  const notes = Array.isArray(state.library?.notes) ? state.library.notes : [];
  renderRagSettingsSummary(notes);
  if (state.ragLoading && !notes.length) {
    elements.ragSettingsList.innerHTML = `<p class="settings-empty rag-settings-empty">Loading RAG status...</p>`;
    return;
  }
  if (!notes.length) {
    elements.ragSettingsList.innerHTML = `<p class="settings-empty rag-settings-empty">No papers in this workspace.</p>`;
    return;
  }

  elements.ragSettingsList.innerHTML = notes.map((note) => {
    const noteId = normalizeText(note.id);
    const status = ragStatusForNote(noteId);
    const busy = state.ragBusyNoteId === noteId;
    const disabled = state.ragLoading || Boolean(state.ragBusyNoteId);
    const tone = ragStatusTone(status);
    const label = state.ragLoading && !status ? "Checking..." : ragStatusLabel(status);
    const pdfPath = normalizeText(status?.pdfPath || note.href || "");
    const fileName = ragFileName(pdfPath);
    return `
      <article class="rag-settings-row is-${escapeHtml(tone)}">
        <div class="rag-settings-mark" aria-hidden="true">R</div>
        <div class="rag-settings-copy">
          <div class="rag-settings-title-row">
            <strong>${escapeHtml(note.title || "Untitled Paper")}</strong>
            <span class="rag-status-pill is-${escapeHtml(tone)}">${escapeHtml(label)}</span>
          </div>
          <div class="rag-settings-path" title="${escapeHtml(pdfPath || "No PDF path available")}">
            <span>${escapeHtml(fileName || "No PDF path available")}</span>
          </div>
          <div class="rag-index-parts" aria-label="Index parts">
            ${ragIndexPartLabel(status, "qdrant", "Vector")}
            ${ragIndexPartLabel(status, "bm25", "BM25")}
          </div>
        </div>
        <div class="rag-settings-row-actions">
          <button class="toolbar-button toolbar-button-primary" type="button" data-rag-index="${escapeHtml(noteId)}"${disabled ? " disabled" : ""}>${busy ? "Indexing..." : "Index"}</button>
          <button class="toolbar-button" type="button" data-rag-rebuild="${escapeHtml(noteId)}"${disabled ? " disabled" : ""}>Rebuild</button>
        </div>
      </article>
    `;
  }).join("");
}

async function loadRagSettings() {
  const notes = Array.isArray(state.library?.notes) ? state.library.notes : [];
  state.ragLoading = true;
  setRagSettingsError("");
  renderRagSettingsDialog();
  try {
    const statuses = await Promise.all(notes.map(async (note) => {
      const noteId = normalizeText(note.id);
      try {
        const status = await fetchJson(`/api/rag/status?noteId=${encodeURIComponent(noteId)}`);
        return [noteId, status];
      } catch (error) {
        return [noteId, { error: error.message || "Status failed" }];
      }
    }));
    state.ragStatuses = Object.fromEntries(statuses);
  } finally {
    state.ragLoading = false;
    renderRagSettingsDialog();
  }
}

async function buildRagIndex(noteId, { rebuild = false } = {}) {
  const cleanNoteId = normalizeText(noteId);
  if (!cleanNoteId || state.ragBusyNoteId) return;
  state.ragBusyNoteId = cleanNoteId;
  setRagSettingsError("");
  renderRagSettingsDialog();
  try {
    const status = await fetchJson("/api/rag/index", {
      method: "POST",
      body: { noteId: cleanNoteId, rebuild }
    });
    state.ragStatuses = { ...state.ragStatuses, [cleanNoteId]: status };
  } catch (error) {
    setRagSettingsError(error.message || "RAG index failed.");
  } finally {
    state.ragBusyNoteId = "";
    renderRagSettingsDialog();
  }
}

async function openRagSettingsDialog() {
  closeSettingsMenu();
  clearSettingsPanelUrl();
  setRagSettingsError("");
  renderRagSettingsDialog();
  elements.ragSettingsDialog?.showModal();
  await loadRagSettings();
}

function closeRagSettingsDialog() {
  setRagSettingsError("");
  elements.ragSettingsDialog?.close();
  clearSettingsPanelUrl();
}
