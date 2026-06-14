let readerModelCatalogLoadPromise = null;

function renderReaderIcon(name, label = "", className = "", size = 16) {
  return window.renderPaperIcon
    ? window.renderPaperIcon(name, { label, className, size })
    : "";
}

function renderReaderModelControls() {
  const settings = readerState.aiSettings || normalizeReaderAiSettings({});
  const availableProviders = modelProvidersForMenu();
  const currentProvider = currentReaderProvider();
  const savedProvider = availableProviders.some((item) => item.name === currentProvider)
    ? currentProvider
    : availableProviders[0]?.name || currentProvider;
  const provider = readerState.modelMenuOpen ? activeReaderModelProvider() : savedProvider;
  const isModelLevel = readerState.modelMenuOpen && readerState.modelMenuLevel === "models";
  const profile = providerProfileFor(provider);
  const savedModel = currentReaderModel();
  const selectedModel = provider === savedProvider ? savedModel : defaultModelForProvider(provider);
  const options = modelOptionsForProvider(provider, selectedModel);
  const savedLabel = modelDisplayLabel(savedModel, savedProvider, "label");
  const selectedShortLabel = modelDisplayLabel(savedModel, savedProvider, "shortLabel");
  const loading = readerState.aiSettingsLoading || readerState.modelCatalogLoading;
  const noConfiguredProviders = !loading && !availableProviders.length;
  const configured = Boolean(profile?.configured || (settings.provider === provider && settings.configured));

  if (elements.readerModelMenuButton) {
    const buttonLabel = loading ? "Model" : noConfiguredProviders ? "No model" : selectedShortLabel || "Model";
    elements.readerModelMenuButton.innerHTML = modelButtonHtml({
      provider: savedProvider,
      label: buttonLabel,
      loading: loading || noConfiguredProviders,
    });
    elements.readerModelMenuButton.title = savedLabel
      ? `${providerDisplayName(savedProvider)}: ${savedLabel}`
      : noConfiguredProviders
        ? "No configured providers"
        : `${providerDisplayName(savedProvider)}: select a model`;
    elements.readerModelMenuButton.disabled = loading || readerState.modelSaving || isChatSessionPending();
    elements.readerModelMenuButton.setAttribute("aria-expanded", String(readerState.modelMenuOpen));
  }

  if (elements.readerModelPopover) {
    elements.readerModelPopover.hidden = !readerState.modelMenuOpen;
  }
  if (elements.readerModelBack) {
    elements.readerModelBack.hidden = !isModelLevel;
    elements.readerModelBack.disabled = readerState.modelSaving || isChatSessionPending();
  }
  if (elements.readerModelTitle) {
    elements.readerModelTitle.textContent = isModelLevel ? providerDisplayName(provider) : "Model";
  }
  if (elements.readerModelProvider) {
    elements.readerModelProvider.hidden = !isModelLevel;
    elements.readerModelProvider.textContent = "Save";
    elements.readerModelProvider.disabled = readerState.modelSaving || isChatSessionPending();
  }
  if (elements.readerProviderList) {
    elements.readerProviderList.hidden = isModelLevel;
    if (loading) {
      elements.readerProviderList.innerHTML = `<p class="ask-session-empty">Loading providers...</p>`;
    } else {
      elements.readerProviderList.innerHTML = "";
      const providers = modelProvidersForMenu();
      if (!providers.length) {
        elements.readerProviderList.innerHTML = `<p class="ask-session-empty">No configured providers. Open Settings to connect one.</p>`;
      }
      providers.forEach((item) => {
        const button = document.createElement("button");
        button.className = "ask-provider-option";
        button.classList.toggle("is-active", item.name === provider);
        button.type = "button";
        button.disabled = readerState.modelSaving || isChatSessionPending();
        button.dataset.provider = item.name;
        button.setAttribute("aria-haspopup", "menu");
        button.title = `${item.displayName} configured`;
        button.innerHTML = `
          <span class="ask-provider-name">${escapeHtml(item.displayName)}</span>
          <span class="ask-provider-meta">
            <span class="ask-provider-state">configured</span>
            <span class="ask-provider-chevron" aria-hidden="true">›</span>
          </span>
        `;
        button.addEventListener("click", () => selectReaderProvider(item.name));
        elements.readerProviderList.appendChild(button);
      });
    }
  }
  if (elements.readerModelStatus) {
    const selectedModelLabel = modelDisplayLabel(selectedModel, provider, "label") || selectedModel;
    const savedModelLabel = modelDisplayLabel(savedModel, savedProvider, "label")
      || modelDisplayLabel(defaultModelForProvider(savedProvider), savedProvider, "label")
      || savedModel
      || defaultModelForProvider(savedProvider);
    const savedModelStatusLabel = modelStatusLabelWithThink(savedProvider, savedModelLabel);
    const defaultStatus = isModelLevel
      ? selectedModel
        ? configured
          ? `${selectedModelLabel} is selected.`
          : `${providerDisplayName(provider)} not configured.`
        : "Select a model for the current provider."
      : modelProvidersForMenu().length
        ? `${savedModelStatusLabel || providerDisplayName(savedProvider)} is selected.`
        : "No configured providers.";
    const status = loading
      ? "Loading model settings..."
      : readerState.modelSaving ? "Saving model..." : readerState.modelStatus || defaultStatus;
    elements.readerModelStatus.textContent = status;
    elements.readerModelStatus.hidden = !readerState.modelMenuOpen || !status;
  }
  if (!elements.readerModelList) return;

  elements.readerModelList.hidden = !isModelLevel;
  if (!isModelLevel) {
    elements.readerModelList.innerHTML = "";
    return;
  }

  if (loading) {
    elements.readerModelList.innerHTML = `<p class="ask-session-empty">Loading models...</p>`;
    return;
  }

  elements.readerModelList.innerHTML = "";
  if (!options.length) {
    elements.readerModelList.innerHTML = `<p class="ask-session-empty">No models available.</p>`;
    return;
  }
  options.forEach((option) => {
    const button = document.createElement("button");
    button.className = "ask-model-option";
    button.classList.toggle("is-active", provider === savedProvider && option.value === savedModel);
    button.type = "button";
    button.disabled = readerState.modelSaving || (provider === savedProvider && option.value === savedModel);
    button.dataset.model = option.value;
    button.title = option.description ? `${option.label} - ${option.description}` : option.label;
    button.innerHTML = `
      <span class="ask-model-name">${escapeHtml(option.label)}</span>
    `;
    button.addEventListener("click", () => selectReaderModel(option.value));
    elements.readerModelList.appendChild(button);
  });

  if (
    provider === "deepseek"
    || providerSupportsGptThinkMode(provider)
  ) {
    elements.readerModelList.appendChild(renderThinkSettings(provider, selectedModel));
  }
}

function modelStatusLabelWithThink(provider, label, model = currentReaderModel()) {
  const baseLabel = normalizeText(label);
  if (!baseLabel) return "";
  const normalizedProvider = normalizeProviderName(provider);
  if (normalizedProvider === "deepseek") {
    const thinkMode = currentDeepSeekThinkMode();
    return `${baseLabel}-think-${thinkMode.enabled ? thinkMode.effort : "off"}`;
  }
  if (providerSupportsGptThinkMode(normalizedProvider)) {
    const thinkMode = currentGptThinkMode(model, normalizedProvider);
    return `${baseLabel}-think-${thinkMode.enabled ? thinkMode.effort : "off"}`;
  }
  return baseLabel;
}

function modelButtonHtml({ provider, label, loading }) {
  const normalizedProvider = normalizeProviderName(provider);
  if (
    loading
    || (
      normalizedProvider !== "deepseek"
      && !providerSupportsGptThinkMode(normalizedProvider)
    )
  ) {
    return `${renderReaderIcon("bot", "", "", 16)}<span class="ask-model-button-label">${escapeHtml(label || "Model")}</span>`;
  }
  const thinkMode = normalizedProvider === "deepseek"
    ? currentDeepSeekThinkMode()
    : currentGptThinkMode(currentReaderModel(), normalizedProvider);
  const thinkLabel = thinkMode.enabled || !gptReasoningOffSupported(normalizedProvider, currentReaderModel())
    ? `Think ${thinkModeLabel(normalizedProvider, thinkMode.effort)}`
    : "Think off";
  return `
    ${renderReaderIcon("bot", "", "", 16)}
    <span class="ask-model-button-stack">
      <span class="ask-model-button-label">${escapeHtml(label || "Model")}</span>
      <span class="ask-model-button-meta">${escapeHtml(thinkLabel)}</span>
    </span>
  `;
}

function renderThinkSettings(provider, model = currentReaderModel()) {
  const normalizedProvider = normalizeProviderName(provider);
  const thinkMode = normalizedProvider === "deepseek"
    ? currentDeepSeekThinkMode()
    : currentGptThinkMode(model, normalizedProvider);
  const section = document.createElement("section");
  section.className = "ask-think-settings";
  const gptOffSupported = !providerSupportsGptThinkMode(normalizedProvider)
    || gptReasoningOffSupported(normalizedProvider, model);

  if (gptOffSupported) {
    const toggle = document.createElement("button");
    toggle.className = "ask-think-toggle";
    toggle.classList.toggle("is-active", thinkMode.enabled);
    toggle.type = "button";
    toggle.setAttribute("aria-pressed", String(thinkMode.enabled));
    toggle.innerHTML = `
      <span>
        <strong>Think mode</strong>
        <small>${thinkMode.enabled ? `${thinkModeLabel(normalizedProvider, thinkMode.effort)} reasoning` : "Off"}</small>
      </span>
      <span class="ask-think-switch" aria-hidden="true"></span>
    `;
    toggle.addEventListener("click", () => setThinkMode(normalizedProvider, {
      enabled: !thinkMode.enabled,
      effort: thinkMode.effort,
    }, model));
    section.appendChild(toggle);
  } else {
    const heading = document.createElement("div");
    heading.className = "ask-think-toggle is-active";
    heading.innerHTML = `
      <span>
        <strong>Think mode</strong>
        <small>Required for this model</small>
      </span>
    `;
    section.appendChild(heading);
  }

  if (thinkMode.enabled) {
    const levels = document.createElement("div");
    levels.className = "ask-think-levels";
    for (const effort of thinkModeEfforts(normalizedProvider, model)) {
      const button = document.createElement("button");
      button.className = "ask-think-level";
      button.classList.toggle("is-active", effort === thinkMode.effort);
      button.type = "button";
      button.dataset.thinkEffort = effort;
      button.textContent = thinkModeLabel(normalizedProvider, effort);
      button.addEventListener("click", () => setThinkMode(normalizedProvider, { enabled: true, effort }, model));
      levels.appendChild(button);
    }
    section.appendChild(levels);
  }
  return section;
}

function thinkModeEfforts(provider, model = currentReaderModel()) {
  const normalizedProvider = normalizeProviderName(provider);
  if (normalizedProvider === "deepseek") return ["high", "max"];
  return ["low", "medium", "high", "xhigh"];
}

function thinkModeLabel(provider, effort) {
  if (normalizeProviderName(provider) === "deepseek") {
    return {
      high: "High",
      max: "Max",
    }[normalizeText(effort).toLowerCase()] || "High";
  }
  return {
    low: "Low",
    medium: "Medium",
    high: "High",
    xhigh: "XHigh",
  }[normalizeText(effort).toLowerCase()] || "Medium";
}

function setThinkMode(provider, mode, model = currentReaderModel()) {
  const normalizedProvider = normalizeProviderName(provider);
  const nextMode = normalizedProvider === "deepseek"
    ? normalizeDeepSeekThinkMode(mode?.enabled ? mode.effort : "off")
    : normalizeGptThinkMode(mode?.enabled ? mode.effort : "off", model, normalizedProvider);
  if (getChatSessionId()) {
    updateReaderSessionThinkMode(normalizedProvider, nextMode, model).catch((error) => {
      readerState.modelStatus = sanitizeVisibleAgentError(error.message || "Could not save think mode.");
      renderReaderModelControls();
    });
  } else if (normalizedProvider === "deepseek") {
    readerState.pendingChatProvider = normalizedProvider;
    readerState.pendingChatModel = model;
    readerState.deepSeekThinkMode = writeStoredDeepSeekThinkMode(nextMode.enabled ? nextMode.effort : "off");
  } else {
    readerState.pendingChatProvider = normalizedProvider;
    readerState.pendingChatModel = model;
    readerState.gptThinkMode = writeStoredGptThinkMode(
      nextMode.enabled ? nextMode.effort : "off",
      model,
      normalizedProvider,
    );
  }
  readerState.modelStatus = nextMode.enabled
    ? `Think mode: ${thinkModeLabel(normalizedProvider, nextMode.effort)}.`
    : "Think mode off.";
  const session = currentReaderSession();
  if (session) {
    if (normalizedProvider === "deepseek") {
      session.deepSeekThinkMode = nextMode.enabled ? nextMode.effort : "off";
    } else {
      session.gptThinkMode = nextMode.enabled ? nextMode.effort : "off";
    }
  }
  renderReaderModelControls();
}

async function updateReaderSessionThinkMode(provider, mode, model = currentReaderModel()) {
  const sessionId = getChatSessionId();
  if (!sessionId) return null;
  const normalizedProvider = normalizeProviderName(provider);
  const normalized = normalizedProvider === "deepseek"
    ? normalizeDeepSeekThinkMode(mode?.enabled ? mode.effort : "off")
    : normalizeGptThinkMode(mode?.enabled ? mode.effort : "off", model, normalizedProvider);
  const metadata = normalizedProvider === "deepseek"
    ? { deepseekThinkMode: normalized.enabled ? normalized.effort : "off" }
    : { gptThinkMode: normalized.enabled ? normalized.effort : "off" };
  const payload = await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(sessionId)}/model`, {
    method: "POST",
    body: {
      provider: normalizedProvider,
      model: model || undefined,
      metadata,
    },
  });
  return upsertReaderChatSession(payload.session);
}

function closeReaderModelMenu() {
  readerState.modelMenuOpen = false;
  readerState.modelMenuLevel = "providers";
  readerState.modelDraftProvider = "";
  readerState.modelStatus = "";
  renderReaderModelControls();
}

function setReaderModelMenuOpen(open) {
  readerState.modelMenuOpen = open;
  if (open) {
    readerState.modelMenuLevel = "providers";
    readerState.modelDraftProvider = currentReaderProvider();
    readerState.modelStatus = "";
    setChatSessionMenuOpen(false);
    closeReaderToolMenu();
    renderReaderModelControls();
    void loadReaderModelCatalog({ silent: true });
  } else {
    readerState.modelMenuLevel = "providers";
    readerState.modelDraftProvider = "";
    readerState.modelStatus = "";
    renderReaderModelControls();
  }
}

async function loadReaderModelCatalog({ silent = false, force = false } = {}) {
  if (!force && readerState.modelCatalogLoaded && readerState.modelCatalog) {
    renderReaderModelControls();
    return readerState.modelCatalog;
  }
  if (readerModelCatalogLoadPromise) return readerModelCatalogLoadPromise;
  readerState.modelCatalogLoading = true;
  renderReaderModelControls();
  readerModelCatalogLoadPromise = (async () => {
    try {
      const payload = await fetchAgentJson("/api/model/providers");
      const catalog = normalizeReaderModelCatalog(payload);
      readerState.modelCatalog = catalog;
      readerState.modelCatalogLoaded = true;
      const provider = normalizeProviderName(catalog.defaultProvider) || "openai";
      const profile = providerProfileFor(provider);
      const existingSettings = readerState.aiSettings || normalizeReaderAiSettings({});
      readerState.aiSettings = normalizeReaderAiSettings({
        ...existingSettings,
        provider,
        model: catalog.defaultModel || profile?.model || profile?.defaultModel,
        modelSource: profile?.modelSource || "profile",
        configured: catalog.modelConnectionConfigured,
        ready: catalog.modelConnectionConfigured,
        codexAuth: catalog.codexAuth || existingSettings.codexAuth
      });
      readerState.modelStatus = "";
      return catalog;
    } catch (error) {
      readerState.modelCatalogLoaded = false;
      if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
      readerState.modelStatus = "Could not load model settings.";
      return null;
    } finally {
      readerModelCatalogLoadPromise = null;
      readerState.modelCatalogLoading = false;
      renderReaderModelControls();
      renderReaderContextControls();
    }
  })();
  return readerModelCatalogLoadPromise;
}

async function loadReaderAiSettings(options = {}) {
  return loadReaderModelCatalog(options);
}

function showReaderProviderMenu() {
  readerState.modelMenuLevel = "providers";
  readerState.modelStatus = "";
  renderReaderModelControls();
}

async function selectReaderProvider(provider) {
  const nextProvider = normalizeProviderName(provider);
  if (!nextProvider || readerState.modelSaving) return;
  readerState.modelDraftProvider = nextProvider;
  readerState.modelMenuLevel = "models";
  const profile = providerProfileFor(nextProvider);
  readerState.modelStatus = profile?.configured
    ? `${modelDisplayLabel(defaultModelForProvider(nextProvider), nextProvider, "label") || providerDisplayName(nextProvider)} is selected.`
    : `${providerDisplayName(nextProvider)} not configured.`;
  renderReaderModelControls();
}

async function selectReaderModel(model) {
  const nextModel = normalizeText(model);
  if (!nextModel || readerState.modelSaving) return;
  const provider = activeReaderModelProvider();
  const keepMenuOpen = providerKeepsModelMenuOpen(provider);
  const selectedStatus = `${modelStatusLabelWithThink(provider, modelDisplayLabel(nextModel, provider, "label") || nextModel, nextModel)} is selected.`;

  if (!getChatSessionId()) {
    writeStoredReaderModelSelection(provider, nextModel);
    readerState.pendingChatProvider = provider;
    readerState.pendingChatModel = nextModel;
    readerState.modelStatus = keepMenuOpen ? selectedStatus : "";
    if (!keepMenuOpen) setReaderModelMenuOpen(false);
    setReaderChatError("");
    renderReaderModelControls();
    resetReaderContextStatus();
    return;
  }

  readerState.modelSaving = true;
  readerState.modelStatus = "";
  renderReaderModelControls();
  try {
    const sessionId = getChatSessionId();
    const payload = await fetchAgentJson(`/api/agent/sessions/${encodeURIComponent(sessionId)}/model`, {
      method: "POST",
      body: {
        provider,
        model: nextModel
      }
    });
    const session = upsertReaderChatSession(payload.session);
    if (session?.id) setCurrentChatSessionId(session.id);
    resetReaderContextStatus({ refresh: true });
    readerState.modelStatus = keepMenuOpen ? selectedStatus : "";
    if (!keepMenuOpen) setReaderModelMenuOpen(false);
    setReaderChatError("");
  } catch (error) {
    readerState.modelStatus = sanitizeVisibleAgentError(error.message || "Could not save model.");
  } finally {
    readerState.modelSaving = false;
    renderReaderModelControls();
  }
}

function providerKeepsModelMenuOpen(provider) {
  const normalized = normalizeProviderName(provider);
  return normalized === "deepseek"
    || providerSupportsGptThinkMode(normalized);
}
