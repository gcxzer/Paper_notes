function renderChatProgress() {
  const progress = normalizeChatProgress(currentChatProgress());
  if (!progress) return "";
  if (!isChatSessionPending()) return "";
  const compactionMarkerHtml = renderContextCompactionMarker(progress.events, { running: true });
  const rows = progressInlineRows(progress);
  const activeToolIndex = activeProgressToolRowIndex(rows);
  const rowsHtml = rows.map((row, index) => renderProgressInlineRow(row, { active: index === activeToolIndex })).join("");
  return `${compactionMarkerHtml}${rowsHtml}`;
}

function renderManualContextCompactionProgress() {
  if (!readerState.contextCompacting) return "";
  return renderContextCompactionDivider("Compacting context", "running");
}

function renderContextCompactionMarker(events, { running = false } = {}) {
  const normalizedEvents = Array.isArray(events) ? events : [];
  const hasCompacted = normalizedEvents.some((event) => normalizeText(event?.type) === "context_compressed");
  const hasCompacting = normalizedEvents.some((event) => normalizeText(event?.type) === "context_compressing");
  if (hasCompacted) return renderContextCompactionDivider("Context compacted", "done");
  if (hasCompacting && running) return renderContextCompactionDivider("Compacting context", "running");
  return "";
}

function messageContextCompactionMarker(message, options = {}) {
  const normalized = normalizeChatMessage(message);
  if (normalized.role !== "assistant") return "";
  return renderContextCompactionMarker(normalized.runTrace?.events, options);
}

function renderContextCompactionDivider(text, state = "done") {
  const running = state === "running";
  return `
    <div class="ask-context-compaction-divider is-${escapeHtml(state)}" role="status" aria-live="polite">
      <span></span>
      <strong>
        ${running
          ? `<span class="ask-context-compaction-spinner" aria-hidden="true"></span>`
          : `<span class="ask-context-compaction-icon" aria-hidden="true">▧</span>`}
        <span>${escapeHtml(text)}</span>
      </strong>
      <span></span>
    </div>
  `;
}

function renderProgressInlineRow(row, { active = false } = {}) {
  const detailText = normalizeText(row.detail);
  const detail = escapeHtml(detailText);
  const type = progressInlineType(row.type);
  const activeClass = active && type === "tool" ? " is-active" : "";
  const textHtml = activeClass ? renderProgressInlineReadingText(detailText, row.at) : renderTraceInlineMarkdown(detailText);
  return `
    <div class="ask-message ask-message-assistant ask-message-progress-inline${activeClass}" role="status" aria-live="polite">
      <div class="ask-message-stack">
        <div class="ask-progress-inline${activeClass}">
          <span class="ask-progress-inline-type">${escapeHtml(workTraceItemLabel(type))}</span>
          <span class="ask-progress-inline-text" data-progress-text="${detail}" aria-label="${detail}">${textHtml}</span>
        </div>
      </div>
    </div>
  `;
}

function renderProgressInlineReadingText(text, startedAt = "") {
  const chars = Array.from(normalizeText(text));
  const stepSeconds = 0.032;
  const durationSeconds = Math.max(3.2, Math.min(9, chars.length * stepSeconds + 0.9));
  const startedMs = Date.parse(normalizeText(startedAt));
  const elapsedSeconds = Number.isFinite(startedMs) ? Math.max(0, (Date.now() - startedMs) / 1000) : 0;
  const phaseSeconds = elapsedSeconds % durationSeconds;
  return chars.map((char, index) => {
    const targetPhase = index * stepSeconds;
    const currentPhase = (phaseSeconds - targetPhase + durationSeconds) % durationSeconds;
    const delay = -currentPhase;
    return `<span class="ask-progress-inline-char" style="--progress-char-duration: ${durationSeconds.toFixed(3)}s; --progress-char-delay: ${delay.toFixed(3)}s" aria-hidden="true">${escapeHtml(char)}</span>`;
  }).join("");
}

function renderRunTraceSummary(trace, workTrace = null, classPrefix = "ask") {
  const normalized = normalizeRunTrace(trace);
  if (!normalized) return "";
  const duration = normalized.durationMs ? formatRunTraceDuration(normalized.durationMs) : "a moment";
  const workItems = runSummaryWorkItems(normalized, workTrace);
  const summaryKey = runSummaryStateKey(normalized);
  const expanded = Boolean(summaryKey && readerState.runSummaryOpen?.[summaryKey]);
  return `
    <div class="${classPrefix}-run-summary" data-run-summary-key="${escapeHtml(summaryKey)}">
      <div class="${classPrefix}-run-summary-row">
        <button class="${classPrefix}-run-summary-toggle" type="button" data-run-summary-toggle aria-expanded="${expanded ? "true" : "false"}">
          <span>Worked for ${escapeHtml(duration)}</span>
          <span class="${classPrefix}-run-summary-chevron" aria-hidden="true"></span>
        </button>
      </div>
      <div class="${classPrefix}-run-summary-body" data-run-summary-body${expanded ? "" : " hidden"}>
        ${workItems.length ? `
          <ol class="${classPrefix}-run-summary-events">
            ${workItems.map((item) => `
              <li>
                <span class="${classPrefix}-run-summary-type">${escapeHtml(workTraceItemLabel(item.type))}</span>
                <span>${renderTraceInlineMarkdown(item.text)}</span>
              </li>
            `).join("")}
          </ol>
        ` : `<p class="${classPrefix}-run-summary-empty">No visible work steps recorded.</p>`}
      </div>
    </div>
  `;
}

function runSummaryStateKey(trace) {
  const normalized = normalizeRunTrace(trace);
  if (!normalized) return "";
  return normalizeText(normalized.requestId)
    || [
      normalized.startedAt,
      normalized.finishedAt,
      normalized.durationMs,
      normalized.status,
    ].map((part) => normalizeText(part)).join("|");
}

function runSummaryWorkItems(trace, workTrace = null) {
  const startItem = startingRunStatusItem(trace);
  const workTraceItems = (normalizeWorkTrace(workTrace)?.items || [])
    .filter((item) => !isHiddenRunSummaryMessage(item.type, item.text));
  const items = [
    ...(startItem ? [startItem] : []),
    ...workTraceItems,
    ...runTraceVisibleWorkItems(trace, { includeToolEvents: !workTraceItems.length }),
  ];
  const compacted = sortTraceItemsChronologically(compactWorkTraceItems(items));
  const terminalItem = terminalRunStatusItem(trace);
  if (!compacted.length) return fallbackRunStatusItems(trace);
  return terminalItem && !hasEquivalentWorkTraceItem(compacted, terminalItem)
    ? [...compacted, terminalItem]
    : compacted;
}

function runTraceVisibleWorkItems(trace, { includeToolEvents = true } = {}) {
  const normalized = normalizeRunTrace(trace);
  if (!normalized?.events?.length) return [];
  return normalized.events.map((event) => runTraceEventWorkItem(event, { includeToolEvents })).filter(Boolean);
}

function runTraceEventWorkItem(event, { includeToolEvents = true } = {}) {
  const eventType = normalizeText(event?.type);
  const message = sanitizeChatProgressDetail(event?.message);
  const data = event?.data && typeof event.data === "object" ? event.data : {};
  const text = sanitizeChatProgressDetail(data.text || data.delta || message);
  const traceType = normalizeText(data.traceType) || eventType;
  const nativeWebSearchText = providerNativeWebSearchText(data);
  if (eventType === "model_response" && nativeWebSearchText) {
    return {
      type: "tool",
      text: nativeWebSearchText,
      at: event.at,
      source: "provider",
      complete: true,
    };
  }
  if (!text || isHiddenRunSummaryMessage(eventType, text) || isStructuredToolCallProgressText(traceType, text)) return null;
  if (eventType === "work_trace_item" || eventType === "work_trace_delta") {
    return {
      type: traceType || "summary",
      text,
      at: event.at,
      source: normalizeText(data.source) || "provider",
    };
  }
  if (eventType === "tool_call" || eventType === "tool_result") {
    if (!includeToolEvents) return null;
    const name = normalizeText(data.name || data.toolName);
    return {
      type: name && (name === "skills_list" || name === "skill_view") ? "skill" : "tool",
      text,
      at: event.at,
      source: "runtime",
    };
  }
  if (eventType === "tool_error" || eventType === "tool_blocked" || eventType === "tool_warning") {
    return { type: "status", text, at: event.at, source: "runtime" };
  }
  if (isStatusProgressType(eventType) || isStatusProgressType(event.stage)) {
    return { type: "status", text, at: event.at, source: "runtime" };
  }
  if (eventType === "commentary") {
    return { type: "commentary", text, at: event.at, source: "runtime" };
  }
  if (eventType === "reasoning" || eventType === "summary") {
    return { type: eventType, text, at: event.at, source: "provider" };
  }
  return null;
}

function fallbackRunStatusItems(trace) {
  const normalized = normalizeRunTrace(trace);
  if (!normalized) return [];
  const items = [];
  if (normalized.startedAt) {
    items.push({
      type: "status",
      text: "Starting agent run.",
      at: normalized.startedAt,
      source: "runtime",
    });
  }
  const terminalItem = terminalRunStatusItem(normalized);
  if (terminalItem) items.push(terminalItem);
  return sortTraceItemsChronologically(compactWorkTraceItems(items));
}

function startingRunStatusItem(trace) {
  const normalized = normalizeRunTrace(trace);
  if (!normalized?.startedAt) return null;
  return {
    type: "status",
    text: "Starting agent run.",
    at: normalized.startedAt,
    source: "runtime",
  };
}

function terminalRunStatusItem(trace) {
  const normalized = normalizeRunTrace(trace);
  if (!normalized) return null;
  const terminalText = terminalRunStatusText(normalized.status, normalized.error);
  if (!terminalText) return null;
  return {
    type: "status",
    text: terminalText,
    at: normalized.finishedAt,
    source: "runtime",
  };
}

function terminalRunStatusText(status, error = "") {
  const normalized = normalizeText(status);
  if (normalized === "completed") return "Agent run completed.";
  if (normalized === "cancelled") return "Agent run cancelled.";
  if (normalized === "failed") return sanitizeChatProgressDetail(error) || "Agent run failed.";
  if (normalized === "stopped") return "Agent run stopped.";
  return "";
}

function isHiddenRunTraceMessage(type, text) {
  const normalizedType = normalizeText(type);
  const normalizedText = sanitizeChatProgressDetail(text);
  if (["model_request", "model_response", "model_delta", "completed", "tool_approval_resolved"].includes(normalizedType)) {
    return true;
  }
  return [
    "Agent run completed.",
    "Calling model provider.",
    "Model response received.",
    "Model provider returned a response.",
    "Receiving model response.",
  ].includes(normalizedText);
}

function isHiddenRunSummaryMessage(type, text) {
  const normalizedType = progressInlineType(type);
  const normalizedText = sanitizeChatProgressDetail(text);
  if (normalizedType === "status" && normalizedText === "Agent run started.") return true;
  return isHiddenRunTraceMessage(type, text);
}

function hasEquivalentWorkTraceItem(items, candidate) {
  const candidateType = normalizeText(candidate?.type);
  const candidateText = sanitizeChatProgressDetail(candidate?.text);
  return (items || []).some((item) => (
    normalizeText(item?.type) === candidateType
    && sanitizeChatProgressDetail(item?.text) === candidateText
  ));
}

function workTraceItemLabel(type) {
  const normalized = normalizeText(type);
  if (normalized === "skill") return "Skill";
  if (normalized === "tool") return "Tool";
  if (normalized === "status" || isStatusProgressType(normalized)) return "Status";
  if (normalized === "commentary") return "Progress";
  return "Think";
}
