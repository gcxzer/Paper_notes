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
      stage: normalizeText(event?.stage),
      message: sanitizeChatProgressDetail(event?.message || event?.detail),
      at: normalizeText(event?.at),
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

function canMergeStreamingWorkTraceType(type) {
  return ["summary", "commentary", "reasoning"].includes(normalizeText(type));
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
  while (/[.,!?;:，。！？；：、]$/.test(trimmed)) {
    trailing = trimmed.slice(-1) + trailing;
    trimmed = trimmed.slice(0, -1);
  }
  return [trimmed, trailing];
}

function renderChatMathExpression(source, displayMode = false) {
  const formula = String(source || "").trim();
  if (!formula) return "";
  if (globalThis.katex?.renderToString) {
    return globalThis.katex.renderToString(formula, {
      displayMode,
      throwOnError: false,
      strict: "ignore",
      trust: false
    });
  }
  const tag = displayMode ? "div" : "span";
  return `<${tag} class="chat-math-fallback">${escapeHtml(formula)}</${tag}>`;
}

function extractChatMathSegments(text) {
  const mathSegments = [];
  const protect = (displayMode) => (_, formula) => {
    const token = `@@CHATMATH${mathSegments.length}@@`;
    mathSegments.push({
      displayMode,
      html: renderChatMathExpression(formula, displayMode)
    });
    return token;
  };
  const source = String(text || "")
    .replace(/\\\[([\s\S]*?)\\\]/g, protect(true))
    .replace(/\$\$([\s\S]*?)\$\$/g, protect(true))
    .replace(/\\\(([\s\S]*?)\\\)/g, protect(false));
  return { source, mathSegments };
}

function restoreChatMathSegments(html, mathSegments) {
  let output = String(html || "");
  mathSegments.forEach((segment, index) => {
    const token = `@@CHATMATH${index}@@`;
    const replacement = segment.displayMode
      ? `<div class="chat-math-block">${segment.html}</div>`
      : `<span class="chat-math-inline">${segment.html}</span>`;
    output = output.replaceAll(`<p>${token}</p>`, replacement);
    output = output.replaceAll(token, replacement);
  });
  return output;
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
  const { source: withMath, mathSegments } = extractChatMathSegments(withCodeBlocks);
  const codeSpans = [];
  const codeSpanLabels = [];
  let html = escapeHtml(withMath).replace(/`([^`\n]+)`/g, (_, code) => {
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
  html = html.replace(/(https?:\/\/[^\s<>"'()[\]{}（）【】《》]+)/gi, (url) => {
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
  return restoreChatMathSegments(html, mathSegments);
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
    const quote = line.match(/^\s*(?:>|&gt;)\s?(.*)$/);
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

function renderChatToolActivity(toolActivity, { showActions = true, activityScope = "" } = {}) {
  const items = groupToolActivityItems(collapseIntermediateToolActivity(normalizeToolActivity(toolActivity)));
  if (!items.length) return "";
  return `
    <div class="ask-tool-activity" aria-label="Tool activity">
      ${items.map((item, itemIndex) => {
        const undoTarget = toolActivityUndoSnapshotId(item);
        const redoTarget = toolActivityRedoSnapshotId(item);
        const undoState = normalizeText(readerState.toolUndoStates[toolActivityStateKey(item)]);
        const undoBusy = undoState === "undoing" || undoState === "redoing";
        const toggleMode = undoState === "undone" ? "redo" : "undo";
        const toggleSnapshots = toolActivityToggleSnapshotIds(item, toggleMode);
        const toggleTarget = toggleSnapshots[0] || (toggleMode === "redo" ? redoTarget : undoTarget);
        const toggleLabel = toggleMode === "redo" ? "Redo" : "Undo";
        const snapshotState = toolSnapshotStateFor(toggleTarget);
        const toggleUnavailable = snapshotState
          ? (toggleMode === "redo" ? !snapshotState.canRedo : !snapshotState.canUndo)
          : false;
        const showView = toolActivityChangesHtmlNote(item);
        const viewNoteId = normalizeText(item.noteId) || (showView ? currentChatNoteId() : "");
        const viewHeading = toolActivityViewHeading(item);
        const viewAddedHeadings = toolActivityAddedHeadings(item);
        const previewKey = toolActivityPreviewKey(item, activityScope, itemIndex);
        const previewSnapshotIds = toolActivitySnapshotIds(item);
        return `
        <div class="ask-tool-activity-item" data-tool-activity-id="${escapeHtml(toolActivityStateKey(item))}">
          <div class="ask-tool-activity-copy">
            <strong>${escapeHtml(toolDisplayName(item.name))}</strong>
            <span>${escapeHtml(toolActivitySummary(item))}</span>
          </div>
          ${showActions ? `
            <div class="ask-tool-activity-actions">
              ${showView && viewNoteId ? `
                <button
                  class="ask-tool-action"
                  type="button"
                  data-tool-view-note="${escapeHtml(viewNoteId)}"
                  data-tool-view-heading="${escapeHtml(viewHeading)}"
                  data-tool-view-position="${escapeHtml(item.position)}"
                  data-tool-view-added-headings="${escapeHtml(JSON.stringify(viewAddedHeadings))}"
                >View</button>
              ` : ""}
              ${showView && previewSnapshotIds.length ? `
                <button
                  class="ask-tool-action"
                  type="button"
                  data-tool-preview="${escapeHtml(previewSnapshotIds[previewSnapshotIds.length - 1])}"
                  data-tool-preview-snapshots="${escapeHtml(previewSnapshotIds.join(","))}"
                  data-tool-preview-key="${escapeHtml(previewKey)}"
                  data-tool-session-id="${escapeHtml(item.sessionId)}"
                  ${readerState.toolDiffActionId === previewKey ? "disabled" : ""}
                >${readerState.toolDiffActionId === previewKey ? "Loading" : "Preview"}</button>
              ` : ""}
              ${item.undoable && toggleTarget ? `
                <button
                  class="ask-tool-action ask-tool-undo"
                  type="button"
                  data-tool-toggle="${escapeHtml(toggleTarget)}"
                  data-tool-toggle-snapshots="${escapeHtml(toggleSnapshots.join(","))}"
                  data-tool-toggle-mode="${escapeHtml(toggleMode)}"
                  data-tool-state-key="${escapeHtml(toolActivityStateKey(item))}"
                  data-tool-session-id="${escapeHtml(item.sessionId)}"
                  ${undoBusy || toggleUnavailable ? "disabled" : ""}
                >${escapeHtml(toggleLabel)}</button>
              ` : ""}
            </div>
            ${renderToolActivityDiff(item, previewKey)}
          ` : ""}
        </div>
      `;
      }).join("")}
    </div>
  `;
}

function collapseIntermediateToolActivity(items) {
  const latestByWriteTarget = new Map();
  const sequencesByWriteTarget = new Map();
  items.forEach((item, index) => {
    const key = intermediateToolActivityKey(item);
    if (!key) return;
    latestByWriteTarget.set(key, index);
    const sequence = sequencesByWriteTarget.get(key) || [];
    if (item.snapshotId) sequence.push(item.snapshotId);
    sequencesByWriteTarget.set(key, sequence);
  });
  return items.map((item, index) => {
    const key = intermediateToolActivityKey(item);
    if (!key || latestByWriteTarget.get(key) !== index) return item;
    const snapshotIds = sequencesByWriteTarget.get(key) || [];
    return {
      ...item,
      snapshotIds,
      undoSnapshotId: snapshotIds[0] || item.snapshotId,
      redoSnapshotId: snapshotIds[snapshotIds.length - 1] || item.snapshotId,
      collapsedCount: snapshotIds.length
    };
  }).filter((item, index) => {
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

function toolActivityPreviewKey(item, activityScope, itemIndex) {
  return [
    normalizeText(activityScope) || "activity",
    toolActivityStateKey(item) || normalizeText(item?.snapshotId) || "snapshot",
    String(Math.max(0, Number(itemIndex) || 0))
  ].join(":");
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
      snapshotIds: toolActivitySnapshotIds(item),
      undoSnapshotId: normalizeText(item.undoSnapshotId) || toolActivitySnapshotIds(item)[0] || item.snapshotId,
      redoSnapshotId: normalizeText(item.redoSnapshotId) || toolActivitySnapshotIds(item).at(-1) || item.snapshotId
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

function toolActivityStateKey(item) {
  const snapshotIds = toolActivitySnapshotIds(item);
  return snapshotIds.length > 1 ? snapshotIds.join("|") : normalizeText(item?.undoSnapshotId || item?.snapshotId);
}

function toolActivitySnapshotIds(item) {
  const rawIds = Array.isArray(item?.snapshotIds) ? item.snapshotIds : [];
  const ids = rawIds.map(normalizeText).filter(Boolean);
  if (!ids.length && item?.snapshotId) ids.push(normalizeText(item.snapshotId));
  return [...new Set(ids)];
}

function toolActivityToggleSnapshotIds(item, mode) {
  const ids = toolActivitySnapshotIds(item);
  return mode === "redo" ? ids : [...ids].reverse();
}

function toolSnapshotStateFor(snapshotId) {
  const targetSnapshotId = normalizeText(snapshotId);
  if (!targetSnapshotId) return null;
  return (readerState.toolSnapshots || []).find((snapshot) => snapshot.snapshotId === targetSnapshotId) || null;
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

function renderToolActivityDiff(item, previewKey = "") {
  if (!readerState.toolDiffOpen?.[previewKey]) return "";
  const snapshotIds = toolActivitySnapshotIds(item);
  const diffs = snapshotIds
    .map((snapshotId) => normalizeToolDiff(readerState.toolDiffs[snapshotId]))
    .filter((diff) => diff?.files?.length);
  if (!diffs.length) return "";
  const showStepLabels = diffs.length > 1;
  return `
    <div class="ask-tool-diff" data-tool-diff="${escapeHtml(snapshotIds.join(","))}">
      ${diffs.map((diff, diffIndex) => diff.files.map((file, fileIndex) => {
        const changeKey = toolDiffChangeKey(previewKey, diff, diffIndex, file, fileIndex);
        const collapsed = Boolean(readerState.toolDiffCollapsed?.[changeKey]);
        const changeLabel = showStepLabels ? `Change ${diffIndex + 1}` : "Change";
        return `
        <div class="ask-tool-diff-file${collapsed ? " is-collapsed" : ""}" data-tool-diff-change="${escapeHtml(changeKey)}">
          <div class="ask-tool-diff-header">
            <div class="ask-tool-diff-heading">
              <button
                class="ask-tool-diff-collapse"
                type="button"
                data-tool-diff-collapse="${escapeHtml(changeKey)}"
                aria-expanded="${collapsed ? "false" : "true"}"
                aria-label="${escapeHtml(collapsed ? `Expand ${changeLabel}` : `Collapse ${changeLabel}`)}"
              >
                <span class="ask-tool-diff-chevron" aria-hidden="true"></span>
              </button>
              <strong>
                ${escapeHtml(file.path)}
                ${showStepLabels ? `<span class="ask-tool-diff-step-count">Change ${escapeHtml(diffIndex + 1)} / ${escapeHtml(diffs.length)}</span>` : ""}
              </strong>
            </div>
            ${renderToolDiffSummary(file.diff)}
          </div>
          ${collapsed ? "" : renderToolDiffPreview(file.diff, file.path)}
        </div>
      `;
      }).join("")).join("")}
    </div>
  `;
}

function toolDiffChangeKey(previewKey, diff, diffIndex, file, fileIndex) {
  return [
    normalizeText(previewKey),
    normalizeText(diff?.snapshotId) || `diff-${diffIndex}`,
    normalizeText(file?.path) || `file-${fileIndex}`,
    String(fileIndex)
  ].join("|");
}

function parseToolDiffLines(diffText) {
  const added = [];
  const removed = [];
  String(diffText || "").split(/\r?\n/).forEach((rawLine) => {
    if (!rawLine || rawLine.startsWith("@@") || rawLine.startsWith("+++") || rawLine.startsWith("---")) return;
    const marker = rawLine[0];
    if (marker !== "+" && marker !== "-") return;
    const value = rawLine.slice(1).trim();
    if (!value) return;
    if (marker === "+") added.push(value);
    if (marker === "-") removed.push(value);
  });
  return { added, removed };
}

function toolDiffSummary(diffText) {
  const { added, removed } = parseToolDiffLines(diffText);
  const parts = [];
  if (removed.length) parts.push(`${removed.length} removed`);
  if (added.length) parts.push(`${added.length} added`);
  return parts.join(" · ") || "No rendered changes";
}

function renderToolDiffSummary(diffText) {
  const { added, removed } = parseToolDiffLines(diffText);
  const parts = [];
  if (removed.length) {
    parts.push(`<span class="ask-tool-diff-stat is-removed">${escapeHtml(removed.length)} removed</span>`);
  }
  if (added.length) {
    parts.push(`<span class="ask-tool-diff-stat is-added">${escapeHtml(added.length)} added</span>`);
  }
  return `<span class="ask-tool-diff-stats">${parts.join(`<span class="ask-tool-diff-stat-separator">·</span>`) || "No rendered changes"}</span>`;
}

function renderToolDiffPreview(diffText) {
  if (!diffText) return `<p>No text diff available.</p>`;
  return `
    <div class="ask-tool-diff-viewer" role="table" aria-label="Preview diff">
      ${renderToolDiffRows(diffText)}
    </div>
  `;
}

function renderToolDiffRows(diffText) {
  const lines = String(diffText || "").split(/\r?\n/);
  let oldLine = 0;
  let newLine = 0;
  let hasReliableLineNumbers = false;
  const rows = [];
  lines.forEach((rawLine) => {
    if (!rawLine || rawLine.startsWith("---") || rawLine.startsWith("+++")) return;
    const hunk = rawLine.match(/@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@(.*)$/);
    if (hunk) {
      oldLine = Number(hunk[1]) || 0;
      newLine = Number(hunk[2]) || 0;
      hasReliableLineNumbers = true;
      const trailingContent = normalizeText(hunk[3]);
      if (!trailingContent) {
        rows.push(`
          <div class="ask-tool-diff-row is-hunk has-no-lines" role="row">
            <span class="ask-tool-diff-line"></span>
            <span class="ask-tool-diff-line"></span>
            <span class="ask-tool-diff-marker">@@</span>
            <code>${escapeHtml(rawLine.slice(hunk.index || 0))}</code>
          </div>
        `);
        return;
      }
      rows.push(renderToolDiffRow("context", hasReliableLineNumbers ? oldLine : "", hasReliableLineNumbers ? newLine : "", "", trailingContent));
      oldLine += 1;
      newLine += 1;
      return;
    }
    const marker = rawLine[0];
    const content = rawLine.slice(marker === "+" || marker === "-" || marker === " " ? 1 : 0);
    if (marker === "-") {
      rows.push(renderToolDiffRow("removed", hasReliableLineNumbers ? oldLine : "", "", "-", content));
      oldLine += 1;
      return;
    }
    if (marker === "+") {
      rows.push(renderToolDiffRow("added", "", hasReliableLineNumbers ? newLine : "", "+", content));
      newLine += 1;
      return;
    }
    rows.push(renderToolDiffRow(
      "context",
      hasReliableLineNumbers && oldLine ? oldLine : "",
      hasReliableLineNumbers && newLine ? newLine : "",
      "",
      marker === " " ? content : rawLine
    ));
    if (oldLine) oldLine += 1;
    if (newLine) newLine += 1;
  });
  return rows.join("") || `<p>No text diff available.</p>`;
}

function renderToolDiffRow(kind, oldLine, newLine, marker, content) {
  const hasLineNumber = normalizeText(oldLine) || normalizeText(newLine);
  return `
    <div class="ask-tool-diff-row is-${escapeHtml(kind)}${hasLineNumber ? "" : " has-no-lines"}" role="row">
      <span class="ask-tool-diff-line">${escapeHtml(oldLine)}</span>
      <span class="ask-tool-diff-line">${escapeHtml(newLine)}</span>
      <span class="ask-tool-diff-marker">${escapeHtml(marker)}</span>
      <code>${escapeHtml(content)}</code>
    </div>
  `;
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
  if (!isChatSessionPending()) return "";
  const compactionMarkerHtml = renderContextCompactionMarker(progress.events, { running: true });
  const pendingApproval = pendingApprovalFromProgress(progress);
  const rows = progressInlineRows(progress);
  const activeToolIndex = lastProgressToolRowIndex(rows);
  const rowsHtml = rows.map((row, index) => renderProgressInlineRow(row, { active: index === activeToolIndex })).join("");
  const approvalHtml = pendingApproval ? renderProgressApprovalMessage(pendingApproval) : "";
  return `${compactionMarkerHtml}${rowsHtml}${approvalHtml}`;
}

function renderManualContextCompactionProgress() {
  if (!readerState.contextCompacting) return "";
  return renderContextCompactionDivider("Compacting context", "running");
}

function progressInlineRows(progress) {
  const rows = [];
  if (progress.workTrace?.items?.length) {
    rows.push(...progress.workTrace.items.map((item) => ({
      type: normalizeText(item.type) || "status",
      detail: item.text,
      at: item.at
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
  return sortTraceItemsChronologically(rows).map((row) => {
    const detail = sanitizeChatProgressDetail(row.detail);
    if (!detail) return null;
    const type = progressInlineType(row.type);
    if (isHiddenRunTraceMessage(type, detail)) return null;
    const key = `${type}\n${detail}`;
    if (seen.has(key)) return null;
    seen.add(key);
    return { type, detail, at: normalizeText(row.at) };
  }).filter(Boolean);
}

function lastProgressToolRowIndex(rows) {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (progressInlineType(rows[index]?.type) === "tool") return index;
  }
  return -1;
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
  const textHtml = activeClass ? renderProgressInlineReadingText(detailText, row.at) : detail;
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
        ${normalized.requestId ? `<button class="${classPrefix}-run-summary-debug" type="button" data-debug-run-open="${escapeHtml(normalized.requestId)}">Debug</button>` : ""}
      </div>
      <div class="${classPrefix}-run-summary-body" data-run-summary-body${expanded ? "" : " hidden"}>
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
    .filter((item) => !isHiddenRunTraceMessage(item.type, item.text));
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
  if (!text || isHiddenRunTraceMessage(eventType, text)) return null;
  if (eventType === "work_trace_item" || eventType === "work_trace_delta") {
    return {
      type: normalizeText(data.trace_type || data.traceType) || "summary",
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
    return Boolean(text) && !isHiddenRunTraceMessage(type, text);
  });
  return normalizeWorkTrace({ status: normalized.status, items: visibleRows });
}

function mergeWorkTraces(first, second) {
  const firstItems = normalizeWorkTrace(first)?.items || [];
  const secondItems = normalizeWorkTrace(second)?.items || [];
  const status = normalizeText(second?.status || first?.status) || "completed";
  return normalizeWorkTrace({ status, items: [...firstItems, ...secondItems] });
}

function renderProgressApproval(approval) {
  const actioning = readerState.toolApprovalActionId === approval.approvalId;
  const summary = approval.argumentSummary || approval.risk || "Local note write";
  return `
    <div class="ask-inline-approval">
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

function renderProgressApprovalMessage(approval) {
  return `
    <div class="ask-message ask-message-assistant ask-message-progress-inline ask-message-progress-approval" role="status" aria-live="polite">
      <div class="ask-message-stack">
        ${renderProgressApproval(approval)}
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
    const noteEditHtml = message.role === "assistant" ? renderNoteEditDraft(message.noteEdit) : "";
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
        ${noteEditHtml}
        ${toolActivityHtml}
      </div>
    </div>
  `;
  }).join("");
  elements.readerChatMessages.innerHTML = `${messagesHtml}${insertedProgress ? "" : chatProgressHtml}`;
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
    : (message.text || "Context compacted");
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

async function previewReaderToolSnapshotDiff(snapshotIds, { sessionId = getChatSessionId(), previewKey = "" } = {}) {
  const targetSnapshotIds = Array.isArray(snapshotIds)
    ? [...new Set(snapshotIds.map(normalizeText).filter(Boolean))]
    : normalizeToolToggleSnapshotIds(snapshotIds);
  const targetSessionId = normalizeText(sessionId);
  const targetPreviewKey = normalizeText(previewKey) || targetSnapshotIds.join("|");
  if (!targetSnapshotIds.length || !targetSessionId) return null;
  if (readerState.toolDiffOpen?.[targetPreviewKey]) {
    const nextOpen = { ...(readerState.toolDiffOpen || {}) };
    delete nextOpen[targetPreviewKey];
    readerState.toolDiffOpen = nextOpen;
    renderReaderChatMessages({ preserveScrollTop: true });
    return null;
  }
  const missingSnapshotIds = targetSnapshotIds.filter((snapshotId) => !readerState.toolDiffs[snapshotId]);
  if (!missingSnapshotIds.length) {
    readerState.toolDiffOpen = {
      ...(readerState.toolDiffOpen || {}),
      [targetPreviewKey]: true
    };
    renderReaderChatMessages({ preserveScrollTop: true });
    return targetSnapshotIds.map((snapshotId) => normalizeToolDiff(readerState.toolDiffs[snapshotId])).filter(Boolean);
  }
  readerState.toolDiffActionId = targetPreviewKey;
  renderReaderChatMessages({ preserveScrollTop: true });
  try {
    const diffs = (await Promise.all(missingSnapshotIds.map(async (snapshotId) => {
      const payload = await fetchAgentJson(
        `/api/chat/tool-snapshot-diff?sessionId=${encodeURIComponent(targetSessionId)}&snapshotId=${encodeURIComponent(snapshotId)}&maxChars=18000`
      );
      return normalizeToolDiff(payload);
    }))).filter(Boolean);
    if (diffs.length) {
      const nextDiffs = { ...(readerState.toolDiffs || {}) };
      diffs.forEach((diff) => {
        nextDiffs[diff.snapshotId] = diff;
      });
      readerState.toolDiffs = {
        ...nextDiffs
      };
      readerState.toolDiffOpen = {
        ...(readerState.toolDiffOpen || {}),
        [targetPreviewKey]: true
      };
    }
    renderReaderChatMessages({ preserveScrollTop: true });
    return targetSnapshotIds.map((snapshotId) => normalizeToolDiff(readerState.toolDiffs[snapshotId])).filter(Boolean);
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    return null;
  } finally {
    readerState.toolDiffActionId = "";
    renderReaderChatMessages({ preserveScrollTop: true });
  }
}

function toggleToolDiffChangeCollapsed(changeKey) {
  const key = normalizeText(changeKey);
  if (!key) return;
  const nextCollapsed = { ...(readerState.toolDiffCollapsed || {}) };
  if (nextCollapsed[key]) {
    delete nextCollapsed[key];
  } else {
    nextCollapsed[key] = true;
  }
  readerState.toolDiffCollapsed = nextCollapsed;
  renderReaderChatMessages({ preserveScrollTop: true });
}

async function handleToolActivityClick(event) {
  const diffCollapseButton = event.target.closest("[data-tool-diff-collapse]");
  if (diffCollapseButton) {
    event.preventDefault();
    toggleToolDiffChangeCollapsed(diffCollapseButton.dataset.toolDiffCollapse);
    return;
  }

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

  const previewButton = event.target.closest("[data-tool-preview]");
  if (previewButton) {
    event.preventDefault();
    await previewReaderToolSnapshotDiff(
      previewButton.dataset.toolPreviewSnapshots || previewButton.dataset.toolPreview,
      {
      sessionId: normalizeText(previewButton.dataset.toolSessionId) || getChatSessionId(),
      previewKey: normalizeText(previewButton.dataset.toolPreviewKey)
      }
    );
    return;
  }

  const toggleButton = event.target.closest("[data-tool-toggle]");
  if (toggleButton) {
    event.preventDefault();
    const snapshotId = normalizeText(toggleButton.dataset.toolToggle);
    const snapshotIds = normalizeToolToggleSnapshotIds(toggleButton.dataset.toolToggleSnapshots, snapshotId);
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
        for (const targetSnapshotId of snapshotIds) {
          await redoReaderToolSnapshot(targetSnapshotId, { sessionId });
        }
        preserveReaderChatScrollTop(() => setToolUndoState(stateKey, ""));
      } else {
        for (const targetSnapshotId of snapshotIds) {
          await restoreReaderToolSnapshot(targetSnapshotId, { sessionId });
        }
        preserveReaderChatScrollTop(() => setToolUndoState(stateKey, "undone"));
      }
    } catch (error) {
      preserveReaderChatScrollTop(() => setToolUndoState(stateKey, currentState));
      setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    }
    return;
  }
}

function normalizeToolToggleSnapshotIds(value, fallback = "") {
  const ids = normalizeText(value)
    .split(",")
    .map(normalizeText)
    .filter(Boolean);
  if (!ids.length && fallback) ids.push(normalizeText(fallback));
  return [...new Set(ids)];
}
