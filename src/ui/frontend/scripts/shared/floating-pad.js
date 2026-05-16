(function () {
  const CONTENT_KEY = "paper-notes-floating-pad-content-v1";
  const POSITION_KEY = "paper-notes-floating-pad-position-v1";
  const OPEN_KEY = "paper-notes-floating-pad-open-v1";
  const ENABLED_KEY = "paper-notes-floating-pad-enabled-v1";
  const LEGACY_HTML_KEY = "paper-notes-floating-pad-html-v1";
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
    return localStorage.getItem(ENABLED_KEY) !== "false";
  }

  function writeJson(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
      // Ignore quota and privacy-mode failures; the pad still works for the page lifetime.
    }
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
      y: Math.max(EDGE_PADDING, viewport.height - BUTTON_SIZE - 28),
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

  function syncContent(textarea, status) {
    try {
      localStorage.setItem(CONTENT_KEY, textarea.value);
      localStorage.removeItem(LEGACY_HTML_KEY);
      status.textContent = textarea.value.trim() ? "Saved" : "Empty";
    } catch (error) {
      status.textContent = "Not saved";
    }
  }

  function createFloatingPad() {
    if (document.querySelector(".floating-pad")) return;

    let position = readPosition();
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
            <span>Plain text · Autosaves locally</span>
          </div>
          <div class="floating-pad-actions">
            <button class="floating-pad-icon" type="button" data-floating-pad-copy aria-label="Copy scratchpad">Copy</button>
            <button class="floating-pad-icon" type="button" data-floating-pad-clear aria-label="Clear scratchpad">Clear</button>
            <button class="floating-pad-close" type="button" data-floating-pad-close aria-label="Close scratchpad">×</button>
          </div>
        </header>
        <textarea class="floating-pad-input" spellcheck="true" placeholder="Write anything here..."></textarea>
        <footer class="floating-pad-footer">
          <span class="floating-pad-status">Empty</span>
        </footer>
      </section>
    `;
    document.body.append(root);

    const button = root.querySelector(".floating-pad-button");
    const panel = root.querySelector(".floating-pad-panel");
    const textarea = root.querySelector(".floating-pad-input");
    const status = root.querySelector(".floating-pad-status");
    const copyButton = root.querySelector("[data-floating-pad-copy]");
    const clearButton = root.querySelector("[data-floating-pad-clear]");
    const closeButton = root.querySelector("[data-floating-pad-close]");
    textarea.value = localStorage.getItem(CONTENT_KEY) || "";
    syncContent(textarea, status);
    setButtonPosition(button, position);
    setOpen(root, panel, button, position, localStorage.getItem(OPEN_KEY) === "true");
    applyVisibility();

    let drag = null;
    let suppressNextClick = false;

    function finishDrag(event, { cancelled = false } = {}) {
      if (!drag || drag.pointerId !== event.pointerId) return false;
      const wasDrag = drag.moved;
      drag = null;
      button.classList.remove("is-dragging");
      try {
        button.releasePointerCapture(event.pointerId);
      } catch (error) {
        // Pointer capture may already be released by the browser.
      }
      if (wasDrag && !cancelled) {
        writeJson(POSITION_KEY, position);
        suppressNextClick = true;
      }
      return wasDrag;
    }

    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      drag = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originX: position.x,
        originY: position.y,
        moved: false,
      };
      button.setPointerCapture(event.pointerId);
    });

    button.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      drag.moved = true;
      button.classList.add("is-dragging");
      position = clampPosition({ x: drag.originX + dx, y: drag.originY + dy });
      setButtonPosition(button, position);
      if (!panel.hidden) setPanelPosition(panel, position);
    });

    button.addEventListener("pointerup", (event) => {
      finishDrag(event);
    });

    button.addEventListener("pointercancel", (event) => {
      finishDrag(event, { cancelled: true });
    });

    button.addEventListener("lostpointercapture", (event) => {
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
      if (open) textarea.focus();
    });

    textarea.addEventListener("input", () => syncContent(textarea, status));

    closeButton.addEventListener("click", () => {
      setOpen(root, panel, button, position, false);
      button.focus();
    });

    clearButton.addEventListener("click", () => {
      textarea.value = "";
      syncContent(textarea, status);
      textarea.focus();
    });

    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(textarea.value);
        status.textContent = "Copied";
      } catch (error) {
        status.textContent = "Copy failed";
      }
    });

    document.addEventListener("pointerdown", (event) => {
      if (panel.hidden) return;
      if (button.contains(event.target) || panel.contains(event.target)) return;
      setOpen(root, panel, button, position, false);
    }, true);

    window.addEventListener("resize", () => {
      position = clampPosition(position);
      setButtonPosition(button, position);
      if (!panel.hidden) setPanelPosition(panel, position);
      writeJson(POSITION_KEY, position);
    });

    function applyVisibility() {
      const enabled = scratchpadEnabled();
      root.hidden = !enabled;
      if (!enabled) setOpen(root, panel, button, position, false);
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
