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

function renderChatIcon(name, label = "", className = "", size = 16) {
  return window.renderPaperIcon
    ? window.renderPaperIcon(name, { label, className, size })
    : "";
}
