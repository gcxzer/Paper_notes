function normalizeMcpSettings(payload) {
  const servers = Array.isArray(payload?.servers) ? payload.servers.map(normalizeMcpServer).filter((server) => server.id) : [];
  return {
    success: payload?.success !== false,
    servers,
    settingsPath: normalizeText(payload?.settingsPath || ".paper-notes/mcp-servers.json")
  };
}

function cloneMcpSettings(settings) {
  return normalizeMcpSettings(JSON.parse(JSON.stringify(settings || {})));
}

function normalizeMcpServer(server) {
  const transport = normalizeText(server?.transport || (server?.url ? "http" : "stdio")).toLowerCase() === "http" ? "http" : "stdio";
  const status = server?.status && typeof server.status === "object" ? server.status : {};
  const failureCount = Number(status.failureCount) || 0;
  return {
    id: normalizeText(server?.id || server?.name || `server_${Date.now().toString(36)}`),
    name: normalizeText(server?.name || server?.id || "MCP server"),
    enabled: server?.enabled !== false,
    transport,
    command: normalizeText(server?.command || ""),
    args: Array.isArray(server?.args) ? server.args.map(normalizeText).filter(Boolean) : [],
    env: normalizeMcpSecretEntries(server?.env),
    url: normalizeText(server?.url || ""),
    headers: normalizeMcpSecretEntries(server?.headers),
    bearerTokenEnvVar: normalizeText(server?.bearerTokenEnvVar || ""),
    headerEnvVars: normalizeMcpEnvRefEntries(server?.headerEnvVars),
    includeTools: normalizeMcpFilterList(server?.includeTools),
    excludeTools: normalizeMcpFilterList(server?.excludeTools),
    runtimeWarnings: normalizeMcpRuntimeWarnings(server?.runtimeWarnings),
    timeoutSeconds: Number(server?.timeoutSeconds) || 120,
    connectTimeoutSeconds: Number(server?.connectTimeoutSeconds) || 10,
    status: {
      connected: Boolean(status.connected),
      error: normalizeText(status.error || ""),
      toolCount: Number(status.toolCount) || 0,
      state: normalizeText(status.state || ""),
      failureCount: Math.max(0, Math.round(failureCount)),
      nextRetryAt: status.nextRetryAt ?? null,
      circuitOpen: Boolean(status.circuitOpen),
      securityWarnings: normalizeMcpSecurityWarnings(status.securityWarnings)
    },
    tools: Array.isArray(server?.tools) ? server.tools.map(normalizeMcpToolSummary).filter((tool) => tool.name) : []
  };
}

function normalizeMcpToolSummary(tool) {
  const readOnly = Boolean(tool?.readOnly);
  return {
    name: normalizeText(tool?.name),
    generatedName: normalizeText(tool?.generatedName),
    description: normalizeText(tool?.description),
    readOnly,
    mutating: tool?.mutating === undefined ? !readOnly : Boolean(tool.mutating),
    title: normalizeText(tool?.title || tool?.annotations?.title || ""),
    destructiveHint: Boolean(tool?.destructiveHint ?? tool?.annotations?.destructiveHint),
    idempotentHint: Boolean(tool?.idempotentHint ?? tool?.annotations?.idempotentHint),
    openWorldHint: Boolean(tool?.openWorldHint ?? tool?.annotations?.openWorldHint),
    hasOutputSchema: Boolean(tool?.hasOutputSchema),
    securityWarnings: normalizeMcpSecurityWarnings(tool?.securityWarnings)
  };
}

function normalizeMcpRuntimeWarnings(raw) {
  if (!Array.isArray(raw)) return [];
  return raw.map((warning) => {
    if (!warning || typeof warning !== "object") return null;
    return {
      code: normalizeText(warning.code || ""),
      severity: normalizeText(warning.severity || ""),
      message: normalizeText(warning.message || warning.detail || "")
    };
  }).filter((warning) => warning && (warning.code || warning.message));
}

function normalizeMcpSecurityWarnings(raw) {
  if (!Array.isArray(raw)) return [];
  return raw.map((warning) => {
    if (!warning || typeof warning !== "object") return null;
    return {
      code: normalizeText(warning.code || ""),
      surface: normalizeText(warning.surface || ""),
      severity: normalizeText(warning.severity || ""),
      message: normalizeText(warning.message || warning.detail || ""),
      match: normalizeText(warning.match || "")
    };
  }).filter((warning) => warning && (warning.code || warning.message || warning.surface || warning.match));
}

function normalizeMcpSecretEntries(raw) {
  if (Array.isArray(raw)) {
    return raw.map((entry) => ({
      name: normalizeText(entry?.name || entry?.key),
      value: normalizeText(entry?.value || ""),
      configured: Boolean(entry?.configured)
    })).filter((entry) => entry.name || entry.value);
  }
  if (raw && typeof raw === "object") {
    return Object.entries(raw).map(([name, value]) => ({
      name: normalizeText(name),
      value: typeof value === "string" ? value : normalizeText(value?.value || ""),
      configured: Boolean(value?.configured || value)
    })).filter((entry) => entry.name);
  }
  return [];
}

function normalizeMcpEnvRefEntries(raw) {
  if (Array.isArray(raw)) {
    return raw.map((entry) => ({
      name: normalizeText(entry?.name || entry?.key || entry?.header),
      value: normalizeText(entry?.value || entry?.envVar || entry?.variable || entry?.env)
    })).filter((entry) => entry.name || entry.value);
  }
  if (raw && typeof raw === "object") {
    return Object.entries(raw).map(([name, value]) => ({
      name: normalizeText(name),
      value: normalizeText(value)
    })).filter((entry) => entry.name || entry.value);
  }
  return [];
}

function normalizeMcpFilterList(raw) {
  const pieces = [];
  if (Array.isArray(raw)) {
    raw.forEach((item) => {
      pieces.push(...normalizeText(item).split(/[\n,]/));
    });
  } else if (typeof raw === "string") {
    pieces.push(...raw.split(/[\n,]/));
  } else {
    return [];
  }
  const seen = new Set();
  return pieces.map(normalizeText).filter((item) => {
    if (!item || seen.has(item)) return false;
    seen.add(item);
    return true;
  });
}

function newMcpServer() {
  const id = `mcp_${Date.now().toString(36)}`;
  return normalizeMcpServer({
    id,
    name: "New MCP server",
    enabled: true,
    transport: "stdio",
    command: "",
    args: [],
    env: [],
    headers: [],
    bearerTokenEnvVar: "",
    headerEnvVars: [],
    includeTools: [],
    excludeTools: [],
    timeoutSeconds: 120,
    connectTimeoutSeconds: 10
  });
}

function currentMcpServer() {
  const settings = state.mcpSettings || normalizeMcpSettings({});
  return settings.servers.find((server) => server.id === state.mcpEditingId) || settings.servers[0] || null;
}

function ensureMcpSelectedServer(settings = state.mcpSettings || normalizeMcpSettings({}), visibleServers = null) {
  const servers = Array.isArray(settings?.servers) ? settings.servers : [];
  if (!servers.length) {
    state.mcpEditingId = "";
    return null;
  }
  const selected = servers.find((server) => server.id === state.mcpEditingId);
  if (selected) return selected;
  const fallback = Array.isArray(visibleServers) && visibleServers.length ? visibleServers[0] : servers[0];
  state.mcpEditingId = fallback.id;
  return fallback;
}

function filterMcpServers(servers) {
  const query = normalizeText(state.mcpSearchQuery).toLowerCase();
  if (!query) return servers || [];
  return (servers || []).filter((server) => [
    server.name,
    server.id,
    server.transport,
    server.command,
    server.url,
    mcpServerEndpoint(server),
    mcpStatusMeta(server).label
  ].some((value) => normalizeText(value).toLowerCase().includes(query)));
}

function displayMcpSettingsPath(path) {
  const normalized = normalizeText(path || ".paper-notes/mcp-servers.json");
  const marker = ".paper-notes/";
  const markerIndex = normalized.lastIndexOf(marker);
  return markerIndex >= 0 ? normalized.slice(markerIndex) : normalized;
}

function mcpActionKey(action, serverId = "") {
  return `${action}:${serverId || "global"}`;
}

function mcpActionError(action, serverId = "") {
  return state.mcpActionErrors?.[mcpActionKey(action, serverId)] || null;
}

function setMcpActionError(action, serverId = "", message = "", title = "") {
  const key = mcpActionKey(action, serverId);
  const next = { ...(state.mcpActionErrors || {}) };
  if (message) {
    next[key] = { title: title || "MCP error", message };
  } else {
    delete next[key];
  }
  state.mcpActionErrors = next;
}

function clearMcpActionError(action, serverId = "") {
  setMcpActionError(action, serverId, "");
}

function renderMcpActionErrorCard(action, serverId = "") {
  const error = mcpActionError(action, serverId);
  if (!error) return "";
  return `
    <div class="mcp-button-error" data-mcp-action-error="${escapeHtml(action)}" role="alert">
      <strong>${escapeHtml(error.title)}</strong>
      <span>${escapeHtml(error.message)}</span>
    </div>
  `;
}

function renderMcpActionErrorRegion(actions, serverId = "") {
  const cards = actions.map((action) => renderMcpActionErrorCard(action, serverId)).filter(Boolean);
  if (!cards.length) return "";
  return `<div class="mcp-action-error-region">${cards.join("")}</div>`;
}

function renderMcpSaveError() {
  if (!elements.mcpSaveError) return;
  const error = mcpActionError("save");
  elements.mcpSaveError.innerHTML = error ? `<span>${escapeHtml(error.message)}</span>` : "";
  elements.mcpSaveError.hidden = !error;
}

function setMcpSettingsError(message = "", title = "") {
  setMcpActionError("save", "", message, title);
  renderMcpSaveError();
}

function clearMcpTransientFeedback() {
  state.mcpTestResult = null;
  state.mcpLogResult = null;
  state.mcpActionErrors = {};
  setMcpSettingsError("");
}

function mcpRequestErrorMessage(error, fallback) {
  if (error?.status === 404 || normalizeText(error?.message).toLowerCase() === "not found") {
    return "MCP settings API is unavailable. Restart Paper Notes and try again.";
  }
  return error?.message || fallback;
}

function renderMcpSettingsDialog() {
  if (!elements.mcpSettingsDialog) return;
  const settings = state.mcpSettings || normalizeMcpSettings({});
  const servers = settings.servers || [];
  const visibleServers = filterMcpServers(servers);
  const active = ensureMcpSelectedServer(settings, visibleServers);
  const isEmpty = !state.mcpSettingsLoading && !servers.length;

  elements.mcpSettingsCount.textContent = `${servers.length} ${servers.length === 1 ? "server" : "servers"}`;
  if (elements.mcpSearchInput && elements.mcpSearchInput.value !== state.mcpSearchQuery) {
    elements.mcpSearchInput.value = state.mcpSearchQuery;
  }
  elements.mcpSettingsSource.textContent = `Config file: ${displayMcpSettingsPath(settings.settingsPath)}`;
  elements.saveMcpSettings.disabled = state.mcpSettingsLoading;
  elements.mcpSettingsForm?.classList.toggle("is-empty", isEmpty);
  elements.mcpServerList?.closest(".mcp-settings-layout")?.classList.toggle("is-empty", isEmpty);

  if (state.mcpSettingsLoading) {
    elements.mcpServerList.innerHTML = `<p class="mcp-list-empty">Loading MCP servers...</p>`;
    elements.mcpServerEditor.innerHTML = "";
    return;
  }

  elements.mcpServerList.innerHTML = visibleServers.length
    ? visibleServers.map(renderMcpServerListItem).join("")
    : servers.length
      ? `<p class="mcp-list-empty">No matching servers.</p>`
    : "";
  elements.mcpServerEditor.innerHTML = active ? renderMcpServerEditor(active) : renderMcpEmptyEditor();
  renderMcpSaveError();
}

function mcpStatusMeta(server) {
  if (state.mcpOperationId === `connect:${server.id}`) return { label: "Connecting", tone: "warning" };
  const status = mcpDisplayStatus(server);
  if (!server.enabled) return { label: "Off", tone: "off" };
  if (status.circuitOpen) return { label: "Circuit open", tone: "warning" };
  if (status.state === "reconnecting") return { label: "Reconnecting", tone: "warning" };
  if (status.state === "connecting") return { label: "Connecting", tone: "warning" };
  if (status.connected) return { label: "Connected", tone: "connected" };
  if (status.error) return { label: "Error", tone: "error" };
  return { label: "Ready", tone: "idle" };
}

function mcpDisplayStatus(server) {
  const connectError = mcpActionError("connect", server.id)?.message || "";
  if (!connectError) return server.status || {};
  return {
    ...(server.status || {}),
    connected: false,
    error: connectError,
    toolCount: 0,
    state: "error",
    failureCount: 0,
    nextRetryAt: null,
    circuitOpen: false
  };
}

function mcpServerEndpoint(server) {
  if (server.transport === "http") return server.url || "HTTP endpoint";
  return server.command || "stdio command";
}

function mcpWarningCount(server) {
  const statusWarnings = server.status?.securityWarnings?.length || 0;
  const toolWarnings = (server.tools || []).reduce((count, tool) => count + (tool.securityWarnings?.length || 0), 0);
  return statusWarnings + toolWarnings;
}

function mcpTestWarningCount(test) {
  return (test?.securityWarnings?.length || 0) + (test?.tools || []).reduce((count, tool) => count + (tool.securityWarnings?.length || 0), 0);
}

function mcpWarningLabel(count) {
  return `${count} security ${count === 1 ? "warning" : "warnings"}`;
}

function formatMcpRetryTime(value) {
  if (value === null || value === undefined || value === "") return "";
  const numeric = Number(value);
  const timestamp = Number.isFinite(numeric)
    ? (Math.abs(numeric) < 1000000000000 ? numeric * 1000 : numeric)
    : Date.parse(String(value));
  if (!Number.isFinite(timestamp)) return "";
  return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function mcpServerStatusDetail(server) {
  const status = mcpDisplayStatus(server);
  const retryLabel = formatMcpRetryTime(status.nextRetryAt);
  if (status.circuitOpen) {
    const failures = status.failureCount ? `${status.failureCount} failures` : "Circuit paused";
    return retryLabel ? `${failures}, retry ${retryLabel}` : failures;
  }
  if (status.connected) return `${status.toolCount || server.tools.length || 0} tools`;
  if (status.failureCount) return `${status.failureCount} failures${retryLabel ? `, retry ${retryLabel}` : ""}`;
  if (status.error) return status.error;
  return mcpServerEndpoint(server);
}

function renderMcpServerListItem(server) {
  const active = server.id === state.mcpEditingId;
  const status = mcpStatusMeta(server);
  const toolLabel = mcpServerStatusDetail(server);
  return `
    <button class="mcp-server-row${active ? " is-active" : ""}" type="button" data-mcp-select="${escapeHtml(server.id)}">
      <span class="mcp-server-row-copy">
        <strong>${escapeHtml(server.name)}</strong>
        <small>${escapeHtml(toolLabel)}</small>
      </span>
      <span class="mcp-status-pill is-${escapeHtml(status.tone)}">${escapeHtml(status.label)}</span>
    </button>
  `;
}

function renderMcpEmptyEditor() {
  return `
    <div class="mcp-empty-editor">
      <strong>No servers configured</strong>
      <span>Add a stdio or HTTP MCP server to make its tools available to the agent.</span>
      <button class="toolbar-button toolbar-button-primary" type="button" data-mcp-empty-add>Add server</button>
    </div>
  `;
}

function renderMcpToolChip(tool) {
  const warningCount = tool.securityWarnings?.length || 0;
  const label = warningCount ? "Warning" : (tool.readOnly ? "Read-only" : (tool.destructiveHint ? "Destructive" : "Requires approval"));
  return `
    <span class="mcp-tool-chip${warningCount ? " is-warning" : ""}">
      <strong>${escapeHtml(tool.generatedName || tool.name)}</strong>
      <em>${escapeHtml(label)}</em>
    </span>
  `;
}

function renderMcpStatusSection(server) {
  const displayStatus = mcpDisplayStatus(server);
  const connectError = mcpActionError("connect", server.id);
  const status = mcpStatusMeta(server);
  const retryLabel = formatMcpRetryTime(displayStatus.nextRetryAt);
  const warningCount = mcpWarningCount(server);
  const reconnecting = state.mcpOperationId === `reconnect:${server.id}`;
  const resetting = state.mcpOperationId === `reset:${server.id}`;
  const loadingLog = state.mcpOperationId === `log:${server.id}`;
  const busy = Boolean(state.mcpOperationId);
  const rows = [
    ["State", status.label],
    ["Tools", String(displayStatus.toolCount || server.tools.length || 0)],
  ];
  if (displayStatus.failureCount) rows.push(["Failures", String(displayStatus.failureCount)]);
  if (retryLabel) rows.push(["Next retry", retryLabel]);
  if (warningCount) rows.push(["Warnings", mcpWarningLabel(warningCount)]);
  return `
    <section class="mcp-section">
      <div class="mcp-section-title">
        <strong>Status</strong>
        <span>${escapeHtml(status.label)}</span>
      </div>
      <div class="mcp-status-grid">
        ${rows.map(([label, value]) => `
          <div class="mcp-status-item">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
          </div>
        `).join("")}
      </div>
      ${server.status.error && !connectError ? `<p class="mcp-status-note is-error">${escapeHtml(server.status.error)}</p>` : ""}
      ${warningCount ? `<p class="mcp-status-note is-warning">${escapeHtml(mcpWarningLabel(warningCount))} detected in MCP metadata.</p>` : ""}
      <div class="mcp-status-actions">
        <div class="mcp-action-slot">
          <button class="toolbar-button" type="button" data-mcp-reconnect="${escapeHtml(server.id)}"${busy ? " disabled" : ""}>${reconnecting ? "Reconnecting..." : "Reconnect"}</button>
        </div>
        <div class="mcp-action-slot">
          <button class="toolbar-button" type="button" data-mcp-reset-circuit="${escapeHtml(server.id)}"${busy ? " disabled" : ""}>${resetting ? "Resetting..." : "Reset circuit"}</button>
        </div>
        <div class="mcp-action-slot">
          <button class="toolbar-button" type="button" data-mcp-view-log="${escapeHtml(server.id)}"${busy ? " disabled" : ""}>${loadingLog ? "Loading log..." : "View stderr log"}</button>
        </div>
      </div>
      ${renderMcpActionErrorRegion(["reconnect", "reset", "log"], server.id)}
      ${renderMcpLogPanel(server)}
    </section>
  `;
}

function renderMcpRuntimeWarnings(warnings = []) {
  const items = normalizeMcpRuntimeWarnings(warnings);
  if (!items.length) return "";
  return `
    <section class="mcp-section">
      <div class="mcp-section-title">
        <strong>Runtime note</strong>
      </div>
      ${items.map((warning) => `<p class="mcp-status-note is-warning">${escapeHtml(warning.message)}</p>`).join("")}
    </section>
  `;
}

function renderMcpLogPanel(server) {
  const log = state.mcpLogResult;
  if (!log || log.serverId !== server.id || log.success === false) return "";
  const body = log.log || "No MCP stderr output has been captured yet.";
  return `
    <details class="mcp-log-panel" open>
      <summary>
        <span>MCP stderr log</span>
        ${log.truncated ? "<em>Tail shown</em>" : ""}
      </summary>
      <pre>${escapeHtml(body)}</pre>
    </details>
  `;
}

function renderMcpServerEditor(server) {
  const test = state.mcpTestResult?.id === server.id ? state.mcpTestResult : null;
  const testWarningCount = mcpTestWarningCount(test);
  const connecting = state.mcpOperationId === `connect:${server.id}`;
  const busy = Boolean(state.mcpOperationId);
  const testHtml = test && test.success !== false ? `
    <section class="mcp-test-result ${test.success ? "is-success" : "is-error"}">
      <div class="mcp-test-summary">
        <strong>${test.success ? `Discovered ${test.toolCount || 0} tools` : "Connection failed"}</strong>
        ${test.error ? `<span>${escapeHtml(test.error)}</span>` : ""}
        ${testWarningCount ? `<span>${escapeHtml(mcpWarningLabel(testWarningCount))} returned by this test.</span>` : ""}
      </div>
      ${test.tools?.length ? `<div class="mcp-tool-chips">${test.tools.slice(0, 8).map((tool) => `
        ${renderMcpToolChip(tool)}
      `).join("")}</div>` : ""}
    </section>
  ` : "";
  return `
    <div class="mcp-editor-head">
      <div class="mcp-editor-title">
        <span class="mcp-kicker">${escapeHtml(server.transport === "http" ? "Streamable HTTP" : "stdio")}</span>
        <div class="mcp-editor-name-row">
          <strong>${escapeHtml(server.name)}</strong>
          <label class="mcp-switch mcp-title-switch">
            <input type="checkbox" data-mcp-field="enabled"${server.enabled ? " checked" : ""}${busy ? " disabled" : ""}>
            <span aria-hidden="true"></span>
            <em>${server.enabled ? "Enabled" : "Off"}</em>
          </label>
        </div>
      </div>
      <div class="mcp-editor-state">
        <button class="toolbar-button toolbar-button-danger mcp-title-remove" type="button" data-mcp-delete="${escapeHtml(server.id)}">Delete</button>
      </div>
    </div>
    ${renderMcpRuntimeWarnings(server.runtimeWarnings)}
    <section class="mcp-section">
      <div class="mcp-section-title">
        <strong>Basics</strong>
        <span>${escapeHtml(server.id)}</span>
      </div>
      <div class="mcp-editor-grid">
        <label class="field">
          <span>Name</span>
          <input type="text" value="${escapeHtml(server.name)}" data-mcp-field="name" autocomplete="off">
        </label>
        <div class="mcp-transport-field">
          <span>Transport</span>
          <div class="mcp-transport-segment" role="group" aria-label="Transport">
            <button class="${server.transport === "stdio" ? "is-active" : ""}" type="button" data-mcp-transport-option="stdio" aria-pressed="${server.transport === "stdio" ? "true" : "false"}">stdio</button>
            <button class="${server.transport === "http" ? "is-active" : ""}" type="button" data-mcp-transport-option="http" aria-pressed="${server.transport === "http" ? "true" : "false"}">HTTP</button>
          </div>
        </div>
      </div>
    </section>
    ${server.transport === "http" ? renderMcpHttpFields(server) : renderMcpStdioFields(server)}
    <section class="mcp-section">
      <div class="mcp-section-title">
        <strong>Timeouts</strong>
      </div>
      <div class="mcp-editor-grid">
        <label class="field">
          <span>Tool timeout seconds</span>
          <input type="number" min="1" value="${escapeHtml(String(server.timeoutSeconds))}" data-mcp-field="timeoutSeconds">
        </label>
        <label class="field">
          <span>Connect timeout seconds</span>
          <input type="number" min="1" value="${escapeHtml(String(server.connectTimeoutSeconds))}" data-mcp-field="connectTimeoutSeconds">
        </label>
      </div>
    </section>
    ${renderMcpStatusSection(server)}
    ${renderMcpFilterFields(server)}
    ${testHtml}
    <div class="mcp-editor-actions">
      <div class="mcp-action-slot">
        <button class="toolbar-button" type="button" data-mcp-test="${escapeHtml(server.id)}"${state.mcpTestingId || busy ? " disabled" : ""}>${state.mcpTestingId === server.id ? "Testing..." : "Test"}</button>
      </div>
      <div class="mcp-action-slot">
        <button class="toolbar-button toolbar-button-primary" type="button" data-mcp-connect="${escapeHtml(server.id)}"${state.mcpTestingId || busy ? " disabled" : ""}>${connecting ? "Connecting..." : "Connect"}</button>
      </div>
    </div>
    ${renderMcpActionErrorRegion(["test", "connect"], server.id)}
    ${test?.runtimeWarnings?.length ? renderMcpRuntimeWarnings(test.runtimeWarnings) : ""}
  `;
}

function renderMcpFilterFields(server) {
  return `
    <section class="mcp-section">
      <div class="mcp-section-title">
        <strong class="settings-title-with-info">
          Tool filters
          ${renderInfoHint("Use MCP tool names or wildcard patterns. Empty include allows all tools; exclude is applied last and wins over include.", "Tool filters", "mcp-tool-filters")}
        </strong>
        <span>Optional</span>
      </div>
      <div class="mcp-editor-grid">
        <label class="field">
          <span>Include tools</span>
          <textarea data-mcp-field="includeTools" spellcheck="false" placeholder="read_*&#10;list_resources">${escapeHtml((server.includeTools || []).join("\n"))}</textarea>
        </label>
        <label class="field">
          <span>Exclude tools</span>
          <textarea data-mcp-field="excludeTools" spellcheck="false" placeholder="write_*&#10;delete_file">${escapeHtml((server.excludeTools || []).join("\n"))}</textarea>
        </label>
      </div>
    </section>
  `;
}

function renderMcpStdioFields(server) {
  return `
    <section class="mcp-section">
      <div class="mcp-section-title">
        <strong>Connection</strong>
      </div>
      <label class="field">
        <span>Command</span>
        <input type="text" value="${escapeHtml(server.command)}" data-mcp-field="command" autocomplete="off" spellcheck="false" placeholder="npx">
      </label>
      <label class="field">
        <span>Arguments</span>
        <textarea data-mcp-field="args" spellcheck="false" placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;/path/to/folder">${escapeHtml((server.args || []).join("\n"))}</textarea>
      </label>
    </section>
    ${renderMcpSecretEditor("Environment", "env", server.env)}
  `;
}

function renderMcpHttpFields(server) {
  return `
    <section class="mcp-section">
      <div class="mcp-section-title">
        <strong>Connection</strong>
      </div>
      <label class="field">
        <span>URL</span>
        <input type="url" value="${escapeHtml(server.url)}" data-mcp-field="url" autocomplete="off" spellcheck="false" placeholder="http://localhost:8000/mcp">
      </label>
      <label class="field">
        <span class="settings-label-with-info">
          Bearer token env var
          ${renderInfoHint("Reads this variable from the process environment or local env files.", "Bearer token env var", "mcp-bearer-token-env-var")}
        </span>
        <input type="text" value="${escapeHtml(server.bearerTokenEnvVar || "")}" data-mcp-field="bearerTokenEnvVar" autocomplete="off" spellcheck="false" placeholder="MCP_BEARER_TOKEN">
      </label>
    </section>
    ${renderMcpSecretEditor("Headers", "headers", server.headers)}
    ${renderMcpSecretEditor("Headers from environment variables", "headerEnvVars", server.headerEnvVars, {
      addLabel: "Add variable",
      namePlaceholder: "Authorization",
      valuePlaceholder: "MCP_AUTH_HEADER",
      valueType: "text",
      hint: "Only the declared variables are read from the process environment or local env files.",
      hintKey: "mcp-header-env-vars"
    })}
  `;
}

function renderMcpSecretEditor(title, kind, entries, options = {}) {
  const rows = (entries || []).map((entry, index) => renderMcpSecretRow(kind, entry, index, options)).join("");
  const titleHint = options.hint
    ? renderInfoHint(options.hint, title, options.hintKey || `mcp-${kind}-hint`)
    : "";
  return `
    <section class="mcp-section mcp-secret-section">
      <div class="mcp-section-title mcp-secret-header">
        <strong class="${titleHint ? "settings-title-with-info" : ""}">
          ${escapeHtml(title)}
          ${titleHint}
        </strong>
        <button class="toolbar-button" type="button" data-mcp-secret-add="${escapeHtml(kind)}">${escapeHtml(options.addLabel || "Add")}</button>
      </div>
      <div class="mcp-secret-list">
        ${rows || `<p class="mcp-inline-empty">None configured.</p>`}
      </div>
    </section>
  `;
}

function renderMcpSecretRow(kind, entry, index, options = {}) {
  const valueType = options.valueType || "password";
  const valuePlaceholder = options.valuePlaceholder
    || (entry.configured ? "Leave blank to keep current value" : "Value");
  return `
    <div class="mcp-secret-row">
      <input type="text" value="${escapeHtml(entry.name)}" data-mcp-secret-name="${escapeHtml(kind)}" data-mcp-secret-index="${index}" placeholder="${escapeHtml(options.namePlaceholder || (kind === "env" ? "API_KEY" : "Authorization"))}" spellcheck="false">
      <input type="${escapeHtml(valueType)}" value="${escapeHtml(entry.value || "")}" data-mcp-secret-value="${escapeHtml(kind)}" data-mcp-secret-index="${index}" placeholder="${escapeHtml(valuePlaceholder)}" spellcheck="false">
      <button class="icon-button" type="button" data-mcp-secret-remove="${escapeHtml(kind)}" data-mcp-secret-index="${index}" aria-label="Remove">x</button>
    </div>
  `;
}

async function loadMcpSettings() {
  state.mcpSettingsLoading = true;
  renderMcpSettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/mcp");
    state.mcpSettings = normalizeMcpSettings(payload);
    state.mcpSettingsBaseline = cloneMcpSettings(state.mcpSettings);
    state.mcpRuntimePreviewDirty = false;
    ensureMcpSelectedServer(state.mcpSettings);
    setMcpSettingsError("");
  } catch (error) {
    state.mcpSettings = normalizeMcpSettings({});
    state.mcpEditingId = "";
    setMcpSettingsError(error?.status === 404 ? "" : mcpRequestErrorMessage(error, "Could not load MCP settings."), "Load failed");
    console.error(error);
  } finally {
    state.mcpSettingsLoading = false;
    renderMcpSettingsDialog();
  }
}

async function openMcpSettingsDialog() {
  closeSettingsMenu();
  setMcpSettingsError("");
  state.mcpRuntimePreviewDirty = false;
  elements.mcpSettingsDialog.showModal();
  renderMcpSettingsDialog();
  await loadMcpSettings();
}

async function refreshMcpSettings() {
  await restoreMcpRuntimeFromBaseline();
  await loadMcpSettings();
}

function closeMcpSettingsDialog(options = {}) {
  setMcpSettingsError("");
  elements.mcpSettingsDialog.close();
  clearSettingsPanelUrl();
  if (options.restoreRuntime) {
    void restoreMcpRuntimeFromBaseline();
  }
}

function cancelMcpSettingsDialog() {
  closeMcpSettingsDialog({ restoreRuntime: true });
}

function updateMcpServer(id, updater, shouldRender = true) {
  const settings = state.mcpSettings || normalizeMcpSettings({});
  state.mcpSettings = {
    ...settings,
    servers: settings.servers.map((server) => server.id === id ? updater(server) : server)
  };
  if (shouldRender) renderMcpSettingsDialog();
}

function addMcpServer() {
  const server = newMcpServer();
  const settings = state.mcpSettings || normalizeMcpSettings({});
  state.mcpSettings = { ...settings, servers: [...settings.servers, server] };
  state.mcpEditingId = server.id;
  clearMcpTransientFeedback();
  renderMcpSettingsDialog();
}

function removeMcpServer(id) {
  const settings = state.mcpSettings || normalizeMcpSettings({});
  const servers = settings.servers.filter((server) => server.id !== id);
  state.mcpSettings = { ...settings, servers };
  state.mcpEditingId = servers[0]?.id || "";
  clearMcpTransientFeedback();
  renderMcpSettingsDialog();
}

function confirmDeleteMcpServer(id) {
  const server = (state.mcpSettings || normalizeMcpSettings({})).servers.find((entry) => entry.id === id);
  if (!server) return;
  openConfirmDialog({
    eyebrow: "MCP",
    title: `Delete ${server.name}?`,
    body: "This removes the server from the MCP settings draft. Save the settings to persist the deletion.",
    actionLabel: "Delete",
    danger: true,
    action: () => removeMcpServer(id)
  });
}

function updateMcpSecret(kind, index, updates, shouldRender = true) {
  const server = currentMcpServer();
  if (!server) return;
  clearMcpTransientFeedback();
  updateMcpServer(server.id, (current) => {
    const entries = [...(current[kind] || [])];
    entries[index] = { ...(entries[index] || { name: "", value: "", configured: false }), ...updates };
    return { ...current, [kind]: entries };
  }, shouldRender);
}

function addMcpSecret(kind) {
  const server = currentMcpServer();
  if (!server) return;
  clearMcpTransientFeedback();
  updateMcpServer(server.id, (current) => ({
    ...current,
    [kind]: [...(current[kind] || []), { name: "", value: "", configured: false }]
  }));
}

function removeMcpSecret(kind, index) {
  const server = currentMcpServer();
  if (!server) return;
  clearMcpTransientFeedback();
  updateMcpServer(server.id, (current) => ({
    ...current,
    [kind]: (current[kind] || []).filter((_, itemIndex) => itemIndex !== index)
  }));
}

function mcpServerForSave(server) {
  const secretForSave = (entries) => (entries || [])
    .filter((entry) => normalizeText(entry.name))
    .map((entry) => ({
      name: normalizeText(entry.name),
      value: entry.value || "",
      configured: Boolean(entry.configured)
    }));
  const envRefForSave = (entries) => (entries || [])
    .filter((entry) => normalizeText(entry.name) && normalizeText(entry.value))
    .map((entry) => ({
      name: normalizeText(entry.name),
      value: normalizeText(entry.value)
    }));
  return {
    id: server.id,
    name: server.name,
    enabled: server.enabled,
    transport: server.transport,
    command: server.command,
    args: server.args || [],
    env: secretForSave(server.env),
    url: server.url,
    headers: secretForSave(server.headers),
    bearerTokenEnvVar: normalizeText(server.bearerTokenEnvVar || ""),
    headerEnvVars: envRefForSave(server.headerEnvVars),
    includeTools: normalizeMcpFilterList(server.includeTools || []),
    excludeTools: normalizeMcpFilterList(server.excludeTools || []),
    timeoutSeconds: server.timeoutSeconds,
    connectTimeoutSeconds: server.connectTimeoutSeconds
  };
}

function validateMcpServer(server) {
  const name = normalizeText(server?.name || server?.id || "MCP server");
  const timeoutSeconds = Number(server?.timeoutSeconds);
  const connectTimeoutSeconds = Number(server?.connectTimeoutSeconds);
  const envNamePattern = /^[A-Za-z_][A-Za-z0-9_]*$/;
  if (server?.transport === "http") {
    if (!normalizeText(server?.url)) return `${name}: HTTP URL is required.`;
    try {
      const parsed = new URL(normalizeText(server.url));
      if (!["http:", "https:"].includes(parsed.protocol)) return `${name}: HTTP URL must start with http:// or https://.`;
    } catch (error) {
      return `${name}: HTTP URL is invalid.`;
    }
    const bearerTokenEnvVar = normalizeText(server?.bearerTokenEnvVar || "");
    if (bearerTokenEnvVar && !envNamePattern.test(bearerTokenEnvVar)) {
      return `${name}: bearer token env var is invalid.`;
    }
    for (const entry of server?.headerEnvVars || []) {
      const envName = normalizeText(entry.value);
      if (envName && !envNamePattern.test(envName)) return `${name}: header env var ${envName} is invalid.`;
    }
  } else if (!normalizeText(server?.command)) {
    return `${name}: stdio command is required.`;
  }
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1) return `${name}: tool timeout must be a positive integer.`;
  if (!Number.isInteger(connectTimeoutSeconds) || connectTimeoutSeconds < 1) return `${name}: connect timeout must be a positive integer.`;
  return "";
}

function validateMcpSettings(settings) {
  const servers = Array.isArray(settings?.servers) ? settings.servers : [];
  for (const server of servers) {
    const error = validateMcpServer(server);
    if (error) return error;
  }
  return "";
}

async function saveMcpSettings() {
  const settings = state.mcpSettings || normalizeMcpSettings({});
  const validationError = validateMcpSettings(settings);
  if (validationError) {
    state.mcpTestResult = null;
    renderMcpSettingsDialog();
    setMcpSettingsError(validationError, "Settings validation failed");
    return;
  }
  elements.saveMcpSettings.disabled = true;
  try {
    const payload = await fetchJson("/api/settings/mcp", {
      method: "POST",
      body: { servers: settings.servers.map(mcpServerForSave) }
    });
    state.mcpSettings = normalizeMcpSettings(payload);
    state.mcpSettingsBaseline = cloneMcpSettings(state.mcpSettings);
    state.mcpRuntimePreviewDirty = false;
    setMcpSettingsError("");
    closeMcpSettingsDialog();
  } catch (error) {
    setMcpSettingsError(mcpRequestErrorMessage(error, "Could not save MCP settings."), "Save failed");
    console.error(error);
  } finally {
    elements.saveMcpSettings.disabled = false;
  }
}

async function testMcpServer(id) {
  const server = (state.mcpSettings || normalizeMcpSettings({})).servers.find((entry) => entry.id === id);
  if (!server) return;
  const validationError = validateMcpServer(server);
  if (validationError) {
    state.mcpTestResult = { id, success: false, error: validationError, toolCount: 0, tools: [] };
    setMcpActionError("test", id, validationError, "Connection failed");
    setMcpSettingsError("");
    renderMcpSettingsDialog();
    return;
  }
  state.mcpTestingId = id;
  state.mcpTestResult = null;
  clearMcpActionError("test", id);
  setMcpSettingsError("");
  renderMcpSettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/mcp/test", {
      method: "POST",
      body: mcpServerForSave(server)
    });
    state.mcpTestResult = {
      id,
      success: payload?.success !== false,
      error: normalizeText(payload?.error || ""),
      toolCount: Number(payload?.toolCount) || 0,
      tools: Array.isArray(payload?.tools) ? payload.tools.map(normalizeMcpToolSummary) : [],
      runtimeWarnings: normalizeMcpRuntimeWarnings(payload?.runtimeWarnings),
      securityWarnings: normalizeMcpSecurityWarnings(payload?.securityWarnings)
    };
    if (state.mcpTestResult.success === false) {
      setMcpActionError("test", id, state.mcpTestResult.error || "MCP test failed.", "Connection failed");
    } else {
      clearMcpActionError("test", id);
    }
  } catch (error) {
    const message = mcpRequestErrorMessage(error, "MCP test failed.");
    state.mcpTestResult = { id, success: false, error: message, toolCount: 0, tools: [] };
    setMcpActionError("test", id, message, "Connection failed");
  } finally {
    state.mcpTestingId = "";
    renderMcpSettingsDialog();
  }
}

async function connectMcpServer(id) {
  if (!id || state.mcpOperationId) return;
  const settings = state.mcpSettings || normalizeMcpSettings({});
  const server = settings.servers.find((entry) => entry.id === id);
  if (!server) return;
  const validationError = validateMcpServer(server);
  if (validationError) {
    state.mcpTestResult = null;
    setMcpActionError("connect", id, validationError, "Connect failed");
    setMcpSettingsError("");
    renderMcpSettingsDialog();
    return;
  }
  state.mcpOperationId = `connect:${id}`;
  state.mcpLogResult = null;
  clearMcpActionError("connect", id);
  setMcpSettingsError("");
  renderMcpSettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/mcp/connect", {
      method: "POST",
      body: {
        serverId: id,
        servers: settings.servers.map(mcpServerForSave),
        persist: false
      }
    });
    if (payload?.success === false) {
      setMcpActionError("connect", id, payload.error || "Could not connect MCP server.", "Connect failed");
      return;
    }
    state.mcpSettings = normalizeMcpSettings(payload);
    state.mcpEditingId = id;
    state.mcpRuntimePreviewDirty = true;
    state.mcpTestResult = null;
    clearMcpActionError("connect", id);
  } catch (error) {
    setMcpActionError("connect", id, mcpRequestErrorMessage(error, "Could not connect MCP server."), "Connect failed");
  } finally {
    state.mcpOperationId = "";
    renderMcpSettingsDialog();
  }
}

async function restoreMcpRuntimeFromBaseline() {
  if (!state.mcpRuntimePreviewDirty) return;
  const baseline = cloneMcpSettings(state.mcpSettingsBaseline || normalizeMcpSettings({}));
  state.mcpRuntimePreviewDirty = false;
  try {
    await fetchJson("/api/settings/mcp/connect", {
      method: "POST",
      body: {
        serverId: state.mcpEditingId || "",
        servers: baseline.servers.map(mcpServerForSave),
        persist: false
      }
    });
    state.mcpSettings = baseline;
  } catch (error) {
    console.error("Could not restore MCP runtime state.", error);
  }
}

async function reconnectMcpServer(id) {
  if (!id || state.mcpOperationId) return;
  const settings = state.mcpSettings || normalizeMcpSettings({});
  const server = settings.servers.find((entry) => entry.id === id);
  if (!server) return;
  const validationError = validateMcpServer(server);
  if (validationError) {
    setMcpActionError("reconnect", id, validationError, "Reconnect failed");
    setMcpSettingsError("");
    renderMcpSettingsDialog();
    return;
  }
  state.mcpOperationId = `reconnect:${id}`;
  state.mcpLogResult = null;
  clearMcpActionError("reconnect", id);
  setMcpSettingsError("");
  renderMcpSettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/mcp/connect", {
      method: "POST",
      body: {
        serverId: id,
        servers: settings.servers.map(mcpServerForSave),
        persist: false
      }
    });
    if (payload?.success === false) {
      setMcpActionError("reconnect", id, payload.error || "Could not reconnect MCP server.", "Reconnect failed");
      return;
    }
    state.mcpSettings = normalizeMcpSettings(payload);
    state.mcpEditingId = id;
    state.mcpRuntimePreviewDirty = true;
    state.mcpTestResult = null;
    clearMcpActionError("reconnect", id);
  } catch (error) {
    setMcpActionError("reconnect", id, mcpRequestErrorMessage(error, "Could not reconnect MCP server."), "Reconnect failed");
  } finally {
    state.mcpOperationId = "";
    renderMcpSettingsDialog();
  }
}

async function resetMcpCircuit(id) {
  if (!id || state.mcpOperationId) return;
  state.mcpOperationId = `reset:${id}`;
  state.mcpLogResult = null;
  clearMcpActionError("reset", id);
  setMcpSettingsError("");
  renderMcpSettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/mcp/reset-circuit", {
      method: "POST",
      body: { serverId: id }
    });
    if (payload?.success === false) {
      setMcpActionError("reset", id, payload.error || "Could not reset MCP circuit.", "Reset failed");
      return;
    }
    clearMcpActionError("reset", id);
    await loadMcpSettings();
  } catch (error) {
    setMcpActionError("reset", id, mcpRequestErrorMessage(error, "Could not reset MCP circuit."), "Reset failed");
  } finally {
    state.mcpOperationId = "";
    renderMcpSettingsDialog();
  }
}

async function viewMcpStderrLog(id) {
  if (!id || state.mcpOperationId) return;
  state.mcpOperationId = `log:${id}`;
  clearMcpActionError("log", id);
  setMcpSettingsError("");
  renderMcpSettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/mcp/stderr-log?maxChars=60000");
    state.mcpLogResult = {
      serverId: id,
      success: payload?.success !== false,
      log: normalizeText(payload?.log || ""),
      error: normalizeText(payload?.error || ""),
      truncated: Boolean(payload?.truncated)
    };
    if (state.mcpLogResult.success === false) {
      setMcpActionError("log", id, state.mcpLogResult.error || "Could not read MCP stderr log.", "Log unavailable");
    } else {
      clearMcpActionError("log", id);
    }
  } catch (error) {
    const message = mcpRequestErrorMessage(error, "Could not read MCP stderr log.");
    state.mcpLogResult = {
      serverId: id,
      success: false,
      log: "",
      error: message,
      truncated: false
    };
    setMcpActionError("log", id, message, "Log unavailable");
  } finally {
    state.mcpOperationId = "";
    renderMcpSettingsDialog();
  }
}
