function readStoredReaderModelSelection() {
  try {
    const parsed = JSON.parse(localStorage.getItem(READER_MODEL_SELECTION_KEY) || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const provider = normalizeProviderName(parsed.provider);
    const model = normalizeText(parsed.model);
    return provider && model ? { provider, model } : {};
  } catch (error) {
    return {};
  }
}

function writeStoredReaderModelSelection(provider, model) {
  const normalizedProvider = normalizeProviderName(provider);
  const normalizedModel = normalizeText(model);
  if (!normalizedProvider || !normalizedModel) return {};
  const selection = { provider: normalizedProvider, model: normalizedModel };
  try {
    localStorage.setItem(READER_MODEL_SELECTION_KEY, JSON.stringify(selection));
  } catch (error) {
    console.warn("Failed to save reader model selection.", error);
  }
  return selection;
}

function normalizeDeepSeekThinkMode(rawMode) {
  const mode = normalizeText(rawMode).toLowerCase();
  if (!mode || mode === "off" || mode === "none" || mode === "false") return { enabled: false, effort: "high" };
  const effort = ["high", "max"].includes(mode) ? mode : "high";
  return { enabled: true, effort };
}

function readStoredDeepSeekThinkMode() {
  try {
    return normalizeDeepSeekThinkMode(localStorage.getItem(DEEPSEEK_THINK_MODE_KEY) || "");
  } catch (error) {
    return { enabled: false, effort: "high" };
  }
}

function writeStoredDeepSeekThinkMode(mode) {
  const normalized = normalizeDeepSeekThinkMode(mode);
  try {
    localStorage.setItem(DEEPSEEK_THINK_MODE_KEY, normalized.enabled ? normalized.effort : "off");
  } catch (error) {
    console.warn("Failed to save DeepSeek think mode.", error);
  }
  return normalized;
}

function currentDeepSeekThinkMode() {
  const sessionMode = normalizeText(currentReaderSession()?.deepSeekThinkMode);
  if (sessionMode) return normalizeDeepSeekThinkMode(sessionMode);
  return normalizeDeepSeekThinkMode(readerState.deepSeekThinkMode?.enabled ? readerState.deepSeekThinkMode.effort : "off");
}

function normalizeGptThinkMode(rawMode, model = "", provider = "") {
  const mode = normalizeText(rawMode).toLowerCase();
  if (!mode || mode === "off" || mode === "none" || mode === "false") {
    const selectedProvider = normalizeProviderName(provider);
    const selectedModel = normalizeText(model);
    return !selectedProvider || !selectedModel || gptReasoningOffSupported(selectedProvider, selectedModel)
      ? { enabled: false, effort: "medium" }
      : { enabled: true, effort: "low" };
  }
  const effort = ["low", "medium", "high", "xhigh"].includes(mode) ? mode : "medium";
  return { enabled: true, effort };
}

function readStoredGptThinkMode(model = "", provider = "") {
  try {
    return normalizeGptThinkMode(localStorage.getItem(GPT_THINK_MODE_KEY) || "", model, provider);
  } catch (error) {
    return { enabled: false, effort: "medium" };
  }
}

function writeStoredGptThinkMode(mode, model = currentReaderModel(), provider = currentReaderProvider()) {
  const normalized = normalizeGptThinkMode(mode, model, provider);
  try {
    localStorage.setItem(GPT_THINK_MODE_KEY, normalized.enabled ? normalized.effort : "off");
  } catch (error) {
    console.warn("Failed to save GPT think mode.", error);
  }
  return normalized;
}

function providerSupportsGptThinkMode(provider) {
  const normalized = normalizeProviderName(provider);
  return normalized === "openai" || normalized === "codex-oauth";
}

function currentGptThinkMode(model = currentReaderModel(), provider = currentReaderProvider()) {
  const sessionMode = normalizeText(currentReaderSession()?.gptThinkMode);
  if (sessionMode) return normalizeGptThinkMode(sessionMode, model, provider);
  return normalizeGptThinkMode(readerState.gptThinkMode?.enabled ? readerState.gptThinkMode.effort : "off", model, provider);
}

function syncReaderThinkModesFromStorage() {
  readerState.deepSeekThinkMode = readStoredDeepSeekThinkMode();
  readerState.gptThinkMode = readStoredGptThinkMode(currentReaderModel(), currentReaderProvider());
}

syncReaderThinkModesFromStorage();

function isCodexProvider(provider) {
  return normalizeProviderName(provider) === "codex-oauth";
}

function fallbackProviderDisplayName(provider) {
  const normalized = normalizeText(provider);
  if (normalized === "codex-oauth") return "Codex OAuth";
  if (normalized === "openai") return "OpenAI API key";
  return normalized || "Provider";
}

function normalizeProviderName(value) {
  const provider = normalizeText(value);
  if (!provider) return "";
  if (provider === "codex" || provider === "openai-codex" || provider === "codex-oauth") {
    return "codex-oauth";
  }
  if (provider === "openai" || provider === "openai-api-key") return "openai";
  const catalog = readerState?.modelCatalog;
  const profile = catalog?.providers?.find((item) => item.name === provider || item.aliases?.includes(provider));
  return profile?.name || provider;
}

function normalizeModelOption(rawOption) {
  const value = normalizeText(rawOption?.value || rawOption?.model || rawOption?.id || rawOption);
  if (!value) return null;
  const label = normalizeText(rawOption?.label) || value;
  const shortLabel = normalizeText(rawOption?.shortLabel) || label;
  const description = normalizeText(rawOption?.description || rawOption?.detail);
  const hasCapabilities = rawOption
    && typeof rawOption === "object"
    && Object.prototype.hasOwnProperty.call(rawOption, "capabilities");
  return {
    value,
    label,
    shortLabel,
    description,
    detail: description,
    capabilities: hasCapabilities ? normalizeModelCapabilities(rawOption.capabilities) : null
  };
}

function normalizeModelCapabilities(rawCapabilities) {
  const raw = rawCapabilities && typeof rawCapabilities === "object" ? rawCapabilities : {};
  return {
    supportsTools: raw.supportsTools !== false,
    supportsVision: Boolean(raw.supportsVision),
    supportsImageGeneration: Boolean(raw.supportsImageGeneration),
    supportsImageArtifactGeneration: Boolean(raw.supportsImageArtifactGeneration),
    supportsWebSearch: Boolean(raw.supportsWebSearch),
    supportsReasoningOff: raw.supportsReasoningOff !== false,
    contextWindow: Math.max(0, Math.round(Number(raw.contextWindow) || 0)),
    imageInputMode: normalizeText(raw.imageInputMode)
  };
}

function normalizeModelProvider(rawProvider) {
  const name = normalizeProviderName(rawProvider?.name || rawProvider?.provider);
  if (!name) return null;
  const aliases = Array.isArray(rawProvider?.aliases)
    ? rawProvider.aliases.map(normalizeText).filter(Boolean)
    : [];
  const models = (Array.isArray(rawProvider?.models) ? rawProvider.models : [])
    .map(normalizeModelOption)
    .filter(Boolean);
  const defaultModel = normalizeText(rawProvider?.defaultModel);
  const selectedModel = normalizeText(rawProvider?.selectedModel || rawProvider?.model);
  return {
    name,
    aliases,
    displayName: normalizeText(rawProvider?.displayName) || fallbackProviderDisplayName(name),
    authType: normalizeText(rawProvider?.authType),
    description: normalizeText(rawProvider?.description),
    defaultModel,
    configured: Boolean(rawProvider?.configured),
    ready: Boolean(rawProvider?.ready),
    model: selectedModel,
    selectedModel,
    modelSource: normalizeText(rawProvider?.modelSource || "profile"),
    capabilities: normalizeModelCapabilities(rawProvider?.capabilities),
    models
  };
}

function normalizeReaderModelCatalog(payload) {
  const providers = (Array.isArray(payload?.providers) ? payload.providers : [])
    .map(normalizeModelProvider)
    .filter(Boolean);
  const requestedDefault = normalizeProviderName(payload?.defaultProvider || payload?.provider);
  const defaultProvider = providers.some((profile) => profile.name === requestedDefault)
    ? requestedDefault
    : providers.find((profile) => profile.configured)?.name || providers[0]?.name || requestedDefault || "openai";
  return {
    defaultProvider,
    defaultModel: normalizeText(payload?.defaultModel || payload?.model),
    modelConnectionConfigured: Boolean(payload?.modelConnectionConfigured || payload?.configured),
    codexAuth: payload && Object.prototype.hasOwnProperty.call(payload, "codexAuth")
      ? normalizeReaderCodexAuth(payload.codexAuth)
      : null,
    providers
  };
}

function normalizeReaderCodexAuth(payload) {
  const auth = payload && typeof payload === "object" ? payload : {};
  return {
    loggedIn: Boolean(auth.loggedIn),
    authMode: normalizeText(auth.authMode || ""),
    planType: normalizeText(auth.planType || ""),
    accountId: normalizeText(auth.accountId || ""),
    accountEmail: normalizeText(auth.accountEmail || ""),
    lastRefresh: normalizeText(auth.lastRefresh || ""),
    authStorePath: normalizeText(auth.authStorePath || "")
  };
}

function normalizeReaderAiSettings(payload) {
  const provider = normalizeProviderName(payload?.provider) || "openai";
  return {
    provider,
    model: normalizeText(payload?.model),
    modelSource: normalizeText(payload?.modelSource || "missing"),
    configured: Boolean(payload?.configured),
    ready: Boolean(payload?.ready),
    codexAuth: normalizeReaderCodexAuth(payload?.codexAuth)
  };
}

function currentReaderSession() {
  const sessionId = getChatSessionId();
  if (!sessionId) return null;
  const listedSession = readerState.chatSessions.find((session) => session.id === sessionId);
  if (listedSession) {
    readerState.currentChatSession = listedSession;
    return listedSession;
  }
  return readerState.currentChatSession?.id === sessionId ? readerState.currentChatSession : null;
}

function currentReaderModelCatalog() {
  return readerState.modelCatalog || normalizeReaderModelCatalog({});
}

function modelProvidersForMenu() {
  const catalog = currentReaderModelCatalog();
  const configuredProviders = catalog.providers.filter((profile) => profile.configured);
  if (configuredProviders.length) return configuredProviders;
  if (catalog.providers.length) return [];
  const settings = readerState.aiSettings || normalizeReaderAiSettings({});
  return [
    {
      name: "openai",
      displayName: "OpenAI API key",
      aliases: [],
      configured: settings.provider === "openai" && settings.configured,
      ready: settings.provider === "openai" && settings.ready,
      model: settings.provider === "openai" ? settings.model : "",
      selectedModel: settings.provider === "openai" ? settings.model : "",
      modelSource: settings.modelSource || "missing",
      defaultModel: "",
      models: []
    },
    {
      name: "codex-oauth",
      displayName: "Codex OAuth",
      aliases: ["codex", "openai-codex"],
      configured: settings.provider === "codex-oauth" && settings.configured,
      ready: settings.provider === "codex-oauth" && settings.ready,
      model: settings.provider === "codex-oauth" ? settings.model : "",
      selectedModel: settings.provider === "codex-oauth" ? settings.model : "",
      modelSource: settings.modelSource || "missing",
      defaultModel: "",
      models: []
    }
  ].filter((profile) => profile.configured);
}

function providerProfileFor(provider) {
  const normalized = normalizeProviderName(provider) || normalizeProviderName(currentReaderModelCatalog().defaultProvider) || "openai";
  const menuProfile = modelProvidersForMenu().find((profile) => profile.name === normalized || profile.aliases?.includes(normalized));
  if (menuProfile) return menuProfile;
  const catalogProfile = currentReaderModelCatalog().providers.find(
    (profile) => profile.name === normalized || profile.aliases?.includes(normalized)
  );
  return catalogProfile?.configured ? catalogProfile : null;
}

function modelOptionsForProvider(provider, selectedModel = "") {
  const selected = normalizeText(selectedModel);
  const profile = providerProfileFor(provider);
  const options = (profile?.models || []).map((option) => ({ ...option }));
  const ensureOption = (value, label = "", description = "") => {
    const normalized = normalizeText(value);
    if (!normalized || options.some((option) => option.value === normalized)) return;
    options.push({
      value: normalized,
      label: normalizeText(label) || normalized,
      shortLabel: normalizeText(label) || normalized,
      description: normalizeText(description),
      detail: normalizeText(description)
    });
  };
  ensureOption(normalizeText(profile?.model || profile?.defaultModel), "", "Provider default");
  if (providerAllowsSavedModel(provider, selected, options)) {
    ensureOption(selected, "", "Current saved model");
  }
  return options;
}

function providerAllowsSavedModel(provider, model, options = null) {
  const selected = normalizeText(model);
  if (!selected) return false;
  const normalizedProvider = normalizeProviderName(provider);
  const catalogOptions = options || (providerProfileFor(provider)?.models || []);
  if (catalogOptions.some((option) => option.value === selected)) return true;
  return normalizedProvider !== "codex-oauth";
}

function defaultModelForProvider(provider) {
  const profile = providerProfileFor(provider);
  return normalizeText(profile?.model || profile?.defaultModel) || modelOptionsForProvider(provider)[0]?.value || "";
}

function currentReaderModel() {
  const activeSessionId = getChatSessionId();
  const sessionModel = normalizeText(currentReaderSession()?.model);
  const provider = currentReaderProvider();
  if (sessionModel) return sessionModel;
  if (activeSessionId) {
    return defaultModelForProvider(provider)
      || (normalizeProviderName(readerState.aiSettings?.provider) === provider ? normalizeText(readerState.aiSettings?.model) : "");
  }
  if (normalizeProviderName(readerState.pendingChatProvider) === provider) {
    const pendingModel = normalizeText(readerState.pendingChatModel);
    if (providerAllowsSavedModel(provider, pendingModel)) return pendingModel;
  }
  const stored = readStoredReaderModelSelection();
  if (normalizeProviderName(stored.provider) === provider && normalizeText(stored.model)) {
    const storedModel = normalizeText(stored.model);
    if (providerAllowsSavedModel(provider, storedModel)) return storedModel;
  }
  return defaultModelForProvider(provider)
    || (normalizeProviderName(readerState.aiSettings?.provider) === provider ? normalizeText(readerState.aiSettings?.model) : "");
}

function currentReaderProvider() {
  const activeSessionId = getChatSessionId();
  const sessionProvider = normalizeProviderName(currentReaderSession()?.provider);
  if (sessionProvider) return sessionProvider;
  if (activeSessionId) {
    return normalizeProviderName(currentReaderModelCatalog().defaultProvider)
      || normalizeProviderName(readerState.aiSettings?.provider)
      || "openai";
  }
  const stored = readStoredReaderModelSelection();
  const storedProvider = normalizeProviderName(stored.provider);
  return normalizeProviderName(readerState.pendingChatProvider)
    || (storedProvider && providerProfileFor(storedProvider) ? storedProvider : "")
    || normalizeProviderName(currentReaderModelCatalog().defaultProvider)
    || normalizeProviderName(readerState.aiSettings?.provider)
    || "openai";
}

function activeReaderModelProvider() {
  return normalizeProviderName(readerState.modelDraftProvider) || currentReaderProvider();
}

function providerDisplayName(provider) {
  return normalizeText(providerProfileFor(provider)?.displayName) || fallbackProviderDisplayName(provider);
}

function modelDisplayLabel(model, provider, field = "label") {
  const selected = normalizeText(model);
  const option = modelOptionsForProvider(provider, selected).find((item) => item.value === selected);
  return normalizeText(option?.[field] || selected);
}

function modelCapabilitiesFor(provider, model) {
  const profile = providerProfileFor(provider);
  const selected = normalizeText(model);
  const option = modelOptionsForProvider(provider, selected).find((item) => item.value === selected);
  return option?.capabilities || profile?.capabilities || normalizeModelCapabilities({});
}

function gptReasoningOffSupported(provider, model = currentReaderModel()) {
  return Boolean(modelCapabilitiesFor(provider, model).supportsReasoningOff);
}

function activeProviderSupportsImageArtifacts() {
  const provider = currentReaderProvider();
  const profile = providerProfileFor(provider);
  const capabilities = modelCapabilitiesFor(provider, currentReaderModel());
  const settings = readerState.aiSettings || normalizeReaderAiSettings({});
  const configured = Boolean(
    profile?.configured
    || (normalizeProviderName(settings.provider) === provider && settings.configured)
  );
  if (!configured) return false;
  return Boolean(capabilities.supportsImageArtifactGeneration);
}

function activeProviderImageGenerationUnsupportedMessage() {
  const provider = currentReaderProvider();
  const profile = providerProfileFor(provider);
  const settings = readerState.aiSettings || normalizeReaderAiSettings({});
  const configured = Boolean(
    profile?.configured
    || (normalizeProviderName(settings.provider) === provider && settings.configured)
  );
  if (configured) {
    const label = modelDisplayLabel(currentReaderModel(), provider, "label") || currentReaderModel();
    return `${label || providerDisplayName(provider)} does not support image generation.`;
  }
  return "Image generation needs a connected Codex OAuth or OpenAI API key provider.";
}

function activeProviderSupportsImageInput() {
  const capabilities = modelCapabilitiesFor(currentReaderProvider(), currentReaderModel());
  return Boolean(capabilities.supportsVision && capabilities.imageInputMode !== "unsupported");
}

function activeProviderImageInputUnsupportedMessage() {
  if (normalizeProviderName(currentReaderProvider()) === "deepseek") {
    return "DeepSeek does not support image input. Files can still be attached.";
  }
  return "The selected model does not support image input. Files can still be attached.";
}

function modelSourceLabel(source) {
  const normalized = normalizeText(source);
  const labels = {
    default: "default",
    environment: "environment",
    local: "local settings",
    ".env.local": ".env.local",
    ".env": ".env",
    profile: "profile",
    selected: "selected",
    session: "session",
    missing: "not set"
  };
  return labels[normalized] || normalized || "not set";
}
