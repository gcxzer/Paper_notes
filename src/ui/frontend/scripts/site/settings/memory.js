function normalizeMemoryFile(file, fallbackName) {
  const data = file && typeof file === "object" ? file : {};
  return {
    name: normalizeText(data.name || fallbackName),
    path: normalizeText(data.path),
    exists: data.exists !== false,
    content: typeof data.content === "string" ? data.content : normalizeText(data.content)
  };
}

function normalizeMemorySettings(payload) {
  const files = payload?.files && typeof payload.files === "object" ? payload.files : {};
  const systemFile = normalizeMemoryFile(files.system, "system.md");
  const userFile = normalizeMemoryFile(files.user, "user.md");
  const system = typeof payload?.system === "string" ? payload.system : systemFile.content;
  const user = typeof payload?.user === "string" ? payload.user : userFile.content;
  return {
    success: payload?.success !== false,
    memoryDir: normalizeText(payload?.memoryDir || payload?.memory_dir || ".paper-notes/memory"),
    system,
    user,
    files: {
      system: { ...systemFile, content: system },
      user: { ...userFile, content: user }
    }
  };
}

function memorySettingsSnapshot(settings) {
  const normalized = normalizeMemorySettings(settings || {});
  return {
    system: normalized.system || "",
    user: normalized.user || ""
  };
}

function memorySettingsPayloadFromInputs() {
  return {
    system: elements.memorySystemInput?.value || "",
    user: elements.memoryUserInput?.value || ""
  };
}

function memorySettingsChanged() {
  const baseline = state.memorySettingsBaseline || { system: "", user: "" };
  const current = memorySettingsPayloadFromInputs();
  return current.system !== baseline.system || current.user !== baseline.user;
}

function setMemorySettingsError(message = "") {
  if (!elements.memorySettingsError) return;
  elements.memorySettingsError.textContent = message;
  elements.memorySettingsError.hidden = !message;
}

function setMemorySettingsStatus(message = "") {
  if (!elements.memorySettingsStatus) return;
  elements.memorySettingsStatus.textContent = message;
}

function syncMemorySettingsInputs(settings) {
  const normalized = normalizeMemorySettings(settings || {});
  if (elements.memorySystemInput) elements.memorySystemInput.value = normalized.system || "";
  if (elements.memoryUserInput) elements.memoryUserInput.value = normalized.user || "";
  if (elements.memorySystemPath) {
    elements.memorySystemPath.textContent = normalized.files.system.path || ".paper-notes/memory/system.md";
  }
  if (elements.memoryUserPath) {
    elements.memoryUserPath.textContent = normalized.files.user.path || ".paper-notes/memory/user.md";
  }
  if (elements.memorySettingsSource) {
    elements.memorySettingsSource.textContent = normalized.memoryDir;
  }
}

function renderMemorySettingsDialog() {
  const busy = Boolean(state.memorySettingsLoading || state.memorySettingsSaving);
  state.memorySettingsDirty = memorySettingsChanged();
  if (elements.memorySystemInput) elements.memorySystemInput.disabled = busy;
  if (elements.memoryUserInput) elements.memoryUserInput.disabled = busy;
  if (elements.refreshMemorySettings) elements.refreshMemorySettings.disabled = busy;
  if (elements.saveMemorySettings) {
    elements.saveMemorySettings.disabled = busy || !state.memorySettingsDirty;
    elements.saveMemorySettings.textContent = state.memorySettingsSaving ? "Saving..." : "Save";
  }
  if (state.memorySettingsLoading) setMemorySettingsStatus("Loading...");
  else if (state.memorySettingsSaving) setMemorySettingsStatus("Saving...");
  else if (state.memorySettingsDirty) setMemorySettingsStatus("Unsaved changes");
  else if (state.memorySettings) setMemorySettingsStatus("Saved");
  else setMemorySettingsStatus("");
}

function handleMemorySettingsInput() {
  state.memorySettings = {
    ...(state.memorySettings || normalizeMemorySettings({})),
    ...memorySettingsPayloadFromInputs()
  };
  setMemorySettingsError("");
  renderMemorySettingsDialog();
}

async function loadMemorySettings() {
  state.memorySettingsLoading = true;
  setMemorySettingsError("");
  renderMemorySettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/memory");
    state.memorySettings = normalizeMemorySettings(payload);
    state.memorySettingsBaseline = memorySettingsSnapshot(state.memorySettings);
    syncMemorySettingsInputs(state.memorySettings);
  } catch (error) {
    setMemorySettingsError(error.message || "Could not load memory settings.");
  } finally {
    state.memorySettingsLoading = false;
    renderMemorySettingsDialog();
  }
}

async function saveMemorySettings() {
  if (state.memorySettingsSaving) return;
  state.memorySettingsSaving = true;
  setMemorySettingsError("");
  renderMemorySettingsDialog();
  try {
    const payload = await fetchJson("/api/settings/memory", {
      method: "POST",
      body: memorySettingsPayloadFromInputs()
    });
    state.memorySettings = normalizeMemorySettings(payload);
    state.memorySettingsBaseline = memorySettingsSnapshot(state.memorySettings);
    syncMemorySettingsInputs(state.memorySettings);
  } catch (error) {
    setMemorySettingsError(error.message || "Could not save memory settings.");
  } finally {
    state.memorySettingsSaving = false;
    renderMemorySettingsDialog();
  }
}

async function openMemorySettingsDialog() {
  closeSettingsMenu();
  clearSettingsPanelUrl();
  setMemorySettingsError("");
  elements.memorySettingsDialog?.showModal();
  renderMemorySettingsDialog();
  await loadMemorySettings();
  elements.memorySystemInput?.focus();
}

function closeMemorySettingsDialog() {
  setMemorySettingsError("");
  if (elements.memorySettingsDialog?.open) {
    elements.memorySettingsDialog.close();
  }
  clearSettingsPanelUrl();
}
