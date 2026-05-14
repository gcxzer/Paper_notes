function renderReaderModelControls() {
  const settings = readerState.aiSettings || normalizeReaderAiSettings({});
  const session = currentReaderSession();
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
  const configured = Boolean(profile?.configured || (settings.provider === provider && settings.configured));

  if (elements.readerModelMenuButton) {
    elements.readerModelMenuButton.textContent = loading
      ? "Model"
      : selectedShortLabel || "Model";
    elements.readerModelMenuButton.title = savedLabel
      ? `${providerDisplayName(savedProvider)}: ${savedLabel}`
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
    elements.readerModelProvider.textContent = isModelLevel
      ? configured ? "Configured" : "Not configured"
      : providerDisplayName(savedProvider);
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
    const defaultStatus = isModelLevel
      ? selectedModel
        ? configured
          ? provider === savedProvider
            ? `Using ${session?.model ? modelSourceLabel("session") : modelSourceLabel(profile?.modelSource || settings.modelSource)} value.`
            : `Choose a ${providerDisplayName(provider)} model to use it for this session.`
          : `${providerDisplayName(provider)} not configured.`
        : "Select a model for the current provider."
      : modelProvidersForMenu().length ? "Choose a provider." : "No configured providers.";
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
    closeReaderContextPopover();
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

async function loadReaderModelCatalog({ silent = false } = {}) {
  readerState.modelCatalogLoading = true;
  renderReaderModelControls();
  try {
    const payload = await fetchAgentJson("/api/model/providers");
    const catalog = normalizeReaderModelCatalog(payload);
    readerState.modelCatalog = catalog;
    const provider = normalizeProviderName(catalog.defaultProvider) || "openai";
    const profile = providerProfileFor(provider);
    readerState.aiSettings = normalizeReaderAiSettings({
      provider,
      model: catalog.defaultModel || profile?.model || profile?.defaultModel,
      modelSource: profile?.modelSource || "profile",
      configured: catalog.modelConnectionConfigured,
      ready: catalog.modelConnectionConfigured
    });
    readerState.modelStatus = "";
  } catch (error) {
    if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    readerState.modelStatus = "Could not load model settings.";
  } finally {
    readerState.modelCatalogLoading = false;
    renderReaderModelControls();
    scheduleReaderContextStatusRefresh();
  }
}

async function loadReaderAiSettings(options = {}) {
  return loadReaderModelCatalog(options);
}

async function loadReaderToolSettings({ silent = true } = {}) {
  readerState.toolSettingsLoading = true;
  try {
    const payload = await fetchAgentJson("/api/settings/tools");
    readerState.toolSettings = normalizeToolSettings(payload);
    readerState.writeToolMode = writeStoredWriteToolMode(readerState.toolSettings.defaultWriteMode);
    renderReaderToolControls();
  } catch (error) {
    if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    console.warn("Could not load tool settings.", error);
  } finally {
    readerState.toolSettingsLoading = false;
  }
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
    ? `Choose a ${providerDisplayName(nextProvider)} model to use it for this session.`
    : `${providerDisplayName(nextProvider)} not configured.`;
  renderReaderModelControls();
}

async function selectReaderModel(model) {
  const nextModel = normalizeText(model);
  if (!nextModel || readerState.modelSaving) return;
  const provider = activeReaderModelProvider();
  writeStoredReaderModelSelection(provider, nextModel);

  if (!getChatSessionId()) {
    readerState.pendingChatProvider = provider;
    readerState.pendingChatModel = nextModel;
    readerState.modelStatus = "";
    setReaderModelMenuOpen(false);
    setReaderChatError("");
    renderReaderModelControls();
    return;
  }

  readerState.modelSaving = true;
  readerState.modelStatus = "";
  renderReaderModelControls();
  try {
    const sessionId = getChatSessionId();
    const payload = await fetchAgentJson("/api/chat/session/model", {
      method: "POST",
      body: {
        sessionId,
        provider,
        model: nextModel
      }
    });
    const session = upsertReaderChatSession(payload.session);
    if (session?.id) setCurrentChatSessionId(session.id);
    readerState.modelStatus = "";
    setReaderModelMenuOpen(false);
    setReaderChatError("");
  } catch (error) {
    readerState.modelStatus = sanitizeVisibleAgentError(error.message || "Could not save model.");
  } finally {
    readerState.modelSaving = false;
    renderReaderModelControls();
  }
}

