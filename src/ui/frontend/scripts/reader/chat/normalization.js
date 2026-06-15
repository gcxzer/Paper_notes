function normalizeChatMessage(message) {
  const role = message?.role === "user" ? "user" : message?.role === "divider" ? "divider" : "assistant";
  const text = normalizeText(message?.text);
  const error = Boolean(message?.error);
  if (role === "divider") {
    return {
      role,
      text,
      markerType: normalizeText(message?.markerType),
      focus: normalizeText(message?.focus),
      warning: normalizeText(message?.warning)
    };
  }
  return {
    role,
    text: role === "assistant" && error ? sanitizeVisibleAgentError(text) : text,
    error,
    generation: normalizeGenerationRequest(message?.generation),
    selectedTextContext: normalizeSelectedTextContext(message?.selectedTextContext || message?.metadata?.selectedTextContext),
    attachments: normalizeImageArtifacts(message?.attachments),
    artifacts: normalizeImageArtifacts(message?.artifacts),
    sources: normalizeChatSources(message?.sources),
    toolActivity: normalizeToolActivity(message?.toolActivity),
    runTrace: normalizeRunTrace(message?.runTrace),
    workTrace: normalizeWorkTrace(message?.workTrace)
  };
}

function normalizeRunTrace(rawTrace) {
  if (!rawTrace || typeof rawTrace !== "object") return null;
  const events = Array.isArray(rawTrace.events)
    ? rawTrace.events.map((event) => ({
      type: normalizeText(event?.type),
      stage: normalizeText(event?.stage),
      message: sanitizeChatProgressDetail(event?.message || event?.detail),
      at: normalizeText(event?.at),
      data: event?.data && typeof event.data === "object" ? event.data : {}
    })).filter((event) => {
      const traceType = normalizeText(event.data?.traceType || event.data?.trace_type || event.stage || event.type);
      const text = sanitizeChatProgressDetail(event.data?.text || event.data?.delta || event.message);
      return (event.type || event.message) && !isStructuredToolCallProgressText(traceType, text);
    })
    : [];
  const durationMs = Number(rawTrace.durationMs || rawTrace.duration_ms || 0);
  if (!events.length && !durationMs) return null;
  return {
    requestId: normalizeText(rawTrace.requestId || rawTrace.request_id),
    startedAt: normalizeText(rawTrace.startedAt || rawTrace.started_at),
    finishedAt: normalizeText(rawTrace.finishedAt || rawTrace.finished_at),
    durationMs: Number.isFinite(durationMs) ? Math.max(0, durationMs) : 0,
    status: normalizeText(rawTrace.status) || "completed",
    error: normalizeText(rawTrace.error),
    events
  };
}

function normalizeWorkTrace(rawTrace) {
  if (!rawTrace || typeof rawTrace !== "object") return null;
  const rawItems = Array.isArray(rawTrace.items)
    ? rawTrace.items.map((item) => ({
      type: normalizeText(item?.type) || "summary",
      text: sanitizeChatProgressDetail(item?.text || item?.detail),
      at: normalizeText(item?.at),
      source: normalizeText(item?.source),
      data: item?.data && typeof item.data === "object" ? item.data : {},
      complete: item?.complete === true
    })).filter((item) => item.text && !isStructuredToolCallProgressText(item.type, item.text))
    : [];
  const items = sortTraceItemsChronologically(compactWorkTraceItems(rawItems));
  if (!items.length) return null;
  return {
    status: normalizeText(rawTrace.status) || "completed",
    items
  };
}

function sortTraceItemsChronologically(items) {
  return (Array.isArray(items) ? items : [])
    .map((item, index) => ({ item, index, time: Date.parse(normalizeText(item?.at)) }))
    .sort((left, right) => {
      const leftTime = Number.isFinite(left.time) ? left.time : null;
      const rightTime = Number.isFinite(right.time) ? right.time : null;
      if (leftTime !== null && rightTime !== null && leftTime !== rightTime) return leftTime - rightTime;
      return left.index - right.index;
    })
    .map((entry) => entry.item);
}

function compactWorkTraceItems(items) {
  const compacted = [];
  for (const item of Array.isArray(items) ? items : []) {
    const type = normalizeText(item?.type) || "summary";
    const text = sanitizeChatProgressDetail(item?.text || item?.detail);
    if (!text) continue;
    const source = normalizeText(item?.source);
    const identity = workTraceItemIdentity(item);
    const identityIndex = identity
      ? compacted.findIndex((existing) => (
        existing.type === type
        && workTraceItemIdentity(existing) === identity
      ))
      : -1;
    if (identityIndex !== -1) {
      const existing = compacted[identityIndex];
      compacted[identityIndex] = {
        ...existing,
        ...item,
        type,
        source: source || existing.source,
        text: text.length >= normalizeText(existing.text).length ? text : normalizeText(existing.text),
        complete: item.complete === true || (existing.complete === true && item.complete !== false),
      };
      continue;
    }
    const duplicateIndex = compacted.findIndex((existing) => (
      existing.type === type
      && existing.text === text
    ));
    if (duplicateIndex !== -1) continue;
    const relatedIndex = canMergeStreamingWorkTraceType(type)
      ? compacted.findLastIndex((existing) => (
        existing.type === type
        && existing.source === source
        && workTraceTextsOverlap(existing.text, text)
      ))
      : -1;
    if (relatedIndex !== -1) {
      if (text.length >= compacted[relatedIndex].text.length) {
        compacted[relatedIndex] = { ...item, type, text, source };
      }
      continue;
    }
    compacted.push({ ...item, type, text, source });
  }
  return compacted;
}

function workTraceItemIdentity(item) {
  const data = item?.data && typeof item.data === "object" ? item.data : {};
  return normalizeText(
    data.itemId
    || data.item_id
    || data.id
    || data.item?.id
    || data.item?.itemId
    || data.item?.item_id
    || data.toolCallId
    || data.tool_call_id
    || data.toolCall?.id
    || data.toolCall?.tool_call_id
    || data.tool_call?.id
    || data.tool_call?.tool_call_id
  );
}

function canMergeStreamingWorkTraceType(type) {
  return ["summary", "commentary", "reasoning"].includes(normalizeText(type));
}

function workTraceTextsOverlap(first, second) {
  const a = normalizeText(first);
  const b = normalizeText(second);
  if (!a || !b) return false;
  return a.startsWith(b) || b.startsWith(a) || a.includes(b) || b.includes(a);
}

function isStructuredToolCallProgressText(type, text) {
  const normalizedType = normalizeText(type);
  if (normalizedType && normalizedType !== "commentary" && normalizedType !== "progress") return false;
  const detail = sanitizeChatProgressDetail(text).trim();
  if (!detail || (detail[0] !== "{" && detail[0] !== "[")) return false;
  try {
    return payloadHasStructuredToolCalls(JSON.parse(detail));
  } catch (_error) {
    return false;
  }
}

function payloadHasStructuredToolCalls(payload) {
  if (Array.isArray(payload)) return payload.some((item) => payloadHasStructuredToolCalls(item));
  if (!payload || typeof payload !== "object") return false;
  if (normalizeText(payload.kind) === "tool_calls") return true;
  return Array.isArray(payload.tool_calls) || Array.isArray(payload.toolCalls);
}

function normalizeImageArtifacts(rawArtifacts) {
  return normalizeAttachmentArtifacts(rawArtifacts);
}

function normalizeAttachmentArtifacts(rawArtifacts) {
  if (!Array.isArray(rawArtifacts)) return [];
  return rawArtifacts.map((artifact) => {
    if (!artifact || typeof artifact !== "object") return null;
    const id = normalizeText(artifact.id || artifact.artifactId);
    const url = normalizeText(artifact.url || artifact.previewUrl || artifact.localPreviewUrl);
    const downloadUrl = normalizeText(artifact.downloadUrl || artifact.download_url);
    if (!id && !url) return null;
    return {
      id,
      kind: normalizeText(artifact.kind) || "image",
      source: normalizeText(artifact.source),
      mimeType: normalizeText(artifact.mimeType || artifact.mime_type),
      fileName: normalizeText(artifact.fileName || artifact.file_name) || "attachment",
      url,
      downloadUrl,
      size: Number(artifact.size) || 0,
      width: Number(artifact.width) || 0,
      height: Number(artifact.height) || 0,
      uploadPending: Boolean(artifact.uploadPending),
      uploadError: normalizeText(artifact.uploadError),
      localPreviewUrl: normalizeText(artifact.localPreviewUrl)
    };
  }).filter(Boolean);
}

function isImageArtifact(artifact) {
  return normalizeText(artifact?.kind) === "image" || normalizeText(artifact?.mimeType).startsWith("image/");
}

function normalizeChatSources(rawSources) {
  if (!Array.isArray(rawSources)) return [];
  return rawSources.slice(0, 12).map((source) => {
    const raw = typeof source === "string" ? { uri: source } : source;
    if (!raw || typeof raw !== "object") return null;
    const page = Number(raw.page);
    return {
      type: normalizeText(raw.type) || "source",
      label: normalizeText(raw.label),
      uri: normalizeText(raw.uri),
      noteId: normalizeText(raw.noteId),
      page: Number.isFinite(page) && page > 0 ? Math.round(page) : null,
      excerpt: normalizeText(raw.excerpt)
    };
  }).filter((source) => source && (source.label || source.uri || source.excerpt));
}

