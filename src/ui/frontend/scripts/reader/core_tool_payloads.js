function normalizeToolActivity(rawItems) {
  if (!Array.isArray(rawItems)) return [];
  const seenSnapshotIds = new Set();
  return rawItems.map((raw) => {
    if (!raw || typeof raw !== "object") return null;
    const changedFiles = Array.isArray(raw.changedFiles)
      ? raw.changedFiles.map((file) => ({
        path: normalizeText(file?.path),
        beforeBytes: Math.max(0, Math.round(Number(file?.beforeBytes) || 0)),
        afterBytes: Math.max(0, Math.round(Number(file?.afterBytes) || 0))
      })).filter((file) => file.path)
      : [];
    return {
      name: normalizeText(raw.name) || "tool",
      sessionId: normalizeText(raw.sessionId),
      noteId: normalizeText(raw.noteId),
      snapshotId: normalizeText(raw.snapshotId),
      heading: normalizeText(raw.heading),
      position: normalizeText(raw.position),
      addedHeadings: (Array.isArray(raw.addedHeadings) ? raw.addedHeadings : [])
        .map(normalizeText)
        .filter(Boolean),
      undoable: Boolean(raw.undoable),
      writeMode: normalizeWriteToolMode(raw.writeMode),
      message: normalizeText(raw.message),
      toolMessage: normalizeText(raw.toolMessage),
      summary: normalizeText(raw.summary),
      changed: raw.changed !== false,
      changedFiles
    };
  }).filter((item) => {
    if (!item || !item.changedFiles.length) return false;
    if (!item.snapshotId) return true;
    if (seenSnapshotIds.has(item.snapshotId)) return false;
    seenSnapshotIds.add(item.snapshotId);
    return true;
  });
}

function normalizeWriteToolMode(value) {
  const mode = normalizeText(value).toLowerCase();
  return ["auto", "warn", "ask", "readonly"].includes(mode) ? mode : "auto";
}

function writeToolModeLabel(mode) {
  const normalized = normalizeWriteToolMode(mode);
  if (normalized === "warn") return "Warn";
  if (normalized === "ask") return "Ask";
  if (normalized === "readonly") return "Read-only";
  return "Auto";
}

function normalizeToolSettings(payload) {
  const globalAccess = normalizeText(payload?.globalAccess || "default").toLowerCase() === "full_access"
    ? "full_access"
    : "default";
  const tools = (Array.isArray(payload?.tools) ? payload.tools : []).map((tool) => ({
    name: normalizeText(tool.name),
    enabled: tool.enabled !== false,
    access: normalizeText(tool.access || "inherit").toLowerCase(),
    mutating: Boolean(tool.mutating),
    readOnly: Boolean(tool.readOnly || tool.read_only)
  })).filter((tool) => tool.name);
  const builtInTools = (Array.isArray(payload?.builtInTools) ? payload.builtInTools : []).map((tool) => ({
    name: normalizeText(tool.name),
    enabled: tool.enabled !== false,
  })).filter((tool) => tool.name);
  const customTools = (Array.isArray(payload?.customTools) ? payload.customTools : []).map((tool) => ({
    name: normalizeText(tool.name),
    enabled: tool.enabled !== false,
  })).filter((tool) => tool.name);
  const disabledTools = Array.isArray(payload?.disabledTools)
    ? payload.disabledTools.map(normalizeText).filter(Boolean)
    : tools.filter((tool) => !tool.enabled || tool.access === "disabled").map((tool) => tool.name);
  const disabledToolsets = Array.isArray(payload?.disabledToolsets)
    ? payload.disabledToolsets.map(normalizeText).filter(Boolean)
    : tools.filter((tool) => !tool.enabled || tool.access === "disabled").map((tool) => tool.name);
  const enabledToolsets = Array.isArray(payload?.enabledToolsets)
    ? payload.enabledToolsets.map(normalizeText).filter(Boolean)
    : customTools.filter((tool) => tool.enabled).map((tool) => tool.name);
  const webSearchProviders = normalizeReaderWebSearchProviders(payload?.webSearchProviders);
  const toolWriteModes = {};
  const rawWriteModes = payload?.toolWriteModes && typeof payload.toolWriteModes === "object"
    ? payload.toolWriteModes
    : {};
  Object.entries(rawWriteModes).forEach(([name, mode]) => {
    const normalizedName = normalizeText(name);
    const normalizedMode = normalizeWriteToolMode(mode);
    if (normalizedName) toolWriteModes[normalizedName] = normalizedMode;
  });
  return {
    globalAccess,
    defaultWriteMode: globalAccess === "full_access" ? "auto" : "ask",
    disabledTools,
    disabledToolsets,
    enabledToolsets,
    toolWriteModes,
    webSearchProviders,
    nativeWebSearchEnabled: Boolean(
      payload?.nativeWebSearchEnabled
      || builtInTools.some((tool) => tool.name === "native_web_search" && tool.enabled)
    )
  };
}

function normalizeReaderWebSearchProviders(raw) {
  const providers = raw && typeof raw === "object" ? raw : {};
  const nativeRaw = providers.nativeProvider || {};
  const customRaw = providers.customProvider || {};
  const enabledEntry = (value) => ({
    enabled: Boolean(value && typeof value === "object" && value.enabled)
  });
  return {
    nativeProvider: {
      openaiCodex: enabledEntry(nativeRaw.openaiCodex),
      openaiAPIKey: enabledEntry(nativeRaw.openaiAPIKey),
    },
    customProvider: {
      Tavily: enabledEntry(customRaw.Tavily || customRaw.tavily),
      Brave: enabledEntry(customRaw.Brave || customRaw.brave || customRaw.braveSearch),
    }
  };
}

function readerToolSettingsPayload() {
  const settings = readerState.toolSettings || normalizeToolSettings({});
  const enabledToolsets = settings.enabledToolsets?.length ? ["default", ...settings.enabledToolsets] : [];
  const nativeSearchEnabled = readerNativeWebSearchEnabledForCurrentProvider(settings);
  const disabledTools = [...(settings.disabledTools || [])];
  if (nativeSearchEnabled && !disabledTools.includes("web_search")) {
    disabledTools.push("web_search");
  }
  return {
    enabledToolsets,
    disabledToolsets: settings.disabledToolsets,
    disabledTools,
    toolWriteModes: settings.toolWriteModes,
    requestOptions: {
      _paper_notes_native_web_search: nativeSearchEnabled
    }
  };
}

function readerNativeWebSearchEnabledForCurrentProvider(settings) {
  const provider = currentReaderProvider();
  const capabilities = modelCapabilitiesFor(provider, currentReaderModel());
  if (!capabilities.supportsWebSearch) {
    return false;
  }
  const native = settings?.webSearchProviders?.nativeProvider || {};
  const customSearchEnabled = readerCustomWebSearchEnabled(settings);
  if (provider === "codex-oauth") {
    return Boolean(native.openaiCodex?.enabled || settings?.nativeWebSearchEnabled);
  }
  if (provider === "openai") {
    return Boolean(native.openaiAPIKey?.enabled || settings?.nativeWebSearchEnabled || !customSearchEnabled);
  }
  return false;
}

function readerCustomWebSearchEnabled(settings) {
  const custom = settings?.webSearchProviders?.customProvider || {};
  return Boolean(custom.Tavily?.enabled || custom.Brave?.enabled);
}

function readerGenerationPayload() {
  return generationPayloadForRequest({
    type: readerState.generationMode,
    format: readerState.fileGenerationFormat,
  });
}

function normalizeGenerationRequest(raw) {
  if (!raw || typeof raw !== "object") return null;
  const normalizedType = normalizeText(raw.type).toLowerCase();
  if (normalizedType === "file") {
    return {
      type: "file",
      format: normalizeFileGenerationFormat(raw.format)
    };
  }
  if (normalizedType === "image") {
    return { type: "image", format: "image" };
  }
  const fileGeneration = raw.fileGeneration;
  if (fileGeneration?.enabled) {
    return {
      type: "file",
      format: normalizeFileGenerationFormat(fileGeneration.format)
    };
  }
  const imageGeneration = raw.imageGeneration;
  if (imageGeneration?.enabled) {
    return { type: "image", format: "image" };
  }
  return null;
}

function generationPayloadFromRequest(generation) {
  return generationPayloadForRequest(normalizeGenerationRequest(generation));
}

function generationPayloadForRequest(normalized) {
  if (!normalized) return {};
  if (normalized.type === "image") {
    return {
      imageGeneration: {
        enabled: true,
        size: "1024x1024",
        quality: "auto",
        format: "png"
      }
    };
  }
  if (normalized.type === "file") {
    return {
      fileGeneration: {
        enabled: true,
        format: normalizeFileGenerationFormat(normalized.format)
      }
    };
  }
  return {};
}

function generationRequestLabel(generation, attachments = []) {
  if (!generation) return "";
  if (generation.type === "image") {
    const imageCount = normalizeAttachmentArtifacts(attachments).filter((attachment) => attachment.kind === "image").length;
    return imageCount > 0 ? `Generate image · ${imageCount} images` : "Generate image";
  }
  if (generation.type === "file") return `Generate file · ${fileGenerationFormatLabel(generation.format)}`;
  return "";
}

function normalizeSelectedTextContext(raw) {
  if (!raw || typeof raw !== "object") return null;
  const text = normalizeText(raw.text || raw.selectionText).slice(0, 4000);
  if (!text) return null;
  const words = text.split(/\s+/).filter(Boolean).length;
  return {
    type: "selected_text",
    text,
    page: normalizeText(raw.page || raw.currentPage),
    wordCount: Number(raw.wordCount || words || 0) || 0
  };
}
