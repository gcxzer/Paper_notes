function normalizeChatProgress(progress) {
  if (!progress || typeof progress !== "object") return null;
  const events = Array.isArray(progress.events)
    ? progress.events.map((event) => ({
      type: normalizeText(event?.type),
      stage: normalizeText(event?.stage),
      detail: sanitizeChatProgressDetail(event?.detail),
      at: normalizeText(event?.at),
      data: event?.data && typeof event.data === "object" ? event.data : {}
    })).filter((event) => event.detail)
    : [];
  const visibleEvents = Array.isArray(progress.visibleEvents)
    ? progress.visibleEvents.map((event) => ({
      stage: normalizeText(event?.stage),
      detail: sanitizeChatProgressDetail(event?.detail),
      at: normalizeText(event?.at)
    })).filter((event) => event.detail)
    : [];
  return {
    requestId: normalizeText(progress.requestId),
    status: normalizeText(progress.status) || "running",
    stage: normalizeText(progress.visibleStage || progress.stage) || "working",
    detail: sanitizeChatProgressDetail(progress.visibleDetail || progress.detail),
    events,
    visibleEvents,
    workTrace: normalizeWorkTrace(progress.workTrace)
  };
}

function isTerminalChatProgressStatus(status) {
  return ["completed", "failed", "pending", "stopped", "cancelled"].includes(normalizeText(status));
}

function progressInlineRows(progress) {
  const rows = [];
  if (progress.workTrace?.items?.length) {
    rows.push(...progress.workTrace.items.map((item) => ({
      type: normalizeText(item.type) || "status",
      detail: item.text,
      at: item.at,
      complete: item.complete === true
    })));
  } else if (progress.visibleEvents.length) {
    rows.push(...progress.visibleEvents.map((event) => ({
      type: normalizeText(event.stage) || progress.stage || "status",
      detail: event.detail,
      at: event.at
    })));
  }
  if (!rows.length) {
    rows.push({
      type: progress.status === "running" ? progress.stage : progress.status,
      detail: progress.detail
    });
  }
  const seen = new Set();
  const output = sortTraceItemsChronologically(rows).map((row) => {
    const detail = sanitizeChatProgressDetail(row.detail);
    if (!detail) return null;
    const type = progressInlineType(row.type);
    if (isHiddenRunTraceMessage(type, detail)) return null;
    const key = `${type}\n${detail}`;
    if (seen.has(key)) return null;
    seen.add(key);
    return { type, detail, at: normalizeText(row.at), complete: row.complete === true };
  }).filter(Boolean);
  if (output.length <= 1) return output;
  return output.filter((row) => !isStartingProgressInlineRow(row));
}

function isStartingProgressInlineRow(row) {
  return progressInlineType(row?.type) === "status"
    && ["Starting agent run.", "Agent run started."].includes(sanitizeChatProgressDetail(row?.detail));
}

function activeProgressToolRowIndex(rows) {
  if (!Array.isArray(rows) || !rows.length) return -1;
  const lastIndex = rows.length - 1;
  const lastRow = rows[lastIndex];
  return progressInlineType(lastRow?.type) === "tool" && lastRow?.complete !== true ? lastIndex : -1;
}

function progressInlineType(type) {
  const normalized = normalizeText(type);
  if (isStatusProgressType(normalized)) return "status";
  if (["tool", "skill", "status", "commentary", "reasoning", "summary"].includes(normalized)) return normalized;
  if (normalized.includes("tool")) return "tool";
  if (normalized.includes("skill")) return "skill";
  if (normalized.includes("status")) return "status";
  return normalized || "status";
}

function isStatusProgressType(type) {
  return [
    "approval",
    "cancelled",
    "cancelling",
    "completed",
    "failed",
    "halted",
    "pending",
    "planning",
    "queued",
    "running",
    "starting",
    "stopped",
    "thinking",
    "waiting",
    "working",
  ].includes(normalizeText(type));
}

function formatRunTraceDuration(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs || 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes && seconds) return `${minutes}m ${seconds}s`;
  if (minutes) return `${minutes}m`;
  return `${seconds}s`;
}

function runTraceFromPayload(payload, startedAtMs) {
  const events = Array.isArray(payload?.events) ? payload.events : [];
  if (!events.length) return null;
  const start = Number.isFinite(startedAtMs) ? startedAtMs : Date.now();
  const end = Date.now();
  return normalizeRunTrace({
    requestId: normalizeText(payload?.requestId),
    startedAt: new Date(start).toISOString(),
    finishedAt: new Date(end).toISOString(),
    durationMs: Math.max(0, end - start),
    status: payload?.cancelled ? "cancelled" : payload?.completed ? "completed" : payload?.error ? "failed" : "stopped",
    error: payload?.error || "",
    events
  });
}

function runTraceFromProgress(progress) {
  const normalized = normalizeChatProgress(progress);
  if (!normalized) return null;
  const events = normalized.events.length ? normalized.events : [{ type: normalized.stage, detail: normalized.detail }];
  const startedAtMs = Date.parse(events[0]?.at || "") || Date.now();
  const finishedAtMs = Date.parse(events[events.length - 1]?.at || "") || Date.now();
  return normalizeRunTrace({
    requestId: normalized.requestId,
    startedAt: new Date(startedAtMs).toISOString(),
    finishedAt: new Date(finishedAtMs).toISOString(),
    durationMs: Math.max(0, finishedAtMs - startedAtMs),
    status: normalized.status,
    events: events.map((event) => ({
      type: normalizeText(event.type || event.stage) || "status",
      message: event.detail,
      at: event.at,
      data: event.data || {}
    }))
  });
}

function attachRunTraceFallback(messages, payload, startedAtMs, progress = null) {
  const trace = runTraceFromPayload(payload, startedAtMs);
  const progressTrace = workTraceFromProgressPayload(progress || payload?.progress || payload?.chatProgress);
  if (!trace && !progressTrace) return messages;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") {
      if (trace && !messages[index].runTrace) messages[index].runTrace = trace;
      if (progressTrace) {
        messages[index].workTrace = mergeWorkTraces(messages[index].workTrace, progressTrace);
      }
      return messages;
    }
  }
  return messages;
}

function workTraceFromProgressPayload(progress) {
  const normalized = normalizeChatProgress(progress);
  if (!normalized) return null;
  const rows = [];
  if (normalized.workTrace?.items?.length) {
    rows.push(...normalized.workTrace.items.map((item) => ({
      type: normalizeText(item.type) || "status",
      text: item.text,
      at: item.at,
      source: item.source || "runtime",
      complete: item.complete === true,
    })));
  }
  if (normalized.visibleEvents.length) {
    rows.push(...normalized.visibleEvents.map((event) => ({
      type: progressInlineType(event.stage),
      text: event.detail,
      at: event.at,
      source: "runtime",
    })));
  }
  if (!rows.length) {
    rows.push({
      type: progressInlineType(normalized.status === "running" ? normalized.stage : normalized.status),
      text: normalized.detail,
      source: "runtime",
    });
  }
  const visibleRows = rows.filter((row) => {
    const type = progressInlineType(row.type);
    const text = sanitizeChatProgressDetail(row.text);
    return Boolean(text) && !isHiddenRunSummaryMessage(type, text) && !isStructuredToolCallProgressText(type, text);
  });
  return normalizeWorkTrace({ status: normalized.status, items: visibleRows });
}

function providerNativeWebSearchText(data) {
  const searchCount = positiveInteger(data?.webSearchCallCount);
  if (!searchCount) return "";
  const sourceCount = positiveInteger(data?.webSearchSourceCount);
  const searchLabel = searchCount === 1 ? "search" : "searches";
  const countText = `${searchCount} ${searchLabel}${sourceCount ? `, ${sourceCount} ${sourceCount === 1 ? "source" : "sources"}` : ""}`;
  const queryText = webSearchQuerySummary(data?.webSearchQueries);
  return queryText
    ? `Searched the web: ${queryText} (${countText}).`
    : `Searched the web: ${countText}.`;
}

function webSearchQuerySummary(value) {
  const queries = Array.isArray(value) ? value : [];
  const parts = [];
  for (const item of queries) {
    let text = normalizeText(item);
    if (!text) continue;
    if (text.length > 96) text = `${text.slice(0, 95)}…`;
    parts.push(`"${text}"`);
    if (parts.length >= 3) break;
  }
  if (!parts.length) return "";
  const remaining = queries.length - parts.length;
  return `${parts.join("; ")}${remaining > 0 ? `; +${remaining} more` : ""}`;
}

function positiveInteger(value) {
  const number = Number.parseInt(value || 0, 10);
  return Number.isFinite(number) ? Math.max(0, number) : 0;
}

function mergeWorkTraces(first, second) {
  const firstItems = normalizeWorkTrace(first)?.items || [];
  const secondItems = normalizeWorkTrace(second)?.items || [];
  const status = normalizeText(second?.status || first?.status) || "completed";
  return normalizeWorkTrace({ status, items: [...firstItems, ...secondItems] });
}

function setReaderChatProgress(progress, sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  const normalized = mergeReaderChatProgress(readerState.chatProgressBySession[runKey], progress);
  if (normalized) {
    readerState.chatProgressBySession[runKey] = normalized;
  } else {
    delete readerState.chatProgressBySession[runKey];
  }
  if (isCurrentChatSessionRunKey(runKey)) {
    syncCurrentChatRunState();
    renderReaderChatMessages({ scrollToBottom: Boolean(readerState.chatPending) });
  }
}

function mergeReaderChatProgress(previousProgress, nextProgress) {
  const next = normalizeChatProgress(nextProgress);
  if (!next) return null;
  const previous = normalizeChatProgress(previousProgress);
  if (!previous) return next;
  if (previous.requestId && next.requestId && previous.requestId !== next.requestId) return next;
  return {
    ...next,
    requestId: next.requestId || previous.requestId,
    events: mergeProgressItems(previous.events, next.events, progressEventKey),
    visibleEvents: mergeProgressItems(previous.visibleEvents, next.visibleEvents, progressVisibleEventKey),
    workTrace: mergeProgressWorkTrace(previous.workTrace, next.workTrace, next.status)
  };
}

function mergeProgressItems(previousItems, nextItems, keyForItem) {
  const output = [];
  const seen = new Set();
  for (const item of [...(previousItems || []), ...(nextItems || [])]) {
    const key = keyForItem(item);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    output.push(item);
  }
  return output;
}

function progressEventKey(event) {
  const data = event?.data && typeof event.data === "object" ? JSON.stringify(event.data) : "";
  return [normalizeText(event?.type || event?.stage), sanitizeChatProgressDetail(event?.detail || event?.message), normalizeText(event?.at), data].join("\n");
}

function progressVisibleEventKey(event) {
  return [normalizeText(event?.stage), sanitizeChatProgressDetail(event?.detail), normalizeText(event?.at)].join("\n");
}

function mergeProgressWorkTrace(previousTrace, nextTrace, status = "running") {
  const previous = normalizeWorkTrace(previousTrace);
  const next = normalizeWorkTrace(nextTrace);
  const items = mergeProgressWorkTraceItems(previous?.items || [], next?.items || []);
  if (!items.length) return null;
  return { status: normalizeText(next?.status || previous?.status || status) || "running", items };
}

function progressWorkTraceKey(item) {
  const identity = typeof workTraceItemIdentity === "function" ? workTraceItemIdentity(item) : "";
  return [
    normalizeText(item?.type),
    normalizeText(item?.source),
    identity || sanitizeChatProgressDetail(item?.text || item?.detail)
  ].join("\n");
}

function mergeProgressWorkTraceItems(previousItems, nextItems) {
  const output = [];
  const indexByKey = new Map();
  for (const item of [...(previousItems || []), ...(nextItems || [])]) {
    const key = progressWorkTraceKey(item);
    if (!key.trim()) continue;
    const existingIndex = indexByKey.get(key);
    if (existingIndex === undefined) {
      indexByKey.set(key, output.length);
      output.push(item);
      continue;
    }
    const previous = output[existingIndex];
    const nextText = sanitizeChatProgressDetail(item?.text || item?.detail);
    const previousText = sanitizeChatProgressDetail(previous?.text || previous?.detail);
    output[existingIndex] = {
      ...previous,
      ...item,
      text: nextText.length >= previousText.length ? nextText : previousText,
      complete: item?.complete === true || (previous?.complete === true && item?.complete !== false),
    };
  }
  return output;
}

function appendProgressStatusWorkTrace(progress, text) {
  const normalized = normalizeChatProgress(progress) || {
    status: "running",
    events: [],
    workTrace: { status: "running", items: [] }
  };
  const detail = sanitizeChatProgressDetail(text);
  if (!detail) return normalized;
  const trace = mergeProgressWorkTrace(normalized.workTrace, {
    status: normalized.status,
    items: [{ type: "status", text: detail, at: new Date().toISOString(), source: "system" }]
  }, normalized.status) || { status: normalized.status, items: [] };
  return { ...normalized, workTrace: trace };
}

function finalizeReaderChatProgress(progress, { text = "Agent run stopped.", error = false } = {}) {
  const normalized = normalizeChatProgress(progress);
  if (!normalized) return;
  const trace = runTraceFromProgress(normalized);
  const draft = latestReaderStreamingAssistantMessage() || ensureReaderStreamingAssistantMessage();
  draft.streaming = false;
  if (!normalizeText(draft.text)) draft.text = text;
  draft.error = Boolean(error);
  if (trace) draft.runTrace = trace;
  if (normalized.workTrace?.items?.length) draft.workTrace = normalized.workTrace;
  flushReaderStreamingRender();
}

function clearReaderChatRecoveryPoll(sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  const timer = readerState.chatRecoveryTimersBySession[runKey];
  if (timer) window.clearTimeout(timer);
  delete readerState.chatRecoveryTimersBySession[runKey];
}

function scheduleReaderChatRecoveryPoll({ sessionId, requestId, latestUserText = "", delay = 2400 } = {}) {
  const targetSessionId = normalizeText(sessionId);
  const targetRequestId = normalizeText(requestId);
  if (!targetSessionId || !targetRequestId) return;
  const runKey = chatSessionRunKey(targetSessionId);
  clearReaderChatRecoveryPoll(runKey);
  readerState.chatRecoveryTimersBySession[runKey] = window.setTimeout(async () => {
    delete readerState.chatRecoveryTimersBySession[runKey];
    if (readerState.chatProgressRequestIdsBySession[runKey] !== targetRequestId) return;
    try {
      if (typeof recoverReaderChatFromSession === "function") {
        const recovered = await recoverReaderChatFromSession({
          sessionId: targetSessionId,
          latestUserText
        });
        if (recovered) return;
      }
    } catch (error) {
      console.debug("Could not recover pending chat run yet.", error);
    }
    if (readerState.chatProgressRequestIdsBySession[runKey] === targetRequestId) {
      scheduleReaderChatRecoveryPoll({
        sessionId: targetSessionId,
        requestId: targetRequestId,
        latestUserText,
        delay: Math.min(6000, Math.round(delay * 1.25))
      });
    }
  }, delay);
}

function clearReaderChatProgress(sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  clearReaderChatRecoveryPoll(runKey);
  delete readerState.chatProgressBySession[runKey];
  delete readerState.chatProgressRequestIdsBySession[runKey];
  if (isCurrentChatSessionRunKey(runKey)) syncCurrentChatRunState();
}

function startReaderChatProgress(requestId, sessionId = getChatSessionId()) {
  const runKey = chatSessionRunKey(sessionId);
  const startedAt = new Date().toISOString();
  const startText = "Starting agent run.";
  clearReaderChatProgress(runKey);
  readerState.chatProgressRequestIdsBySession[runKey] = requestId;
  setReaderChatProgress({
    requestId,
    status: "running",
    stage: "starting",
    detail: startText,
    visibleEvents: [{ stage: "starting", detail: startText, at: startedAt }],
    events: [],
    workTrace: {
      status: "running",
      items: [{
        type: "status",
        text: startText,
        at: startedAt,
        source: "runtime",
        complete: true
      }]
    }
  }, runKey);
}

function appendReaderChatProgressWorkTrace(data, runKey = chatSessionRunKey(), eventType = "") {
  const text = normalizeText(data?.text || data?.delta);
  if (!text) return;
  const itemType = normalizeText(data?.traceType) || "summary";
  if (isStructuredToolCallProgressText(itemType, text)) return;
  const source = normalizeText(data?.source) || "provider";
  const at = normalizeText(data?.at) || new Date().toISOString();
  const itemData = data?.data && typeof data.data === "object" ? data.data : {};
  const isDelta = normalizeText(eventType) === "work_trace_delta" || Boolean(normalizeText(data?.delta));
  const explicitComplete = itemData.statusComplete === true || itemData.complete === true
    ? true
    : itemData.statusComplete === false || itemData.complete === false
      ? false
      : null;
  const progress = normalizeChatProgress(readerState.chatProgressBySession[runKey]) || {
    requestId: readerState.chatProgressRequestIdsBySession[runKey],
    status: "running",
    stage: "thinking",
    events: [],
    workTrace: { status: "running", items: [] },
  };
  const trace = normalizeWorkTrace(progress.workTrace) || { status: progress.status || "running", items: [] };
  const canMerge = canMergeStreamingWorkTraceType(itemType);
  const itemIdentity = typeof workTraceItemIdentity === "function" ? workTraceItemIdentity({ data: itemData }) : "";
  const relatedByIdentity = () => itemIdentity
    ? trace.items.findIndex((item) => (
      item.type === itemType
      && workTraceItemIdentity(item) === itemIdentity
    ))
    : -1;
  const upsertWorkTraceItem = (complete) => {
    const relatedIndex = relatedByIdentity();
    if (relatedIndex !== -1) {
      const previous = trace.items[relatedIndex];
      const previousText = normalizeText(previous.text);
      trace.items[relatedIndex] = {
        ...previous,
        text: text.length >= previousText.length ? text : previousText,
        source: source || previous.source,
        at,
        data: itemData,
        complete,
      };
      return;
    }
    trace.items.push({
      type: itemType,
      text,
      source,
      at,
      data: itemData,
      complete,
    });
  };
  const exactDuplicate = () => trace.items.some((item) => (
    item.type === itemType
    && item.source === source
    && sanitizeChatProgressDetail(item.text || item.detail) === text
  ));
  if (isDelta) {
    const last = trace.items[trace.items.length - 1];
    if (canMerge && last && last.type === itemType && last.source === source && (
      text.startsWith(normalizeText(last.text)) || normalizeText(last.text).startsWith(text)
    )) {
      last.text = text;
    } else if (itemIdentity || !exactDuplicate()) {
      upsertWorkTraceItem(explicitComplete ?? false);
    }
  } else {
    const last = trace.items[trace.items.length - 1];
    if (canMerge && last && last.type === itemType && last.source === source && (
      text.startsWith(normalizeText(last.text)) || normalizeText(last.text).startsWith(text)
    )) {
      last.text = text.length >= normalizeText(last.text).length ? text : normalizeText(last.text);
      last.complete = explicitComplete ?? true;
    } else if (itemIdentity || !exactDuplicate()) {
      upsertWorkTraceItem(explicitComplete ?? true);
    }
  }
  progress.workTrace = trace;
  setReaderChatProgress(progress, runKey);
  if (
    explicitComplete === true
    && typeof workTraceItemWritesHtmlNote === "function"
    && workTraceItemWritesHtmlNote({ type: itemType, text, data: itemData, complete: true })
  ) {
    readerState.htmlNoteWriteRunsBySession[runKey] = true;
  }
}
