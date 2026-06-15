function setRagSettingsError(message = "") {
  if (!elements.ragSettingsError) return;
  elements.ragSettingsError.textContent = message;
  elements.ragSettingsError.hidden = !message;
}

const RAG_ACTIVE_JOB_STATUSES = new Set(["queued", "running", "paused"]);
const RAG_TERMINAL_JOB_STATUSES = new Set(["succeeded", "failed"]);

function ragStatusForNote(noteId) {
  return state.ragStatuses?.[noteId] || null;
}

function ragProgressForNote(noteId) {
  return state.ragProgresses?.[noteId] || null;
}

function ragJobForNote(noteId) {
  return state.ragJobs?.[noteId] || null;
}

function ragJobStatus(job) {
  return normalizeText(job?.status);
}

function ragJobActive(job) {
  return RAG_ACTIVE_JOB_STATUSES.has(ragJobStatus(job));
}

function ragJobPaused(job) {
  return ragJobStatus(job) === "paused";
}

function refreshRagBusyNote() {
  const jobs = state.ragJobs || {};
  const active = Object.entries(jobs).find(([, job]) => ragJobActive(job));
  state.ragBusyNoteId = active?.[0] || "";
}

function setRagJob(noteId, job) {
  const cleanNoteId = normalizeText(noteId || job?.noteId);
  if (!cleanNoteId || !job) return null;
  const jobId = normalizeText(job.id || job.jobId);
  const nextJob = {
    ...(state.ragJobs?.[cleanNoteId] || {}),
    ...job,
    id: jobId,
    jobId,
    noteId: cleanNoteId
  };
  state.ragJobs = {
    ...(state.ragJobs || {}),
    [cleanNoteId]: nextJob
  };
  if (job.progress) setRagProgress(cleanNoteId, job.progress);
  refreshRagBusyNote();
  return nextJob;
}

function clearRagJob(noteId) {
  const cleanNoteId = normalizeText(noteId);
  if (!cleanNoteId || !state.ragJobs?.[cleanNoteId]) return;
  const next = { ...state.ragJobs };
  delete next[cleanNoteId];
  state.ragJobs = next;
  refreshRagBusyNote();
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

function normalizeRagProgress(payload) {
  const data = payload && typeof payload === "object" ? payload : {};
  const current = Number(data.current);
  const total = Number(data.total);
  const rawPercent = Number(data.percent);
  const percent = Number.isFinite(rawPercent)
    ? Math.max(0, Math.min(100, Math.round(rawPercent)))
    : 0;
  return {
    stage: normalizeText(data.stage) || "indexing",
    message: normalizeText(data.message || data.error) || "Indexing...",
    percent,
    current: Number.isFinite(current) ? Math.max(0, Math.round(current)) : null,
    total: Number.isFinite(total) ? Math.max(0, Math.round(total)) : null,
    error: normalizeText(data.error),
    code: normalizeText(data.code),
    status: normalizeText(data.status),
    jobId: normalizeText(data.jobId || data.id),
    seq: Number.isFinite(Number(data.seq)) ? Number(data.seq) : null,
    paused: Boolean(data.paused)
  };
}

function ragProgressDetail(progress) {
  if (!progress) return "";
  if (progress.total && progress.current != null) {
    return `${progress.message} ${progress.current}/${progress.total}`;
  }
  return progress.message;
}

function ragActionIcon(name) {
  const iconName = name === "play" ? "play" : "pause";
  return `<span class="ui-icon rag-action-icon" aria-hidden="true" style="--ui-icon-url: url('/node_modules/lucide-static/icons/${iconName}.svg'); --ui-icon-size: 14px;"></span>`;
}

function renderRagActionControls(noteId, { busy = false, paused = false, jobId = "", disabled = false } = {}) {
  const safeNoteId = escapeHtml(noteId);
  if (busy) {
    if (!jobId) {
      return `
        <div class="rag-settings-row-actions is-busy">
          <span class="rag-action-status"><span class="rag-action-spinner" aria-hidden="true"></span>Starting</span>
        </div>
      `;
    }
    return `
      <div class="rag-settings-row-actions is-busy">
        ${paused
          ? `<button class="toolbar-button toolbar-button-primary rag-control-button" type="button" data-rag-resume="${safeNoteId}">${ragActionIcon("play")}Resume</button>`
          : `<button class="toolbar-button rag-control-button" type="button" data-rag-pause="${safeNoteId}">${ragActionIcon("pause")}Pause</button>`}
      </div>
    `;
  }
  return `
    <div class="rag-settings-row-actions">
      <button class="toolbar-button${disabled ? "" : " toolbar-button-primary"}" type="button" data-rag-index="${safeNoteId}"${disabled ? " disabled" : ""}>Index</button>
      <button class="toolbar-button" type="button" data-rag-rebuild="${safeNoteId}"${disabled ? " disabled" : ""}>Rebuild</button>
    </div>
  `;
}

function renderRagProgress(progress) {
  if (!progress) return "";
  const detail = ragProgressDetail(progress);
  const stageLabels = {
    bm25: "BM25",
    captioning: "Image caption",
    chunking: "Chunking",
    complete: "Done",
    loading: "Loading",
    parsing: "LlamaParse",
    paused: "Paused",
    qdrant: "Vector index",
    queued: "Queued",
    resuming: "Resuming"
  };
  const stage = stageLabels[progress.stage] || progress.stage;
  return `
    <div class="rag-progress${progress.stage === "paused" || progress.status === "paused" ? " is-paused" : ""}" aria-label="RAG indexing progress">
      <div class="rag-progress-meta">
        <span>${escapeHtml(stage)}</span>
        <strong>${escapeHtml(String(progress.percent || 0))}%</strong>
      </div>
      <div class="rag-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${escapeHtml(String(progress.percent || 0))}">
        <span style="width: ${escapeHtml(String(progress.percent || 0))}%"></span>
      </div>
      <div class="rag-progress-detail">${escapeHtml(detail)}</div>
    </div>
  `;
}

function setRagProgress(noteId, payload) {
  const cleanNoteId = normalizeText(noteId);
  if (!cleanNoteId) return;
  state.ragProgresses = {
    ...(state.ragProgresses || {}),
    [cleanNoteId]: normalizeRagProgress(payload)
  };
}

function clearRagProgress(noteId) {
  const cleanNoteId = normalizeText(noteId);
  if (!cleanNoteId || !state.ragProgresses?.[cleanNoteId]) return;
  const next = { ...state.ragProgresses };
  delete next[cleanNoteId];
  state.ragProgresses = next;
}

function updateRagJobFromEvent(noteId, event, data = {}) {
  const cleanNoteId = normalizeText(data.noteId || noteId);
  if (!cleanNoteId) return null;
  const jobId = normalizeText(data.jobId || data.id);
  const existing = ragJobForNote(cleanNoteId);
  const status = normalizeText(data.status)
    || (event === "final" ? "succeeded" : "")
    || (event === "error" ? "failed" : "")
    || existing?.status
    || "running";
  const nextJob = {
    ...(existing || {}),
    id: jobId || normalizeText(existing?.id || existing?.jobId),
    jobId: jobId || normalizeText(existing?.jobId || existing?.id),
    noteId: cleanNoteId,
    requestId: normalizeText(data.requestId || existing?.requestId),
    status,
    active: RAG_ACTIVE_JOB_STATUSES.has(status),
    seq: Number.isFinite(Number(data.seq)) ? Number(data.seq) : existing?.seq || 0
  };
  if (event === "start" || event === "progress" || event === "done" || event === "error") {
    nextJob.progress = normalizeRagProgress(data);
    setRagProgress(cleanNoteId, data);
  }
  if (event === "final") {
    nextJob.result = data;
    nextJob.status = "succeeded";
    nextJob.active = false;
    state.ragStatuses = { ...state.ragStatuses, [cleanNoteId]: data };
    setRagProgress(cleanNoteId, { stage: "complete", message: "RAG indexing complete.", percent: 100, status: "succeeded", jobId: nextJob.jobId });
  }
  if (event === "error") {
    nextJob.error = data;
    nextJob.status = "failed";
    nextJob.active = false;
  }
  if (event === "done" && RAG_TERMINAL_JOB_STATUSES.has(status)) {
    nextJob.active = false;
  }
  return setRagJob(cleanNoteId, nextJob);
}

function removeRagJobStream(jobId) {
  const cleanJobId = normalizeText(jobId);
  if (!cleanJobId || !state.ragJobStreams?.[cleanJobId]) return;
  const next = { ...state.ragJobStreams };
  delete next[cleanJobId];
  state.ragJobStreams = next;
}

function scheduleRagProgressClear(noteId) {
  const cleanNoteId = normalizeText(noteId);
  if (!cleanNoteId) return;
  window.setTimeout(() => {
    const job = ragJobForNote(cleanNoteId);
    if (!ragJobActive(job)) {
      clearRagProgress(cleanNoteId);
      if (job && RAG_TERMINAL_JOB_STATUSES.has(ragJobStatus(job))) clearRagJob(cleanNoteId);
      renderRagSettingsDialog();
    }
  }, 1400);
}

function handleRagStreamEvent(noteId, event, data) {
  const job = updateRagJobFromEvent(noteId, event, data || {});
  if (event === "error") {
    setRagSettingsError(data?.error || data?.message || "RAG index failed.");
  }
  if (event === "done" && job && !ragJobActive(job)) {
    scheduleRagProgressClear(job.noteId);
  }
  renderRagSettingsDialog();
  return job;
}

async function connectRagJob(noteId, jobId, { afterSeq = 0 } = {}) {
  const cleanNoteId = normalizeText(noteId);
  const cleanJobId = normalizeText(jobId);
  if (!cleanNoteId || !cleanJobId || state.ragJobStreams?.[cleanJobId]) return;
  state.ragJobStreams = {
    ...(state.ragJobStreams || {}),
    [cleanJobId]: true
  };
  try {
    await fetchEventStream(`/api/rag/index/jobs/${encodeURIComponent(cleanJobId)}/events?after=${encodeURIComponent(String(afterSeq || 0))}`, {
      method: "GET",
      onEvent: ({ event, data }) => {
        handleRagStreamEvent(cleanNoteId, event, data);
      }
    });
  } catch (error) {
    if (!RAG_TERMINAL_JOB_STATUSES.has(ragJobStatus(ragJobForNote(cleanNoteId)))) {
      setRagSettingsError(error.message || "RAG progress stream disconnected.");
    }
  } finally {
    removeRagJobStream(cleanJobId);
    refreshRagBusyNote();
    renderRagSettingsDialog();
  }
}

async function loadRagJobStatuses(notes) {
  const jobs = await Promise.all(notes.map(async (note) => {
    const noteId = normalizeText(note.id);
    try {
      const payload = await fetchJson(`/api/rag/index/jobs?noteId=${encodeURIComponent(noteId)}`);
      return [noteId, payload.job || null];
    } catch (error) {
      return [noteId, null];
    }
  }));
  jobs.forEach(([noteId, job]) => {
    if (!job) {
      clearRagJob(noteId);
      return;
    }
    const status = ragJobStatus(job);
    if (!RAG_ACTIVE_JOB_STATUSES.has(status)) {
      if (job.result) state.ragStatuses = { ...state.ragStatuses, [noteId]: job.result };
      clearRagJob(noteId);
      return;
    }
    const nextJob = setRagJob(noteId, job);
    if (job.progress) setRagProgress(noteId, job.progress);
    void connectRagJob(noteId, nextJob.id || nextJob.jobId, { afterSeq: nextJob.seq || 0 });
  });
  refreshRagBusyNote();
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
    const job = ragJobForNote(noteId);
    const busy = ragJobActive(job) || state.ragBusyNoteId === noteId;
    const paused = ragJobPaused(job);
    const progress = ragProgressForNote(noteId);
    const disabled = state.ragLoading || busy || Boolean(state.ragBusyNoteId && state.ragBusyNoteId !== noteId);
    const tone = paused ? "paused" : ragStatusTone(status);
    const label = paused ? "Paused" : (busy ? "Indexing" : (state.ragLoading && !status ? "Checking..." : ragStatusLabel(status)));
    const pdfPath = normalizeText(status?.pdfPath || note.href || "");
    const fileName = ragFileName(pdfPath);
    const jobId = normalizeText(job?.id || job?.jobId);
    const progressHtml = renderRagProgress(progress);
    return `
      <article class="rag-settings-row is-${escapeHtml(tone)}${busy ? " is-indexing" : ""}${paused ? " is-paused" : ""}${progressHtml ? " has-progress" : ""}">
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
        ${renderRagActionControls(noteId, { busy, paused, jobId, disabled })}
        ${progressHtml}
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
    await loadRagJobStatuses(notes);
  } finally {
    state.ragLoading = false;
    renderRagSettingsDialog();
  }
}

async function buildRagIndex(noteId, { rebuild = false } = {}) {
  const cleanNoteId = normalizeText(noteId);
  if (!cleanNoteId || state.ragBusyNoteId) return;
  state.ragBusyNoteId = cleanNoteId;
  setRagProgress(cleanNoteId, { stage: "queued", message: "Starting RAG indexing.", percent: 0 });
  setRagSettingsError("");
  renderRagSettingsDialog();
  let streamError = null;
  try {
    await fetchEventStream("/api/rag/index/stream", {
      body: {
        noteId: cleanNoteId,
        rebuild,
        requestId: `rag-${Date.now()}-${Math.random().toString(36).slice(2)}`
      },
      onEvent: ({ event, data }) => {
        const job = handleRagStreamEvent(cleanNoteId, event, data);
        if (event === "start" && job?.id) {
          state.ragJobStreams = { ...(state.ragJobStreams || {}), [job.id]: true };
        }
        if (event === "error") {
          streamError = new Error(data?.error || data?.message || "RAG index failed.");
          streamError.code = data?.code || "";
        }
      }
    });
    if (streamError) throw streamError;
    scheduleRagProgressClear(cleanNoteId);
  } catch (error) {
    if (error.code === "stream_unsupported") {
      try {
        const status = await fetchJson("/api/rag/index", {
          method: "POST",
          body: { noteId: cleanNoteId, rebuild }
        });
        state.ragStatuses = { ...state.ragStatuses, [cleanNoteId]: status };
        setRagProgress(cleanNoteId, { stage: "complete", message: "RAG indexing complete.", percent: 100 });
      } catch (fallbackError) {
        setRagSettingsError(fallbackError.message || "RAG index failed.");
        setRagProgress(cleanNoteId, { stage: "error", message: fallbackError.message || "RAG index failed.", percent: 100 });
      }
    } else {
      setRagSettingsError(error.message || "RAG index failed.");
    }
  } finally {
    const job = ragJobForNote(cleanNoteId);
    if (job?.id) removeRagJobStream(job.id);
    state.ragBusyNoteId = "";
    refreshRagBusyNote();
    renderRagSettingsDialog();
  }
}

async function pauseRagIndex(noteId) {
  const cleanNoteId = normalizeText(noteId);
  const job = ragJobForNote(cleanNoteId);
  const jobId = normalizeText(job?.id || job?.jobId);
  if (!cleanNoteId || !jobId) return;
  setRagSettingsError("");
  try {
    const payload = await fetchJson(`/api/rag/index/jobs/${encodeURIComponent(jobId)}/pause`, { method: "POST" });
    if (payload.job) setRagJob(cleanNoteId, payload.job);
  } catch (error) {
    setRagSettingsError(error.message || "Failed to pause RAG indexing.");
  } finally {
    renderRagSettingsDialog();
  }
}

async function resumeRagIndex(noteId) {
  const cleanNoteId = normalizeText(noteId);
  const job = ragJobForNote(cleanNoteId);
  const jobId = normalizeText(job?.id || job?.jobId);
  if (!cleanNoteId || !jobId) return;
  setRagSettingsError("");
  try {
    const payload = await fetchJson(`/api/rag/index/jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
    const nextJob = payload.job ? setRagJob(cleanNoteId, payload.job) : job;
    void connectRagJob(cleanNoteId, jobId, { afterSeq: nextJob?.seq || 0 });
  } catch (error) {
    setRagSettingsError(error.message || "Failed to resume RAG indexing.");
  } finally {
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
  if (elements.ragSettingsDialog?.open) {
    elements.ragSettingsDialog.close();
  }
  clearSettingsPanelUrl();
}
