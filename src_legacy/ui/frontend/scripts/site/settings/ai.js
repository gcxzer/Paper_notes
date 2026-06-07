function normalizeAiSettings(payload) {
  const codexAuth = payload?.codexAuth || {};
  return {
    provider: normalizeText(payload?.provider || "openai"),
    providerSource: normalizeText(payload?.providerSource || "default"),
    supportedProviders: Array.isArray(payload?.supportedProviders) ? payload.supportedProviders.map(normalizeText) : ["openai"],
    configured: Boolean(payload?.configured),
    ready: Boolean(payload?.ready),
    model: normalizeText(payload?.model || ""),
    modelConfigured: Boolean(payload?.modelConfigured),
    modelSource: normalizeText(payload?.modelSource || "missing"),
    keySource: normalizeText(payload?.keySource || "missing"),
    localKeyConfigured: Boolean(payload?.localKeyConfigured),
    environmentKeyConfigured: Boolean(payload?.environmentKeyConfigured),
    localModelConfigured: Boolean(payload?.localModelConfigured),
    environmentModelConfigured: Boolean(payload?.environmentModelConfigured),
    localProviderConfigured: Boolean(payload?.localProviderConfigured),
    environmentProviderConfigured: Boolean(payload?.environmentProviderConfigured),
    modelConnectionConfigured: Boolean(payload?.modelConnectionConfigured),
    localSecretsPath: normalizeText(payload?.localSecretsPath || ".paper-notes/secrets.env"),
    codexAuth: {
      loggedIn: Boolean(codexAuth.loggedIn),
      authMode: normalizeText(codexAuth.authMode || ""),
      planType: normalizeText(codexAuth.planType || ""),
      accountId: normalizeText(codexAuth.accountId || ""),
      accountEmail: normalizeText(codexAuth.accountEmail || ""),
      lastRefresh: normalizeText(codexAuth.lastRefresh || ""),
      authStorePath: normalizeText(codexAuth.authStorePath || ".paper-notes/auth/codex.json")
    }
  };
}

function settingsSourceLabel(source) {
  const normalized = normalizeText(source);
  const labels = {
    default: "default",
    environment: "environment",
    local: "local settings",
    ".env.local": ".env.local",
    ".env": ".env",
    missing: "not set"
  };
  return labels[normalized] || normalized || "not set";
}

function isCodexProvider(provider = state.aiSettings?.provider) {
  return normalizeText(provider) === "codex-oauth";
}

function isGeminiProvider(provider = state.aiSettings?.provider) {
  return normalizeText(provider) === "gemini";
}

function isAnthropicProvider(provider = state.aiSettings?.provider) {
  return normalizeText(provider) === "anthropic";
}

function isDeepSeekProvider(provider = state.aiSettings?.provider) {
  return normalizeText(provider) === "deepseek";
}

function normalizeAiProvider(provider) {
  const value = normalizeText(provider);
  if (isCodexProvider(value)) return "codex-oauth";
  if (isAnthropicProvider(value) || value === "claude") return "anthropic";
  if (isGeminiProvider(value)) return "gemini";
  if (isDeepSeekProvider(value)) return "deepseek";
  return "openai";
}

function aiProviderProfile(provider) {
  const target = normalizeAiProvider(provider);
  const providers = Array.isArray(state.aiProviderCatalog?.providers) ? state.aiProviderCatalog.providers : [];
  return providers.find((profile) => normalizeAiProvider(profile?.name) === target) || null;
}

function openAiProviderConfigured(settings = state.aiSettings) {
  const profile = aiProviderProfile("openai");
  if (profile) return Boolean(profile.configured);
  const normalized = settings || normalizeAiSettings({});
  return Boolean(
    normalized.localKeyConfigured
    || normalized.environmentKeyConfigured
    || (normalizeAiProvider(normalized.provider) === "openai" && normalized.configured)
  );
}

function codexProviderConfigured(settings = state.aiSettings) {
  if (settings) return Boolean(normalizeAiSettings(settings).codexAuth.loggedIn);
  const profile = aiProviderProfile("codex-oauth");
  return Boolean(profile?.configured);
}

function geminiProviderConfigured(settings = state.aiSettings) {
  const profile = aiProviderProfile("gemini");
  if (profile) return Boolean(profile.configured);
  const normalized = settings || normalizeAiSettings({});
  return Boolean(isGeminiProvider(normalized.provider) && normalized.configured);
}

function anthropicProviderConfigured(settings = state.aiSettings) {
  const profile = aiProviderProfile("anthropic");
  if (profile) return Boolean(profile.configured);
  const normalized = settings || normalizeAiSettings({});
  return Boolean(isAnthropicProvider(normalized.provider) && normalized.configured);
}

function deepSeekProviderConfigured(settings = state.aiSettings) {
  const profile = aiProviderProfile("deepseek");
  if (profile) return Boolean(profile.configured);
  const normalized = settings || normalizeAiSettings({});
  return Boolean(isDeepSeekProvider(normalized.provider) && normalized.configured);
}

function providerLocalKeyConfigured(provider, settings = state.aiSettings) {
  const normalizedProvider = normalizeAiProvider(provider);
  const profile = aiProviderProfile(normalizedProvider);
  if (profile) return Boolean(profile.localKeyConfigured);
  const normalized = settings || normalizeAiSettings({});
  return Boolean(normalized.provider === normalizedProvider && normalized.localKeyConfigured);
}

function providerDisplayName(provider) {
  if (isCodexProvider(provider)) return "Codex OAuth";
  if (isAnthropicProvider(provider)) return "Anthropic";
  if (isGeminiProvider(provider)) return "Google Gemini";
  if (isDeepSeekProvider(provider)) return "DeepSeek";
  return "OpenAI API key";
}

function sortedAiProviders() {
  return ["openai", "codex-oauth", "anthropic", "gemini", "deepseek"]
    .sort((a, b) => providerDisplayName(a).localeCompare(providerDisplayName(b), undefined, { sensitivity: "base" }));
}

function aiProviderPanel(provider) {
  if (isAnthropicProvider(provider)) return elements.anthropicSettingsPanel;
  if (isCodexProvider(provider)) return elements.codexSettingsPanel;
  if (isDeepSeekProvider(provider)) return elements.deepSeekSettingsPanel;
  if (isGeminiProvider(provider)) return elements.geminiSettingsPanel;
  return elements.openAiSettingsPanel;
}

function orderAiProviderPanels() {
  const parent = elements.openAiSettingsPanel?.parentElement;
  if (!parent) return;
  sortedAiProviders().forEach((provider) => {
    const panel = aiProviderPanel(provider);
    if (panel) parent.appendChild(panel);
  });
}

function providerKeyName(provider) {
  if (isAnthropicProvider(provider)) return "Anthropic";
  if (isGeminiProvider(provider)) return "Gemini";
  if (isDeepSeekProvider(provider)) return "DeepSeek";
  return "OpenAI";
}

function providerStatusLabel(provider, settings = state.aiSettings) {
  if (isCodexProvider(provider)) {
    return codexProviderConfigured(settings) ? "connected" : "not connected";
  }
  if (isGeminiProvider(provider)) {
    return geminiProviderConfigured(settings) ? "key configured" : "key not configured";
  }
  if (isAnthropicProvider(provider)) {
    return anthropicProviderConfigured(settings) ? "key configured" : "key not configured";
  }
  if (isDeepSeekProvider(provider)) {
    return deepSeekProviderConfigured(settings) ? "key configured" : "key not configured";
  }
  return openAiProviderConfigured(settings) ? "key configured" : "key not configured";
}

function setProviderStatusBadge(element, isConfigured, configuredLabel = "Connected", missingLabel = "Not configured") {
  if (!element) return;
  element.textContent = isConfigured ? configuredLabel : missingLabel;
  element.classList.toggle("is-ready", isConfigured);
}

function renderDefaultProviderOptions(provider, settings) {
  if (!elements.aiProviderInput) return;
  const selectedProvider = normalizeText(provider) ? normalizeAiProvider(provider) : "";
  const options = sortedAiProviders().map((value) => ({
    value,
    label: `${providerDisplayName(value)} (${providerStatusLabel(value, settings)})`
  }));
  elements.aiProviderInput.innerHTML = options.map((option) => (
    `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`
  )).join("");
  elements.aiProviderInput.value = selectedProvider;
}

function configuredAiProviders(settings = state.aiSettings) {
  const normalized = settings || normalizeAiSettings({});
  return sortedAiProviders().filter((provider) => {
    if (provider === "codex-oauth") return codexProviderConfigured(normalized);
    if (provider === "anthropic") return anthropicProviderConfigured(normalized);
    if (provider === "gemini") return geminiProviderConfigured(normalized);
    if (provider === "deepseek") return deepSeekProviderConfigured(normalized);
    return openAiProviderConfigured(normalized);
  });
}

function hasSavedAiProvider(settings = state.aiSettings) {
  const normalized = settings || normalizeAiSettings({});
  return Boolean(normalized.localProviderConfigured || normalized.environmentProviderConfigured);
}

function effectiveDefaultAiProvider(settings = state.aiSettings) {
  const normalized = settings || normalizeAiSettings({});
  const configured = configuredAiProviders(normalized);
  if (!configured.length) return "";
  if (configured.length === 1) return configured[0];
  const selected = normalizeAiProvider(elements.aiProviderInput?.value || normalized.provider);
  return configured.includes(selected) ? selected : configured[0];
}

function selectedAiProvider(settings = state.aiSettings) {
  return effectiveDefaultAiProvider(settings);
}

function capabilityValue(capabilities, key, fallback = false) {
  if (!capabilities || typeof capabilities !== "object") return fallback;
  return Boolean(capabilities[key]);
}

function capabilityText(value) {
  return value ? "Yes" : "No";
}

function modelCapabilityRows() {
  const providers = Array.isArray(state.aiProviderCatalog?.providers) ? state.aiProviderCatalog.providers : [];
  const rowsByModel = new Map();
  providers.forEach((provider) => {
    const providerCapabilities = provider?.capabilities || {};
    const models = Array.isArray(provider?.models) ? provider.models : [];
    models.forEach((model) => {
      const capabilities = model?.capabilities || providerCapabilities;
      const modelId = normalizeText(model?.value || "");
      const modelKey = modelId || normalizeText(model?.label || "unknown-model").toLowerCase();
      const row = rowsByModel.get(modelKey) || {
        entries: [],
        model: normalizeText(model?.label || model?.value || "Unknown model"),
        modelId,
        family: providerFamily(provider?.name),
      };
      row.entries.push({
        provider: providerDisplayName(provider?.name),
        textInput: true,
        imageInput: capabilityValue(capabilities, "supportsVision"),
        imageInputMode: normalizeText(capabilities?.imageInputMode || (capabilityValue(capabilities, "supportsVision") ? "native" : "unsupported")),
        textOutput: true,
        imageOutput: supportsPaperNotesImageGeneration(provider?.name, modelId),
        tools: capabilityValue(capabilities, "supportsTools"),
        nativeWebSearch: capabilityValue(capabilities, "supportsWebSearch"),
        reasoningOff: capabilityValue(capabilities, "supportsReasoningOff"),
        contextWindow: Number(capabilities?.contextWindow) || 0,
      });
      rowsByModel.set(modelKey, row);
    });
  });
  return Array.from(rowsByModel.values());
}

function supportsPaperNotesImageGeneration(provider, model = "") {
  const normalizedProvider = normalizeAiProvider(provider);
  const normalizedModel = normalizeText(model).toLowerCase();
  if (normalizedProvider === "codex-oauth" && normalizedModel === "gpt-5.3-codex-spark") return false;
  return normalizedProvider === "openai" || normalizedProvider === "codex-oauth";
}

function providerFamily(provider) {
  const normalizedProvider = normalizeAiProvider(provider);
  if (normalizedProvider === "openai" || normalizedProvider === "codex-oauth") return "openai";
  return normalizedProvider || "other";
}

function formatContextWindow(value) {
  const numeric = Number(value) || 0;
  return numeric > 0 ? numeric.toLocaleString() : "Unknown";
}

function renderProviderStack(providers) {
  return providers.map((provider, index) => `
    <span class="model-capability-line">
      ${escapeHtml(provider)}${index < providers.length - 1 ? `<span class="model-capability-inline-separator">/</span>` : ""}
    </span>
  `).join("");
}

function renderCapabilityStack(values) {
  const uniqueValues = Array.from(new Set(values.map((value) => normalizeText(value))));
  return uniqueValues.map((value, index) => `
    <span class="model-capability-line">
      ${escapeHtml(value)}${index < uniqueValues.length - 1 ? `<span class="model-capability-inline-separator">/</span>` : ""}
    </span>
  `).join("");
}

function imageInputLabel(entry) {
  return `${capabilityText(entry.imageInput)}${entry.imageInputMode ? ` (${entry.imageInputMode})` : ""}`;
}

function isModelCapabilitiesDialogOpen() {
  const dialog = elements.modelCapabilitiesDialog;
  if (!dialog) return false;
  if (typeof HTMLDialogElement !== "undefined" && dialog instanceof HTMLDialogElement) return dialog.open;
  return !dialog.hidden;
}

function renderModelCapabilitiesTable() {
  if (!elements.modelCapabilitiesTableWrap) return;
  const rows = modelCapabilityRows();
  if (!rows.length) {
    elements.modelCapabilitiesTableWrap.innerHTML = `<p class="model-capabilities-empty">No model capability data is available.</p>`;
    return;
  }
  elements.modelCapabilitiesTableWrap.innerHTML = `
    <table class="model-capabilities-table">
      <thead>
        <tr>
          <th>Model</th>
          <th>Provider</th>
          <th>Text in</th>
          <th>Image in</th>
          <th>Text out</th>
          <th>Image out</th>
          <th>Tools</th>
          <th>Web search</th>
          <th>Reasoning off</th>
          <th>Context</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row, index) => {
          const previousFamily = index > 0 ? rows[index - 1].family : "";
          const startsFamily = index > 0 && row.family !== previousFamily;
          return `
          <tr class="${startsFamily ? "is-provider-family-start" : ""}">
            <td>
              <strong>${escapeHtml(row.model)}</strong>
            </td>
            <td>${renderProviderStack(row.entries.map((entry) => entry.provider))}</td>
            <td>${renderCapabilityStack(row.entries.map((entry) => capabilityText(entry.textInput)))}</td>
            <td>${renderCapabilityStack(row.entries.map(imageInputLabel))}</td>
            <td>${renderCapabilityStack(row.entries.map((entry) => capabilityText(entry.textOutput)))}</td>
            <td>${renderCapabilityStack(row.entries.map((entry) => capabilityText(entry.imageOutput)))}</td>
            <td>${renderCapabilityStack(row.entries.map((entry) => capabilityText(entry.tools)))}</td>
            <td>${renderCapabilityStack(row.entries.map((entry) => capabilityText(entry.nativeWebSearch)))}</td>
            <td>${renderCapabilityStack(row.entries.map((entry) => capabilityText(entry.reasoningOff)))}</td>
            <td>${renderCapabilityStack(row.entries.map((entry) => formatContextWindow(entry.contextWindow)))}</td>
          </tr>
        `;
        }).join("")}
      </tbody>
    </table>
  `;
}

async function openModelCapabilitiesDialog() {
  if (!elements.modelCapabilitiesDialog) return;
  if (!state.aiProviderCatalog && !state.aiSettingsLoading) {
    await loadAiSettings();
  }
  renderModelCapabilitiesTable();
  if (typeof elements.modelCapabilitiesDialog.showModal === "function") {
    elements.modelCapabilitiesDialog.hidden = false;
    if (!elements.modelCapabilitiesDialog.open) elements.modelCapabilitiesDialog.showModal();
    return;
  }
  elements.modelCapabilitiesDialog.hidden = false;
}

function closeModelCapabilitiesDialog() {
  if (!elements.modelCapabilitiesDialog) return;
  if (typeof elements.modelCapabilitiesDialog.close === "function" && elements.modelCapabilitiesDialog.open) {
    elements.modelCapabilitiesDialog.close();
    return;
  }
  elements.modelCapabilitiesDialog.hidden = true;
}

function hasModelConnection(settings = state.aiSettings) {
  const normalized = settings || normalizeAiSettings({});
  if (normalized.modelConnectionConfigured) return true;
  if (state.aiProviderCatalog?.modelConnectionConfigured) return true;
  const hasOpenAiConnection = openAiProviderConfigured(normalized)
    && (normalized.modelConfigured || normalized.localModelConfigured || normalized.environmentModelConfigured);
  const hasAnthropicConnection = anthropicProviderConfigured(normalized)
    && (normalized.modelConfigured || normalized.localModelConfigured || normalized.environmentModelConfigured);
  const hasGeminiConnection = geminiProviderConfigured(normalized)
    && (normalized.modelConfigured || normalized.localModelConfigured || normalized.environmentModelConfigured);
  const hasDeepSeekConnection = deepSeekProviderConfigured(normalized)
    && (normalized.modelConfigured || normalized.localModelConfigured || normalized.environmentModelConfigured);
  const hasCodexConnection = normalized.codexAuth.loggedIn
    && (isCodexProvider(normalized.provider) ? normalized.modelConfigured : false);
  return Boolean(hasOpenAiConnection || hasAnthropicConnection || hasGeminiConnection || hasDeepSeekConnection || hasCodexConnection);
}

function renderModelConnectionStatus() {
  if (!elements.modelConnectionStatus) return;
  const configured = hasModelConnection();
  elements.modelConnectionStatus.textContent = configured ? "Model configured" : "Model not configured";
  elements.modelConnectionStatus.classList.toggle("is-configured", configured);
}

function setAiSettingsError(message = "") {
  elements.aiSettingsError.textContent = message;
  elements.aiSettingsError.hidden = !message;
}

function setAiKeyDialogError(message = "") {
  if (!elements.providerKeyDialogError) return;
  elements.providerKeyDialogError.textContent = message;
  elements.providerKeyDialogError.hidden = !message;
}

function setAiKeyVisibility(visible) {
  state.aiKeyVisible = Boolean(visible);
  if (elements.aiKeyInput) {
    elements.aiKeyInput.type = state.aiKeyVisible ? "text" : "password";
  }
  if (elements.toggleAiKeyVisibilityButton) {
    elements.toggleAiKeyVisibilityButton.classList.toggle("is-visible", state.aiKeyVisible);
    elements.toggleAiKeyVisibilityButton.setAttribute("aria-pressed", state.aiKeyVisible ? "true" : "false");
    elements.toggleAiKeyVisibilityButton.setAttribute("aria-label", state.aiKeyVisible ? "Hide key" : "Show key");
  }
}

function toggleAiKeyVisibility() {
  setAiKeyVisibility(!state.aiKeyVisible);
  elements.aiKeyInput?.focus({ preventScroll: true });
}

function renderAiSettings() {
  if (!elements.aiSettingsDialog) return;
  orderAiProviderPanels();
  renderModelConnectionStatus();
  const settings = state.aiSettings || normalizeAiSettings({});
  const provider = selectedAiProvider(settings);
  const openAiKeyConfigured = openAiProviderConfigured(settings);
  const codexConfigured = codexProviderConfigured(settings);
  const anthropicKeyConfigured = anthropicProviderConfigured(settings);
  const geminiKeyConfigured = geminiProviderConfigured(settings);
  const deepSeekKeyConfigured = deepSeekProviderConfigured(settings);
  const configuredProviders = configuredAiProviders(settings);
  const hasMultipleConfiguredProviders = configuredProviders.length > 1;
  const keyEditingProvider = normalizeAiProvider(state.aiKeyEditingProvider);
  const keyDialogOpen = Boolean(state.aiKeyEditingProvider);

  renderDefaultProviderOptions(provider, settings);
  const openAiDefault = provider === "openai";
  const codexDefault = provider === "codex-oauth";
  const anthropicDefault = provider === "anthropic";
  const geminiDefault = provider === "gemini";
  const deepSeekDefault = provider === "deepseek";
  elements.openAiSettingsPanel?.classList.toggle("is-default", openAiDefault);
  elements.codexSettingsPanel?.classList.toggle("is-default", codexDefault);
  elements.anthropicSettingsPanel?.classList.toggle("is-default", anthropicDefault);
  elements.geminiSettingsPanel?.classList.toggle("is-default", geminiDefault);
  elements.deepSeekSettingsPanel?.classList.toggle("is-default", deepSeekDefault);
  elements.openAiDefaultBadge.hidden = !openAiDefault;
  elements.codexDefaultBadge.hidden = !codexDefault;
  elements.anthropicDefaultBadge.hidden = !anthropicDefault;
  elements.geminiDefaultBadge.hidden = !geminiDefault;
  elements.deepSeekDefaultBadge.hidden = !deepSeekDefault;
  elements.setOpenAiDefaultButton.hidden = !hasMultipleConfiguredProviders || openAiDefault || !openAiKeyConfigured;
  elements.setCodexDefaultButton.hidden = !hasMultipleConfiguredProviders || codexDefault || !codexConfigured;
  elements.setAnthropicDefaultButton.hidden = !hasMultipleConfiguredProviders || anthropicDefault || !anthropicKeyConfigured;
  elements.setGeminiDefaultButton.hidden = !hasMultipleConfiguredProviders || geminiDefault || !geminiKeyConfigured;
  elements.setDeepSeekDefaultButton.hidden = !hasMultipleConfiguredProviders || deepSeekDefault || !deepSeekKeyConfigured;
  elements.setOpenAiDefaultButton.disabled = state.aiSettingsLoading;
  elements.setCodexDefaultButton.disabled = state.aiSettingsLoading;
  elements.setAnthropicDefaultButton.disabled = state.aiSettingsLoading;
  elements.setGeminiDefaultButton.disabled = state.aiSettingsLoading;
  elements.setDeepSeekDefaultButton.disabled = state.aiSettingsLoading;
  elements.openAiKeyTitle.textContent = "OpenAI API key";
  setProviderStatusBadge(elements.openAiStatusBadge, openAiKeyConfigured, "Key saved");
  elements.openAiKeyDetail.textContent = openAiKeyConfigured
    ? settings.provider === "openai" && settings.environmentKeyConfigured
      ? "An environment key is active. Save a local key only if you want a local fallback."
      : "A local key is saved."
    : "Add a local key to enable OpenAI.";
  elements.addAiKeyButton.textContent = openAiKeyConfigured ? "Replace key" : "Add key";
  elements.deleteAiKeyButton.hidden = !providerLocalKeyConfigured("openai", settings);
  elements.anthropicKeyTitle.textContent = "Anthropic";
  setProviderStatusBadge(elements.anthropicStatusBadge, anthropicKeyConfigured, "Key saved");
  elements.anthropicKeyDetail.textContent = anthropicKeyConfigured
    ? settings.provider === "anthropic" && settings.environmentKeyConfigured
      ? "An environment key is active. Save a local key only if you want a local fallback."
      : "An Anthropic key is saved."
    : "Add an Anthropic API key to enable Claude.";
  elements.addAnthropicKeyButton.textContent = anthropicKeyConfigured ? "Replace key" : "Add key";
  elements.deleteAnthropicKeyButton.hidden = !providerLocalKeyConfigured("anthropic", settings);
  elements.geminiKeyTitle.textContent = "Google Gemini";
  setProviderStatusBadge(elements.geminiStatusBadge, geminiKeyConfigured, "Key saved");
  elements.geminiKeyDetail.textContent = geminiKeyConfigured
    ? settings.provider === "gemini" && settings.environmentKeyConfigured
      ? "An environment key is active. Save a local key only if you want a local fallback."
      : "A Gemini key is saved."
    : "Add a Gemini API key to enable Google Gemini.";
  elements.addGeminiKeyButton.textContent = geminiKeyConfigured ? "Replace key" : "Add key";
  elements.deleteGeminiKeyButton.hidden = !providerLocalKeyConfigured("gemini", settings);
  elements.deepSeekKeyTitle.textContent = "DeepSeek";
  setProviderStatusBadge(elements.deepSeekStatusBadge, deepSeekKeyConfigured, "Key saved");
  elements.deepSeekKeyDetail.textContent = deepSeekKeyConfigured
    ? settings.provider === "deepseek" && settings.environmentKeyConfigured
      ? "An environment key is active. Save a local key only if you want a local fallback."
      : "A DeepSeek key is saved."
    : "Add a DeepSeek API key to enable DeepSeek.";
  elements.addDeepSeekKeyButton.textContent = deepSeekKeyConfigured ? "Replace key" : "Add key";
  elements.deleteDeepSeekKeyButton.hidden = !providerLocalKeyConfigured("deepseek", settings);
  elements.providerKeyDialog.hidden = !keyDialogOpen;
  const keyEditButton = keyEditingProvider === "gemini"
    ? elements.addGeminiKeyButton
    : keyEditingProvider === "anthropic"
      ? elements.addAnthropicKeyButton
      : keyEditingProvider === "deepseek"
        ? elements.addDeepSeekKeyButton
        : elements.addAiKeyButton;
  elements.providerKeyDialogTitle.textContent = `${keyEditButton.textContent} for ${providerDisplayName(keyEditingProvider)}`;
  elements.providerKeyDialogDetail.textContent = keyEditingProvider === "gemini"
    ? "Paste your Gemini API key. It will be stored locally."
    : keyEditingProvider === "anthropic"
      ? "Paste your Anthropic API key. It will be stored locally."
      : keyEditingProvider === "deepseek"
        ? "Paste your DeepSeek API key. It will be stored locally."
        : "Paste your OpenAI API key. It will be stored locally.";
  elements.aiKeyInput.placeholder = keyEditingProvider === "gemini"
    ? "Paste Gemini API key"
    : keyEditingProvider === "anthropic"
      ? "Paste Anthropic API key"
      : keyEditingProvider === "deepseek"
        ? "Paste DeepSeek API key"
        : "Paste OpenAI API key";
  setAiKeyVisibility(keyDialogOpen && state.aiKeyVisible);
  elements.connectCodexButton.hidden = settings.codexAuth.loggedIn;
  elements.logoutCodexButton.hidden = !settings.codexAuth.loggedIn;

  const flow = state.codexAuthFlow;
  elements.codexAuthTitle.textContent = flow && !settings.codexAuth.loggedIn ? "Complete Codex sign-in" : "Codex OAuth";
  setProviderStatusBadge(elements.codexStatusBadge, codexConfigured, "Signed in", "Not connected");
  elements.codexAuthDetail.textContent = settings.codexAuth.loggedIn
    ? [
        settings.codexAuth.accountEmail,
        settings.codexAuth.planType ? `Plan: ${settings.codexAuth.planType}` : "",
      ].filter(Boolean).join(" · ") || "Signed in locally."
    : flow
      ? "Open the Codex sign-in page, enter the code below, then keep this dialog open. Cancel here if you closed the sign-in page."
      : "Connect with your ChatGPT/Codex account. The token is stored locally and is never sent to the frontend.";
  elements.codexAuthCode.hidden = !flow || settings.codexAuth.loggedIn;
  elements.codexAuthCode.textContent = flow ? flow.userCode : "";
  elements.codexAuthLink.hidden = !flow || settings.codexAuth.loggedIn || !safeLinkHref(flow.verificationUri);
  elements.codexAuthLink.href = flow ? safeLinkHref(flow.verificationUri) || "#" : "#";
  elements.aiSettingsSource.textContent = "Image generation: OpenAI API key or Codex OAuth only.";
  elements.saveAiSettings.disabled = state.aiSettingsLoading;
  elements.addAiKeyButton.disabled = state.aiSettingsLoading;
  elements.deleteAiKeyButton.disabled = state.aiSettingsLoading;
  elements.cancelAiKeyEditButton.disabled = state.aiSettingsLoading;
  elements.confirmAiKeyEditButton.disabled = state.aiSettingsLoading;
  elements.addAnthropicKeyButton.disabled = state.aiSettingsLoading;
  elements.deleteAnthropicKeyButton.disabled = state.aiSettingsLoading;
  elements.addGeminiKeyButton.disabled = state.aiSettingsLoading;
  elements.deleteGeminiKeyButton.disabled = state.aiSettingsLoading;
  elements.addDeepSeekKeyButton.disabled = state.aiSettingsLoading;
  elements.deleteDeepSeekKeyButton.disabled = state.aiSettingsLoading;
  elements.connectCodexButton.textContent = state.codexAuthFlow
    ? "Cancel sign-in"
    : state.codexAuthStarting ? "Starting" : "Connect";
  elements.connectCodexButton.disabled = state.aiSettingsLoading || state.codexAuthStarting;
  elements.logoutCodexButton.disabled = state.aiSettingsLoading || state.codexAuthStarting || state.codexAuthPolling;
}

async function loadAiSettings() {
  state.aiSettingsLoading = true;
  renderModelConnectionStatus();
  renderAiSettings();
  try {
    const [payload, providerCatalog] = await Promise.all([
      fetchJson("/api/settings/ai"),
      fetchJson("/api/model/providers")
    ]);
    state.aiSettings = normalizeAiSettings(payload);
    state.aiProviderCatalog = providerCatalog || null;
    elements.aiProviderInput.value = state.aiSettings.provider;
    elements.aiKeyInput.value = "";
    setAiKeyVisibility(false);
    setAiSettingsError("");
  } catch (error) {
    setAiSettingsError(error.message || "Could not load AI provider settings.");
    console.error(error);
  } finally {
    state.aiSettingsLoading = false;
    renderModelConnectionStatus();
    renderAiSettings();
  }
}

async function openAiSettingsDialog() {
  closeSettingsMenu();
  setAiSettingsError("");
  setAiKeyDialogError("");
  state.aiKeyEditingProvider = "";
  elements.aiKeyInput.value = "";
  setAiKeyVisibility(false);
  elements.aiProviderInput.value = state.aiSettings?.provider || "openai";
  elements.aiSettingsDialog.showModal();
  renderAiSettings();
  await loadAiSettings();
  elements.aiSettingsForm?.focus({ preventScroll: true });
}

function closeAiSettingsDialog() {
  setAiSettingsError("");
  setAiKeyDialogError("");
  closeModelCapabilitiesDialog();
  state.aiKeyEditingProvider = "";
  elements.aiKeyInput.value = "";
  setAiKeyVisibility(false);
  stopCodexAuthPolling();
  elements.aiSettingsDialog.close();
  clearSettingsPanelUrl();
}

function startAiKeyEdit(provider = "openai") {
  state.aiKeyEditingProvider = normalizeAiProvider(provider);
  elements.aiKeyInput.value = "";
  setAiKeyVisibility(false);
  setAiSettingsError("");
  setAiKeyDialogError("");
  renderAiSettings();
  requestAnimationFrame(() => elements.aiKeyInput?.focus());
}

function cancelAiKeyEdit() {
  state.aiKeyEditingProvider = "";
  elements.aiKeyInput.value = "";
  setAiKeyVisibility(false);
  setAiSettingsError("");
  setAiKeyDialogError("");
  renderAiSettings();
}

async function confirmAiKeyEdit(provider = state.aiKeyEditingProvider) {
  const editingProvider = normalizeAiProvider(provider);
  const keyInput = elements.aiKeyInput;
  if (!normalizeText(keyInput?.value)) {
    setAiKeyDialogError("Paste a key before saving.");
    keyInput?.focus();
    return;
  }
  setAiKeyDialogError("");
  await saveAiSettings({ closeDialog: false, keyProvider: editingProvider });
}

async function saveAiSettings(options = {}) {
  const { closeDialog = true, keyProvider = state.aiKeyEditingProvider } = options;
  const currentSettings = state.aiSettings || normalizeAiSettings({});
  const editingProvider = normalizeAiProvider(keyProvider);
  const configured = configuredAiProviders(currentSettings);
  const selectedProvider = configured.length
    ? normalizeAiProvider(elements.aiProviderInput.value || currentSettings.provider)
    : "";
  const shouldAutoDefaultToFirstKey = Boolean(
    keyProvider
    && editingProvider
    && !configured.length
    && !hasSavedAiProvider(currentSettings)
  );
  const body = {};
  const providerForSave = shouldAutoDefaultToFirstKey ? editingProvider : selectedProvider;
  if (providerForSave || hasSavedAiProvider(currentSettings)) {
    body.provider = normalizeText(providerForSave || currentSettings.provider || "openai");
  }
  const keyInput = elements.aiKeyInput;
  const apiKey = keyProvider ? normalizeText(keyInput?.value) : "";
  if (apiKey) {
    body.apiKey = apiKey;
    body.apiKeyProvider = editingProvider;
  }

  elements.saveAiSettings.disabled = true;
  elements.deleteAiKeyButton.disabled = true;
  elements.deleteAnthropicKeyButton.disabled = true;
  elements.deleteGeminiKeyButton.disabled = true;
  elements.deleteDeepSeekKeyButton.disabled = true;
  elements.confirmAiKeyEditButton.disabled = true;
  try {
    const payload = await fetchJson("/api/settings/ai", { method: "POST", body });
    state.aiSettings = normalizeAiSettings(payload);
    elements.aiProviderInput.value = state.aiSettings.provider;
    elements.aiKeyInput.value = "";
    state.aiKeyEditingProvider = "";
    setAiKeyVisibility(false);
    setAiSettingsError("");
    setAiKeyDialogError("");
    renderAiSettings();
    if (closeDialog) {
      closeAiSettingsDialog();
      void refreshAiSettingsAfterSave();
    } else {
      await refreshAiSettingsAfterSave({ showError: true });
    }
  } catch (error) {
    if (keyProvider) {
      setAiKeyDialogError(error.message || "Could not save this API key.");
      elements.aiKeyInput?.focus();
    } else {
      setAiSettingsError(error.message || "Could not save AI provider settings.");
    }
    console.error(error);
  } finally {
    elements.saveAiSettings.disabled = false;
    elements.deleteAiKeyButton.disabled = false;
    elements.deleteAnthropicKeyButton.disabled = false;
    elements.deleteGeminiKeyButton.disabled = false;
    elements.deleteDeepSeekKeyButton.disabled = false;
    elements.confirmAiKeyEditButton.disabled = false;
  }
}

async function refreshAiSettingsAfterSave({ showError = false } = {}) {
  try {
    await loadAiSettings();
    await loadToolSettings();
  } catch (refreshError) {
    console.error(refreshError);
    if (showError) {
      setAiSettingsError("Key saved, but provider status could not refresh. Reopen AI Provider settings to check it.");
    }
  }
}

async function deleteAiKey(provider = "openai") {
  const normalizedProvider = normalizeAiProvider(provider);
  if (!providerLocalKeyConfigured(normalizedProvider)) return;
  openConfirmDialog({
    eyebrow: "AI Provider",
    title: `Delete ${providerKeyName(normalizedProvider)} key?`,
    body: "This removes the local API key from Paper Notes.",
    actionLabel: "Delete key",
    danger: true,
    action: () => {
      void performDeleteAiKey(normalizedProvider);
    }
  });
}

async function performDeleteAiKey(provider = "openai") {
  const normalizedProvider = normalizeAiProvider(provider);
  if (!providerLocalKeyConfigured(normalizedProvider)) return;
  state.aiKeyEditingProvider = "";
  elements.aiKeyInput.value = "";
  setAiKeyVisibility(false);
  const deleteButton = normalizedProvider === "gemini"
    ? elements.deleteGeminiKeyButton
    : normalizedProvider === "anthropic"
      ? elements.deleteAnthropicKeyButton
      : normalizedProvider === "deepseek"
        ? elements.deleteDeepSeekKeyButton
        : elements.deleteAiKeyButton;
  deleteButton.disabled = true;
  try {
    const payload = await fetchJson(`/api/settings/ai/key?provider=${encodeURIComponent(normalizedProvider)}`, {
      method: "DELETE"
    });
    state.aiSettings = normalizeAiSettings(payload);
    elements.aiProviderInput.value = state.aiSettings.provider;
    elements.aiKeyInput.value = "";
    setAiKeyVisibility(false);
    await loadAiSettings();
    setAiSettingsError("");
    renderAiSettings();
  } catch (error) {
    setAiSettingsError(error.message || "Could not delete the local key.");
    console.error(error);
  } finally {
    deleteButton.disabled = false;
  }
}

function handleAiProviderChange() {
  stopCodexAuthPolling();
  setAiSettingsError("");
  renderAiSettings();
}

function selectDefaultAiProvider(provider) {
  const nextProvider = normalizeAiProvider(provider);
  if (elements.aiProviderInput) elements.aiProviderInput.value = nextProvider;
  stopCodexAuthPolling();
  setAiSettingsError("");
  renderAiSettings();
}

function handleAiSettingsKeydown(event) {
  if (event.key === "Escape" && isModelCapabilitiesDialogOpen()) {
    event.preventDefault();
    closeModelCapabilitiesDialog();
    return;
  }
  if (event.key === "Enter" && state.aiKeyEditingProvider && event.target === elements.aiKeyInput) {
    event.preventDefault();
    event.stopPropagation();
    void confirmAiKeyEdit();
    return;
  }
  if (event.key !== " ") return;
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
    return;
  }
  if (target === elements.aiSettingsForm || target === elements.aiSettingsDialog) {
    event.preventDefault();
  }
}

elements.compareModelsButton?.addEventListener("click", () => {
  void openModelCapabilitiesDialog();
});
elements.closeModelCapabilitiesDialog?.addEventListener("click", closeModelCapabilitiesDialog);
elements.modelCapabilitiesDialog?.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeModelCapabilitiesDialog();
});
elements.modelCapabilitiesDialog?.addEventListener("click", (event) => {
  if (event.target === elements.modelCapabilitiesDialog) closeModelCapabilitiesDialog();
});

async function startCodexLogin() {
  setAiSettingsError("");
  stopCodexAuthPolling();
  state.codexAuthStarting = true;
  renderAiSettings();
  try {
    const payload = await fetchJson("/api/auth/codex/start", { method: "POST", body: {} });
    state.codexAuthFlow = {
      userCode: normalizeText(payload.userCode),
      deviceAuthId: normalizeText(payload.deviceAuthId),
      verificationUri: normalizeText(payload.verificationUri),
      interval: Math.max(3, Number(payload.interval) || 5)
    };
    state.codexAuthStarting = false;
    state.codexAuthPolling = true;
    if (state.codexAuthFlow.verificationUri) {
      window.open(state.codexAuthFlow.verificationUri, "_blank", "noopener,noreferrer");
    }
    renderAiSettings();
    scheduleCodexAuthPoll(0);
  } catch (error) {
    state.codexAuthStarting = false;
    state.codexAuthPolling = false;
    state.codexAuthFlow = null;
    setAiSettingsError(error.message || "Could not start Codex OAuth.");
    renderAiSettings();
    console.error(error);
  }
}

function handleCodexConnectAction() {
  if (state.codexAuthFlow || state.codexAuthPolling) {
    stopCodexAuthPolling();
    setAiSettingsError("");
    renderAiSettings();
    return;
  }
  startCodexLogin();
}

function scheduleCodexAuthPoll(delaySeconds = state.codexAuthFlow?.interval || 5) {
  window.clearTimeout(state.codexAuthPollTimer);
  state.codexAuthPollTimer = window.setTimeout(pollCodexLogin, Math.max(0, delaySeconds) * 1000);
}

function stopCodexAuthPolling() {
  window.clearTimeout(state.codexAuthPollTimer);
  state.codexAuthPollTimer = null;
  state.codexAuthStarting = false;
  state.codexAuthPolling = false;
  state.codexAuthFlow = null;
}

async function pollCodexLogin() {
  const flow = state.codexAuthFlow;
  if (!flow) {
    stopCodexAuthPolling();
    renderAiSettings();
    return;
  }
  try {
    const payload = await fetchJson("/api/auth/codex/poll", {
      method: "POST",
      body: {
        deviceAuthId: flow.deviceAuthId,
        userCode: flow.userCode
      }
    });
    if (payload.status === "pending") {
      scheduleCodexAuthPoll(flow.interval);
      return;
    }
    if (payload.status === "connected" && payload.auth) {
      state.aiSettings = normalizeAiSettings({
        ...(state.aiSettings || {}),
        configured: true,
        codexAuth: payload.auth
      });
      stopCodexAuthPolling();
      setAiSettingsError("");
      renderAiSettings();
      return;
    }
    throw new Error("Unexpected Codex OAuth response.");
  } catch (error) {
    stopCodexAuthPolling();
    setAiSettingsError(error.message || "Could not finish Codex OAuth.");
    renderAiSettings();
    console.error(error);
  }
}

async function logoutCodex() {
  openConfirmDialog({
    eyebrow: "AI Provider",
    title: "Log out of Codex OAuth?",
    body: "This removes the local Codex OAuth credentials from Paper Notes.",
    actionLabel: "Log out",
    danger: true,
    action: () => {
      void performLogoutCodex();
    }
  });
}

async function performLogoutCodex() {
  stopCodexAuthPolling();
  elements.logoutCodexButton.disabled = true;
  try {
    const payload = await fetchJson("/api/auth/codex/logout", { method: "POST", body: {} });
    state.aiSettings = normalizeAiSettings({
      ...(state.aiSettings || {}),
      configured: false,
      ready: false,
      codexAuth: payload
    });
    setAiSettingsError("");
    renderAiSettings();
  } catch (error) {
    setAiSettingsError(error.message || "Could not log out of Codex OAuth.");
    console.error(error);
  } finally {
    elements.logoutCodexButton.disabled = false;
  }
}
