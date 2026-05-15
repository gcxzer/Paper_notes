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
  const thinkMode = debugRunThinkSummary(run);
  const duration = run.durationMs ? formatRunTraceDuration(run.durationMs) : "";
  return [model, thinkMode, duration].filter(Boolean).join(" · ");
}

function debugRunThinkSummary(run) {
  const provider = normalizeText(run?.provider).toLowerCase();
  const model = normalizeText(run?.model).toLowerCase();
  const metadata = run?.metadata && typeof run.metadata === "object" ? run.metadata : {};
  const requestOptions = metadata.requestOptions && typeof metadata.requestOptions === "object" ? metadata.requestOptions : {};
  const reasoning = requestOptions.reasoning && typeof requestOptions.reasoning === "object" ? requestOptions.reasoning : {};
  const gptMode = normalizeText(metadata.gptThinkMode || metadata.gpt_think_mode).toLowerCase();
  const gptEffort = normalizeText(reasoning.effort).toLowerCase();
  if (provider === "openai" || provider === "codex-oauth") {
    const effort = gptMode || (gptEffort === "none" ? "off" : gptEffort);
    if (effort === "off" || effort === "none") return "Think off";
    if (["low", "medium", "high", "xhigh"].includes(effort)) return `Think ${debugThinkLabel(effort)}`;
    return "";
  }
  if (provider === "gemini") {
    const geminiMode = normalizeText(metadata.geminiThinkMode || metadata.gemini_think_mode).toLowerCase();
    const thinkingConfig = requestOptions.thinkingConfig && typeof requestOptions.thinkingConfig === "object"
      ? requestOptions.thinkingConfig
      : requestOptions.thinking_config && typeof requestOptions.thinking_config === "object"
        ? requestOptions.thinking_config
        : {};
    const level = normalizeText(thinkingConfig.thinkingLevel || thinkingConfig.thinking_level).toLowerCase();
    const effort = geminiMode || (level === "minimal" ? "off" : level);
    if (effort === "off" || effort === "minimal") return "Think off";
    if (["low", "medium", "high"].includes(effort)) return `Think ${debugThinkLabel(effort)}`;
    return "";
  }
  if (provider === "anthropic") {
    const anthropicMode = normalizeText(metadata.anthropicThinkMode || metadata.anthropic_think_mode).toLowerCase();
    const thinking = requestOptions.thinking && typeof requestOptions.thinking === "object" ? requestOptions.thinking : {};
    const outputConfig = requestOptions.output_config && typeof requestOptions.output_config === "object"
      ? requestOptions.output_config
      : requestOptions.outputConfig && typeof requestOptions.outputConfig === "object"
        ? requestOptions.outputConfig
        : {};
    const thinkingType = normalizeText(thinking.type).toLowerCase();
    if (anthropicMode === "off" || thinkingType === "disabled") return "Think off";
    const effort = anthropicMode || normalizeText(outputConfig.effort).toLowerCase();
    if (["low", "medium", "high", "xhigh", "max"].includes(effort)) return `Think ${debugThinkLabel(effort)}`;
    if (thinkingType === "adaptive") return "Think on";
    return "";
  }
  const thinking = requestOptions.thinking && typeof requestOptions.thinking === "object" ? requestOptions.thinking : {};
  const explicitMode = normalizeText(metadata.deepseekThinkMode || metadata.deepseek_think_mode).toLowerCase();
  const reasoningEffort = normalizeText(requestOptions.reasoning_effort || requestOptions.reasoningEffort).toLowerCase();
  const thinkingType = normalizeText(thinking.type).toLowerCase();
  const hasThinkSignal = Boolean(explicitMode || reasoningEffort || thinkingType);
  if (provider !== "deepseek" || (!model.includes("pro") && !hasThinkSignal)) return "";
  if (explicitMode === "off" || thinkingType === "disabled") return "Think off";
  const effort = explicitMode || reasoningEffort;
  if (effort === "high" || effort === "max") return `Think ${debugThinkLabel(effort)}`;
  if (thinkingType === "enabled") return "Think on";
  return "";
}

function debugThinkLabel(effort) {
  return {
    low: "Low",
    medium: "Medium",
    high: "High",
    xhigh: "XHigh",
    max: "Max",
  }[normalizeText(effort).toLowerCase()] || normalizeText(effort);
}

function renderReaderDebugDialog() {
  if (!elements.readerDebugDialog) return;
  renderReaderDebugCleanupMenu();
  if (elements.readerDebugError) {
    elements.readerDebugError.hidden = !readerState.debugError;
    elements.readerDebugError.textContent = readerState.debugError;
  }
  if (elements.readerDebugRunList) {
    if (readerState.debugLoading) {
      elements.readerDebugRunList.innerHTML = `<p class="debug-empty">Loading runs...</p>`;
    } else if (!readerState.debugRuns.length) {
      elements.readerDebugRunList.innerHTML = `<p class="debug-empty">No debug logs yet.</p>`;
    } else {
      elements.readerDebugRunList.innerHTML = readerState.debugRuns.map((rawRun) => {
        const run = normalizeDebugRun(rawRun);
        if (!run) return "";
        const active = readerState.activeDebugRun?.requestId === run.requestId;
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
  if (elements.readerDebugRunDetail) {
    elements.readerDebugRunDetail.innerHTML = renderReaderDebugRunDetail(readerState.activeDebugRun);
  }
}

function renderReaderDebugCleanupMenu() {
  if (elements.readerCleanupDebugMenu) {
    elements.readerCleanupDebugMenu.hidden = !readerState.debugCleanupMenuOpen;
  }
  if (elements.readerCleanupDebugRuns) {
    elements.readerCleanupDebugRuns.setAttribute("aria-expanded", String(readerState.debugCleanupMenuOpen));
  }
}

function setReaderDebugCleanupMenuOpen(open) {
  readerState.debugCleanupMenuOpen = Boolean(open);
  renderReaderDebugCleanupMenu();
}

function renderReaderDebugRunDetail(rawRun) {
  const run = normalizeDebugRun(rawRun);
  if (!run) return `<p class="debug-empty">Select a run to inspect its events.</p>`;
  const error = run.error ? JSON.stringify(run.error, null, 2) : "";
  const debugEvents = run.events.filter((event) => normalizeText(event?.type) !== "work_trace_delta");
  const events = debugEvents.length
    ? debugEvents.map((event, index) => {
      const type = normalizeText(event?.type) || "event";
      const message = normalizeText(event?.message);
      const data = debugEventDataForDisplay(event);
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

function debugEventDataForDisplay(event) {
  if (!event?.data || typeof event.data !== "object") return "";
  const type = normalizeText(event.type);
  const data = { ...event.data };
  if (type === "work_trace_item" || type === "work_trace_delta") {
    delete data.text;
    delete data.delta;
  }
  const keys = Object.keys(data);
  if (!keys.length) return "";
  return JSON.stringify(data, null, 2);
}

async function loadReaderDebugRuns({ selectId = "" } = {}) {
  readerState.debugLoading = true;
  readerState.debugError = "";
  renderReaderDebugDialog();
  try {
    const payload = await fetchAgentJson("/api/debug/runs?limit=50");
    readerState.debugRuns = Array.isArray(payload.runs) ? payload.runs.map(normalizeDebugRun).filter(Boolean) : [];
    const targetId = selectId || readerState.activeDebugRun?.requestId || readerState.debugRuns[0]?.requestId || "";
    if (targetId) {
      await loadReaderDebugRunDetail(targetId, { render: false });
    } else {
      readerState.activeDebugRun = null;
    }
  } catch (error) {
    readerState.debugError = sanitizeVisibleAgentError(error.message || "Could not load debug logs.");
  } finally {
    readerState.debugLoading = false;
    renderReaderDebugDialog();
  }
}

async function loadReaderDebugRunDetail(requestId, { render = true } = {}) {
  const id = normalizeText(requestId);
  if (!id) return;
  try {
    const payload = await fetchAgentJson(`/api/debug/runs/${encodeURIComponent(id)}`);
    readerState.activeDebugRun = normalizeDebugRun(payload.run) || null;
    readerState.debugError = "";
  } catch (error) {
    readerState.debugError = sanitizeVisibleAgentError(error.message || "Could not load debug run.");
  }
  if (render) renderReaderDebugDialog();
}

async function openReaderDebugDialog(requestId = "") {
  if (elements.readerDebugDialog && !elements.readerDebugDialog.open) elements.readerDebugDialog.showModal();
  await loadReaderDebugRuns({ selectId: normalizeText(requestId) });
}

function closeReaderDebugDialog() {
  elements.readerDebugDialog?.close();
}

function canScrollDebugElement(element, deltaY) {
  if (!element || Math.abs(deltaY) < 1) return false;
  const overflow = element.scrollHeight - element.clientHeight;
  if (overflow <= 1) return false;
  if (deltaY > 0) return element.scrollTop < overflow - 1;
  return element.scrollTop > 1;
}

function handleReaderDebugWheel(event) {
  if (!elements.readerDebugDialog?.open) return;
  const deltaY = Number(event.deltaY) || 0;
  if (Math.abs(deltaY) < 1) return;
  const candidates = [
    event.target?.closest?.(".debug-run-detail, .debug-run-list"),
    elements.readerDebugRunDetail,
    elements.readerDebugRunList,
    elements.readerDebugDialog
  ].filter(Boolean);
  const target = candidates.find((element) => canScrollDebugElement(element, deltaY));
  if (!target) return;
  target.scrollTop += deltaY;
  event.preventDefault();
}

async function cleanupReaderDebugRunsAction(maxAgeDays = 30) {
  readerState.debugError = "";
  setReaderDebugCleanupMenuOpen(false);
  try {
    await fetchAgentJson("/api/debug/runs/cleanup", {
      method: "POST",
      body: { maxAgeDays, keep: 200 }
    });
    await loadReaderDebugRuns();
  } catch (error) {
    readerState.debugError = sanitizeVisibleAgentError(error.message || "Could not clean debug logs.");
    renderReaderDebugDialog();
  }
}

async function copyActiveReaderDebugRun() {
  if (!readerState.activeDebugRun) return;
  try {
    await copyTextToClipboard(JSON.stringify(readerState.activeDebugRun, null, 2));
  } catch (error) {
    readerState.debugError = "Could not copy debug log.";
    renderReaderDebugDialog();
  }
}
