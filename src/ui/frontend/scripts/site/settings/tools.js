function normalizeToolAccess(value) {
  const normalized = normalizeText(value || "inherit").toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
  if (normalized === "default") return "inherit";
  return ["inherit", "ask", "auto", "warn", "readonly", "block", "halt", "disabled"].includes(normalized)
    ? normalized
    : "inherit";
}

function normalizeToolSettings(payload) {
  const globalAccess = normalizeText(payload?.globalAccess || "default").toLowerCase() === "full_access"
    ? "full_access"
    : "default";
  const webSearchProviders = normalizeWebSearchProviders(payload?.webSearchProviders || payload?.web_search_providers);
  const customWebSearchEnabled = isAnyCustomWebSearchProviderEnabled(webSearchProviders);
  const normalizeToolList = (items) => (Array.isArray(items) ? items : []).map((tool) => {
    const mutating = Boolean(tool.mutating);
    const readOnly = Boolean(tool.readOnly || tool.read_only);
    const access = normalizeToolAccess(tool.access);
    return {
      name: normalizeText(tool.name),
      label: normalizeText(tool.label || tool.name),
      description: normalizeText(tool.description),
      toolset: normalizeText(tool.toolset || "default"),
      readOnly,
      mutating,
      risk: normalizeText(tool.risk || (mutating ? "write" : "read")),
      childCount: Number(tool.childCount || tool.child_count) || 0,
      enabled: tool.enabled !== false,
      access: readOnly && access === "inherit" ? "readonly" : access,
      effectiveAccess: normalizeText(tool.effectiveAccess || tool.effective_access || "")
    };
  }).filter((tool) => tool.name);
  const builtInTools = normalizeToolList(payload?.builtInTools || payload?.built_in_tools || payload?.tools);
  const customTools = normalizeToolList(payload?.customTools || payload?.custom_tools);
  const tools = normalizeToolList(payload?.tools).length ? normalizeToolList(payload?.tools) : [
    ...builtInTools.filter((tool) => tool.name !== "native_web_search"),
    ...customTools
  ];
  const disabledTools = Array.isArray(payload?.disabledTools)
    ? payload.disabledTools.map(normalizeText).filter(Boolean)
    : tools.filter((tool) => !tool.enabled || tool.access === "disabled").map((tool) => tool.name);
  const disabledToolsets = Array.isArray(payload?.disabledToolsets)
    ? payload.disabledToolsets.map(normalizeText).filter(Boolean)
    : tools.filter((tool) => !tool.enabled || tool.access === "disabled").map((tool) => tool.name);
  const disabledToolNames = new Set([...disabledTools, ...disabledToolsets]);
  const applyRuntimeDisabled = (items) => items.map((tool) => {
    if (tool.name === "web_search") {
      return { ...tool, enabled: customWebSearchEnabled };
    }
    return disabledToolNames.has(tool.name) ? { ...tool, enabled: false, effectiveAccess: "disabled" } : tool;
  });
  const visibleBuiltInTools = applyRuntimeDisabled(builtInTools);
  const visibleCustomTools = applyRuntimeDisabled(customTools);
  const visibleTools = applyRuntimeDisabled(tools);
  const enabledToolsets = Array.isArray(payload?.enabledToolsets)
    ? payload.enabledToolsets.map(normalizeText).filter(Boolean)
    : visibleCustomTools.filter((tool) => tool.enabled).map((tool) => tool.name);
  const toolWriteModes = {};
  if (payload?.toolWriteModes && typeof payload.toolWriteModes === "object") {
    Object.entries(payload.toolWriteModes).forEach(([name, mode]) => {
      const normalizedName = normalizeText(name);
      const normalizedMode = normalizeToolAccess(mode);
      if (normalizedName && ["ask", "auto", "warn", "readonly", "block", "halt"].includes(normalizedMode)) {
        toolWriteModes[normalizedName] = normalizedMode;
      }
    });
  } else {
    tools.forEach((tool) => {
      if (tool.enabled && tool.mutating && tool.access !== "inherit" && tool.access !== "disabled") {
        toolWriteModes[tool.name] = tool.access;
      }
    });
  }
  return {
    globalAccess,
    defaultWriteMode: globalAccess === "full_access" ? "auto" : "ask",
    builtInTools: visibleBuiltInTools,
    customTools: visibleCustomTools,
    tools: visibleTools,
    disabledToolsets,
    enabledToolsets,
    disabledTools,
    toolWriteModes,
    nativeWebSearchEnabled: Boolean(payload?.nativeWebSearchEnabled || visibleBuiltInTools.some((tool) => tool.name === "native_web_search" && tool.enabled)),
    webSearchProviders,
    settingsPath: normalizeText(payload?.settingsPath || ".paper-notes/tool-settings.json")
  };
}

function normalizeWebSearchProviders(raw) {
  const value = raw && typeof raw === "object" ? raw : {};
  const nativeProvider = value.native_provider || value.nativeProvider || {};
  const customProvider = value.custom_provider || value.customProvider || {};
  const openaiCodex = nativeProvider.openaiCodex || nativeProvider.openai_codex || {};
  const openaiAPIKey = nativeProvider.openaiAPIKey || nativeProvider.openai_api_key || {};
  const tavily = customProvider.Tavily || customProvider.tavily || {};
  const brave = customProvider.Brave || customProvider.brave || {};
  const customProviderName = normalizeText(value.customProviderName || value.custom_provider_name || value.providerName || value.provider_name);
  let mode = normalizeText(value.mode).toLowerCase().replaceAll("-", "_");
  if (!["native", "tavily", "native_tavily"].includes(mode)) {
    const nativeEnabled = Boolean(openaiCodex.enabled || openaiAPIKey.enabled);
    const tavilyEnabled = Boolean(tavily.enabled);
    mode = nativeEnabled && tavilyEnabled ? "native_tavily" : nativeEnabled ? "native" : tavilyEnabled ? "tavily" : "tavily";
  }
  return {
    mode,
    customProviderName: customProviderName || (tavily.enabled ? "Tavily" : brave.enabled ? "Brave" : "Tavily"),
    tavilyApiKey: "",
    braveSearchApiKey: "",
    tavilyKeyConfigured: Boolean(value.tavilyKeyConfigured || value.tavily_key_configured),
    tavilyKeySource: normalizeText(value.tavilyKeySource || value.tavily_key_source || "missing"),
    braveSearchKeyConfigured: Boolean(value.braveSearchKeyConfigured || value.brave_search_key_configured),
    braveSearchKeySource: normalizeText(value.braveSearchKeySource || value.brave_search_key_source || "missing"),
    native_provider: {
      openaiCodex: { enabled: Boolean(openaiCodex.enabled) },
      openaiAPIKey: { enabled: Boolean(openaiAPIKey.enabled) }
    },
    custom_provider: {
      Tavily: { enabled: Boolean(tavily.enabled) },
      Brave: { enabled: Boolean(brave.enabled) }
    }
  };
}

function isCustomWebSearchProviderEnabled(provider, name) {
  const custom = provider?.custom_provider || {};
  return Boolean(custom[name]?.enabled);
}

function isAnyCustomWebSearchProviderEnabled(provider) {
  return isCustomWebSearchProviderEnabled(provider, "Tavily")
    || isCustomWebSearchProviderEnabled(provider, "Brave");
}

function toolAccessLabel(access) {
  const normalized = normalizeToolAccess(access);
  if (normalized === "auto") return "Auto";
  if (normalized === "ask") return "Ask";
  if (normalized === "warn") return "Warn";
  if (normalized === "readonly") return "Read-only";
  if (normalized === "block") return "Block";
  if (normalized === "halt") return "Halt";
  if (normalized === "disabled") return "Off";
  return "Default";
}

function setToolSettingsError(message = "") {
  elements.toolSettingsError.textContent = message;
  elements.toolSettingsError.hidden = !message;
}

function renderToolSettingsDialog() {
  if (!elements.toolSettingsDialog) return;
  const settings = state.toolSettings || normalizeToolSettings({});
  const builtInTools = settings.builtInTools || [];
  const customTools = settings.customTools || settings.tools || [];
  const inheritedLabel = settings.defaultWriteMode === "auto" ? "Auto" : "Ask";

  elements.toolAccessDefault.checked = settings.globalAccess !== "full_access";
  elements.toolAccessFull.checked = settings.globalAccess === "full_access";
  elements.builtInToolSettingsCount.textContent = `${builtInTools.length} ${builtInTools.length === 1 ? "tool" : "tools"}`;
  elements.toolSettingsCount.textContent = `${customTools.length} ${customTools.length === 1 ? "tool" : "tools"}`;
  elements.toolSettingsSource.textContent = `Local tool settings are stored in ${settings.settingsPath}.`;
  elements.saveToolSettings.disabled = state.toolSettingsLoading;

  if (state.toolSettingsLoading) {
    elements.builtInToolSettingsList.innerHTML = `<p class="memory-empty">Loading tools...</p>`;
    elements.toolSettingsList.innerHTML = `<p class="memory-empty">Loading tools...</p>`;
    return;
  }
  elements.builtInToolSettingsList.innerHTML = builtInTools.length
    ? renderToolSettingsItems(builtInTools, inheritedLabel)
    : `<p class="memory-empty">No built-in tools registered.</p>`;
  elements.toolSettingsList.innerHTML = customTools.length
    ? renderToolSettingsItems(customTools, inheritedLabel)
    : `<p class="memory-empty">No custom tools registered.</p>`;
}

function renderToolSettingsItems(tools, inheritedLabel) {
  return tools.map((tool) => {
    if (tool.name === "web_search") {
      return renderCustomWebSearchSettingsItem(tool);
    }
    const access = tool.readOnly ? "readonly" : normalizeToolAccess(tool.access);
    const disabled = !tool.enabled;
    const accessSelect = tool.mutating ? `
      <label class="tool-access-select">
        <select aria-label="Access for ${escapeHtml(tool.label || tool.name)}" data-tool-access="${escapeHtml(tool.name)}"${disabled ? " disabled" : ""}>
          <option value="inherit"${access === "inherit" ? " selected" : ""}>Default (${escapeHtml(inheritedLabel)})</option>
          <option value="ask"${access === "ask" ? " selected" : ""}>Ask</option>
          <option value="auto"${access === "auto" ? " selected" : ""}>Auto</option>
          <option value="readonly"${access === "readonly" ? " selected" : ""}>Read-only</option>
        </select>
      </label>
    ` : `
      <span class="tool-readonly-pill">Read-only</span>
    `;
    const providerDetails = tool.name === "web_search" ? renderWebSearchProviderDetails(disabled) : "";
    return `
      <article class="tool-settings-item${disabled ? " is-disabled" : ""}">
        <div class="tool-settings-copy">
          <strong>${escapeHtml(tool.label || tool.name)}</strong>
          <span>${escapeHtml(tool.description)}</span>
          ${providerDetails}
        </div>
        <div class="tool-settings-controls">
          ${accessSelect}
          <label class="tool-enabled-toggle">
            <input type="checkbox" data-tool-enabled="${escapeHtml(tool.name)}"${tool.enabled ? " checked" : ""}>
            <span>${tool.enabled ? "Enabled" : "Off"}</span>
          </label>
        </div>
      </article>
    `;
  }).join("");
}

function renderCustomWebSearchSettingsItem(tool) {
  return `
    <article class="tool-settings-item tool-settings-item--web-search">
      <div class="tool-settings-copy">
        <strong>${escapeHtml(tool.label || tool.name)}</strong>
        <span>${escapeHtml(tool.description)}</span>
        ${renderWebSearchProviderDetails()}
      </div>
      <div class="tool-settings-controls">
        <span class="tool-readonly-pill">Read-only</span>
      </div>
    </article>
  `;
}

function renderWebSearchProviderDetails() {
  const settings = state.toolSettings || normalizeToolSettings({});
  const provider = settings.webSearchProviders || normalizeWebSearchProviders({});
  const tavilyEnabled = isCustomWebSearchProviderEnabled(provider, "Tavily");
  const braveEnabled = isCustomWebSearchProviderEnabled(provider, "Brave");
  const tavilyStatus = provider.tavilyKeyConfigured
    ? `Key configured (${escapeHtml(provider.tavilyKeySource || "local")})`
    : "Key not configured";
  const braveStatus = provider.braveSearchKeyConfigured
    ? `Key configured (${escapeHtml(provider.braveSearchKeySource || "local")})`
    : "Key not configured";
  return `
    <details class="tool-provider-details"${state.toolSettingsWebSearchOpen ? " open" : ""}>
      <summary>Configure providers</summary>
      <div class="tool-provider-panel">
        ${renderWebSearchProviderRow({
          name: "Tavily",
          label: "Tavily",
          enabled: tavilyEnabled,
          keyLabel: "Tavily API key",
          keyAttr: "data-web-search-tavily-key",
          placeholder: provider.tavilyKeyConfigured ? "Leave blank to keep current key" : "tvly-...",
          status: tavilyStatus
        })}
        ${renderWebSearchProviderRow({
          name: "Brave",
          label: "Brave Search",
          enabled: braveEnabled,
          keyLabel: "Brave Search API key",
          keyAttr: "data-web-search-brave-key",
          placeholder: provider.braveSearchKeyConfigured ? "Leave blank to keep current key" : "BSA...",
          status: braveStatus
        })}
      </div>
    </details>
  `;
}

function renderWebSearchProviderRow({ name, label, enabled, keyLabel, keyAttr, placeholder, status }) {
  return `
    <section class="web-search-provider-row${enabled ? "" : " is-off"}">
      <div class="web-search-provider-header">
        <div class="web-search-provider-title">
          <strong>${escapeHtml(label)}</strong>
          <small>${escapeHtml(status)}</small>
        </div>
        <label class="tool-enabled-toggle">
          <input type="checkbox" data-web-search-provider-enabled="${escapeHtml(name)}"${enabled ? " checked" : ""}>
          <span>${enabled ? "Enabled" : "Off"}</span>
        </label>
      </div>
      <label class="tool-provider-field">
        <span>${escapeHtml(keyLabel)}</span>
        <input ${keyAttr} type="password" autocomplete="off" placeholder="${escapeHtml(placeholder)}">
      </label>
    </section>
  `;
}

async function loadToolSettings() {
  state.toolSettingsLoading = true;
  renderToolSettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/tools");
    state.toolSettings = normalizeToolSettings(payload);
    setToolSettingsError("");
  } catch (error) {
    setToolSettingsError(error.message || "Could not load tool settings.");
    console.error(error);
  } finally {
    state.toolSettingsLoading = false;
    renderToolSettingsDialog();
  }
}

async function openToolSettingsDialog() {
  closeSettingsMenu();
  setToolSettingsError("");
  elements.toolSettingsDialog.showModal();
  renderToolSettingsDialog();
  await loadToolSettings();
}

function closeToolSettingsDialog() {
  setToolSettingsError("");
  elements.toolSettingsDialog.close();
  clearSettingsPanelUrl();
}

function updateToolSettingsGlobalAccess(value) {
  const settings = state.toolSettings || normalizeToolSettings({});
  state.toolSettings = {
    ...settings,
    globalAccess: value === "full_access" ? "full_access" : "default",
    defaultWriteMode: value === "full_access" ? "auto" : "ask"
  };
  renderToolSettingsDialog();
}

function updateToolSetting(name, updates) {
  const settings = state.toolSettings || normalizeToolSettings({});
  const updateList = (tools = []) => tools.map((tool) => (
    tool.name === name ? { ...tool, ...updates } : tool
  ));
  state.toolSettings = {
    ...settings,
    builtInTools: updateList(settings.builtInTools),
    customTools: updateList(settings.customTools),
    tools: updateList(settings.tools)
  };
  renderToolSettingsDialog();
}

function updateWebSearchProviders(updates) {
  const settings = state.toolSettings || normalizeToolSettings({});
  state.toolSettings = {
    ...settings,
    webSearchProviders: {
      ...(settings.webSearchProviders || normalizeWebSearchProviders({})),
      ...updates
    }
  };
  renderToolSettingsDialog();
}

function isToolEnabled(tools, name) {
  return Boolean((tools || []).find((tool) => tool.name === name)?.enabled);
}

function webSearchProvidersForSave(settings) {
  const provider = settings.webSearchProviders || normalizeWebSearchProviders({});
  const nativeEnabled = isToolEnabled(settings.builtInTools, "native_web_search");
  return {
    native_provider: {
      openaiCodex: { enabled: nativeEnabled },
      openaiAPIKey: { enabled: nativeEnabled }
    },
    custom_provider: {
      Tavily: { enabled: isCustomWebSearchProviderEnabled(provider, "Tavily") },
      Brave: { enabled: isCustomWebSearchProviderEnabled(provider, "Brave") }
    },
    tavilyApiKey: provider.tavilyApiKey || "",
    braveSearchApiKey: provider.braveSearchApiKey || ""
  };
}

function webSearchEnabledForSave(settings) {
  const provider = settings.webSearchProviders || normalizeWebSearchProviders({});
  return isToolEnabled(settings.builtInTools, "native_web_search") || isAnyCustomWebSearchProviderEnabled(provider);
}

async function saveToolSettings() {
  const settings = state.toolSettings || normalizeToolSettings({});
  elements.saveToolSettings.disabled = true;
  const allTools = [...(settings.builtInTools || []), ...(settings.customTools || [])];
  try {
    const payload = await fetchJson("/api/settings/tools", {
      method: "POST",
      body: {
        globalAccess: settings.globalAccess,
        tools: allTools.map((tool) => ({
          name: tool.name,
          enabled: tool.name === "web_search" ? webSearchEnabledForSave(settings) : tool.enabled,
          access: tool.readOnly ? "inherit" : normalizeToolAccess(tool.access)
        })),
        webSearchProviders: webSearchProvidersForSave(settings)
      }
    });
    state.toolSettings = normalizeToolSettings(payload);
    setToolSettingsError("");
    renderToolSettingsDialog();
    closeToolSettingsDialog();
  } catch (error) {
    setToolSettingsError(error.message || "Could not save tool settings.");
    console.error(error);
  } finally {
    elements.saveToolSettings.disabled = false;
  }
}

