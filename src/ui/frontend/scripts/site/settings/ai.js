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

function openAiProviderConfigured(settings = state.aiSettings) {
  const normalized = settings || normalizeAiSettings({});
  return Boolean(
    normalized.localKeyConfigured
    || normalized.environmentKeyConfigured
    || (!isCodexProvider(normalized.provider) && normalized.configured)
  );
}

function codexProviderConfigured(settings = state.aiSettings) {
  return Boolean((settings || normalizeAiSettings({})).codexAuth.loggedIn);
}

function providerDisplayName(provider) {
  return isCodexProvider(provider) ? "Codex OAuth" : "OpenAI API key";
}

function providerStatusLabel(provider, settings = state.aiSettings) {
  if (isCodexProvider(provider)) {
    return codexProviderConfigured(settings) ? "connected" : "not connected";
  }
  return openAiProviderConfigured(settings) ? "key configured" : "key not configured";
}

function renderDefaultProviderOptions(provider, settings) {
  if (!elements.aiProviderInput) return;
  const selectedProvider = isCodexProvider(provider) ? "codex-oauth" : "openai";
  const options = [
    {
      value: "openai",
      label: `OpenAI API key (${providerStatusLabel("openai", settings)})`
    },
    {
      value: "codex-oauth",
      label: `Codex OAuth (${providerStatusLabel("codex-oauth", settings)})`
    }
  ];
  elements.aiProviderInput.innerHTML = options.map((option) => (
    `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`
  )).join("");
  elements.aiProviderInput.value = selectedProvider;
}

function hasModelConnection(settings = state.aiSettings) {
  const normalized = settings || normalizeAiSettings({});
  if (normalized.modelConnectionConfigured) return true;
  const hasOpenAiConnection = openAiProviderConfigured(normalized)
    && (normalized.modelConfigured || normalized.localModelConfigured || normalized.environmentModelConfigured);
  const hasCodexConnection = normalized.codexAuth.loggedIn
    && (isCodexProvider(normalized.provider) ? normalized.modelConfigured : false);
  return Boolean(hasOpenAiConnection || hasCodexConnection);
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

function renderAiSettings() {
  if (!elements.aiSettingsDialog) return;
  renderModelConnectionStatus();
  const settings = state.aiSettings || normalizeAiSettings({});
  const provider = normalizeText(elements.aiProviderInput?.value || settings.provider || "openai");
  const openAiKeyConfigured = openAiProviderConfigured(settings);
  const codexConfigured = codexProviderConfigured(settings);
  const modelConfigured = hasModelConnection(settings);
  const credentialsLabel = [
    openAiKeyConfigured ? `OpenAI key from ${settingsSourceLabel(settings.keySource)}` : "OpenAI key not configured",
    codexConfigured ? "Codex OAuth connected" : "Codex OAuth not connected"
  ].join(" · ");

  if (state.aiSettingsLoading) {
    elements.aiSettingsStatus.innerHTML = `
      <strong>Loading</strong>
      <span>Checking local provider settings...</span>
    `;
  } else {
    elements.aiSettingsStatus.classList.toggle("is-ready", modelConfigured);
    elements.aiSettingsStatus.classList.toggle("is-missing", !modelConfigured);
    elements.aiSettingsStatus.innerHTML = `
      <strong>${modelConfigured ? "Model configured" : "Model not configured"}</strong>
      <span>${escapeHtml(credentialsLabel)}</span>
    `;
  }

  renderDefaultProviderOptions(provider, settings);
  elements.openAiKeyTitle.textContent = openAiKeyConfigured
    ? "OpenAI API key configured"
    : "OpenAI API key not configured";
  elements.openAiKeyDetail.textContent = state.aiKeyEditing
    ? "Paste a local key below, then save."
    : openAiKeyConfigured
    ? settings.environmentKeyConfigured
      ? "An environment key is active. Save a local key only if you want a local fallback."
      : "A local key is saved. Use Replace key to update it."
    : "Add a local key to enable OpenAI.";
  elements.openAiKeyField.hidden = !state.aiKeyEditing;
  elements.addAiKeyButton.hidden = state.aiKeyEditing;
  elements.addAiKeyButton.textContent = openAiKeyConfigured ? "Replace key" : "Add key";
  elements.codexSettingsPanel.hidden = false;
  elements.deleteAiKeyButton.hidden = !settings.localKeyConfigured || state.aiKeyEditing;
  elements.connectCodexButton.hidden = settings.codexAuth.loggedIn;
  elements.logoutCodexButton.hidden = !settings.codexAuth.loggedIn;

  const flow = state.codexAuthFlow;
  elements.codexAuthTitle.textContent = settings.codexAuth.loggedIn
    ? "Codex OAuth connected"
    : flow ? "Complete Codex sign-in"
    : "Codex OAuth not connected";
  elements.codexAuthDetail.textContent = settings.codexAuth.loggedIn
    ? [
        settings.codexAuth.accountEmail,
        settings.codexAuth.planType ? `Plan: ${settings.codexAuth.planType}` : "",
        settings.codexAuth.lastRefresh ? `Last refresh: ${settings.codexAuth.lastRefresh}` : ""
      ].filter(Boolean).join(" · ") || "Local Codex OAuth credentials are present."
    : flow
      ? "Open the Codex sign-in page, enter the code below, then keep this dialog open. Cancel here if you closed the sign-in page."
      : "Connect with your ChatGPT/Codex account. The token is stored locally and is never sent to the frontend.";
  elements.codexAuthCode.hidden = !flow || settings.codexAuth.loggedIn;
  elements.codexAuthCode.textContent = flow ? flow.userCode : "";
  elements.codexAuthLink.hidden = !flow || settings.codexAuth.loggedIn || !safeLinkHref(flow.verificationUri);
  elements.codexAuthLink.href = flow ? safeLinkHref(flow.verificationUri) || "#" : "#";
  elements.aiSettingsSource.textContent = [
    `Local settings are stored in ${settings.localSecretsPath}.`,
    `Codex auth uses ${settings.codexAuth.authStorePath}.`
  ].join(" ");
  elements.saveAiSettings.disabled = state.aiSettingsLoading;
  elements.addAiKeyButton.disabled = state.aiSettingsLoading;
  elements.deleteAiKeyButton.disabled = state.aiSettingsLoading;
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
    const payload = await fetchJson("/api/settings/ai");
    state.aiSettings = normalizeAiSettings(payload);
    elements.aiProviderInput.value = state.aiSettings.provider;
    elements.aiKeyInput.value = "";
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
  state.aiKeyEditing = false;
  elements.aiKeyInput.value = "";
  elements.aiProviderInput.value = state.aiSettings?.provider || "openai";
  elements.aiSettingsDialog.showModal();
  renderAiSettings();
  await loadAiSettings();
  elements.aiProviderInput.focus();
}

function closeAiSettingsDialog() {
  setAiSettingsError("");
  state.aiKeyEditing = false;
  elements.aiKeyInput.value = "";
  stopCodexAuthPolling();
  elements.aiSettingsDialog.close();
  clearSettingsPanelUrl();
}

function startAiKeyEdit() {
  state.aiKeyEditing = true;
  elements.aiKeyInput.value = "";
  setAiSettingsError("");
  renderAiSettings();
  requestAnimationFrame(() => elements.aiKeyInput?.focus());
}

async function saveAiSettings() {
  const body = {
    provider: normalizeText(elements.aiProviderInput.value || "openai")
  };
  const apiKey = normalizeText(elements.aiKeyInput.value);
  if (apiKey) body.apiKey = apiKey;

  elements.saveAiSettings.disabled = true;
  elements.deleteAiKeyButton.disabled = true;
  try {
    const payload = await fetchJson("/api/settings/ai", { method: "POST", body });
    state.aiSettings = normalizeAiSettings(payload);
    elements.aiProviderInput.value = state.aiSettings.provider;
    elements.aiKeyInput.value = "";
    state.aiKeyEditing = false;
    setAiSettingsError("");
    await loadToolSettings();
    renderAiSettings();
    closeAiSettingsDialog();
  } catch (error) {
    setAiSettingsError(error.message || "Could not save AI provider settings.");
    console.error(error);
  } finally {
    elements.saveAiSettings.disabled = false;
    elements.deleteAiKeyButton.disabled = false;
  }
}

async function deleteAiKey() {
  if (!state.aiSettings?.localKeyConfigured) return;
  state.aiKeyEditing = false;
  elements.aiKeyInput.value = "";
  elements.deleteAiKeyButton.disabled = true;
  try {
    const payload = await fetchJson("/api/settings/ai/key", { method: "DELETE" });
    state.aiSettings = normalizeAiSettings(payload);
    elements.aiProviderInput.value = state.aiSettings.provider;
    elements.aiKeyInput.value = "";
    setAiSettingsError("");
    renderAiSettings();
  } catch (error) {
    setAiSettingsError(error.message || "Could not delete the local key.");
    console.error(error);
  } finally {
    elements.deleteAiKeyButton.disabled = false;
  }
}

function handleAiProviderChange() {
  stopCodexAuthPolling();
  setAiSettingsError("");
  renderAiSettings();
}

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

