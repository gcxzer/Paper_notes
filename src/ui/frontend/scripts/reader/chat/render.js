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
    attachments: normalizeImageArtifacts(message?.attachments),
    artifacts: normalizeImageArtifacts(message?.artifacts),
    sources: normalizeChatSources(message?.sources),
    noteEdit: normalizeNoteEditDraft(message?.noteEdit),
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
      message: sanitizeChatProgressDetail(event?.message || event?.detail),
      data: event?.data && typeof event.data === "object" ? event.data : {}
    })).filter((event) => event.type || event.message)
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
      source: normalizeText(item?.source)
    })).filter((item) => item.text)
    : [];
  const items = compactWorkTraceItems(rawItems);
  if (!items.length) return null;
  return {
    status: normalizeText(rawTrace.status) || "completed",
    items
  };
}

function compactWorkTraceItems(items) {
  const compacted = [];
  for (const item of Array.isArray(items) ? items : []) {
    const type = normalizeText(item?.type) || "summary";
    const text = sanitizeChatProgressDetail(item?.text || item?.detail);
    if (!text) continue;
    const source = normalizeText(item?.source);
    const duplicateIndex = compacted.findIndex((existing) => (
      existing.type === type
      && existing.source === source
      && existing.text === text
    ));
    if (duplicateIndex !== -1) continue;
    const relatedIndex = ["summary", "commentary", "reasoning"].includes(type)
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

function workTraceTextsOverlap(first, second) {
  const a = normalizeText(first);
  const b = normalizeText(second);
  if (!a || !b) return false;
  return a.startsWith(b) || b.startsWith(a) || a.includes(b) || b.includes(a);
}

function safeChatLinkHref(rawHref) {
  const href = normalizeText(rawHref);
  if (!href) return "";
  const sandboxMedia = href.match(/^sandbox:(\/api\/media\/[A-Za-z0-9._~/%+-]+)$/i);
  if (sandboxMedia) return sandboxMedia[1];
  if (/^https?:\/\//i.test(href)) {
    try {
      return new URL(href).href;
    } catch (error) {
      return "";
    }
  }
  if (/^\/api\/media\/[A-Za-z0-9._~/%+-]+$/i.test(href)) {
    return href;
  }
  if (/^\/?(resources|assets)\//i.test(href) || /^\/(?!api\/)[A-Za-z0-9._~/%+-]+$/i.test(href)) {
    return href;
  }
  return "";
}

function splitTrailingUrlPunctuation(url) {
  let trimmed = url;
  let trailing = "";
  while (/[.,!?;:]$/.test(trimmed)) {
    trailing = trimmed.slice(-1) + trailing;
    trimmed = trimmed.slice(0, -1);
  }
  return [trimmed, trailing];
}

function renderChatMarkdown(text) {
  const source = normalizeText(text);
  if (!source) return "";
  const codeBlocks = [];
  const withCodeBlocks = source.replace(/```([A-Za-z0-9_+.-]*)[ \t]*\n([\s\S]*?)```/g, (_, language, code) => {
    const token = `@@CODEBLOCK${codeBlocks.length}@@`;
    codeBlocks.push(renderChatCodeBlock(normalizeFencedCode(code), language));
    return token;
  });
  const codeSpans = [];
  const codeSpanLabels = [];
  let html = escapeHtml(withCodeBlocks).replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `@@CODESPAN${codeSpans.length}@@`;
    codeSpans.push(`<code>${code}</code>`);
    codeSpanLabels.push(code);
    return token;
  });
  html = html.replace(/\*\*([^*\n](?:[\s\S]*?[^*\n])?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__([^_\n](?:[\s\S]*?[^_\n])?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*\*/g, "");
  html = html.replace(/__/g, "");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/(^|[^\w])_([^_\n]+?)_(?=[^\w]|$)/g, "$1<em>$2</em>");
  const linkSpans = [];
  html = html.replace(/\[([^\]\n]{1,240})\]\(([^)\s]+)\)/g, (match, label, href) => {
    const safeHref = safeChatLinkHref(href);
    if (!safeHref) return match;
    const token = `@@LINKSPAN${linkSpans.length}@@`;
    const linkLabel = label.replace(/@@CODESPAN(\d+)@@/g, (spanToken, index) => codeSpanLabels[Number(index)] ?? spanToken);
    linkSpans.push(`<a href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer">${linkLabel}</a>`);
    return token;
  });
  html = html.replace(/(https?:\/\/[^\s<>"']+)/gi, (url) => {
    const [hrefCandidate, trailing] = splitTrailingUrlPunctuation(url);
    const safeHref = safeChatLinkHref(hrefCandidate);
    return safeHref
      ? `<a href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer">${hrefCandidate}</a>${trailing}`
      : url;
  });
  html = html.replace(/(^|[\s(])((?:\/api\/media\/)[A-Za-z0-9._~/%+-]+)(?=$|[\s).,!?;:])/g, (match, prefix, path) => (
    `${prefix}<a href="${escapeHtml(path)}" target="_blank" rel="noopener noreferrer">${path}</a>`
  ));
  html = renderChatMarkdownBlocks(html);
  linkSpans.forEach((link, index) => {
    html = html.replace(`@@LINKSPAN${index}@@`, link);
  });
  codeSpans.forEach((code, index) => {
    html = html.replace(`@@CODESPAN${index}@@`, code);
  });
  codeBlocks.forEach((block, index) => {
    html = html.replace(`@@CODEBLOCK${index}@@`, block);
  });
  return html;
}

function renderChatMarkdownBlocks(html) {
  const lines = String(html || "").split(/\r?\n/);
  const output = [];
  let listType = "";
  let blockquote = [];

  const closeList = () => {
    if (!listType) return;
    output.push(`</${listType}>`);
    listType = "";
  };
  const closeBlockquote = () => {
    if (!blockquote.length) return;
    closeList();
    output.push(`<blockquote>${blockquote.join("<br>")}</blockquote>`);
    blockquote = [];
  };
  const openList = (type) => {
    closeBlockquote();
    if (listType === type) return;
    closeList();
    output.push(`<${type}>`);
    listType = type;
  };
  const closeBlocks = () => {
    closeBlockquote();
    closeList();
  };
  const tableSeparator = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const tableRow = (line) => /^\s*\|.+\|\s*$/.test(line);
  const tableCells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  const renderTable = (tableLines) => {
    const header = tableCells(tableLines[0]);
    const rows = tableLines.slice(2).map(tableCells);
    return `
      <div class="chat-table-wrap">
        <table class="chat-markdown-table">
          <thead><tr>${header.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>
          <tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody>
        </table>
      </div>
    `;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      closeBlocks();
      continue;
    }
    if (tableRow(line) && tableSeparator(lines[index + 1] || "")) {
      closeBlocks();
      const tableLines = [line, lines[index + 1].trimEnd()];
      index += 2;
      while (index < lines.length && tableRow(lines[index])) {
        tableLines.push(lines[index].trimEnd());
        index += 1;
      }
      index -= 1;
      output.push(renderTable(tableLines));
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      closeBlocks();
      const level = Math.min(6, heading[1].length);
      output.push(`<h${level}>${heading[2].trim()}</h${level}>`);
      continue;
    }
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      closeBlocks();
      output.push("<hr>");
      continue;
    }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    if (unordered) {
      openList("ul");
      output.push(`<li>${unordered[1]}</li>`);
      continue;
    }
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      openList("ol");
      output.push(`<li>${ordered[1]}</li>`);
      continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      blockquote.push(quote[1]);
      continue;
    }
    closeBlocks();
    output.push(`<p>${line}</p>`);
  }
  closeBlocks();
  return output.join("");
}

function normalizeFencedCode(code) {
  return String(code || "").replace(/^(?:[ \t]*\r?\n)+/, "").replace(/(?:\r?\n[ \t]*)+$/, "");
}

function renderChatCodeBlock(code, language = "") {
  const normalizedCode = String(code || "");
  const label = normalizeText(language);
  return `<div class="chat-code-block">${label ? `<div class="chat-code-language">${escapeHtml(label)}</div>` : ""}<pre><code>${escapeHtml(normalizedCode)}</code></pre><button class="chat-code-copy" type="button" data-code-copy="${escapeHtml(encodeURIComponent(normalizedCode))}">Copy</button></div>`;
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

function normalizeNoteEditDraft(rawEdit) {
  if (!rawEdit || typeof rawEdit !== "object") return null;
  const replacementHtml = String(rawEdit.replacementHtml || "").trim();
  const noteId = normalizeText(rawEdit.noteId);
  if (!replacementHtml || !noteId) return null;
  return {
    id: normalizeText(rawEdit.id) || `note-edit-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    noteId,
    summary: normalizeText(rawEdit.summary) || "Prepared a note edit draft.",
    replacementHtml,
    applied: Boolean(rawEdit.applied)
  };
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
  const generationChip = renderGenerationModeChip();
  if (!attachments.length && !generationChip && !readerState.attachmentUploadPending && !readerState.imageUploadPending) {
    elements.readerAttachmentTray.hidden = true;
    elements.readerAttachmentTray.innerHTML = "";
    return;
  }
  elements.readerAttachmentTray.hidden = false;
  const previews = attachments.map(renderAttachmentTrayItem).join("");
  const loadingChip = (readerState.attachmentUploadPending || readerState.imageUploadPending)
    ? `<span class="ask-attachment-loading">Uploading...</span>`
    : "";
  elements.readerAttachmentTray.innerHTML = `${generationChip}${previews}${loadingChip}`;
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
  return `
    <span class="${classes}" title="${escapeHtml(attachment.fileName)}">
      <span class="ask-attachment-file-icon">${escapeHtml(fileKindLabel(attachment))}</span>
      <span class="ask-attachment-file-name">${escapeHtml(attachment.fileName)}</span>
      ${attachment.uploadPending ? `<span class="ask-attachment-badge">Uploading</span>` : ""}
      ${attachment.uploadError ? `<span class="ask-attachment-badge">Failed</span>` : ""}
      <button type="button" data-attachment-remove="${escapeHtml(attachment.id)}" aria-label="Remove attachment">×</button>
    </span>
  `;
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

function renderNoteEditDraft(noteEdit) {
  if (!noteEdit) return "";
  return `
    <div class="ask-note-edit" data-note-edit-id="${escapeHtml(noteEdit.id)}">
      <div class="ask-note-edit-copy">
        <strong>Note edit draft</strong>
        <span>${escapeHtml(noteEdit.summary)}</span>
      </div>
      <div class="ask-note-edit-actions">
        <button class="ask-note-edit-apply" type="button" data-note-edit-apply="${escapeHtml(noteEdit.id)}"${noteEdit.applied ? " disabled" : ""}>${noteEdit.applied ? "Applied" : "Apply to note"}</button>
        <button class="ask-note-edit-discard" type="button" data-note-edit-discard="${escapeHtml(noteEdit.id)}"${noteEdit.applied ? " hidden" : ""}>Discard</button>
      </div>
      <p class="ask-note-edit-hint">This only changes the local HTML note.</p>
    </div>
  `;
}

function renderChatToolActivity(toolActivity, { showActions = true } = {}) {
  const items = groupToolActivityItems(normalizeToolActivity(toolActivity));
  if (!items.length) return "";
  return `
    <div class="ask-tool-activity" aria-label="Tool activity">
      ${items.map((item) => {
        const undoTarget = toolActivityUndoSnapshotId(item);
        const redoTarget = toolActivityRedoSnapshotId(item);
        const undoState = normalizeText(readerState.toolUndoStates[toolActivityStateKey(item)]);
        const undoBusy = undoState === "undoing" || undoState === "redoing";
        const toggleMode = undoState === "undone" ? "redo" : "undo";
        const toggleTarget = toggleMode === "redo" ? redoTarget : undoTarget;
        const toggleLabel = undoState === "undoing" ? "Undoing" : undoState === "redoing" ? "Redoing" : toggleMode === "redo" ? "Redo" : "Undo";
        const showView = toolActivityChangesHtmlNote(item);
        return `
        <div class="ask-tool-activity-item" data-tool-activity-id="${escapeHtml(toolActivityStateKey(item))}">
          <div class="ask-tool-activity-copy">
            <strong>${escapeHtml(toolDisplayName(item.name))}</strong>
            <span>${escapeHtml(toolActivitySummary(item))}</span>
          </div>
          ${showActions ? `
            <div class="ask-tool-activity-actions">
              ${showView && item.noteId ? `
                <button class="ask-tool-action" type="button" data-tool-view-note="${escapeHtml(item.noteId)}">View</button>
              ` : showView && item.snapshotId ? `
                <button
                  class="ask-tool-action"
                  type="button"
                  data-tool-preview="${escapeHtml(item.snapshotId)}"
                  data-tool-session-id="${escapeHtml(item.sessionId)}"
                  ${readerState.toolDiffActionId === item.snapshotId ? "disabled" : ""}
                >${readerState.toolDiffActionId === item.snapshotId ? "Loading" : "View"}</button>
              ` : ""}
              ${item.undoable && toggleTarget ? `
                <button
                  class="ask-tool-action ask-tool-undo"
                  type="button"
                  data-tool-toggle="${escapeHtml(toggleTarget)}"
                  data-tool-toggle-mode="${escapeHtml(toggleMode)}"
                  data-tool-state-key="${escapeHtml(toolActivityStateKey(item))}"
                  data-tool-session-id="${escapeHtml(item.sessionId)}"
                  ${undoBusy ? "disabled" : ""}
                >${escapeHtml(toggleLabel)}</button>
              ` : ""}
            </div>
            ${renderToolActivityDiff(item)}
          ` : ""}
        </div>
      `;
      }).join("")}
    </div>
  `;
}

function groupToolActivityItems(items) {
  const grouped = [];
  items.forEach((item) => {
    const previous = grouped[grouped.length - 1];
    if (canMergeToolActivity(previous, item)) {
      previous.count += 1;
      previous.snapshotIds.push(item.snapshotId);
      previous.redoSnapshotId = item.snapshotId;
      previous.changedFiles = mergeToolActivityChangedFiles(previous.changedFiles, item.changedFiles);
      return;
    }
    grouped.push({
      ...item,
      count: 1,
      snapshotIds: item.snapshotId ? [item.snapshotId] : [],
      undoSnapshotId: item.snapshotId,
      redoSnapshotId: item.snapshotId
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
  if (!item || item.name !== "paper_notes_edit") return false;
  const text = normalizeText(item.summary || item.toolMessage || item.message).toLowerCase();
  return text === "deleted annotation." && toolActivityChangesAnnotations(item);
}

function toolActivityChangedFileKey(item) {
  return (item.changedFiles || []).map((file) => normalizeText(file.path)).sort().join("|");
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

function toolActivityStateKey(item) {
  return normalizeText(item?.undoSnapshotId || item?.snapshotId);
}

function toolActivityUndoSnapshotId(item) {
  return normalizeText(item?.undoSnapshotId || item?.snapshotId);
}

function toolActivityRedoSnapshotId(item) {
  return normalizeText(item?.redoSnapshotId || item?.snapshotId);
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

function renderToolActivityDiff(item) {
  const diff = normalizeToolDiff(readerState.toolDiffs[item.snapshotId]);
  if (!diff || !diff.files.length) return "";
  return `
    <div class="ask-tool-diff" data-tool-diff="${escapeHtml(item.snapshotId)}">
      ${diff.files.map((file) => `
        <div class="ask-tool-diff-file">
          <div class="ask-tool-diff-header">
            <strong>${escapeHtml(file.path)}</strong>
          </div>
          ${file.diff ? `<pre>${escapeHtml(file.diff)}</pre>` : `<p>No text diff available.</p>`}
        </div>
      `).join("")}
    </div>
  `;
}

function toolDisplayName(name) {
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
    detail: sanitizeChatProgressDetail(progress.visibleDetail || progress.detail) || "Working...",
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
  const terminalVisible = ["cancelled", "failed"].includes(progress.status);
  if (!isChatSessionPending() && !terminalVisible) return "";
  const visibleSteps = progress.workTrace?.items?.length
    ? progress.workTrace.items.map((item) => ({ detail: item.text }))
    : progress.visibleEvents.length
      ? progress.visibleEvents
      : [{ stage: progress.stage, detail: progress.detail }];
  const pendingApproval = pendingApprovalFromProgress(progress);
  const canCancel = ["queued", "running", "waiting"].includes(progress.status) && Boolean(progress.requestId || currentChatProgressRequestId());
  const showSpinner = !["cancelled", "failed", "stopped"].includes(progress.status);
  return `
    <div class="ask-message ask-message-assistant ask-message-progress">
      <div class="ask-message-stack">
        <div class="ask-progress-card" role="status" aria-live="polite">
          <div class="ask-progress-header">
            <span class="ask-progress-copy">
              ${showSpinner ? `<span class="ask-progress-spinner" aria-hidden="true"></span>` : ""}
              <strong>${escapeHtml(progress.detail)}</strong>
            </span>
            ${canCancel ? `<button class="ask-progress-cancel" type="button" data-chat-cancel>Cancel</button>` : ""}
          </div>
          ${pendingApproval ? renderProgressApproval(pendingApproval) : ""}
          ${visibleSteps.length > 1 ? `
            <ol class="ask-progress-steps">
              ${visibleSteps.slice(-3).map((event, index, events) => `
                <li class="${index === events.length - 1 ? "is-current" : "is-done"}">
                  <span>${escapeHtml(event.detail)}</span>
                </li>
              `).join("")}
            </ol>
          ` : ""}
        </div>
      </div>
    </div>
  `;
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
  const workItems = normalizeWorkTrace(workTrace)?.items || [];
  return `
    <div class="${classPrefix}-run-summary">
      <div class="${classPrefix}-run-summary-row">
        <button class="${classPrefix}-run-summary-toggle" type="button" data-run-summary-toggle aria-expanded="false">
          <span>Worked for ${escapeHtml(duration)}</span>
          <span class="${classPrefix}-run-summary-chevron" aria-hidden="true"></span>
        </button>
        ${normalized.requestId ? `<button class="${classPrefix}-run-summary-debug" type="button" data-debug-run-open="${escapeHtml(normalized.requestId)}">Debug</button>` : ""}
      </div>
      <div class="${classPrefix}-run-summary-body" data-run-summary-body hidden>
        ${workItems.length ? `
          <ol class="${classPrefix}-run-summary-events">
            ${workItems.map((item) => `
              <li>
                <span class="${classPrefix}-run-summary-type">${escapeHtml(workTraceItemLabel(item.type))}</span>
                <span>${escapeHtml(item.text)}</span>
              </li>
            `).join("")}
          </ol>
        ` : `<p class="${classPrefix}-run-summary-empty">No visible work steps recorded.</p>`}
      </div>
    </div>
  `;
}

function workTraceItemLabel(type) {
  const normalized = normalizeText(type);
  if (normalized === "skill") return "Skill";
  if (normalized === "tool") return "Tool";
  if (normalized === "status") return "Status";
  if (normalized === "commentary") return "Update";
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
      data: event.data || {}
    }))
  });
}

function attachRunTraceFallback(messages, payload, startedAtMs) {
  const trace = runTraceFromPayload(payload, startedAtMs);
  if (!trace) return messages;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") {
      if (!messages[index].runTrace) messages[index].runTrace = trace;
      return messages;
    }
  }
  return messages;
}

function renderProgressApproval(approval) {
  const actioning = readerState.toolApprovalActionId === approval.approvalId;
  const summary = approval.argumentSummary || approval.risk || "Local note write";
  return `
    <div class="ask-progress-approval">
      <div class="ask-progress-approval-copy">
        <strong>${escapeHtml(toolDisplayName(approval.toolName))}</strong>
        <span>${escapeHtml(summary)}</span>
      </div>
      <div class="ask-progress-approval-actions">
        <button type="button" data-progress-approval-action="allow_once" data-progress-approval-id="${escapeHtml(approval.approvalId)}" ${actioning ? "disabled" : ""}>Allow</button>
        <button type="button" data-progress-approval-action="allow_always" data-progress-approval-id="${escapeHtml(approval.approvalId)}" ${actioning ? "disabled" : ""}>Always</button>
        <button type="button" data-progress-approval-action="deny" data-progress-approval-id="${escapeHtml(approval.approvalId)}" ${actioning ? "disabled" : ""}>Deny</button>
      </div>
    </div>
  `;
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
  if (!readerState.chatMessages.length && !isChatSessionPending()) {
    elements.readerChatMessages.innerHTML = "";
    return;
  }

  const latestUserIndex = latestReaderUserMessageIndex();
  const messagesHtml = readerState.chatMessages.map((rawMessage, index) => {
    const message = normalizeChatMessage(rawMessage);
    if (message.role === "divider") {
      return renderChatDivider(message);
    }
    const sourcesHtml = message.role === "assistant" ? renderChatSources(message.sources) : "";
    const imageHtml = renderChatImages([...(message.attachments || []), ...(message.artifacts || [])]);
    const noteEditHtml = message.role === "assistant" ? renderNoteEditDraft(message.noteEdit) : "";
    const toolActivityHtml = message.role === "assistant" ? renderChatToolActivity(message.toolActivity) : "";
    const traceHtml = message.role === "assistant" ? renderRunTraceSummary(message.runTrace, message.workTrace) : "";
    const editing = message.role === "user" && readerState.chatEditingIndex === index;
    const generationHtml = message.role === "user" ? renderUserGenerationBadge(message.generation, message.attachments) : "";
    const userActionsHtml = renderReaderUserMessageActions(message, index, latestUserIndex);
    const bubbleHtml = editing
      ? renderReaderUserMessageEdit(message, index)
      : message.text
        ? `<div class="ask-bubble">${rawMessage.streaming ? renderStreamingChatText(message.text) : renderChatMarkdown(message.text)}</div>`
        : "";
    return `
    <div class="ask-message ask-message-${message.role}${message.error ? " ask-message-error" : ""}">
      <div class="ask-message-stack">
        ${traceHtml}
        ${bubbleHtml}
        ${imageHtml}
        ${generationHtml}
        ${editing ? "" : userActionsHtml}
        ${sourcesHtml}
        ${noteEditHtml}
        ${toolActivityHtml}
      </div>
    </div>
  `;
  }).join("");
  elements.readerChatMessages.innerHTML = `${messagesHtml}${renderChatProgress()}`;
  if (forceScrollToBottom || (scrollToBottom && wasNearBottom)) {
    elements.readerChatMessages.scrollTop = elements.readerChatMessages.scrollHeight;
  } else if (preserveScrollTop || scrollToBottom) {
    elements.readerChatMessages.scrollTop = previousScrollTop;
    requestAnimationFrame(() => {
      if (elements.readerChatMessages) elements.readerChatMessages.scrollTop = previousScrollTop;
    });
  }
}

function renderUserGenerationBadge(generation, attachments = []) {
  const label = generationRequestLabel(generation, attachments);
  if (!label) return "";
  return `<div class="ask-user-generation-badge">${escapeHtml(label)}</div>`;
}

function renderChatDivider(message) {
  const text = message.text || "Context compacted. Earlier conversation was summarized.";
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

function findChatNoteEdit(editId) {
  for (const message of readerState.chatMessages) {
    const noteEdit = normalizeNoteEditDraft(message.noteEdit);
    if (noteEdit?.id === editId) return message.noteEdit;
  }
  return null;
}

function markChatNoteEditApplied(editId) {
  readerState.chatMessages.forEach((message) => {
    if (message.noteEdit?.id === editId) {
      message.noteEdit.applied = true;
    }
  });
}

function discardChatNoteEdit(editId) {
  readerState.chatMessages.forEach((message) => {
    if (message.noteEdit?.id === editId) {
      message.noteEdit = null;
    }
  });
  renderReaderChatMessages();
}

async function applyChatNoteEdit(editId) {
  const noteEdit = normalizeNoteEditDraft(findChatNoteEdit(editId));
  if (!noteEdit || noteEdit.applied) return;
  setReaderChatError(ASSISTANT_UNAVAILABLE_MESSAGE);
}

function handleNoteEditDraftClick(event) {
  const applyButton = event.target.closest("[data-note-edit-apply]");
  if (applyButton) {
    event.preventDefault();
    applyChatNoteEdit(applyButton.dataset.noteEditApply);
    return;
  }
  const discardButton = event.target.closest("[data-note-edit-discard]");
  if (discardButton) {
    event.preventDefault();
    discardChatNoteEdit(discardButton.dataset.noteEditDiscard);
  }
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
  const approvalButton = event.target.closest("[data-progress-approval-action]");
  if (approvalButton) {
    event.preventDefault();
    respondReaderToolApproval(
      approvalButton.dataset.progressApprovalId,
      approvalButton.dataset.progressApprovalAction
    ).catch((error) => setReaderChatError(error.message || GENERIC_AGENT_ERROR));
    return;
  }

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

async function viewToolActivityNote(noteId) {
  const targetNoteId = normalizeText(noteId);
  if (!targetNoteId) return;
  if (targetNoteId && targetNoteId !== currentChatNoteId()) {
    setReaderChatError("Open that note from the library to view the change.");
    return;
  }
  await refreshCurrentNoteAfterToolUndo();
  setHtmlPaneVisible(true);
  elements.notePane?.scrollTo({ top: 0, behavior: "smooth" });
}

async function previewReaderToolSnapshotDiff(snapshotId, { sessionId = getChatSessionId() } = {}) {
  const targetSnapshotId = normalizeText(snapshotId);
  const targetSessionId = normalizeText(sessionId);
  if (!targetSnapshotId || !targetSessionId) return null;
  if (readerState.toolDiffs[targetSnapshotId]) {
    const nextDiffs = { ...readerState.toolDiffs };
    delete nextDiffs[targetSnapshotId];
    readerState.toolDiffs = nextDiffs;
    renderReaderChatMessages({ preserveScrollTop: true });
    return null;
  }
  readerState.toolDiffActionId = targetSnapshotId;
  renderReaderChatMessages({ preserveScrollTop: true });
  try {
    const payload = await fetchAgentJson(
      `/api/chat/tool-snapshot-diff?sessionId=${encodeURIComponent(targetSessionId)}&snapshotId=${encodeURIComponent(targetSnapshotId)}&maxChars=18000`
    );
    const diff = normalizeToolDiff(payload);
    if (diff) {
      readerState.toolDiffs = {
        ...readerState.toolDiffs,
        [targetSnapshotId]: diff
      };
    }
    renderReaderChatMessages({ preserveScrollTop: true });
    return diff;
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    return null;
  } finally {
    readerState.toolDiffActionId = "";
    renderReaderChatMessages({ preserveScrollTop: true });
  }
}

async function handleToolActivityClick(event) {
  const viewButton = event.target.closest("[data-tool-view-note]");
  if (viewButton) {
    event.preventDefault();
    await viewToolActivityNote(viewButton.dataset.toolViewNote);
    return;
  }

  const previewButton = event.target.closest("[data-tool-preview]");
  if (previewButton) {
    event.preventDefault();
    await previewReaderToolSnapshotDiff(previewButton.dataset.toolPreview, {
      sessionId: normalizeText(previewButton.dataset.toolSessionId) || getChatSessionId()
    });
    return;
  }

  const toggleButton = event.target.closest("[data-tool-toggle]");
  if (toggleButton) {
    event.preventDefault();
    const snapshotId = normalizeText(toggleButton.dataset.toolToggle);
    const mode = normalizeText(toggleButton.dataset.toolToggleMode) === "redo" ? "redo" : "undo";
    const stateKey = normalizeText(toggleButton.dataset.toolStateKey) || snapshotId;
    const sessionId = normalizeText(toggleButton.dataset.toolSessionId) || getChatSessionId();
    const currentState = normalizeText(readerState.toolUndoStates[stateKey]);
    if (!snapshotId || !sessionId || currentState === "undoing" || currentState === "redoing") return;
    if (mode === "redo" && currentState !== "undone") return;
    if (mode === "undo" && currentState === "undone") return;
    preserveReaderChatScrollTop(() => setToolUndoState(stateKey, mode === "redo" ? "redoing" : "undoing"));
    try {
      if (mode === "redo") {
        await redoReaderToolSnapshot(snapshotId, { sessionId, force: true });
        preserveReaderChatScrollTop(() => setToolUndoState(stateKey, ""));
      } else {
        await restoreReaderToolSnapshot(snapshotId, { sessionId, force: true });
        preserveReaderChatScrollTop(() => setToolUndoState(stateKey, "undone"));
      }
    } catch (error) {
      preserveReaderChatScrollTop(() => setToolUndoState(stateKey, currentState));
      setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    }
    return;
  }
}
