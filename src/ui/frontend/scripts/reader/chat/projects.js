let readerProjectFlyoutCloseTimer = 0;

function normalizeReaderChatProject(rawProject) {
  const id = normalizeText(rawProject?.id || rawProject?.projectId || rawProject?.project_id);
  const name = normalizeText(rawProject?.name || rawProject?.title);
  if (!id || !name) return null;
  return {
    id,
    name,
    createdAt: normalizeText(rawProject?.createdAt || rawProject?.created_at),
    updatedAt: normalizeText(rawProject?.updatedAt || rawProject?.updated_at),
    order: Number(rawProject?.order) || 0,
  };
}

function normalizeReaderChatProjects(rawProjects) {
  return (Array.isArray(rawProjects) ? rawProjects : [])
    .map(normalizeReaderChatProject)
    .filter(Boolean)
    .sort((left, right) => (
      (left.order - right.order)
      || left.name.localeCompare(right.name)
      || left.id.localeCompare(right.id)
    ));
}

function readerProjectIcon(name, size = 15) {
  return window.paperIcons?.render?.(name, { size }) || "";
}

function readerChatProjectById(projectId) {
  const id = normalizeText(projectId);
  if (!id) return null;
  return readerState.chatProjects.find((project) => project.id === id) || null;
}

function readerChatProjectName(projectId) {
  return normalizeText(readerChatProjectById(projectId)?.name);
}

function readerSessionProjectId(session) {
  return normalizeText(session?.projectId || session?.metadata?.projectId || session?.metadata?.project_id);
}

function readerSessionProjectName(session) {
  return normalizeText(session?.projectName || session?.metadata?.projectName || session?.metadata?.project_name)
    || readerChatProjectName(readerSessionProjectId(session));
}

function enrichReaderSessionProject(session) {
  if (!session) return session;
  const projectId = readerSessionProjectId(session);
  if (projectId && !session.projectName) session.projectName = readerChatProjectName(projectId);
  return session;
}

function chatSessionMatchesProject(session) {
  const scopeId = normalizeText(readerState.chatProjectScopeId);
  if (!scopeId) return true;
  return readerSessionProjectId(session) === scopeId;
}

function readerProjectSessions(projectId) {
  const normalizedProjectId = normalizeText(projectId);
  if (!normalizedProjectId) return [];
  return readerState.chatSessions.filter((session) => (
    session?.state === "active" && readerSessionProjectId(session) === normalizedProjectId
  ));
}

function readerProjectSessionSummary(projectId) {
  const count = readerProjectSessions(projectId).length;
  if (readerState.chatSessionsLoading) return "Loading sessions";
  if (count === 0) return "No sessions yet";
  return `${count} session${count === 1 ? "" : "s"}`;
}

function renderReaderProjectSessions(project) {
  const sessions = readerProjectSessions(project.id);
  if (readerState.chatSessionsLoading) {
    return `<p class="ask-project-session-empty">Loading sessions...</p>`;
  }
  if (!sessions.length) {
    return `<p class="ask-project-session-empty">No sessions in this project</p>`;
  }
  return sessions.map((session) => {
    const paperLabel = typeof chatSessionPaperLabel === "function" ? chatSessionPaperLabel(session) : "";
    const timeText = typeof formatChatSessionTime === "function" ? formatChatSessionTime(session.updatedAt) : "";
    return `
      <button class="ask-project-session" type="button" data-project-session="${escapeHtml(session.id)}">
        <span class="ask-project-session-title">${escapeHtml(session.title || "New chat")}</span>
        <span class="ask-project-session-meta">${escapeHtml([timeText, paperLabel].filter(Boolean).join(" · "))}</span>
      </button>
    `;
  }).join("");
}

function renderReaderProjectRow(project, scopeId) {
  const projectId = escapeHtml(project.id);
  if (readerState.renamingChatProjectId === project.id) {
    return `
      <form class="ask-project-rename ask-session-rename-form" data-project-rename-form data-project-id="${projectId}">
        <label class="ask-session-rename-card ask-project-rename-card">
          <span class="sr-only">Project name</span>
          <input type="text" name="name" maxlength="80" autocomplete="off" value="${escapeHtml(project.name)}" aria-label="Project name">
          <button class="ask-session-save" type="submit" aria-label="Save project name">Save</button>
        </label>
      </form>
    `;
  }
  const isMenuOpen = readerState.openProjectActionMenuId === project.id;
  return `
    <div class="ask-project-group ${project.id === scopeId ? "is-active" : ""}">
      <div class="ask-project-row ${isMenuOpen ? "is-menu-open" : ""}" data-project-row="${projectId}">
        <button class="ask-project-option ${project.id === scopeId ? "is-active" : ""}" type="button" data-project-open="${projectId}" aria-haspopup="menu" aria-expanded="${String(readerState.expandedChatProjectId === project.id)}">
          <span class="ask-project-option-icon">${readerProjectIcon("folder", 15)}</span>
          <span class="ask-project-option-main">
            <strong>${escapeHtml(project.name)}</strong>
            <small>${escapeHtml(readerProjectSessionSummary(project.id))}</small>
          </span>
          <span class="ask-project-option-check">${readerProjectIcon("chevron-right", 15)}</span>
        </button>
        <button class="ask-project-more" type="button" data-project-menu="${projectId}" aria-label="More actions for project ${escapeHtml(project.name)}" aria-haspopup="menu" aria-expanded="${String(isMenuOpen)}">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <circle cx="6.5" cy="12" r="1.9"></circle>
            <circle cx="12" cy="12" r="1.9"></circle>
            <circle cx="17.5" cy="12" r="1.9"></circle>
          </svg>
        </button>
      </div>
    </div>
  `;
}

function addProjectMenuOption(menu, {
  className = "",
  text = "",
  ariaLabel = "",
  onClick = () => {},
}) {
  return addReaderActionMenuOption(menu, { className, text, ariaLabel, onClick });
}

function populateProjectActionMenu(menu, project) {
  const isConfirmingDelete = readerState.confirmingDeleteChatProjectId === project.id;
  addProjectMenuOption(menu, {
    text: "Rename",
    ariaLabel: `Rename project ${project.name}`,
    onClick: () => {
      readerState.renamingChatProjectId = project.id;
      readerState.confirmingDeleteChatProjectId = "";
      readerState.openProjectActionMenuId = "";
      renderReaderProjectControls();
      requestAnimationFrame(() => elements.readerProjectPopover?.querySelector(".ask-project-rename input")?.focus());
    },
  });
  addProjectMenuOption(menu, {
    className: "ask-project-delete",
    text: isConfirmingDelete ? "Confirm delete" : "Delete",
    ariaLabel: `${isConfirmingDelete ? "Confirm delete" : "Delete"} project ${project.name}`,
    onClick: () => {
      if (readerState.confirmingDeleteChatProjectId === project.id) {
        void deleteReaderChatProject(project.id);
        return;
      }
      readerState.confirmingDeleteChatProjectId = project.id;
      readerState.openProjectActionMenuId = project.id;
      readerState.renamingChatProjectId = "";
      renderReaderProjectControls();
    },
  });
}

function positionProjectActionMenu(menu, row) {
  positionReaderActionMenu(menu, row, {
    popover: elements.readerProjectPopover,
    buttonSelector: ".ask-project-more",
    gap: 8,
  });
}

function appendProjectFloatingActionMenu() {
  const projectId = normalizeText(readerState.openProjectActionMenuId);
  const project = readerChatProjectById(projectId);
  if (!elements.readerProjectPopover || !project) return;
  const row = Array.from(elements.readerProjectPopover.querySelectorAll("[data-project-row]"))
    .find((element) => normalizeText(element.dataset.projectRow) === projectId);
  if (!row) return;
  const menu = document.createElement("div");
  menu.className = "ask-session-action-menu ask-project-action-menu";
  menu.setAttribute("role", "menu");
  menu.style.visibility = "hidden";
  populateProjectActionMenu(menu, project);
  elements.readerProjectPopover.appendChild(menu);
  positionProjectActionMenu(menu, row);
}

function renderReaderProjectButton() {
  if (!elements.readerProjectButton) return;
  elements.readerProjectButton.innerHTML = `
    ${readerProjectIcon("more-horizontal", 17)}
  `;
  elements.readerProjectButton.setAttribute("aria-expanded", String(readerState.chatProjectMenuOpen));
  elements.readerProjectButton.setAttribute("aria-label", "Project menu");
  elements.readerProjectButton.title = "Project menu";
}

function renderReaderProjectEmptyState() {
  return `
    <div class="ask-project-empty-state">
      <span class="ask-project-empty-icon">${readerProjectIcon("folder-plus", 16)}</span>
      <span>Create a project to group Ask sessions.</span>
    </div>
  `;
}

function renderReaderProjectCreateForm() {
  const draftValue = escapeHtml(readerState.chatProjectCreateDraft || "");
  return `
    <form class="ask-project-create" data-project-create>
      <label>
        <span class="sr-only">New project name</span>
        <input id="readerProjectCreateInput" type="text" name="name" maxlength="80" autocomplete="off" placeholder="New project" value="${draftValue}">
      </label>
      <button type="submit" aria-label="Create project">${readerProjectIcon("plus", 15)}</button>
    </form>
  `;
}

function renderReaderProjectSubmenu(project) {
  return `
    <div class="ask-project-flyout" data-project-flyout="${escapeHtml(project.id)}" role="menu" aria-label="${escapeHtml(project.name)} sessions">
      <div class="ask-project-session-list is-submenu">
        ${renderReaderProjectSessions(project)}
      </div>
    </div>
  `;
}

function showReaderProjectFlyout(projectId) {
  const nextProjectId = normalizeText(projectId);
  if (!nextProjectId) return;
  readerState.chatProjectMenuOpen = true;
  const changedProject = readerState.expandedChatProjectId !== nextProjectId;
  readerState.expandedChatProjectId = nextProjectId;
  readerState.openProjectActionMenuId = "";
  readerState.renamingChatProjectId = "";
  readerState.confirmingDeleteChatProjectId = "";
  clearSessionRowState();
  if (changedProject) renderReaderProjectControls();
  if (changedProject && !readerState.chatSessionsLoading) {
    void fetchReaderChatSessions({ silent: true }).then(() => {
      if (readerState.chatProjectMenuOpen && readerState.expandedChatProjectId === nextProjectId) {
        renderReaderProjectControls();
      }
    });
  }
}

function positionReaderProjectFlyout(flyout, row) {
  if (!flyout || !row) return;
  const popover = elements.readerProjectPopover;
  if (!popover) return;
  const popoverRect = popover.getBoundingClientRect();
  const rowRect = row.getBoundingClientRect();
  const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
  const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
  const gap = 10;
  const desiredWidth = 240;
  const width = Math.min(desiredWidth, Math.max(190, viewportWidth - 24));
  const rightSideLeft = rowRect.right + gap;
  const leftSideLeft = rowRect.left - width - gap;
  const hasRightRoom = rightSideLeft + width <= viewportWidth - 12;
  const left = hasRightRoom
    ? rightSideLeft
    : Math.max(12, Math.min(leftSideLeft, viewportWidth - width - 12));
  const maxTop = Math.max(12, viewportHeight - 320 - 12);
  const top = Math.max(12, Math.min(rowRect.top, maxTop));
  flyout.style.width = `${Math.round(width)}px`;
  flyout.style.left = `${Math.round(left - popoverRect.left)}px`;
  flyout.style.top = `${Math.round(top - popoverRect.top)}px`;
}

function positionReaderProjectFlyoutBridge(bridge, row, flyout) {
  const popover = elements.readerProjectPopover;
  if (!bridge || !row || !flyout || !popover) return;
  const popoverRect = popover.getBoundingClientRect();
  const rowRect = row.getBoundingClientRect();
  const flyoutRect = flyout.getBoundingClientRect();
  const overlap = 8;
  const flyoutOnRight = flyoutRect.left >= rowRect.right;
  const gapStart = flyoutOnRight ? rowRect.right : flyoutRect.right;
  const gapEnd = flyoutOnRight ? flyoutRect.left : rowRect.left;
  const width = Math.max(0, gapEnd - gapStart) + overlap * 2;
  const left = gapStart - popoverRect.left - overlap;
  const topEdge = Math.min(rowRect.top, flyoutRect.top);
  const bottomEdge = Math.max(rowRect.bottom, flyoutRect.bottom);
  bridge.style.left = `${Math.round(left)}px`;
  bridge.style.top = `${Math.round(topEdge - popoverRect.top - overlap)}px`;
  bridge.style.width = `${Math.round(width)}px`;
  bridge.style.height = `${Math.round(bottomEdge - topEdge + overlap * 2)}px`;
}

function removeReaderProjectFlyout() {
  document.querySelectorAll(".ask-project-flyout, .ask-project-flyout-bridge").forEach((element) => element.remove());
}

function cancelReaderProjectFlyoutClose() {
  if (!readerProjectFlyoutCloseTimer) return;
  window.clearTimeout(readerProjectFlyoutCloseTimer);
  readerProjectFlyoutCloseTimer = 0;
}

function pointerInsideReaderProjectHoverArea() {
  return Boolean(document.querySelector("#readerProjectPopover:hover, .ask-project-flyout:hover, .ask-project-flyout-bridge:hover"));
}

function scheduleHideReaderProjectFlyout() {
  cancelReaderProjectFlyoutClose();
  readerProjectFlyoutCloseTimer = window.setTimeout(() => {
    readerProjectFlyoutCloseTimer = 0;
    if (!pointerInsideReaderProjectHoverArea()) hideReaderProjectFlyout();
  }, 180);
}

function hideReaderProjectFlyout() {
  cancelReaderProjectFlyoutClose();
  if (!readerState.expandedChatProjectId) return;
  readerState.expandedChatProjectId = "";
  removeReaderProjectFlyout();
}

function isReaderProjectHoverTarget(target) {
  const element = target?.nodeType === Node.ELEMENT_NODE ? target : target?.parentElement;
  return Boolean(element?.closest?.("#readerProjectPopover, .ask-project-flyout, .ask-project-flyout-bridge"));
}

function hideReaderProjectFlyoutIfOutside(event) {
  if (isReaderProjectHoverTarget(event.relatedTarget)) return;
  scheduleHideReaderProjectFlyout();
}

function appendReaderProjectFlyout() {
  const project = readerChatProjectById(readerState.expandedChatProjectId);
  if (!project || !elements.readerProjectPopover) return;
  removeReaderProjectFlyout();
  const row = Array.from(elements.readerProjectPopover.querySelectorAll("[data-project-row]"))
    .find((element) => normalizeText(element.dataset.projectRow) === project.id);
  if (!row) return;
  const wrapper = document.createElement("div");
  wrapper.innerHTML = renderReaderProjectSubmenu(project);
  const flyout = wrapper.firstElementChild;
  if (!flyout) return;
  const bridge = document.createElement("div");
  bridge.className = "ask-project-flyout-bridge";
  bridge.setAttribute("aria-hidden", "true");
  flyout.addEventListener("click", (event) => {
    const sessionButton = event.target.closest("[data-project-session]");
    if (!sessionButton) return;
    event.preventDefault();
    event.stopPropagation();
    void loadReaderChatSession(sessionButton.dataset.projectSession, { closeMenu: false });
    closeReaderProjectMenu();
  });
  bridge.addEventListener("pointerenter", cancelReaderProjectFlyoutClose);
  bridge.addEventListener("pointerleave", hideReaderProjectFlyoutIfOutside);
  flyout.addEventListener("pointerenter", cancelReaderProjectFlyoutClose);
  flyout.addEventListener("pointerleave", hideReaderProjectFlyoutIfOutside);
  elements.readerProjectPopover.appendChild(bridge);
  elements.readerProjectPopover.appendChild(flyout);
  positionReaderProjectFlyout(flyout, row);
  positionReaderProjectFlyoutBridge(bridge, row, flyout);
}

function rememberReaderProjectListScroll() {
  const list = elements.readerProjectPopover?.querySelector(".ask-project-list");
  if (!list) return;
  readerState.chatProjectListScrollTop = list.scrollTop;
}

function rememberReaderProjectCreateDraft() {
  const input = elements.readerProjectPopover?.querySelector("#readerProjectCreateInput");
  if (!input) return;
  readerState.chatProjectCreateDraft = input.value || "";
}

function restoreReaderProjectListScroll() {
  const list = elements.readerProjectPopover?.querySelector(".ask-project-list");
  if (!list) return;
  list.scrollTop = readerState.chatProjectListScrollTop || 0;
  list.addEventListener("scroll", () => {
    readerState.chatProjectListScrollTop = list.scrollTop;
  }, { passive: true });
}

function renderReaderProjectControls() {
  rememberReaderProjectListScroll();
  rememberReaderProjectCreateDraft();
  removeReaderProjectFlyout();
  renderReaderProjectButton();
  if (!elements.readerProjectPopover) return;
  elements.readerProjectPopover.hidden = !readerState.chatProjectMenuOpen;
  if (!readerState.chatProjectMenuOpen) return;

  const activeProjectId = normalizeText(readerState.expandedChatProjectId);
  const projectRows = readerState.chatProjects.map((project) => renderReaderProjectRow(project, activeProjectId)).join("");

  elements.readerProjectPopover.innerHTML = `
    <div class="ask-project-popover-header">
      <strong>Projects</strong>
    </div>
    <div class="ask-project-list">
      ${projectRows || renderReaderProjectEmptyState()}
    </div>
    ${renderReaderProjectCreateForm()}
  `;
  restoreReaderProjectListScroll();
  appendReaderProjectFlyout();
  appendProjectFloatingActionMenu();
}

function setReaderProjectMenuOpen(open) {
  if (open) {
    if (readerState.chatSessionMenuOpen) setChatSessionMenuOpen(false);
    closeReaderModelMenu();
    closeReaderToolMenu();
    readerState.expandedChatProjectId = "";
    readerState.chatProjectScopeId = "";
    readerState.openProjectActionMenuId = "";
    readerState.confirmingDeleteChatProjectId = "";
    readerState.chatProjectListScrollTop = 0;
  } else {
    readerState.chatProjectCreateDraft = "";
  }
  readerState.chatProjectMenuOpen = open;
  renderReaderProjectControls();
  if (open) {
    readerState.chatSessionView = "active";
    readerState.chatProjectScopeId = "";
    if (!readerState.chatProjects.length && !readerState.chatProjectsLoading) {
      void fetchReaderChatProjects({ silent: true });
    }
    if (!readerState.chatSessionsLoading) {
      void fetchReaderChatSessions({ silent: true }).then(() => {
        if (readerState.chatProjectMenuOpen) renderReaderProjectControls();
      });
    }
    requestAnimationFrame(() => {
      const target = elements.readerProjectPopover?.querySelector("[data-project-open], #readerProjectCreateInput");
      target?.focus();
    });
  }
}

function closeReaderProjectMenu() {
  if (!readerState.chatProjectMenuOpen) return;
  readerState.chatProjectMenuOpen = false;
  readerState.openProjectActionMenuId = "";
  readerState.confirmingDeleteChatProjectId = "";
  readerState.expandedChatProjectId = "";
  readerState.chatProjectScopeId = "";
  readerState.chatProjectCreateDraft = "";
  removeReaderProjectFlyout();
  renderReaderProjectControls();
}

async function fetchReaderChatProjects({ silent = false } = {}) {
  const mutationVersion = readerState.chatProjectsMutationVersion;
  readerState.chatProjectsLoading = true;
  renderReaderProjectControls();
  try {
    const payload = await fetchAgentJson("/api/chat/projects");
    if (readerState.chatProjectsMutationVersion !== mutationVersion) {
      readerState.chatProjectsLoading = false;
      return readerState.chatProjects;
    }
    readerState.chatProjects = normalizeReaderChatProjects(payload.projects);
    readerState.chatProjectsLoading = false;
    if (readerState.chatProjectScopeId && !readerChatProjectById(readerState.chatProjectScopeId)) {
      readerState.chatProjectScopeId = "";
    }
    if (readerState.expandedChatProjectId && !readerChatProjectById(readerState.expandedChatProjectId)) {
      readerState.expandedChatProjectId = "";
    }
    if (readerState.openProjectActionMenuId && !readerChatProjectById(readerState.openProjectActionMenuId)) {
      readerState.openProjectActionMenuId = "";
    }
    readerState.chatSessions.forEach(enrichReaderSessionProject);
    if (readerState.currentChatSession) enrichReaderSessionProject(readerState.currentChatSession);
    renderReaderProjectControls();
    renderChatSessionList();
    return readerState.chatProjects;
  } catch (error) {
    readerState.chatProjectsLoading = false;
    if (!silent) setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderReaderProjectControls();
    return [];
  }
}

async function createReaderChatProject(name) {
  const nextName = normalizeText(name);
  if (!nextName) return null;
  try {
    const payload = await fetchAgentJson("/api/chat/projects", {
      method: "POST",
      body: { name: nextName },
    });
    readerState.chatProjects = normalizeReaderChatProjects(payload.projects);
    const project = normalizeReaderChatProject(payload.project);
    if (project) {
      readerState.expandedChatProjectId = project.id;
    }
    readerState.chatProjectsMutationVersion += 1;
    readerState.openProjectActionMenuId = "";
    readerState.renamingChatProjectId = "";
    readerState.confirmingDeleteChatProjectId = "";
    readerState.chatProjectCreateDraft = "";
    setReaderChatError("");
    renderReaderProjectControls();
    renderChatSessionList();
    return project;
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderReaderProjectControls();
    return null;
  }
}

function updateLocalProjectReferences(projectId, projectName) {
  const normalizedProjectId = normalizeText(projectId);
  const normalizedProjectName = normalizeText(projectName);
  const updateSession = (session) => {
    if (!session || readerSessionProjectId(session) !== normalizedProjectId) return session;
    session.projectId = normalizedProjectId;
    session.projectName = normalizedProjectName;
    return session;
  };
  readerState.chatSessions.forEach(updateSession);
  if (readerState.currentChatSession) updateSession(readerState.currentChatSession);
}

function clearLocalProjectReferences(projectId) {
  const normalizedProjectId = normalizeText(projectId);
  const clearSession = (session) => {
    if (!session || readerSessionProjectId(session) !== normalizedProjectId) return session;
    session.projectId = "";
    session.projectName = "";
    return session;
  };
  readerState.chatSessions.forEach(clearSession);
  if (readerState.currentChatSession) clearSession(readerState.currentChatSession);
  if (readerState.chatProjectScopeId === normalizedProjectId) readerState.chatProjectScopeId = "";
  if (readerState.expandedChatProjectId === normalizedProjectId) readerState.expandedChatProjectId = "";
  if (readerState.openProjectActionMenuId === normalizedProjectId) readerState.openProjectActionMenuId = "";
}

async function renameReaderChatProject(projectId, name) {
  const nextProjectId = normalizeText(projectId);
  const nextName = normalizeText(name);
  if (!nextProjectId || !nextName) return null;
  try {
    const payload = await fetchAgentJson("/api/chat/project/rename", {
      method: "POST",
      body: { projectId: nextProjectId, name: nextName },
    });
    readerState.chatProjects = normalizeReaderChatProjects(payload.projects);
    readerState.chatProjectsMutationVersion += 1;
    updateLocalProjectReferences(nextProjectId, nextName);
    readerState.openProjectActionMenuId = "";
    readerState.renamingChatProjectId = "";
    readerState.confirmingDeleteChatProjectId = "";
    setReaderChatError("");
    renderReaderProjectControls();
    renderChatSessionList();
    return normalizeReaderChatProject(payload.project);
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderReaderProjectControls();
    return null;
  }
}

async function deleteReaderChatProject(projectId) {
  const nextProjectId = normalizeText(projectId);
  if (!nextProjectId) return;
  try {
    const payload = await fetchAgentJson("/api/chat/project/delete", {
      method: "POST",
      body: { projectId: nextProjectId },
    });
    readerState.chatProjects = normalizeReaderChatProjects(payload.projects);
    readerState.chatProjectsMutationVersion += 1;
    clearLocalProjectReferences(nextProjectId);
    readerState.renamingChatProjectId = "";
    readerState.confirmingDeleteChatProjectId = "";
    readerState.openProjectActionMenuId = "";
    setReaderChatError("");
    renderReaderProjectControls();
    renderChatSessionList();
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderReaderProjectControls();
  }
}

function selectReaderChatProjectScope(projectId) {
  showReaderProjectFlyout(projectId);
}

function updateLocalReaderSessionProject(sessionId, projectId, projectName) {
  const normalizedSessionId = normalizeText(sessionId);
  const updateSession = (session) => {
    if (!session || session.id !== normalizedSessionId) return session;
    session.projectId = normalizeText(projectId);
    session.projectName = normalizeText(projectName);
    return session;
  };
  readerState.chatSessions.forEach(updateSession);
  if (readerState.currentChatSession?.id === normalizedSessionId) {
    updateSession(readerState.currentChatSession);
  }
}

async function assignReaderChatSessionProject(sessionId, projectId) {
  const project = readerChatProjectById(projectId);
  const nextProjectId = normalizeText(projectId);
  const projectName = nextProjectId ? normalizeText(project?.name) : "";
  try {
    const payload = await fetchAgentJson("/api/chat/session/project", {
      method: "POST",
      body: {
        sessionId,
        projectId: nextProjectId,
        projectName,
      },
    });
    const updated = normalizeReaderChatSession(payload.session);
    if (updated) upsertReaderChatSession(updated);
    updateLocalReaderSessionProject(sessionId, nextProjectId, projectName);
    readerState.assigningProjectSessionId = "";
    clearSessionActionMenu();
    setReaderChatError("");
    setReaderChatNotice(projectName ? `Added to ${projectName}` : "Project updated");
    renderReaderProjectControls();
    renderChatSessionList();
  } catch (error) {
    setReaderChatError(error.message || GENERIC_AGENT_ERROR);
    renderChatSessionList();
  }
}

function addSessionProjectPicker(menu, session) {
  const currentProjectId = readerSessionProjectId(session);
  const header = document.createElement("div");
  header.className = "ask-session-project-menu-header";
  header.innerHTML = `
    <button class="ask-session-project-back" type="button" aria-label="Back to session actions">${readerProjectIcon("chevron-left", 14)}</button>
    <span>Project</span>
  `;
  header.querySelector("button")?.addEventListener("click", (event) => {
    event.stopPropagation();
    readerState.assigningProjectSessionId = "";
    renderChatSessionList();
  });
  menu.appendChild(header);

  const list = document.createElement("div");
  list.className = "ask-session-project-list";
  menu.appendChild(list);

  readerState.chatProjects.forEach((project) => {
    addSessionProjectOption(list, {
      label: project.name,
      projectId: project.id,
      active: project.id === currentProjectId,
      onClick: () => assignReaderChatSessionProject(session.id, project.id),
    });
  });

  if (!readerState.chatProjects.length) {
    const empty = document.createElement("p");
    empty.className = "ask-session-project-empty";
    empty.textContent = "Create a project from the header first.";
    list.appendChild(empty);
  }
}

function addSessionProjectOption(menu, { label, projectId, active, onClick }) {
  return addReaderActionMenuOption(menu, {
    className: `ask-session-project-option ${active ? "is-active" : ""}`,
    dataset: { projectId },
    html: `
    <span>${escapeHtml(label)}</span>
    <span class="ask-session-project-check">${active ? readerProjectIcon("check", 14) : ""}</span>
  `,
    onClick,
  });
}

function handleReaderProjectPopoverClick(event) {
  const sessionButton = event.target.closest("[data-project-session]");
  if (sessionButton) {
    void loadReaderChatSession(sessionButton.dataset.projectSession, { closeMenu: false });
    closeReaderProjectMenu();
    return;
  }

  const menuButton = event.target.closest("[data-project-menu]");
  if (menuButton) {
    const projectId = normalizeText(menuButton.dataset.projectMenu);
    readerState.openProjectActionMenuId = readerState.openProjectActionMenuId === projectId ? "" : projectId;
    readerState.expandedChatProjectId = "";
    readerState.renamingChatProjectId = "";
    if (readerState.openProjectActionMenuId !== projectId) {
      readerState.confirmingDeleteChatProjectId = "";
    }
    renderReaderProjectControls();
    return;
  }

  const option = event.target.closest("[data-project-open]");
  if (!option) {
    if (!event.target.closest(".ask-project-action-menu, [data-project-create], [data-project-rename-form]")) {
      readerState.openProjectActionMenuId = "";
      readerState.confirmingDeleteChatProjectId = "";
      renderReaderProjectControls();
    }
    return;
  }
  selectReaderChatProjectScope(option.dataset.projectOpen || "");
}

function handleReaderProjectPopoverPointerOver(event) {
  if (readerState.openProjectActionMenuId) return;
  cancelReaderProjectFlyoutClose();
  if (event.target.closest(".ask-project-flyout, .ask-project-flyout-bridge")) return;
  const row = event.target.closest("[data-project-row]");
  if (!row || event.target.closest("[data-project-menu]")) {
    hideReaderProjectFlyout();
    return;
  }
  showReaderProjectFlyout(row.dataset.projectRow);
}

function handleReaderProjectPopoverSubmit(event) {
  const renameForm = event.target.closest("[data-project-rename-form]");
  if (renameForm) {
    event.preventDefault();
    const input = renameForm.querySelector("input[name='name']");
    const name = normalizeText(input?.value);
    if (!name) {
      input?.focus();
      return;
    }
    void renameReaderChatProject(renameForm.dataset.projectId, name);
    return;
  }

  const form = event.target.closest("[data-project-create]");
  if (!form) return;
  event.preventDefault();
  const input = form.querySelector("input[name='name']");
  const name = normalizeText(input?.value);
  if (!name) {
    input?.focus();
    return;
  }
  input.value = "";
  readerState.chatProjectCreateDraft = "";
  void createReaderChatProject(name);
}

function handleReaderProjectPopoverInput(event) {
  if (!event.target.closest("#readerProjectCreateInput")) return;
  readerState.chatProjectCreateDraft = event.target.value || "";
}

function initializeReaderProjects() {
  renderReaderProjectControls();
  elements.readerProjectButton?.addEventListener("click", () => {
    setReaderProjectMenuOpen(!readerState.chatProjectMenuOpen);
  });
  elements.readerProjectPopover?.addEventListener("click", handleReaderProjectPopoverClick);
  elements.readerProjectPopover?.addEventListener("pointerover", handleReaderProjectPopoverPointerOver);
  elements.readerProjectPopover?.addEventListener("pointerleave", hideReaderProjectFlyoutIfOutside);
  elements.readerProjectPopover?.addEventListener("input", handleReaderProjectPopoverInput);
  elements.readerProjectPopover?.addEventListener("submit", handleReaderProjectPopoverSubmit);
  void fetchReaderChatProjects({ silent: true });
}
