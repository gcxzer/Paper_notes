function formatRunTraceDuration(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs || 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes && seconds) return `${minutes}m ${seconds}s`;
  if (minutes) return `${minutes}m`;
  return `${seconds}s`;
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function normalizeDebugRun(rawRun) {
  if (!rawRun || typeof rawRun !== "object") return null;
  return {
    requestId: normalizeText(rawRun.requestId || rawRun.request_id),
    status: normalizeText(rawRun.status) || "unknown",
    provider: normalizeText(rawRun.provider),
    model: normalizeText(rawRun.model),
    transport: normalizeText(rawRun.transport),
    sessionId: normalizeText(rawRun.sessionId || rawRun.session_id),
    noteId: normalizeText(rawRun.noteId || rawRun.note_id),
    startedAt: normalizeText(rawRun.startedAt || rawRun.started_at),
    finishedAt: normalizeText(rawRun.finishedAt || rawRun.finished_at),
    durationMs: Number(rawRun.durationMs || rawRun.duration_ms || 0),
    errorPreview: normalizeText(rawRun.errorPreview || rawRun.error_preview),
    finalMessagePreview: normalizeText(rawRun.finalMessagePreview || rawRun.final_message_preview),
    error: rawRun.error && typeof rawRun.error === "object" ? rawRun.error : null,
    events: Array.isArray(rawRun.events) ? rawRun.events : [],
    transcriptPath: normalizeText(rawRun.transcriptPath || rawRun.transcript_path),
    metadata: rawRun.metadata && typeof rawRun.metadata === "object" ? rawRun.metadata : {}
  };
}

function debugRunTitle(run) {
  const started = run.startedAt ? new Date(run.startedAt) : null;
  const time = started && Number.isFinite(started.getTime()) ? started.toLocaleString() : "Unknown time";
  return `${time} · ${run.status}`;
}

function debugRunSummary(run) {
  const model = [run.provider, run.model].filter(Boolean).join(" / ") || "No model";
  const duration = run.durationMs ? formatRunTraceDuration(run.durationMs) : "";
  return [model, run.transport, duration].filter(Boolean).join(" · ");
}

function renderDebugDialog() {
  if (!elements.debugDialog) return;
  renderDebugCleanupMenu();
  if (elements.debugError) {
    elements.debugError.hidden = !state.debugError;
    elements.debugError.textContent = state.debugError;
  }
  if (elements.debugRunList) {
    if (state.debugLoading) {
      elements.debugRunList.innerHTML = `<p class="debug-empty">Loading runs...</p>`;
    } else if (!state.debugRuns.length) {
      elements.debugRunList.innerHTML = `<p class="debug-empty">No debug logs yet.</p>`;
    } else {
      elements.debugRunList.innerHTML = state.debugRuns.map((rawRun) => {
        const run = normalizeDebugRun(rawRun);
        if (!run) return "";
        const active = state.activeDebugRun?.requestId === run.requestId;
        return `
          <button class="debug-run-row${active ? " is-active" : ""}" type="button" data-debug-run-id="${escapeHtml(run.requestId)}">
            <strong>${escapeHtml(debugRunTitle(run))}</strong>
            <span>${escapeHtml(debugRunSummary(run))}</span>
            ${run.errorPreview ? `<small>${escapeHtml(run.errorPreview)}</small>` : ""}
          </button>
        `;
      }).join("");
    }
  }
  if (elements.debugRunDetail) {
    elements.debugRunDetail.innerHTML = renderDebugRunDetail(state.activeDebugRun);
  }
}

function renderDebugCleanupMenu() {
  if (elements.cleanupDebugMenu) {
    elements.cleanupDebugMenu.hidden = !state.debugCleanupMenuOpen;
  }
  if (elements.cleanupDebugRuns) {
    elements.cleanupDebugRuns.setAttribute("aria-expanded", String(state.debugCleanupMenuOpen));
  }
}

function setDebugCleanupMenuOpen(open) {
  state.debugCleanupMenuOpen = Boolean(open);
  renderDebugCleanupMenu();
}

function renderDebugRunDetail(rawRun) {
  const run = normalizeDebugRun(rawRun);
  if (!run) return `<p class="debug-empty">Select a run to inspect its events.</p>`;
  const error = run.error ? JSON.stringify(run.error, null, 2) : "";
  const events = run.events.length
    ? run.events.map((event, index) => {
      const type = normalizeText(event?.type) || "event";
      const message = normalizeText(event?.message);
      const data = event?.data && typeof event.data === "object" ? JSON.stringify(event.data, null, 2) : "";
      return `
        <li>
          <strong>${escapeHtml(type)}</strong>
          ${message ? `<span>${escapeHtml(message)}</span>` : ""}
          ${data ? `<code>${escapeHtml(data.slice(0, 1200))}</code>` : ""}
        </li>
      `;
    }).join("")
    : `<li><span>No recorded events.</span></li>`;
  return `
    <section class="debug-detail-section">
      <h4>${escapeHtml(run.requestId || "Debug run")}</h4>
      <p>${escapeHtml(debugRunSummary(run))}</p>
      <dl class="debug-kv">
        <dt>Status</dt><dd>${escapeHtml(run.status)}</dd>
        <dt>Session</dt><dd>${escapeHtml(run.sessionId || "none")}</dd>
        <dt>Note</dt><dd>${escapeHtml(run.noteId || "none")}</dd>
        <dt>Transcript</dt><dd>${escapeHtml(run.transcriptPath || "not recorded")}</dd>
      </dl>
      ${error ? `<pre class="debug-error-block">${escapeHtml(error)}</pre>` : ""}
      ${run.finalMessagePreview ? `<p class="debug-preview">${escapeHtml(run.finalMessagePreview)}</p>` : ""}
      <ol class="debug-events">${events}</ol>
    </section>
  `;
}

async function loadDebugRuns({ selectId = "" } = {}) {
  state.debugLoading = true;
  state.debugError = "";
  renderDebugDialog();
  try {
    const payload = await fetchJson("/api/debug/runs?limit=50");
    state.debugRuns = Array.isArray(payload.runs) ? payload.runs.map(normalizeDebugRun).filter(Boolean) : [];
    const targetId = selectId || state.activeDebugRun?.requestId || state.debugRuns[0]?.requestId || "";
    if (targetId) {
      await loadDebugRunDetail(targetId, { render: false });
    } else {
      state.activeDebugRun = null;
    }
  } catch (error) {
    state.debugError = sanitizeVisibleAgentError(error.message || "Could not load debug logs.");
  } finally {
    state.debugLoading = false;
    renderDebugDialog();
  }
}

async function loadDebugRunDetail(requestId, { render = true } = {}) {
  const id = normalizeText(requestId);
  if (!id) return;
  try {
    const payload = await fetchJson(`/api/debug/runs/${encodeURIComponent(id)}`);
    state.activeDebugRun = normalizeDebugRun(payload.run) || null;
    state.debugError = "";
  } catch (error) {
    state.debugError = sanitizeVisibleAgentError(error.message || "Could not load debug run.");
  }
  if (render) renderDebugDialog();
}

async function openDebugDialog(requestId = "") {
  closeSettingsMenu();
  state.debugError = "";
  if (elements.debugDialog && !elements.debugDialog.open) elements.debugDialog.showModal();
  await loadDebugRuns({ selectId: normalizeText(requestId) });
}

function closeDebugDialog() {
  elements.debugDialog?.close();
  clearSettingsPanelUrl();
}

function canScrollDebugElement(element, deltaY) {
  if (!element || Math.abs(deltaY) < 1) return false;
  const overflow = element.scrollHeight - element.clientHeight;
  if (overflow <= 1) return false;
  if (deltaY > 0) return element.scrollTop < overflow - 1;
  return element.scrollTop > 1;
}

function handleDebugWheel(event) {
  if (!elements.debugDialog?.open) return;
  const deltaY = Number(event.deltaY) || 0;
  if (Math.abs(deltaY) < 1) return;
  const candidates = [
    event.target?.closest?.(".debug-run-detail, .debug-run-list"),
    elements.debugRunDetail,
    elements.debugRunList,
    elements.debugDialog
  ].filter(Boolean);
  const target = candidates.find((element) => canScrollDebugElement(element, deltaY));
  if (!target) return;
  target.scrollTop += deltaY;
  event.preventDefault();
}

async function cleanupDebugRunsAction(maxAgeDays = 30) {
  state.debugError = "";
  setDebugCleanupMenuOpen(false);
  try {
    await fetchJson("/api/debug/runs/cleanup", {
      method: "POST",
      body: { maxAgeDays, keep: 200 }
    });
    await loadDebugRuns();
  } catch (error) {
    state.debugError = sanitizeVisibleAgentError(error.message || "Could not clean debug logs.");
    renderDebugDialog();
  }
}

async function copyActiveDebugRun() {
  if (!state.activeDebugRun) return;
  try {
    await copyTextToClipboard(JSON.stringify(state.activeDebugRun, null, 2));
  } catch (error) {
    state.debugError = "Could not copy debug JSON.";
    renderDebugDialog();
  }
}

