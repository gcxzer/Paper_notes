function normalizeSkillSummary(skill) {
  return {
    name: normalizeText(skill?.name),
    description: normalizeText(skill?.description),
    category: normalizeText(skill?.category),
    path: normalizeText(skill?.path),
    source: normalizeText(skill?.source),
    enabled: skill?.enabled !== false
  };
}

function normalizeSkillNameList(value) {
  const entries = typeof value === "string"
    ? value.replace(/,/g, "\n").split(/\r?\n/)
    : Array.isArray(value) ? value : [];
  const names = [];
  const seen = new Set();
  entries.forEach((entry) => {
    const name = normalizeText(entry);
    if (!name || seen.has(name)) return;
    seen.add(name);
    names.push(name);
  });
  return names;
}

function normalizeSkillsSettings(payload) {
  const disabledFromPayload = normalizeSkillNameList(payload?.disabledSkills || payload?.disabled_skills);
  const disabledSet = new Set(disabledFromPayload);
  const skills = Array.isArray(payload?.skills)
    ? payload.skills.map(normalizeSkillSummary).filter((skill) => skill.name)
      .map((skill) => ({ ...skill, enabled: disabledSet.has(skill.name) ? false : skill.enabled }))
    : [];
  const disabledSkills = normalizeSkillNameList([
    ...disabledFromPayload,
    ...skills.filter((skill) => skill.enabled === false).map((skill) => skill.name)
  ]);
  const externalDirectories = Array.isArray(payload?.externalDirectories || payload?.external_directories)
    ? (payload.externalDirectories || payload.external_directories).map((entry) => {
      if (typeof entry === "string") {
        return { path: normalizeText(entry), exists: true };
      }
      return {
        path: normalizeText(entry?.path),
        exists: entry?.exists !== false
      };
    }).filter((entry) => entry.path)
    : [];
  return {
    success: payload?.success !== false,
    skills,
    categories: Array.isArray(payload?.categories) ? payload.categories.map(normalizeText).filter(Boolean) : [],
    count: Number(payload?.count) || skills.length,
    disabledSkills,
    message: normalizeText(payload?.message),
    hint: normalizeText(payload?.hint),
    uiHint: normalizeText(payload?.uiHint || payload?.ui_hint),
    roots: Array.isArray(payload?.roots) ? payload.roots.map(normalizeText).filter(Boolean) : [],
    defaultRoots: Array.isArray(payload?.defaultRoots || payload?.default_roots)
      ? (payload.defaultRoots || payload.default_roots).map(normalizeText).filter(Boolean)
      : [],
    externalDirectories,
    settingsPath: normalizeText(payload?.settingsPath || payload?.settings_path)
  };
}

function normalizeSkillDetail(payload) {
  const linkedFilesSource = payload?.linked_files || payload?.linkedFiles;
  const linkedFiles = linkedFilesSource && typeof linkedFilesSource === "object" ? linkedFilesSource : {};
  const availableFilesSource = payload?.available_files || payload?.availableFiles;
  return {
    success: payload?.success !== false,
    name: normalizeText(payload?.name),
    description: normalizeText(payload?.description),
    category: normalizeText(payload?.category),
    tags: Array.isArray(payload?.tags) ? payload.tags.map(normalizeText).filter(Boolean) : [],
    relatedSkills: Array.isArray(payload?.related_skills || payload?.relatedSkills)
      ? (payload.related_skills || payload.relatedSkills).map(normalizeText).filter(Boolean)
      : [],
    content: normalizeText(payload?.content),
    path: normalizeText(payload?.path),
    skillDir: normalizeText(payload?.skill_dir || payload?.skillDir),
    source: normalizeText(payload?.source),
    enabled: payload?.enabled !== false,
    linkedFiles,
    usageHint: normalizeText(payload?.usage_hint || payload?.usageHint),
    readinessStatus: normalizeText(payload?.readiness_status || payload?.readinessStatus || "available"),
    setupNeeded: Boolean(payload?.setup_needed || payload?.setupNeeded),
    setupSkipped: Boolean(payload?.setup_skipped || payload?.setupSkipped),
    requiredEnvironmentVariables: Array.isArray(payload?.required_environment_variables || payload?.requiredEnvironmentVariables)
      ? (payload.required_environment_variables || payload.requiredEnvironmentVariables)
      : [],
    requiredCommands: Array.isArray(payload?.required_commands || payload?.requiredCommands)
      ? (payload.required_commands || payload.requiredCommands).map(normalizeText).filter(Boolean)
      : [],
    missingRequiredEnvironmentVariables: Array.isArray(payload?.missing_required_environment_variables || payload?.missingRequiredEnvironmentVariables)
      ? (payload.missing_required_environment_variables || payload.missingRequiredEnvironmentVariables).map(normalizeText).filter(Boolean)
      : [],
    missingRequiredCommands: Array.isArray(payload?.missing_required_commands || payload?.missingRequiredCommands)
      ? (payload.missing_required_commands || payload.missingRequiredCommands).map(normalizeText).filter(Boolean)
      : [],
    isBinary: Boolean(payload?.is_binary || payload?.isBinary),
    mimeType: normalizeText(payload?.mime_type || payload?.content_type),
    filePath: normalizeText(payload?.file_path || payload?.filePath),
    error: normalizeText(payload?.error),
    hint: normalizeText(payload?.hint),
    availableFiles: availableFilesSource && typeof availableFilesSource === "object" ? availableFilesSource : null
  };
}

function setSkillsSettingsError(message = "") {
  elements.skillsSettingsError.textContent = message;
  elements.skillsSettingsError.hidden = !message;
}

function setSkillsExternalError(message = "") {
  if (!elements.skillsExternalError) return;
  elements.skillsExternalError.textContent = message;
  elements.skillsExternalError.hidden = !message;
}

function skillStatusLabel(detail) {
  if (!detail) return "";
  if (detail.readinessStatus === "setup_needed") return "Setup needed";
  if (detail.readinessStatus === "unsupported") return "Unsupported";
  if (detail.isBinary) return "Binary file";
  return "Available";
}

function skillEnabledStatus(skill) {
  return skill?.enabled === false ? "Off" : "Ready";
}

function renderSkillMetaPills(values, emptyLabel = "") {
  const normalized = (values || []).map(normalizeText).filter(Boolean);
  if (!normalized.length && !emptyLabel) return "";
  if (!normalized.length) return `<span class="skill-meta-pill">${escapeHtml(emptyLabel)}</span>`;
  return normalized.map((value) => `<span class="skill-meta-pill">${escapeHtml(value)}</span>`).join("");
}

function basename(path) {
  const parts = normalizeText(path).split("/").filter(Boolean);
  return parts.at(-1) || normalizeText(path);
}

function skillListSubtitle(skill) {
  return normalizeText(skill.category || skill.source || basename(skill.path) || "local");
}

function currentDisabledSkillNames() {
  const settings = state.skillsSettings || normalizeSkillsSettings({});
  return normalizeSkillNameList([
    ...(settings.disabledSkills || []),
    ...((settings.skills || []).filter((skill) => skill.enabled === false).map((skill) => skill.name))
  ]);
}

function currentSkillSummary(name) {
  const normalizedName = normalizeText(name);
  const settings = state.skillsSettings || normalizeSkillsSettings({});
  return (settings.skills || []).find((skill) => skill.name === normalizedName) || null;
}

function setSkillEnabled(name, enabled) {
  const normalizedName = normalizeText(name);
  if (!normalizedName) return;
  const settings = normalizeSkillsSettings(state.skillsSettings || {});
  const disabled = new Set(currentDisabledSkillNames());
  if (enabled) disabled.delete(normalizedName);
  else disabled.add(normalizedName);
  state.skillsSettings = {
    ...settings,
    disabledSkills: Array.from(disabled),
    skills: (settings.skills || []).map((skill) => (
      skill.name === normalizedName ? { ...skill, enabled } : skill
    ))
  };
  if (normalizeSkillDetail(state.selectedSkillDetail).name === normalizedName) {
    state.selectedSkillDetail = { ...(state.selectedSkillDetail || {}), enabled };
  }
  renderSkillsSettingsDialog();
}

function filterSkills(skills) {
  const query = normalizeText(state.skillsSearchQuery).toLowerCase();
  if (!query) return skills;
  return (skills || []).filter((skill) => [
    skill.name,
    skill.description,
    skill.category,
    skill.source,
    skill.path
  ].some((value) => normalizeText(value).toLowerCase().includes(query)));
}

function stripMarkdownFrontmatter(content) {
  const text = String(content || "");
  if (!text.startsWith("---")) return text;
  const match = text.match(/^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/);
  return match ? text.slice(match[0].length).trimStart() : text;
}

function stripLeadingMarkdownHeading(content) {
  return String(content || "").replace(/^\s*#\s+[^\n]+(?:\r?\n)+/, "").trimStart();
}

function leadingMarkdownHeading(content) {
  const match = String(content || "").match(/^\s*#\s+([^\n]+)(?:\r?\n|$)/);
  return normalizeText(match?.[1]);
}

function renderLinkedSkillFiles(detail) {
  const linkedFiles = detail?.linkedFiles || {};
  const sections = ["references", "templates", "assets", "scripts"].map((group) => {
    const paths = Array.isArray(linkedFiles[group]) ? linkedFiles[group].map(normalizeText).filter(Boolean) : [];
    if (!paths.length) return "";
    return `
      <section class="skill-linked-group">
        <strong>${escapeHtml(group)}</strong>
        <div class="skill-linked-files">
          ${paths.map((path) => `
            <button class="skill-linked-file" type="button" data-skill-file="${escapeHtml(path)}">
              ${escapeHtml(basename(path))}
            </button>
          `).join("")}
        </div>
      </section>
    `;
  }).filter(Boolean);
  return sections.length ? `<div class="skill-linked-list">${sections.join("")}</div>` : "";
}

function renderAvailableSkillFiles(detail) {
  const available = detail?.availableFiles || {};
  const sections = Object.entries(available).map(([group, paths]) => {
    const normalizedPaths = Array.isArray(paths) ? paths.map(normalizeText).filter(Boolean) : [];
    if (!normalizedPaths.length) return "";
    return `
      <section class="skill-linked-group">
        <strong>${escapeHtml(group)}</strong>
        <div class="skill-linked-files">
          ${normalizedPaths.map((path) => `
            <button class="skill-linked-file" type="button" data-skill-file="${escapeHtml(path)}">
              ${escapeHtml(basename(path))}
            </button>
          `).join("")}
        </div>
      </section>
    `;
  }).filter(Boolean);
  return sections.length ? `<div class="skill-linked-list">${sections.join("")}</div>` : "";
}

function renderSkillEditForm(detail, content) {
  return `
    <form id="skillEditForm" class="skill-edit-form" data-skill-edit-form>
      <label class="skill-edit-field skill-edit-field-content">
        <span>Instructions</span>
        <textarea name="content" spellcheck="true"${state.skillEditSaving ? " disabled" : ""}>${escapeHtml(content || "")}</textarea>
      </label>
      <div class="skill-edit-actions">
        <button class="toolbar-button" type="button" data-skill-edit-cancel${state.skillEditSaving ? " disabled" : ""}>Cancel</button>
        <button class="toolbar-button toolbar-button-primary" type="submit"${state.skillEditSaving ? " disabled" : ""}>${state.skillEditSaving ? "Saving" : "Save"}</button>
      </div>
    </form>
  `;
}

function renderSkillDetail() {
  if (!elements.skillsSettingsDetail) return;
  elements.skillsSettingsDetail.classList.remove("is-editing");
  const detail = state.selectedSkillDetail ? normalizeSkillDetail(state.selectedSkillDetail) : null;
  if (state.skillDetailLoading) {
    elements.skillsSettingsDetail.innerHTML = `<p class="memory-empty">Loading skill...</p>`;
    return;
  }
  if (!detail) {
    elements.skillsSettingsDetail.innerHTML = `<p class="memory-empty">Select a skill to view its instructions.</p>`;
    return;
  }
  if (!detail.success) {
    elements.skillsSettingsDetail.innerHTML = `
      <div class="skill-detail-header">
      <div>
        <strong>${escapeHtml(detail.name || state.selectedSkillName || "Skill")}</strong>
        <span>${escapeHtml(detail.error || "Skill could not be loaded.")}</span>
      </div>
    </div>
      ${detail.hint ? `<p class="settings-hint">${escapeHtml(detail.hint)}</p>` : ""}
      ${renderAvailableSkillFiles(detail)}
    `;
    return;
  }
  const envNames = detail.requiredEnvironmentVariables
    .map((entry) => normalizeText(entry?.name || entry))
    .filter(Boolean);
  const activeFile = detail.filePath || state.selectedSkillFilePath;
  const rawContent = detail.isBinary
    ? `Binary file${detail.mimeType ? ` (${detail.mimeType})` : ""}.`
    : stripMarkdownFrontmatter(detail.content);
  const isEditableSkill = !activeFile && !detail.isBinary;
  const isEditing = isEditableSkill && state.skillEditingName === detail.name;
  const content = detail.isBinary || isEditing ? rawContent : stripLeadingMarkdownHeading(rawContent);
  const displayTitle = activeFile ? basename(activeFile) : leadingMarkdownHeading(rawContent) || detail.name || "Skill";
  elements.skillsSettingsDetail.classList.toggle("is-editing", isEditing);
  const skillEnabled = detail.enabled !== false;
  const setupNote = detail.missingRequiredEnvironmentVariables.length || detail.missingRequiredCommands.length ? `
    <p class="skill-setup-note">Missing setup: ${escapeHtml([...detail.missingRequiredEnvironmentVariables, ...detail.missingRequiredCommands].join(", "))}</p>
  ` : "";
  elements.skillsSettingsDetail.innerHTML = `
    <div class="skill-detail-header">
      <div>
        <div class="skill-detail-title-row">
          <strong>${escapeHtml(displayTitle)}</strong>
          ${!activeFile ? `
            <label class="mcp-switch skill-enabled-switch">
              <input type="checkbox" data-skill-enabled="${escapeHtml(detail.name)}"${skillEnabled ? " checked" : ""}${state.skillsSettingsSaving ? " disabled" : ""}>
              <span aria-hidden="true"></span>
              <em>${skillEnabled ? "Enabled" : "Off"}</em>
            </label>
          ` : ""}
        </div>
        ${isEditing ? `
          <textarea class="skill-description-edit" name="description" form="skillEditForm" rows="3" spellcheck="true"${state.skillEditSaving ? " disabled" : ""}>${escapeHtml(detail.description || "")}</textarea>
        ` : `
          <span>${escapeHtml(detail.description || detail.path || "")}</span>
        `}
      </div>
      ${isEditableSkill && !isEditing ? `
        <button class="toolbar-button" type="button" data-skill-edit-start>Edit</button>
      ` : ""}
    </div>
    <div class="skill-detail-body">
      ${setupNote}
      ${isEditing ? renderSkillEditForm(detail, content) : `
        ${renderLinkedSkillFiles(detail)}
        <section class="skill-content-section">
          <div class="skill-content">${renderLinkedText(content || "")}</div>
        </section>
      `}
    </div>
  `;
}

function renderSkillsSettingsDialog() {
  if (!elements.skillsSettingsDialog) return;
  const settings = state.skillsSettings || normalizeSkillsSettings({});
  const skills = settings.skills || [];
  const visibleSkills = filterSkills(skills);
  elements.skillsSettingsCount.textContent = state.skillsSettingsLoading
    ? "Loading skills..."
    : `${settings.count || skills.length} ${(settings.count || skills.length) === 1 ? "skill" : "skills"}`;
  elements.skillsSettingsSource.textContent = "Skill folders: .paper-notes/skills, src/skills, and external directories.";
  elements.refreshSkillsSettings.disabled = state.skillsSettingsLoading;
  elements.addExternalSkillDirectory.disabled = state.skillsSettingsLoading || state.skillsSettingsSaving;
  elements.saveSkillsSettings.disabled = state.skillsSettingsLoading || state.skillsSettingsSaving || state.skillEditSaving;
  elements.saveSkillsSettings.textContent = state.skillsSettingsSaving ? "Saving" : "Save";
  if (elements.skillsSearchInput && elements.skillsSearchInput.value !== state.skillsSearchQuery) {
    elements.skillsSearchInput.value = state.skillsSearchQuery;
  }
  renderExternalSkillDirectories(settings);

  if (state.skillsSettingsLoading) {
    elements.skillsSettingsList.innerHTML = `<p class="memory-empty">Loading skills...</p>`;
    renderSkillDetail();
    return;
  }
  if (!skills.length) {
    elements.skillsSettingsList.innerHTML = `<p class="memory-empty">${escapeHtml(settings.message || "No skills found.")}</p>`;
    state.selectedSkillDetail = null;
    renderSkillDetail();
    return;
  }
  if (!visibleSkills.length) {
    elements.skillsSettingsList.innerHTML = `<p class="memory-empty">No matching skills.</p>`;
    renderSkillDetail();
    return;
  }
  elements.skillsSettingsList.innerHTML = visibleSkills.map((skill) => {
    const selected = skill.name === state.selectedSkillName;
    return `
      <button class="skill-list-item${selected ? " is-active" : ""}" type="button" data-skill-name="${escapeHtml(skill.name)}">
        <span class="skill-list-title-row">
          <strong>${escapeHtml(skill.name)}</strong>
          <small class="skill-list-status${skill.enabled === false ? " is-off" : ""}">${escapeHtml(skillEnabledStatus(skill))}</small>
        </span>
        <span>${escapeHtml(skillListSubtitle(skill))}</span>
      </button>
    `;
  }).join("");
  renderSkillDetail();
}

function renderExternalSkillDirectories(settings = state.skillsSettings || normalizeSkillsSettings({})) {
  if (!elements.externalSkillDirectoryList) return;
  const directories = settings.externalDirectories || [];
  if (!directories.length) {
    elements.externalSkillDirectoryList.innerHTML = `<p class="skills-external-empty">None</p>`;
    return;
  }
  elements.externalSkillDirectoryList.innerHTML = directories.map((entry) => `
    <div class="skills-external-row${entry.exists ? "" : " is-missing"}">
      <span title="${escapeHtml(entry.path)}">${escapeHtml(entry.path)}</span>
      <small>${entry.exists ? "Found" : "Missing"}</small>
      <button class="toolbar-button" type="button" data-external-skill-directory-remove="${escapeHtml(entry.path)}"${state.skillsSettingsSaving ? " disabled" : ""}>Remove</button>
    </div>
  `).join("");
}

async function saveExternalSkillDirectories(paths) {
  state.skillsSettingsSaving = true;
  renderSkillsSettingsDialog();
  try {
    const payload = await fetchJson("/api/skills/settings", {
      method: "POST",
      body: { externalDirectories: paths, disabledSkills: currentDisabledSkillNames() }
    });
    state.skillsSettings = normalizeSkillsSettings({
      ...(state.skillsSettings || {}),
      ...payload
    });
    setSkillsSettingsError("");
    setSkillsExternalError("");
    await loadSkillsSettings();
  } catch (error) {
    setSkillsSettingsError(error.message || "Could not save skill directories.");
    console.error(error);
  } finally {
    state.skillsSettingsSaving = false;
    renderSkillsSettingsDialog();
  }
}

function currentExternalSkillDirectoryPaths() {
  const settings = state.skillsSettings || normalizeSkillsSettings({});
  return (settings.externalDirectories || []).map((entry) => entry.path).filter(Boolean);
}

async function saveSkillSettingsPayload() {
  state.skillsSettingsSaving = true;
  renderSkillsSettingsDialog();
  try {
    const payload = await fetchJson("/api/skills/settings", {
      method: "POST",
      body: {
        externalDirectories: currentExternalSkillDirectoryPaths(),
        disabledSkills: currentDisabledSkillNames()
      }
    });
    state.skillsSettings = normalizeSkillsSettings({
      ...(state.skillsSettings || {}),
      ...payload
    });
    setSkillsSettingsError("");
    setSkillsExternalError("");
    return true;
  } catch (error) {
    setSkillsSettingsError(error.message || "Could not save skills settings.");
    console.error(error);
    return false;
  } finally {
    state.skillsSettingsSaving = false;
    renderSkillsSettingsDialog();
  }
}

async function addExternalSkillDirectory() {
  const path = normalizeText(elements.externalSkillDirectoryInput?.value);
  if (!path) {
    setSkillsExternalError("Directory path is required.");
    return;
  }
  setSkillsExternalError("");
  const paths = currentExternalSkillDirectoryPaths();
  if (!paths.includes(path)) {
    paths.push(path);
  }
  elements.externalSkillDirectoryInput.value = "";
  await saveExternalSkillDirectories(paths);
}

async function removeExternalSkillDirectory(path) {
  const target = normalizeText(path);
  if (!target) return;
  await saveExternalSkillDirectories(currentExternalSkillDirectoryPaths().filter((entry) => entry !== target));
}

async function loadSkillDetail(name, filePath = "") {
  const normalizedName = normalizeText(name);
  if (!normalizedName) return;
  if (state.selectedSkillName !== normalizedName || normalizeText(filePath)) {
    state.skillEditingName = "";
  }
  state.selectedSkillName = normalizedName;
  state.selectedSkillFilePath = normalizeText(filePath);
  state.skillDetailLoading = true;
  renderSkillsSettingsDialog();
  try {
    const params = new URLSearchParams({ name: normalizedName });
    if (state.selectedSkillFilePath) params.set("filePath", state.selectedSkillFilePath);
    const payload = await fetchJson(`/api/skills/view?${params.toString()}`);
    const summary = currentSkillSummary(normalizedName);
    state.selectedSkillDetail = normalizeSkillDetail({
      ...payload,
      name: payload.name || normalizedName,
      enabled: payload.enabled ?? summary?.enabled,
      file_path: state.selectedSkillFilePath || payload.file_path
    });
    setSkillsSettingsError("");
  } catch (error) {
    state.selectedSkillDetail = normalizeSkillDetail({
      success: false,
      name: normalizedName,
      file_path: state.selectedSkillFilePath,
      error: error.message || "Could not load skill."
    });
    setSkillsSettingsError(error.message || "Could not load skill.");
    console.error(error);
  } finally {
    state.skillDetailLoading = false;
    renderSkillsSettingsDialog();
  }
}

async function saveSkillEdit(form) {
  if (!form || !state.selectedSkillName || state.selectedSkillFilePath) return false;
  const formData = new FormData(form);
  state.skillEditSaving = true;
  renderSkillDetail();
  try {
    const payload = await fetchJson("/api/skills/update", {
      method: "POST",
      body: {
        name: state.selectedSkillName,
        description: normalizeText(formData.get("description")),
        content: String(formData.get("content") || "")
      }
    });
    state.selectedSkillDetail = normalizeSkillDetail(payload);
    state.skillEditingName = "";
    const disabledSkills = currentDisabledSkillNames();
    const settingsPayload = await fetchJson("/api/skills");
    state.skillsSettings = normalizeSkillsSettings({ ...settingsPayload, disabledSkills });
    setSkillsSettingsError("");
    return true;
  } catch (error) {
    setSkillsSettingsError(error.message || "Could not save skill.");
    return false;
  } finally {
    state.skillEditSaving = false;
    renderSkillsSettingsDialog();
  }
}

async function saveSkillsSettingsDialog() {
  const editForm = elements.skillsSettingsDetail?.querySelector("[data-skill-edit-form]");
  if (editForm) {
    const saved = await saveSkillEdit(editForm);
    if (!saved) return;
  }
  const settingsSaved = await saveSkillSettingsPayload();
  if (!settingsSaved) return;
  closeSkillsSettingsDialog();
}

async function loadSkillsSettings() {
  state.skillsSettingsLoading = true;
  renderSkillsSettingsDialog();
  try {
    const payload = await fetchJson("/api/skills");
    state.skillsSettings = normalizeSkillsSettings(payload);
    setSkillsSettingsError("");
    const skills = state.skillsSettings.skills || [];
    const selectedExists = skills.some((skill) => skill.name === state.selectedSkillName);
    const nextSkill = selectedExists ? state.selectedSkillName : skills[0]?.name || "";
    if (nextSkill) {
      await loadSkillDetail(nextSkill);
    } else {
      state.selectedSkillName = "";
      state.selectedSkillFilePath = "";
      state.selectedSkillDetail = null;
    }
  } catch (error) {
    setSkillsSettingsError(error.message || "Could not load skills.");
    console.error(error);
  } finally {
    state.skillsSettingsLoading = false;
    renderSkillsSettingsDialog();
  }
}

async function openSkillsSettingsDialog() {
  closeSettingsMenu();
  setSkillsSettingsError("");
  setSkillsExternalError("");
  state.skillEditingName = "";
  elements.skillsSettingsDialog.showModal();
  renderSkillsSettingsDialog();
  await loadSkillsSettings();
}

function closeSkillsSettingsDialog() {
  setSkillsSettingsError("");
  setSkillsExternalError("");
  state.skillEditingName = "";
  elements.skillsSettingsDialog.close();
  clearSettingsPanelUrl();
}
