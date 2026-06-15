function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")));
    reader.addEventListener("error", () => reject(reader.error || new Error("Could not read attachment.")));
    reader.readAsDataURL(file);
  });
}

function createLocalAttachment(file) {
  const image = isImageFile(file);
  const name = normalizeText(file?.name) || (image ? `pasted-image-${Date.now()}.png` : `attachment-${Date.now()}`);
  const previewUrl = image ? URL.createObjectURL(file) : "";
  return {
    id: `local_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    kind: image ? "image" : localFileKind(file),
    source: "local",
    mimeType: normalizeText(file?.type) || mimeTypeForFileName(name),
    fileName: name,
    size: Number(file?.size) || 0,
    url: previewUrl,
    localPreviewUrl: previewUrl,
    uploadPending: true
  };
}

function revokeAttachmentPreview(attachment) {
  const previewUrl = normalizeText(attachment?.localPreviewUrl);
  if (!previewUrl || !previewUrl.startsWith("blob:")) return;
  try {
    URL.revokeObjectURL(previewUrl);
  } catch (error) {
    console.warn("Failed to revoke image preview URL.", error);
  }
}

function isImageFile(file) {
  return Boolean(file && typeof file.type === "string" && file.type.startsWith("image/"));
}

function isSupportedAttachmentFile(file) {
  return Boolean(file);
}

function mimeTypeForFileName(fileName) {
  const name = normalizeText(fileName).toLowerCase();
  if (name.endsWith(".pdf")) return "application/pdf";
  if (name.endsWith(".md") || name.endsWith(".markdown")) return "text/markdown";
  if (name.endsWith(".txt")) return "text/plain";
  if (name.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  if (name.endsWith(".pptx")) return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  if (name.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  return "";
}

function localFileKind(file) {
  const mimeType = normalizeText(file?.type || mimeTypeForFileName(file?.name)).toLowerCase();
  const name = normalizeText(file?.name).toLowerCase();
  if (mimeType === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (name.endsWith(".docx")) return "document";
  if (name.endsWith(".pptx")) return "presentation";
  if (name.endsWith(".xlsx")) return "spreadsheet";
  if (mimeType.startsWith("text/") || name.endsWith(".txt") || name.endsWith(".md") || name.endsWith(".markdown")) return "text";
  return "file";
}

async function uploadReaderAttachmentFile(file) {
  const data = await readFileAsDataUrl(file);
  const payload = await fetchAgentJson("/api/chat/attachments", {
    method: "POST",
    body: {
      data,
      fileName: file?.name || "attachment",
      mimeType: file?.type || mimeTypeForFileName(file?.name),
      sessionId: getChatSessionId(),
      requestId: createRequestId(),
      metadata: { source: "reader_upload" }
    }
  });
  return normalizeAttachmentArtifacts([payload.artifact])[0];
}

async function handleReaderAttachmentFiles(files) {
  let selectedFiles = Array.from(files || []).filter(isSupportedAttachmentFile);
  if (!selectedFiles.length) return;
  const imageFiles = selectedFiles.filter(isImageFile);
  let blockedImageMessage = "";
  if (imageFiles.length && !activeProviderSupportsImageInput()) {
    blockedImageMessage = activeProviderImageInputUnsupportedMessage();
    selectedFiles = selectedFiles.filter((file) => !isImageFile(file));
    setReaderChatError(blockedImageMessage);
    if (!selectedFiles.length) {
      if (elements.readerAttachmentInput) elements.readerAttachmentInput.value = "";
      renderAttachmentTray();
      renderReaderToolControls();
      return;
    }
  }
  readerState.imageUploadPending = true;
  readerState.attachmentUploadPending = true;
  const localAttachments = selectedFiles.map(createLocalAttachment);
  readerState.chatAttachments.push(...localAttachments);
  renderAttachmentTray();
  renderReaderToolControls();
  try {
    for (const [index, file] of selectedFiles.entries()) {
      const localAttachment = localAttachments[index];
      const artifact = await uploadReaderAttachmentFile(file);
      const currentIndex = readerState.chatAttachments.findIndex((entry) => entry.id === localAttachment.id);
      if (currentIndex === -1) {
        revokeAttachmentPreview(localAttachment);
        continue;
      }
      if (artifact) {
        revokeAttachmentPreview(localAttachment);
        readerState.chatAttachments.splice(currentIndex, 1, artifact);
        renderAttachmentTray();
        renderReaderToolControls();
      }
    }
    setReaderChatError(blockedImageMessage || "");
  } catch (error) {
    for (const localAttachment of localAttachments) {
      const current = readerState.chatAttachments.find((entry) => entry.id === localAttachment.id);
      if (current) {
        current.uploadPending = false;
        current.uploadError = error.message || "Upload failed.";
      }
    }
    setReaderChatError(error.message || "Could not upload attachment.");
  } finally {
    readerState.imageUploadPending = false;
    readerState.attachmentUploadPending = false;
    if (elements.readerAttachmentInput) elements.readerAttachmentInput.value = "";
    renderAttachmentTray();
    renderReaderToolControls();
  }
}

function handleReaderImageFiles(files) {
  return handleReaderAttachmentFiles(files);
}

function currentPdfPageCanvasForScreenshot() {
  const page = Number(currentPdfScrollPosition()?.page) || 1;
  const pageElement = elements.pdfViewer?.querySelector(`.pdf-page[data-page="${page}"]`)
    || elements.pdfViewer?.querySelector(".pdf-page");
  const canvas = pageElement?.querySelector(".pdf-page-canvas");
  return { page: Number(pageElement?.dataset?.page) || page, canvas };
}

function canvasToPngBlob(canvas) {
  return new Promise((resolve, reject) => {
    if (!canvas || !canvas.width || !canvas.height) {
      reject(new Error("No rendered PDF page is available to capture."));
      return;
    }
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("Could not capture the current PDF page."));
    }, "image/png");
  });
}

function screenshotFileName(page) {
  const title = normalizeText(readerState.note?.title || "paper")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "paper";
  return `${title}-page-${Number(page) || 1}.png`;
}

async function addCurrentPdfPageScreenshot() {
  if (!activeProviderSupportsImageInput()) {
    setReaderChatError(activeProviderImageInputUnsupportedMessage());
    closeReaderToolMenu();
    return;
  }
  const { page, canvas } = currentPdfPageCanvasForScreenshot();
  const blob = await canvasToPngBlob(canvas);
  const file = new File([blob], screenshotFileName(page), { type: "image/png" });
  closeReaderToolMenu();
  await handleReaderAttachmentFiles([file]);
  elements.readerChatInput?.focus();
}

function handleAttachmentTrayClick(event) {
  const selectedTextRemove = event.target.closest("[data-selected-text-remove]");
  if (selectedTextRemove) {
    event.preventDefault();
    clearReaderSelectedPdfText({ clearNativeSelection: true });
    return;
  }

  const generationRemove = event.target.closest("[data-generation-mode-remove]");
  if (generationRemove) {
    event.preventDefault();
    clearReaderGenerationMode();
    return;
  }

  const removeButton = event.target.closest("[data-attachment-remove]");
  if (removeButton) {
    event.preventDefault();
    const targetId = normalizeText(removeButton.dataset.attachmentRemove);
    const target = readerState.chatAttachments.find((artifact) => artifact.id === targetId);
    revokeAttachmentPreview(target);
    readerState.chatAttachments = readerState.chatAttachments.filter((artifact) => artifact.id !== targetId);
    renderAttachmentTray();
    renderReaderToolControls();
    return;
  }
}
