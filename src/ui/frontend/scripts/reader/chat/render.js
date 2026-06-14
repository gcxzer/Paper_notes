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

function noteForChatSource(source) {
  if (!readerState.library?.notes) return readerState.note;
  if (source.noteId) {
    const byId = readerState.library.notes.find((note) => note.id === source.noteId);
    if (byId) return byId;
  }
  const locator = source.uri;
  if (locator) {
    const byHref = readerState.library.notes.find((note) => (
      [note.href, note.htmlHref].some((href) => href && locator.includes(href))
    ));
    if (byHref) return byHref;
  }
  return readerState.note;
}

function annotationKindFromSource(source) {
  const match = source.excerpt.match(/###\s+([A-Za-z]+)/);
  return match ? match[1].toLowerCase() : "annotation";
}

function chatSourceLabel(source) {
  if (source.label) return source.label;
  const note = noteForChatSource(source);
  const title = note?.title || "Paper";
  const page = source.page ? ` page ${source.page}` : "";
  if (source.type === "pdf") return `PDF: ${title}${page}`;
  if (source.type === "note") return `Note: ${title} note.html`;
  if (source.type === "annotation") return `Annotation:${page || ""} ${annotationKindFromSource(source)}`.replace("  ", " ").trim();
  return source.uri || "Source";
}

function renderChatSources(sources) {
  if (!sources.length) return "";
  return `
    <div class="ask-sources" aria-label="Sources">
      ${sources.map((source) => `
        <button
          class="ask-source"
          type="button"
          data-source-type="${escapeHtml(source.type)}"
          data-source-page="${source.page || ""}"
          data-source-uri="${escapeHtml(encodeURIComponent(source.uri))}"
          data-source-note-id="${escapeHtml(source.noteId)}"
          title="${escapeHtml(source.excerpt || source.uri || chatSourceLabel(source))}"
        >${escapeHtml(chatSourceLabel(source))}</button>
      `).join("")}
    </div>
  `;
}

function renderChatImages(images) {
  const artifacts = normalizeAttachmentArtifacts(images);
  if (!artifacts.length) return "";
  const imageArtifacts = artifacts.filter(isImageArtifact);
  const fileArtifacts = artifacts.filter((artifact) => !isImageArtifact(artifact));
  return `
    ${imageArtifacts.length ? `<div class="ask-image-grid" aria-label="Images">
      ${imageArtifacts.map((image) => `
        <figure class="ask-image-card">
          ${image.url ? `<img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.fileName)}" loading="lazy" data-image-lightbox-url="${escapeHtml(image.url)}" data-image-lightbox-title="${escapeHtml(image.fileName)}" title="Double-click to enlarge">` : ""}
          <figcaption>
            <span>${escapeHtml(image.fileName)}</span>
            ${image.downloadUrl ? `<a href="${escapeHtml(image.downloadUrl)}" download>Download</a>` : ""}
          </figcaption>
        </figure>
      `).join("")}
    </div>` : ""}
    ${fileArtifacts.length ? `<div class="ask-file-list" aria-label="Files">
      ${fileArtifacts.map(renderChatFileCard).join("")}
    </div>` : ""}
  `;
}

function renderAttachmentTray() {
  if (!elements.readerAttachmentTray) return;
  const attachments = normalizeAttachmentArtifacts(readerState.chatAttachments);
  const selectedTextChip = renderSelectedPdfTextChip();
  const generationChip = renderGenerationModeChip();
  if (!attachments.length && !selectedTextChip && !generationChip && !readerState.attachmentUploadPending && !readerState.imageUploadPending) {
    elements.readerAttachmentTray.hidden = true;
    elements.readerAttachmentTray.innerHTML = "";
    return;
  }
  elements.readerAttachmentTray.hidden = false;
  const previews = attachments.map(renderAttachmentTrayItem).join("");
  const loadingChip = (readerState.attachmentUploadPending || readerState.imageUploadPending)
    ? `<span class="ask-attachment-loading">Uploading...</span>`
    : "";
  elements.readerAttachmentTray.innerHTML = `${selectedTextChip}${generationChip}${previews}${loadingChip}`;
}

function renderSelectedPdfTextChip() {
  const context = selectedPdfTextContextFromState();
  if (!context) return "";
  const text = context.text;
  const wordCount = Number(context.wordCount) || text.split(/\s+/).filter(Boolean).length;
  return `
    <span class="ask-selected-text-chip" data-selected-text-preview="${escapeHtml(text)}">
      <span class="ask-selected-text-main">Text selected: ${wordCount} ${wordCount === 1 ? "word" : "words"}</span>
      <button type="button" data-selected-text-remove="1" aria-label="Remove selected text">×</button>
    </span>
  `;
}

function renderGenerationModeChip() {
  if (readerState.generationMode === "image") {
    return `
      <span class="ask-generation-chip">
        <span>Image generation</span>
        <button type="button" data-generation-mode-remove="1" aria-label="Remove image generation mode">×</button>
      </span>
    `;
  }
  if (readerState.generationMode === "file") {
    return `
      <span class="ask-generation-chip">
        <span>${escapeHtml(fileGenerationFormatLabel(readerState.fileGenerationFormat))}</span>
        <button type="button" data-generation-mode-remove="1" aria-label="Remove file creation mode">×</button>
      </span>
    `;
  }
  return "";
}

function renderChatFileCard(file) {
  const meta = fileMetaLabel(file);
  return `
    <a class="ask-file-card" href="${escapeHtml(file.downloadUrl || file.url || "#")}" ${file.downloadUrl || file.url ? "download" : ""}>
      <span class="ask-file-icon">${escapeHtml(fileKindLabel(file))}</span>
      <span class="ask-file-copy">
        <strong>${escapeHtml(file.fileName)}</strong>
        ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
      </span>
    </a>
  `;
}

function renderAttachmentTrayItem(attachment) {
  const classes = [
    "ask-attachment-preview",
    isImageArtifact(attachment) ? "is-image" : "is-file",
    attachment.uploadPending ? "is-uploading" : "",
    attachment.uploadError ? "is-error" : ""
  ].filter(Boolean).join(" ");
  if (isImageArtifact(attachment)) {
    return `
      <span class="${classes}">
        ${attachment.url ? `<img src="${escapeHtml(attachment.url)}" alt="${escapeHtml(attachment.fileName)}">` : ""}
        ${attachment.uploadPending ? `<span class="ask-attachment-badge">Uploading</span>` : ""}
        ${attachment.uploadError ? `<span class="ask-attachment-badge">Failed</span>` : ""}
        <button type="button" data-attachment-remove="${escapeHtml(attachment.id)}" aria-label="Remove attachment">×</button>
      </span>
    `;
  }
  const typeLabel = fileKindLabel(attachment);
  const meta = fileMetaLabel(attachment) || `${typeLabel} file`;
  return `
    <span class="${classes}" title="${escapeHtml(attachment.fileName)}">
      <span class="ask-attachment-file-mark" aria-hidden="true">
        ${renderChatIcon(fileIconName(attachment), "", "ask-attachment-file-glyph", 20)}
        <span class="ask-attachment-file-type">${escapeHtml(typeLabel)}</span>
      </span>
      <span class="ask-attachment-file-copy">
        <span class="ask-attachment-file-name">${escapeHtml(attachment.fileName)}</span>
        <span class="ask-attachment-file-meta">${escapeHtml(meta)}</span>
      </span>
      ${attachment.uploadPending ? `<span class="ask-attachment-badge">Uploading</span>` : ""}
      ${attachment.uploadError ? `<span class="ask-attachment-badge">Failed</span>` : ""}
      <button type="button" data-attachment-remove="${escapeHtml(attachment.id)}" aria-label="Remove attachment">${renderChatIcon("x", "", "", 14)}</button>
    </span>
  `;
}

function renderChatIcon(name, label = "", className = "", size = 16) {
  return window.renderPaperIcon
    ? window.renderPaperIcon(name, { label, className, size })
    : "";
}

function isImageArtifact(artifact) {
  return normalizeText(artifact?.kind) === "image" || normalizeText(artifact?.mimeType).startsWith("image/");
}

function fileKindLabel(file) {
  const kind = normalizeText(file?.kind).toLowerCase();
  const mimeType = normalizeText(file?.mimeType).toLowerCase();
  const name = normalizeText(file?.fileName).toLowerCase();
  if (kind === "pdf" || mimeType === "application/pdf" || name.endsWith(".pdf")) return "PDF";
  if (kind === "document" || name.endsWith(".docx")) return "DOC";
  if (kind === "presentation" || name.endsWith(".pptx")) return "PPT";
  if (kind === "spreadsheet" || name.endsWith(".xlsx")) return "XLS";
  const extensionLabel = fileExtensionLabel(name);
  if (extensionLabel) return extensionLabel;
  if (kind === "text" || mimeType.startsWith("text/")) return "TXT";
  return "FILE";
}

function fileIconName(file) {
  const kind = normalizeText(file?.kind).toLowerCase();
  const mimeType = normalizeText(file?.mimeType).toLowerCase();
  const name = normalizeText(file?.fileName).toLowerCase();
  if (isImageArtifact(file)) return "image";
  if (kind === "spreadsheet" || name.endsWith(".xlsx") || name.endsWith(".csv")) return "file-spreadsheet";
  if (mimeType.includes("json") || name.endsWith(".json")) return "file-json";
  if (name.endsWith(".js") || name.endsWith(".ts") || name.endsWith(".tsx") || name.endsWith(".py") || name.endsWith(".css") || name.endsWith(".html")) return "file-code";
  if (kind === "text" || mimeType.startsWith("text/") || name.endsWith(".md") || name.endsWith(".txt")) return "file-text";
  return "file";
}

function fileExtensionLabel(fileName) {
  const name = normalizeText(fileName).toLowerCase();
  if (!name || !name.includes(".")) return "";
  const extension = name.split(".").filter(Boolean).pop();
  if (!extension || extension.length > 8 || /^\d+$/.test(extension)) return "";
  return extension.toUpperCase();
}

function fileMetaLabel(file) {
  const size = Number(file?.size) || 0;
  return size > 0 ? formatFileSize(size) : "";
}

function formatFileSize(size) {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (size >= 1024) return `${Math.round(size / 1024)} KB`;
  return `${size} B`;
}

function renderChatToolActivity(toolActivity, { showActions = true, activityScope = "" } = {}) {
  const items = groupToolActivityItems(collapseIntermediateToolActivity(normalizeToolActivity(toolActivity)));
  if (!items.length) return "";
  return `
    <div class="ask-tool-activity" aria-label="Tool activity">
      ${items.map((item) => {
        const showView = toolActivityChangesHtmlNote(item);
        const viewNoteId = normalizeText(item.noteId) || (showView ? currentChatNoteId() : "");
        const viewHeading = toolActivityViewHeading(item);
        const viewAddedHeadings = toolActivityAddedHeadings(item);
        return `
        <div class="ask-tool-activity-item">
          <div class="ask-tool-activity-copy">
            <strong>${escapeHtml(toolDisplayName(item.name))}</strong>
            <span>${escapeHtml(toolActivitySummary(item))}</span>
          </div>
          ${showActions && showView && viewNoteId ? `
            <div class="ask-tool-activity-actions">
              <button
                class="ask-tool-action"
                type="button"
                data-tool-view-note="${escapeHtml(viewNoteId)}"
                data-tool-view-heading="${escapeHtml(viewHeading)}"
                data-tool-view-position="${escapeHtml(item.position)}"
                data-tool-view-added-headings="${escapeHtml(JSON.stringify(viewAddedHeadings))}"
              >View</button>
            </div>
          ` : ""}
        </div>
      `;
      }).join("")}
    </div>
  `;
}

function collapseIntermediateToolActivity(items) {
  const latestByWriteTarget = new Map();
  items.forEach((item, index) => {
    const key = intermediateToolActivityKey(item);
    if (!key) return;
    latestByWriteTarget.set(key, index);
  });
  return items.filter((item, index) => {
    const key = intermediateToolActivityKey(item);
    return !key || latestByWriteTarget.get(key) === index;
  });
}

function intermediateToolActivityKey(item) {
  if (!item || !["write_note", "manage_annotations", "write_note_media"].includes(item.name)) return "";
  const fileKey = toolActivityChangedFileKey(item);
  if (!fileKey) return "";
  return [
    item.name,
    normalizeText(item.sessionId),
    normalizeText(item.noteId) || currentChatNoteId(),
    fileKey
  ].join("|");
}

function groupToolActivityItems(items) {
  const grouped = [];
  items.forEach((item) => {
    const previous = grouped[grouped.length - 1];
    if (canMergeToolActivity(previous, item)) {
      previous.count += 1;
      previous.changedFiles = mergeToolActivityChangedFiles(previous.changedFiles, item.changedFiles);
      return;
    }
    grouped.push({
      ...item,
      count: 1
    });
  });
  return grouped;
}

function canMergeToolActivity(previous, item) {
  if (!previous || !item) return false;
  if (!isAnnotationDeleteActivity(previous) || !isAnnotationDeleteActivity(item)) return false;
  if (previous.sessionId !== item.sessionId || previous.noteId !== item.noteId) return false;
  return toolActivityChangedFileKey(previous) === toolActivityChangedFileKey(item);
}

function isAnnotationDeleteActivity(item) {
  if (!item || item.name !== "manage_annotations") return false;
  const text = normalizeText(item.summary || item.toolMessage || item.message).toLowerCase();
  return text === "deleted annotation." && toolActivityChangesAnnotations(item);
}

function toolActivityChangedFileKey(item) {
  return (item.changedFiles || []).map((file) => normalizeText(file.path)).sort().join("|");
}

function toolActivityAddedHeadings(item) {
  return (Array.isArray(item?.addedHeadings) ? item.addedHeadings : [])
    .map(normalizeText)
    .filter(Boolean);
}

function toolActivityViewHeading(item) {
  const addedHeadings = toolActivityAddedHeadings(item);
  return addedHeadings[addedHeadings.length - 1] || normalizeText(item?.heading);
}

function mergeToolActivityChangedFiles(left, right) {
  const byPath = new Map();
  [...(left || []), ...(right || [])].forEach((file) => {
    const path = normalizeText(file?.path);
    if (!path) return;
    byPath.set(path, {
      path,
      beforeBytes: Math.max(Number(byPath.get(path)?.beforeBytes) || 0, Number(file.beforeBytes) || 0),
      afterBytes: Math.max(Number(byPath.get(path)?.afterBytes) || 0, Number(file.afterBytes) || 0)
    });
  });
  return [...byPath.values()];
}

function toolActivityChangesHtmlNote(item) {
  return (item.changedFiles || []).some((file) => {
    const path = normalizeText(file?.path).toLowerCase();
    return path.endsWith(".html") && (path.includes("paper-html/") || path.includes("paper-html\\") || path.includes("/paper-html") || path.includes("\\paper-html"));
  });
}

function toolActivityChangesAnnotations(item) {
  return (item.changedFiles || []).some((file) => {
    const path = normalizeText(file?.path).toLowerCase();
    return path.endsWith(".json") && (path.includes("annotations/") || path.includes("annotations\\"));
  });
}

function chatPayloadChangesAnnotations(payload) {
  return normalizeToolActivity(payload?.message?.toolActivity).some(toolActivityChangesAnnotations);
}

function chatPayloadChangesHtmlNote(payload) {
  const messageActivities = normalizeToolActivity(payload?.message?.toolActivity);
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  const historyActivities = messages.flatMap((message) => normalizeToolActivity(message?.toolActivity));
  return [...messageActivities, ...historyActivities].some(toolActivityChangesHtmlNote);
}

function chatPayloadWritesHtmlNote(payload) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  const eventGroups = [
    payload?.events,
    payload?.runTrace?.events,
    payload?.message?.runTrace?.events,
    ...messages.map((message) => message?.runTrace?.events),
  ];
  if (eventGroups.some((events) => (Array.isArray(events) ? events : []).some(workTraceItemWritesHtmlNote))) {
    return true;
  }
  const workTraces = [
    payload?.message?.workTrace,
    ...messages.map((message) => message?.workTrace),
  ];
  return workTraces.some((trace) => (
    (Array.isArray(trace?.items) ? trace.items : []).some(workTraceItemWritesHtmlNote)
  ));
}

function workTraceItemWritesHtmlNote(item) {
  const type = normalizeText(item?.type || item?.traceType || item?.trace_type || item?.stage);
  if (type && type !== "tool" && !type.includes("tool")) return false;
  const data = item?.data && typeof item.data === "object" ? item.data : {};
  const nested = data.data && typeof data.data === "object" ? data.data : {};
  const toolName = normalizeText(
    item?.toolName
    || item?.tool_name
    || data.toolName
    || data.tool_name
    || nested.toolName
    || nested.tool_name
    || item?.name
  );
  if (!["write_note", "write_note_media"].includes(toolName)) return false;
  const text = normalizeText(item?.text || item?.message || item?.detail).toLowerCase();
  return item?.complete === true
    || data.complete === true
    || nested.complete === true
    || data.statusComplete === true
    || nested.statusComplete === true
    || text.startsWith("tool completed:");
}

function toolActivitySummary(item) {
  if (isAnnotationDeleteActivity(item) && Number(item.count) > 1) {
    return `Deleted ${Math.round(Number(item.count))} annotations.`;
  }
  if (item.summary) return item.summary;
  if (item.toolMessage) return item.toolMessage;
  if (item.message) return item.message;
  const files = item.changedFiles.map((file) => file.path).join(", ");
  return files || "Local note files changed.";
}

function toolDisplayName(name) {
  if (name === "write_note") return "Updated note";
  if (name === "manage_annotations") return "Updated annotation";
  if (name === "write_note_media") return "Updated note media";
  if (name === "append_note_section") return "Appended note section";
  if (name === "replace_note_section") return "Replaced note section";
  if (name === "write_note_section") return "Updated note section";
  if (name === "update_note_metadata") return "Updated note metadata";
  if (name === "update_annotation") return "Updated annotation";
  if (name === "create_annotation") return "Created annotation";
  if (name === "delete_annotation") return "Deleted annotation";
  if (name === "create_image_artifact") return "Generated image";
  if (name === "create_file_artifact") return "Created file";
  return name;
}

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

function latestReaderUserMessageIndex() {
  for (let index = readerState.chatMessages.length - 1; index >= 0; index -= 1) {
    if (readerState.chatMessages[index]?.role === "user") return index;
  }
  return -1;
}

function formatRunTraceDuration(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs || 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes && seconds) return `${minutes}m ${seconds}s`;
  if (minutes) return `${minutes}m`;
  return `${seconds}s`;
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
  const traceType = normalizeText(data.trace_type || data.traceType) || eventType;
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
    const name = normalizeText(data.name || data.toolName || data.tool_name);
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

function runTraceFromPayload(payload, startedAtMs) {
  const events = Array.isArray(payload?.events) ? payload.events : [];
  if (!events.length) return null;
  const start = Number.isFinite(startedAtMs) ? startedAtMs : Date.now();
  const end = Date.now();
  return normalizeRunTrace({
    requestId: normalizeText(payload?.requestId || payload?.request_id),
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
  const searchCount = positiveInteger(data?.web_search_call_count || data?.webSearchCallCount);
  if (!searchCount) return "";
  const sourceCount = positiveInteger(data?.web_search_source_count || data?.webSearchSourceCount);
  const searchLabel = searchCount === 1 ? "search" : "searches";
  const countText = `${searchCount} ${searchLabel}${sourceCount ? `, ${sourceCount} ${sourceCount === 1 ? "source" : "sources"}` : ""}`;
  const queryText = webSearchQuerySummary(data?.web_search_queries || data?.webSearchQueries);
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

function renderReaderUserMessageActions(message, index, latestUserIndex) {
  if (message.role !== "user" || !message.text) return "";
  const canEdit = index === latestUserIndex && !isChatSessionPending();
  const editButton = canEdit
    ? `<button type="button" class="ask-message-action ask-message-action-edit" data-user-message-edit="${index}" aria-label="Edit latest message" title="Edit latest message">
        <span aria-hidden="true">✎</span>
        <span>Edit</span>
      </button>`
    : "";
  return `
    <div class="ask-message-actions">
      ${editButton}
      <button type="button" class="ask-message-action ask-message-action-copy" data-user-message-copy="${index}" aria-label="Copy message" title="Copy">
        <span aria-hidden="true">⧉</span>
        <span class="copy-feedback" aria-hidden="true">Copied</span>
        <span class="sr-only">Copy</span>
      </button>
    </div>
  `;
}

function renderReaderUserMessageEdit(message, index) {
  const value = readerState.chatEditingIndex === index ? readerState.chatEditingText : message.text;
  return `
    <form class="ask-message-edit" data-user-message-edit-form="${index}">
      <textarea data-user-message-edit-input="${index}" rows="2">${escapeHtml(value)}</textarea>
      <div class="ask-message-edit-actions">
        <button type="submit">Send</button>
        <button type="button" data-user-message-edit-cancel="${index}">Cancel</button>
      </div>
    </form>
  `;
}

function readerChatIsNearBottom(container = elements.readerChatMessages) {
  if (!container) return true;
  const distance = container.scrollHeight - container.clientHeight - container.scrollTop;
  return distance < 96;
}

function renderReaderChatMessages({ scrollToBottom = false, forceScrollToBottom = false, preserveScrollTop = false } = {}) {
  if (!elements.readerChatMessages) return;
  const previousScrollTop = elements.readerChatMessages.scrollTop;
  const wasNearBottom = readerChatIsNearBottom(elements.readerChatMessages);
  const manualContextCompactionHtml = renderManualContextCompactionProgress();
  if (!readerState.chatMessages.length && !isChatSessionPending() && !manualContextCompactionHtml) {
    elements.readerChatMessages.innerHTML = `
      <div class="ask-empty-chat">
        <p>Ask about this paper, or tell me what to do.</p>
      </div>
    `;
    return;
  }

  const latestUserIndex = latestReaderUserMessageIndex();
  const chatProgressHtml = `${renderChatProgress()}${manualContextCompactionHtml}`;
  const streamingAssistantIndex = isChatSessionPending()
    ? readerState.chatMessages.findIndex((message, index) => (
      index > latestUserIndex
      && message?.role === "assistant"
      && message.streaming
    ))
    : -1;
  let insertedProgress = false;
  const messagesHtml = readerState.chatMessages.map((rawMessage, index) => {
    const message = normalizeChatMessage(rawMessage);
    const progressBeforeMessage = !insertedProgress && index === streamingAssistantIndex ? chatProgressHtml : "";
    if (progressBeforeMessage) insertedProgress = true;
    if (message.role === "divider") {
      return `${progressBeforeMessage}${renderChatDivider(message)}`;
    }
    const nextCompactionMarkerHtml = message.role === "user"
      ? messageContextCompactionMarker(readerState.chatMessages[index + 1])
      : "";
    const sourcesHtml = message.role === "assistant" ? renderChatSources(message.sources) : "";
    const imageHtml = renderChatImages([...(message.attachments || []), ...(message.artifacts || [])]);
    const toolActivityHtml = message.role === "assistant" ? renderChatToolActivity(message.toolActivity, { activityScope: `message-${index}` }) : "";
    const previousMessage = normalizeChatMessage(readerState.chatMessages[index - 1]);
    const moveCompactionMarkerToPreviousUser = message.role === "assistant"
      && previousMessage.role === "user"
      && Boolean(renderContextCompactionMarker(message.runTrace?.events));
    const compactionMarkerHtml = message.role === "assistant" && !moveCompactionMarkerToPreviousUser
      ? renderContextCompactionMarker(message.runTrace?.events)
      : "";
    const traceHtml = message.role === "assistant" ? renderRunTraceSummary(message.runTrace, message.workTrace) : "";
    const editing = message.role === "user" && readerState.chatEditingIndex === index;
    const userContextBadgesHtml = message.role === "user" ? renderUserContextBadges(message) : "";
    const userActionsHtml = renderReaderUserMessageActions(message, index, latestUserIndex);
    const bubbleHtml = editing
      ? renderReaderUserMessageEdit(message, index)
      : message.text
        ? `<div class="ask-bubble">${rawMessage.streaming ? renderStreamingChatText(message.text) : renderChatMarkdown(message.text)}</div>`
        : "";
    return `${progressBeforeMessage}${nextCompactionMarkerHtml}${compactionMarkerHtml}
    <div class="ask-message ask-message-${message.role}${message.error ? " ask-message-error" : ""}">
      <div class="ask-message-stack">
        ${traceHtml}
        ${bubbleHtml}
        ${imageHtml}
        ${userContextBadgesHtml}
        ${editing ? "" : userActionsHtml}
        ${sourcesHtml}
        ${toolActivityHtml}
      </div>
    </div>
  `;
  }).join("");
  elements.readerChatMessages.innerHTML = `${messagesHtml}${insertedProgress ? "" : chatProgressHtml}`;
  const keepScrolledToBottom = forceScrollToBottom || (scrollToBottom && wasNearBottom);
  if (keepScrolledToBottom) {
    elements.readerChatMessages.scrollTop = elements.readerChatMessages.scrollHeight;
  } else if (preserveScrollTop || scrollToBottom) {
    elements.readerChatMessages.scrollTop = previousScrollTop;
    requestAnimationFrame(() => {
      if (elements.readerChatMessages) elements.readerChatMessages.scrollTop = previousScrollTop;
    });
  }
  scheduleChatMermaidRender(elements.readerChatMessages, { keepScrolledToBottom });
}

function renderUserGenerationBadge(generation, attachments = []) {
  const label = generationRequestLabel(generation, attachments);
  if (!label) return "";
  return `<div class="ask-user-generation-badge">${escapeHtml(label)}</div>`;
}

function renderUserSelectedTextBadge(selectedTextContext) {
  const context = normalizeSelectedTextContext(selectedTextContext);
  if (!context) return "";
  const wordCount = Number(context.wordCount) || context.text.split(/\s+/).filter(Boolean).length;
  return `<div class="ask-user-generation-badge ask-user-selected-text-badge" data-selected-text-preview="${escapeHtml(context.text)}" aria-label="Selected text preview">Text selected: ${wordCount} ${wordCount === 1 ? "word" : "words"}</div>`;
}

function renderUserContextBadges(message) {
  return [
    renderUserGenerationBadge(message.generation, message.attachments),
    renderUserSelectedTextBadge(message.selectedTextContext)
  ].filter(Boolean).join("");
}

function renderChatDivider(message) {
  const text = ["context_compaction_marker", "context_compaction"].includes(message.markerType)
    ? "Context compacted"
    : (message.text || "Divider");
  return `
    <div class="ask-message-divider" role="status">
      <span></span>
      <strong>${escapeHtml(text)}</strong>
      <span></span>
    </div>
  `;
}

function renderStreamingChatText(text) {
  return `${renderChatMarkdown(text)}<span class="ask-stream-caret" aria-hidden="true"></span>`;
}

function preserveReaderChatScrollTop(callback) {
  const container = elements.readerChatMessages;
  if (!container) {
    callback();
    return;
  }
  const previousScrollTop = container.scrollTop;
  callback();
  container.scrollTop = previousScrollTop;
  requestAnimationFrame(() => {
    container.scrollTop = previousScrollTop;
  });
}

function activateChatSource(source) {
  if (source.type === "note") {
    setHtmlPaneVisible(true);
    elements.notePane?.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (source.type === "pdf" || source.type === "annotation") {
    if (source.type === "annotation") setAnnotationSidebarCollapsed(false);
    if (source.page) scrollToPdfPage(source.page, "auto");
  }
}

function handleChatSourceClick(event) {
  const button = event.target.closest(".ask-source");
  if (!button) return;
  event.preventDefault();
  activateChatSource({
    type: normalizeText(button.dataset.sourceType) || "source",
    page: Number(button.dataset.sourcePage) || null,
    uri: decodeURIComponent(button.dataset.sourceUri || ""),
    noteId: normalizeText(button.dataset.sourceNoteId)
  });
}


function handleChatProgressClick(event) {
  const button = event.target.closest("[data-chat-cancel]");
  if (!button) return;
  event.preventDefault();
  cancelReaderChatRequest();
}

async function refreshCurrentNoteAfterToolUndo() {
  const noteId = currentChatNoteId();
  if (!noteId) return;
  const library = await readDefaultLibrary().catch(() => null);
  if (library) {
    readerState.library = library;
    const nextNote = library.notes.find((entry) => entry.id === noteId);
    if (nextNote) updateCurrentNote(nextNote);
  }
  const noteBody = await fetchGeneratedNoteBody(readerState.note);
  if (noteBody && elements.notePage) {
    elements.notePage.innerHTML = noteBody;
    if (typeof window.buildNoteMenu === "function") window.buildNoteMenu(elements.notePage);
    mountReaderNoteMenu();
  }
  await refreshAnnotationsFromServer({ preserveOpenEditor: true, statusText: "" });
}

function parseToolActivityAddedHeadings(value) {
  try {
    const parsed = JSON.parse(normalizeText(value) || "[]");
    return (Array.isArray(parsed) ? parsed : []).map(normalizeText).filter(Boolean);
  } catch (_error) {
    return [];
  }
}

function normalizeToolActivityViewTarget(target) {
  if (target && typeof target === "object") {
    const addedHeadings = (Array.isArray(target.addedHeadings) ? target.addedHeadings : [])
      .map(normalizeText)
      .filter(Boolean);
    return {
      noteId: normalizeText(target.noteId || target.note_id),
      heading: normalizeText(target.heading),
      position: normalizeText(target.position),
      addedHeadings
    };
  }
  return {
    noteId: normalizeText(target),
    heading: "",
    position: "",
    addedHeadings: []
  };
}

function noteHeadingVisibleText(heading) {
  if (!heading) return "";
  const clone = heading.cloneNode(true);
  clone.querySelectorAll("button, .note-heading-toggle").forEach((node) => node.remove());
  return normalizeText(clone.textContent || heading.textContent).toLowerCase();
}

function findNoteHeadingByText(text, { prefer = "first" } = {}) {
  const target = normalizeText(text).toLowerCase();
  if (!target || !elements.notePage) return null;
  const matches = Array.from(elements.notePage.querySelectorAll("h1, h2, h3, h4"))
    .filter((heading) => noteHeadingVisibleText(heading) === target);
  if (!matches.length) return null;
  return prefer === "last" ? matches[matches.length - 1] : matches[0];
}

function scrollNotePaneToElement(element, behavior = "smooth") {
  const pane = elements.notePane;
  if (!pane || !element) return false;
  const paneBox = pane.getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  const anchorOffset = typeof noteScrollAnchorOffset === "function"
    ? noteScrollAnchorOffset()
    : Math.round(Math.min(Math.max(pane.clientHeight * 0.16, 56), 150));
  const maxScroll = Math.max(0, pane.scrollHeight - pane.clientHeight);
  const targetTop = pane.scrollTop + rect.top - paneBox.top - anchorOffset;
  pane.scrollTo({
    top: Math.min(Math.max(targetTop, 0), maxScroll),
    behavior
  });
  return true;
}

function scrollNotePaneToToolActivityTarget(target) {
  const addedHeadings = (Array.isArray(target.addedHeadings) ? target.addedHeadings : [])
    .map(normalizeText)
    .filter(Boolean);
  const heading = addedHeadings[addedHeadings.length - 1] || normalizeText(target.heading);
  const position = normalizeText(target.position);
  const prefer = addedHeadings.length && position !== "prepend" ? "last" : "first";
  const headingElement = findNoteHeadingByText(heading, { prefer });
  if (headingElement && scrollNotePaneToElement(headingElement, "smooth")) return true;
  if (position === "append" && elements.notePane) {
    elements.notePane.scrollTo({
      top: Math.max(0, elements.notePane.scrollHeight - elements.notePane.clientHeight),
      behavior: "smooth"
    });
    return false;
  }
  elements.notePane?.scrollTo({ top: 0, behavior: "smooth" });
  return false;
}

async function viewToolActivityNote(target) {
  const viewTarget = normalizeToolActivityViewTarget(target);
  const targetNoteId = viewTarget.noteId;
  if (!targetNoteId) return;
  if (targetNoteId && targetNoteId !== currentChatNoteId()) {
    setReaderChatError("Open that note from the library to view the change.");
    return;
  }
  await refreshCurrentNoteAfterToolUndo();
  setHtmlPaneVisible(true);
  await new Promise((resolve) => window.requestAnimationFrame(resolve));
  scrollNotePaneToToolActivityTarget(viewTarget);
}

async function handleToolActivityClick(event) {
  const viewButton = event.target.closest("[data-tool-view-note]");
  if (viewButton) {
    event.preventDefault();
    await viewToolActivityNote({
      noteId: viewButton.dataset.toolViewNote,
      heading: viewButton.dataset.toolViewHeading,
      position: viewButton.dataset.toolViewPosition,
      addedHeadings: parseToolActivityAddedHeadings(viewButton.dataset.toolViewAddedHeadings)
    });
    return;
  }
}
