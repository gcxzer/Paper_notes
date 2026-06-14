(function () {
  const CONTENT_KEY = "paper-notes-floating-pad-content-v1";
  const POSITION_KEY = "paper-notes-floating-pad-position-v1";
  const OPEN_KEY = "paper-notes-floating-pad-open-v1";
  const ENABLED_KEY = "paper-notes-floating-pad-enabled-v1";
  const LEGACY_HTML_KEY = "paper-notes-floating-pad-html-v1";
  const PADS_KEY = "paper-notes-floating-pad-pads-v1";
  const ACTIVE_PAD_KEY = "paper-notes-floating-pad-active-v1";
  const SERVER_MIGRATED_KEY = "paper-notes-floating-pad-server-migrated-v1";
  const DRAG_THRESHOLD = 5;
  const EDGE_PADDING = 12;
  const BUTTON_SIZE = 54;

  function readJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (error) {
      return fallback;
    }
  }

  function scratchpadEnabled() {
    return localStorage.getItem(ENABLED_KEY) === "true";
  }

  function writeJson(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
      // Ignore quota and privacy-mode failures; the pad still works for the page lifetime.
    }
  }

  function createPad(title = "") {
    const now = new Date().toISOString();
    return {
      id: `pad-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      title: title || "Untitled pad",
      customTitle: false,
      content: "",
      updatedAt: now,
      createdAt: now,
    };
  }

  function defaultPadState() {
    const pad = createPad("Pad 1");
    return { activeId: pad.id, pads: [pad] };
  }

  function padTitle(pad, index = 0) {
    return String(pad?.title || `Pad ${index + 1}`);
  }

  let writeQueue = Promise.resolve();

  function readLocalPads() {
    const stored = readJson(PADS_KEY, null);
    if (stored && Array.isArray(stored.pads) && stored.pads.length) {
      return {
        activeId: String(stored.activeId || localStorage.getItem(ACTIVE_PAD_KEY) || stored.pads[0].id || ""),
        pads: stored.pads.map((pad, index) => ({
          ...createPad(`Pad ${index + 1}`),
          ...pad,
          id: String(pad.id || `pad-${index + 1}`),
          content: String(pad.content || ""),
        })),
      };
    }
    const legacyContent = localStorage.getItem(CONTENT_KEY) || "";
    const pad = createPad("Pad 1");
    pad.content = legacyContent;
    return { activeId: pad.id, pads: [pad] };
  }

  function normalizePadState(raw) {
    const stored = raw && typeof raw === "object" ? raw : {};
    const rawPads = Array.isArray(stored.pads) ? stored.pads : [];
    const pads = rawPads.map((pad, index) => ({
      ...createPad(`Pad ${index + 1}`),
      ...pad,
      id: String(pad?.id || `pad-${index + 1}`),
      content: String(pad?.content || ""),
    }));
    const activeId = String(stored.activeId || localStorage.getItem(ACTIVE_PAD_KEY) || pads[0]?.id || "");
    return { activeId, pads };
  }

  function hasScratchpadContent(state) {
    return Array.isArray(state?.pads) && state.pads.some((pad) => String(pad?.content || "").trim() || pad?.customTitle);
  }

  function scratchpadApiAvailable() {
    return true;
  }

  async function fetchScratchpads() {
    const response = await fetch("/api/scratchpads", { cache: "no-store" });
    if (!response.ok) throw new Error(`Scratchpad load failed (${response.status})`);
    return normalizePadState(await response.json());
  }

  async function writePadsToServer(state) {
    const response = await fetch("/api/scratchpads", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        activeId: state.activeId,
        pads: state.pads,
      }),
    });
    if (!response.ok) throw new Error(`Scratchpad save failed (${response.status})`);
    return response.json();
  }

  async function readPads() {
    const local = readLocalPads();
    if (!scratchpadApiAvailable()) return local;
    try {
      const remote = await fetchScratchpads();
      if (remote.pads.length) return remote;
      if (!localStorage.getItem(SERVER_MIGRATED_KEY) && hasScratchpadContent(local)) {
        await writePadsToServer(local);
        localStorage.setItem(SERVER_MIGRATED_KEY, "true");
        return local;
      }
      return defaultPadState();
    } catch (error) {
      return local;
    }
  }

  function writePads(state) {
    const pads = Array.isArray(state?.pads) && state.pads.length ? state.pads : [createPad("Pad 1")];
    const activeId = String(state?.activeId || pads[0].id);
    if (state) {
      state.pads = pads;
      state.activeId = activeId;
    }
    try {
      localStorage.setItem(ACTIVE_PAD_KEY, activeId);
      localStorage.removeItem(LEGACY_HTML_KEY);
      if (!scratchpadApiAvailable()) {
        localStorage.setItem(CONTENT_KEY, pads.find((pad) => pad.id === activeId)?.content || "");
        writeJson(PADS_KEY, { activeId, pads });
        return;
      }
    } catch (error) {
      // Ignore quota and privacy-mode failures.
    }
    const snapshot = JSON.parse(JSON.stringify({ activeId, pads }));
    writeQueue = writeQueue.catch(() => null).then(() => writePadsToServer(snapshot)).catch(() => null);
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function viewportSize() {
    return {
      width: Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0),
      height: Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0),
    };
  }

  function defaultPosition() {
    const viewport = viewportSize();
    return {
      x: Math.max(EDGE_PADDING, viewport.width - BUTTON_SIZE - 28),
      y: Math.max(EDGE_PADDING, viewport.height - BUTTON_SIZE - 112),
    };
  }

  function clampPosition(position) {
    const viewport = viewportSize();
    return {
      x: clamp(Number(position?.x) || EDGE_PADDING, EDGE_PADDING, Math.max(EDGE_PADDING, viewport.width - BUTTON_SIZE - EDGE_PADDING)),
      y: clamp(Number(position?.y) || EDGE_PADDING, EDGE_PADDING, Math.max(EDGE_PADDING, viewport.height - BUTTON_SIZE - EDGE_PADDING)),
    };
  }

  function readPosition() {
    return clampPosition(readJson(POSITION_KEY, null) || defaultPosition());
  }

  function setButtonPosition(button, position) {
    button.style.left = `${Math.round(position.x)}px`;
    button.style.top = `${Math.round(position.y)}px`;
  }

  function panelPosition(position, panel) {
    const viewport = viewportSize();
    const rect = panel.getBoundingClientRect();
    const width = rect.width || Math.min(520, viewport.width - EDGE_PADDING * 2);
    const height = rect.height || Math.min(620, viewport.height - EDGE_PADDING * 2);
    const preferLeft = position.x + BUTTON_SIZE - width;
    const preferTop = position.y - height - 12;
    const fallbackTop = position.y + BUTTON_SIZE + 12;
    return {
      x: clamp(preferLeft, EDGE_PADDING, Math.max(EDGE_PADDING, viewport.width - width - EDGE_PADDING)),
      y: clamp(preferTop >= EDGE_PADDING ? preferTop : fallbackTop, EDGE_PADDING, Math.max(EDGE_PADDING, viewport.height - height - EDGE_PADDING)),
    };
  }

  function setPanelPosition(panel, buttonPosition) {
    const next = panelPosition(buttonPosition, panel);
    panel.style.left = `${Math.round(next.x)}px`;
    panel.style.top = `${Math.round(next.y)}px`;
  }

  function setOpen(root, panel, button, position, open) {
    root.classList.toggle("is-open", open);
    panel.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    try {
      localStorage.setItem(OPEN_KEY, open ? "true" : "false");
    } catch (error) {
      // Non-persistent open state is fine.
    }
    if (open) requestAnimationFrame(() => setPanelPosition(panel, position));
  }

  function activePad(state) {
    return state.pads.find((pad) => pad.id === state.activeId) || state.pads[0];
  }

  function syncContent(state, textarea, status, title, list, openMenuId = "") {
    const pad = activePad(state);
    if (!pad) return;
    pad.content = textarea.value;
    pad.updatedAt = new Date().toISOString();
    state.activeId = pad.id;
    writePads(state);
    status.textContent = textarea.value.trim() ? "Saved" : "Empty";
    renderPadTitle(state, title);
    renderPadList(state, list, openMenuId);
  }

  function renderPadTitle(state, title) {
    const pad = activePad(state);
    if (title) title.textContent = padTitle(pad, state.pads.indexOf(pad));
  }

  function renderPadList(state, list, openMenuId = "", { renamingPadId = "", confirmingDeletePadId = "" } = {}) {
    if (!list) return;
    list.innerHTML = state.pads.map((pad, index) => `
      <div class="floating-pad-list-row${pad.id === state.activeId ? " is-active" : ""}${pad.id === openMenuId ? " is-menu-open" : ""}${pad.id === confirmingDeletePadId ? " is-delete-confirming" : ""}">
        ${pad.id === renamingPadId ? `
          <form class="floating-pad-rename-form" data-floating-pad-rename-form="${pad.id}">
            <label class="floating-pad-rename-card">
              <span class="sr-only">Pad name</span>
              <input type="text" maxlength="80" value="${escapeHtml(pad.title || padTitle(pad, index))}" aria-label="Pad name">
              <button class="floating-pad-save" type="submit">Save</button>
            </label>
          </form>
        ` : `
          <button class="floating-pad-list-item" type="button" data-floating-pad-select="${pad.id}">
            <span>${escapeHtml(padTitle(pad, index))}</span>
            <small>${pad.content.trim() ? `${pad.content.trim().split(/\s+/).filter(Boolean).length} words` : "Empty"}</small>
          </button>
          <button class="floating-pad-menu-button" type="button" data-floating-pad-menu="${pad.id}" aria-label="More actions for ${escapeHtml(padTitle(pad, index))}" aria-haspopup="menu" aria-expanded="${pad.id === openMenuId ? "true" : "false"}">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <circle cx="6.5" cy="12" r="1.9"></circle>
              <circle cx="12" cy="12" r="1.9"></circle>
              <circle cx="17.5" cy="12" r="1.9"></circle>
            </svg>
          </button>
        `}
      </div>
    `).join("");
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));
  }

  async function createFloatingPad() {
    if (document.querySelector(".floating-pad")) return;

    let position = readPosition();
    const padState = await readPads();
    writePads(padState);
    const root = document.createElement("div");
    root.className = "floating-pad";
    root.innerHTML = `
      <button class="floating-pad-button" type="button" aria-label="Open scratchpad" aria-expanded="false" aria-controls="floatingPadPanel">
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path d="M4.75 19.25h14.5"></path>
          <path d="M7.25 16.75l1.2-4.5 7.7-7.7a2.05 2.05 0 0 1 2.9 2.9l-7.7 7.7-4.1 1.6Z"></path>
          <path d="M14.75 5.95l3.3 3.3"></path>
        </svg>
      </button>
      <section class="floating-pad-panel" id="floatingPadPanel" role="dialog" aria-label="Scratchpad" hidden>
        <header class="floating-pad-header">
          <div>
            <strong>Scratchpad</strong>
            <span><span class="floating-pad-active-title"></span> · Autosaves to Paper Notes</span>
          </div>
          <div class="floating-pad-actions">
            <button class="floating-pad-icon floating-pad-directory" type="button" data-floating-pad-directory aria-label="Show scratchpad list">Pads</button>
            <button class="floating-pad-icon" type="button" data-floating-pad-clear aria-label="Clear scratchpad">Clear</button>
            <button class="floating-pad-close" type="button" data-floating-pad-close aria-label="Close scratchpad">×</button>
          </div>
        </header>
        <aside class="floating-pad-list-panel" hidden>
          <div class="floating-pad-list-header">
            <strong>Pads</strong>
            <button class="floating-pad-icon" type="button" data-floating-pad-new>New</button>
          </div>
          <div class="floating-pad-list"></div>
        </aside>
        <textarea class="floating-pad-input" spellcheck="true" placeholder="Write anything here..."></textarea>
        <footer class="floating-pad-footer">
          <span class="floating-pad-status">Empty</span>
        </footer>
      </section>
      <div class="floating-pad-action-menu" role="menu" hidden></div>
    `;
    document.body.append(root);

    const button = root.querySelector(".floating-pad-button");
    const panel = root.querySelector(".floating-pad-panel");
    const textarea = root.querySelector(".floating-pad-input");
    const status = root.querySelector(".floating-pad-status");
    const title = root.querySelector(".floating-pad-active-title");
    const listPanel = root.querySelector(".floating-pad-list-panel");
    const list = root.querySelector(".floating-pad-list");
    const directoryButton = root.querySelector("[data-floating-pad-directory]");
    const newButton = root.querySelector("[data-floating-pad-new]");
    const clearButton = root.querySelector("[data-floating-pad-clear]");
    const closeButton = root.querySelector("[data-floating-pad-close]");
    const actionMenu = root.querySelector(".floating-pad-action-menu");
    textarea.value = activePad(padState)?.content || "";
    renderPadTitle(padState, title);
    renderPadList(padState, list);
    status.textContent = textarea.value.trim() ? "Saved" : "Empty";
    setButtonPosition(button, position);
    setOpen(root, panel, button, position, localStorage.getItem(OPEN_KEY) === "true");

    let drag = null;
    let suppressNextClick = false;
    let openPadMenuId = "";
    let renamingPadId = "";
    let confirmingDeletePadId = "";

    applyVisibility();

    function padById(padId) {
      return padState.pads.find((entry) => entry.id === padId);
    }

    function padMenuButton(padId) {
      return Array.from(list.querySelectorAll("[data-floating-pad-menu]")).find((entry) => entry.dataset.floatingPadMenu === padId);
    }

    function positionPadActionMenu() {
      if (!openPadMenuId || actionMenu.hidden) return;
      const menuButton = padMenuButton(openPadMenuId);
      if (!menuButton) return;
      const buttonRect = menuButton.getBoundingClientRect();
      const menuRect = actionMenu.getBoundingClientRect();
      const viewport = viewportSize();
      const gap = 8;
      const left = clamp(buttonRect.right - menuRect.width, EDGE_PADDING, Math.max(EDGE_PADDING, viewport.width - menuRect.width - EDGE_PADDING));
      const top = clamp(buttonRect.bottom + gap, EDGE_PADDING, Math.max(EDGE_PADDING, viewport.height - menuRect.height - EDGE_PADDING));
      actionMenu.style.left = `${Math.round(left)}px`;
      actionMenu.style.top = `${Math.round(top)}px`;
      actionMenu.style.visibility = "";
    }

    function renderPadActionMenu() {
      const pad = padById(openPadMenuId);
      if (!pad) {
        actionMenu.hidden = true;
        actionMenu.innerHTML = "";
        return;
      }
      actionMenu.style.visibility = "hidden";
      actionMenu.hidden = false;
      actionMenu.innerHTML = `
        <button class="floating-pad-menu-option" type="button" data-floating-pad-rename="${pad.id}" role="menuitem">Rename</button>
        <button class="floating-pad-menu-option is-danger" type="button" data-floating-pad-delete="${pad.id}" role="menuitem">${confirmingDeletePadId === pad.id ? "Confirm delete" : "Delete"}</button>
      `;
      requestAnimationFrame(positionPadActionMenu);
    }

    function renderPadListAndMenu() {
      renderPadList(padState, list, openPadMenuId, { renamingPadId, confirmingDeletePadId });
      renderPadActionMenu();
      if (renamingPadId) {
        requestAnimationFrame(() => {
          const input = list.querySelector(`[data-floating-pad-rename-form="${CSS.escape(renamingPadId)}"] input`);
          input?.focus();
          input?.select();
        });
      }
    }

    function closePadMenu() {
      openPadMenuId = "";
      renderPadListAndMenu();
    }

    function clearPadRowState() {
      openPadMenuId = "";
      renamingPadId = "";
      confirmingDeletePadId = "";
    }

    function setPadListOpen(open) {
      listPanel.hidden = !open;
      panel.classList.toggle("is-list-open", open);
      directoryButton.setAttribute("aria-expanded", String(open));
      if (!open) clearPadRowState();
      renderPadListAndMenu();
    }

    function finishDrag(event, { cancelled = false } = {}) {
      const pointerId = event.pointerId ?? "mouse";
      if (!drag || drag.pointerId !== pointerId) return false;
      const wasDrag = drag.moved;
      drag = null;
      button.classList.remove("is-dragging");
      if (event.pointerId !== undefined) {
        try {
          button.releasePointerCapture(event.pointerId);
        } catch (error) {
          // Pointer capture may already be released by the browser.
        }
      }
      if (wasDrag && !cancelled) {
        writeJson(POSITION_KEY, position);
        suppressNextClick = true;
      }
      return wasDrag;
    }

    function startDrag(pointerId, clientX, clientY) {
      drag = {
        pointerId,
        startX: clientX,
        startY: clientY,
        originX: position.x,
        originY: position.y,
        moved: false,
      };
    }

    function updateDrag(event) {
      const pointerId = event.pointerId ?? "mouse";
      if (!drag || drag.pointerId !== pointerId) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      drag.moved = true;
      button.classList.add("is-dragging");
      position = clampPosition({ x: drag.originX + dx, y: drag.originY + dy });
      setButtonPosition(button, position);
      if (!panel.hidden) setPanelPosition(panel, position);
    }

    function beginPointerDrag(event) {
      if (event.button !== 0 || drag) return;
      startDrag(event.pointerId, event.clientX, event.clientY);
      try {
        button.setPointerCapture(event.pointerId);
      } catch (error) {
        // Document-level move handlers keep dragging working if pointer capture is unavailable.
      }
    }

    function beginMouseDrag(event) {
      if (event.button !== 0 || drag) return;
      startDrag("mouse", event.clientX, event.clientY);
    }

    document.addEventListener("pointerdown", (event) => {
      if (event.target?.closest?.(".floating-pad-button") !== button) return;
      beginPointerDrag(event);
    }, true);

    button.addEventListener("pointerdown", beginPointerDrag);

    document.addEventListener("mousedown", (event) => {
      if (event.target?.closest?.(".floating-pad-button") !== button) return;
      beginMouseDrag(event);
    }, true);

    button.addEventListener("mousedown", beginMouseDrag);

    button.addEventListener("pointermove", updateDrag);
    document.addEventListener("pointermove", updateDrag, true);
    document.addEventListener("mousemove", updateDrag, true);

    button.addEventListener("pointerup", (event) => {
      finishDrag(event);
    });
    document.addEventListener("mouseup", (event) => {
      finishDrag(event);
    }, true);

    button.addEventListener("pointercancel", (event) => {
      finishDrag(event, { cancelled: true });
    });

    button.addEventListener("click", (event) => {
      if (suppressNextClick) {
        event.preventDefault();
        suppressNextClick = false;
        return;
      }
      const open = panel.hidden;
      setOpen(root, panel, button, position, open);
      if (!open) {
        clearPadRowState();
        renderPadListAndMenu();
      }
      if (open) textarea.focus();
    });

    textarea.addEventListener("input", () => syncContent(padState, textarea, status, title, list, openPadMenuId));

    closeButton.addEventListener("click", () => {
      clearPadRowState();
      renderPadListAndMenu();
      setOpen(root, panel, button, position, false);
      button.focus();
    });

    clearButton.addEventListener("click", () => {
      textarea.focus();
      textarea.select();
      const deleted = document.execCommand?.("delete");
      if (!deleted) {
        textarea.setRangeText("", 0, textarea.value.length, "end");
        textarea.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward" }));
      }
      syncContent(padState, textarea, status, title, list);
      textarea.focus();
    });

    directoryButton.addEventListener("click", () => {
      setPadListOpen(listPanel.hidden);
    });

    newButton.addEventListener("click", () => {
      const pad = createPad(`Pad ${padState.pads.length + 1}`);
      padState.pads.push(pad);
      padState.activeId = pad.id;
      textarea.value = pad.content;
      clearPadRowState();
      writePads(padState);
      renderPadTitle(padState, title);
      status.textContent = "Empty";
      setPadListOpen(false);
      textarea.focus();
    });

    list.addEventListener("click", (event) => {
      const menuButton = event.target.closest("[data-floating-pad-menu]");
      if (menuButton) {
        openPadMenuId = openPadMenuId === menuButton.dataset.floatingPadMenu ? "" : menuButton.dataset.floatingPadMenu;
        renamingPadId = "";
        renderPadListAndMenu();
        return;
      }

      const item = event.target.closest("[data-floating-pad-select]");
      if (!item) return;
      const pad = padById(item.dataset.floatingPadSelect);
      if (!pad) return;
      padState.activeId = pad.id;
      textarea.value = pad.content || "";
      clearPadRowState();
      writePads(padState);
      renderPadTitle(padState, title);
      status.textContent = textarea.value.trim() ? "Saved" : "Empty";
      setPadListOpen(false);
      textarea.focus();
    });

    list.addEventListener("submit", (event) => {
      const form = event.target.closest("[data-floating-pad-rename-form]");
      if (!form) return;
      event.preventDefault();
      const pad = padById(form.dataset.floatingPadRenameForm);
      if (!pad) return;
      const nextTitle = form.querySelector("input")?.value?.trim() || "Untitled pad";
      pad.title = nextTitle;
      pad.customTitle = true;
      pad.updatedAt = new Date().toISOString();
      clearPadRowState();
      writePads(padState);
      renderPadTitle(padState, title);
      renderPadListAndMenu();
    });

    actionMenu.addEventListener("click", (event) => {
      const renameButton = event.target.closest("[data-floating-pad-rename]");
      if (renameButton) {
        const pad = padById(renameButton.dataset.floatingPadRename);
        if (!pad) return;
        renamingPadId = pad.id;
        openPadMenuId = "";
        confirmingDeletePadId = "";
        renderPadListAndMenu();
        return;
      }

      const deleteButton = event.target.closest("[data-floating-pad-delete]");
      if (deleteButton) {
        const padIndex = padState.pads.findIndex((entry) => entry.id === deleteButton.dataset.floatingPadDelete);
        if (padIndex < 0) return;
        if (confirmingDeletePadId !== padState.pads[padIndex].id) {
          confirmingDeletePadId = padState.pads[padIndex].id;
          openPadMenuId = padState.pads[padIndex].id;
          renamingPadId = "";
          renderPadListAndMenu();
          return;
        }
        const deletingActive = padState.pads[padIndex].id === padState.activeId;
        padState.pads.splice(padIndex, 1);
        if (!padState.pads.length) padState.pads.push(createPad("Pad 1"));
        if (deletingActive || !padState.pads.some((pad) => pad.id === padState.activeId)) {
          padState.activeId = padState.pads[Math.max(0, padIndex - 1)]?.id || padState.pads[0].id;
        }
        const pad = activePad(padState);
        textarea.value = pad?.content || "";
        clearPadRowState();
        writePads(padState);
        renderPadTitle(padState, title);
        renderPadListAndMenu();
        status.textContent = textarea.value.trim() ? "Saved" : "Empty";
        textarea.focus();
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (panel.hidden) return;
      if (button.contains(event.target) || panel.contains(event.target) || actionMenu.contains(event.target)) return;
      clearPadRowState();
      renderPadListAndMenu();
      setOpen(root, panel, button, position, false);
    }, true);

    window.addEventListener("resize", () => {
      position = clampPosition(position);
      setButtonPosition(button, position);
      if (!panel.hidden) setPanelPosition(panel, position);
      positionPadActionMenu();
      writeJson(POSITION_KEY, position);
    });

    function applyVisibility() {
      const enabled = scratchpadEnabled();
      root.hidden = !enabled;
      if (!enabled) {
        clearPadRowState();
        renderPadListAndMenu();
        setOpen(root, panel, button, position, false);
      }
    }

    window.addEventListener("paper-scratchpad-setting-change", applyVisibility);
    window.addEventListener("storage", (event) => {
      if (event.key === ENABLED_KEY) applyVisibility();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createFloatingPad, { once: true });
  } else {
    createFloatingPad();
  }
}());
