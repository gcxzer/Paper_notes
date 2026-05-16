function createDebugPanel(config) {
  const panelState = config.state;
  const panelElements = config.elements;
  const fetchPanelJson = config.fetchJson;

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
    const thinkMode = debugRunThinkSummary(run);
    const duration = run.durationMs ? formatRunTraceDuration(run.durationMs) : "";
    return [model, thinkMode, run.transport, duration].filter(Boolean).join(" · ");
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

  function renderDebugPanel() {
    if (!panelElements.dialog) return;
    renderDebugCleanupMenu();
    if (panelElements.error) {
      panelElements.error.hidden = !panelState.debugError;
      panelElements.error.textContent = panelState.debugError;
    }
    if (panelElements.runList) {
      if (panelState.debugLoading) {
        panelElements.runList.innerHTML = `<p class="debug-empty">Loading runs...</p>`;
      } else if (!panelState.debugRuns.length) {
        panelElements.runList.innerHTML = `<p class="debug-empty">No debug logs yet.</p>`;
      } else {
        panelElements.runList.innerHTML = panelState.debugRuns.map((rawRun) => {
          const run = normalizeDebugRun(rawRun);
          if (!run) return "";
          const active = panelState.activeDebugRun?.requestId === run.requestId;
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
    if (panelElements.runDetail) {
      panelElements.runDetail.innerHTML = renderDebugRunDetail(panelState.activeDebugRun);
    }
  }

  function renderDebugCleanupMenu() {
    if (panelElements.cleanupMenu) {
      panelElements.cleanupMenu.hidden = !panelState.debugCleanupMenuOpen;
    }
    if (panelElements.cleanupButton) {
      panelElements.cleanupButton.setAttribute("aria-expanded", String(panelState.debugCleanupMenuOpen));
    }
  }

  function setDebugCleanupMenuOpen(open) {
    panelState.debugCleanupMenuOpen = Boolean(open);
    renderDebugCleanupMenu();
  }

  function renderDebugRunDetail(rawRun) {
    const run = normalizeDebugRun(rawRun);
    if (!run) return `<p class="debug-empty">Select a run to inspect its events.</p>`;
    const error = run.error ? JSON.stringify(run.error, null, 2) : "";
    const debugEvents = run.events.filter((event) => normalizeText(event?.type) !== "work_trace_delta");
    const events = debugEvents.length
      ? debugEvents.map((event) => {
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

  async function loadDebugRuns({ selectId = "" } = {}) {
    panelState.debugLoading = true;
    panelState.debugError = "";
    renderDebugPanel();
    try {
      const payload = await fetchPanelJson("/api/debug/runs?limit=50");
      panelState.debugRuns = Array.isArray(payload.runs) ? payload.runs.map(normalizeDebugRun).filter(Boolean) : [];
      const targetId = selectId || panelState.activeDebugRun?.requestId || panelState.debugRuns[0]?.requestId || "";
      if (targetId) {
        await loadDebugRunDetail(targetId, { render: false });
      } else {
        panelState.activeDebugRun = null;
      }
    } catch (error) {
      panelState.debugError = sanitizeVisibleAgentError(error.message || "Could not load debug logs.");
    } finally {
      panelState.debugLoading = false;
      renderDebugPanel();
    }
  }

  async function loadDebugRunDetail(requestId, { render = true } = {}) {
    const id = normalizeText(requestId);
    if (!id) return;
    try {
      const payload = await fetchPanelJson(`/api/debug/runs/${encodeURIComponent(id)}`);
      panelState.activeDebugRun = normalizeDebugRun(payload.run) || null;
      panelState.debugError = "";
    } catch (error) {
      panelState.debugError = sanitizeVisibleAgentError(error.message || "Could not load debug run.");
    }
    if (render) renderDebugPanel();
  }

  async function openDebugPanel(requestId = "") {
    if (typeof config.beforeOpen === "function") config.beforeOpen();
    panelState.debugError = "";
    if (panelElements.dialog && !panelElements.dialog.open) panelElements.dialog.showModal();
    await loadDebugRuns({ selectId: normalizeText(requestId) });
  }

  function closeDebugPanel() {
    panelElements.dialog?.close();
    if (typeof config.afterClose === "function") config.afterClose();
  }

  async function cleanupDebugRuns(maxAgeDays = 30) {
    panelState.debugError = "";
    setDebugCleanupMenuOpen(false);
    try {
      await fetchPanelJson("/api/debug/runs/cleanup", {
        method: "POST",
        body: { maxAgeDays, keep: 200 }
      });
      await loadDebugRuns();
    } catch (error) {
      panelState.debugError = sanitizeVisibleAgentError(error.message || "Could not clean debug logs.");
      renderDebugPanel();
    }
  }

  async function copyActiveDebugRun() {
    if (!panelState.activeDebugRun) return;
    try {
      await copyTextToClipboard(JSON.stringify(panelState.activeDebugRun, null, 2));
    } catch (error) {
      panelState.debugError = config.copyError || "Could not copy debug JSON.";
      renderDebugPanel();
    }
  }

  return {
    cleanupDebugRuns,
    closeDebugPanel,
    copyActiveDebugRun,
    loadDebugRunDetail,
    loadDebugRuns,
    normalizeDebugRun,
    openDebugPanel,
    renderDebugPanel,
    setDebugCleanupMenuOpen
  };
}
