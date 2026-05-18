(function () {
  const SLASH_COMMANDS = [
    {
      id: "new",
      trigger: "/new",
      title: "New chat",
      description: "Start a fresh Ask session",
      icon: "plus",
    },
    {
      id: "compact",
      trigger: "/compact",
      title: "Compact",
      description: "Summarize this session's context",
      icon: "layers-3",
    },
  ];

  const state = {
    open: false,
    query: "",
    activeIndex: -1,
    items: [],
    menu: null,
  };

  function renderSlashIcon(name) {
    return window.renderPaperIcon
      ? window.renderPaperIcon(name, { className: "slash-command-icon", size: 18 })
      : "";
  }

  function slashCommandStatus(command) {
    if (command.id !== "compact") return { disabled: false, description: command.description };
    if (isChatSessionPending()) return { disabled: true, description: "Wait for current answer to finish" };
    if (!getChatSessionId()) return { disabled: true, description: "No active session yet" };
    if (readerState.contextCompacting) return { disabled: true, description: "Compacting already in progress" };
    return { disabled: false, description: command.description };
  }

  function matchingSlashCommands(query) {
    const normalized = normalizeText(query).toLowerCase();
    return SLASH_COMMANDS.filter((command) => {
      if (!normalized) return true;
      return command.trigger.slice(1).startsWith(normalized)
        || command.title.toLowerCase().includes(normalized);
    });
  }

  function ensureSlashCommandMenu() {
    if (state.menu) return state.menu;
    const composerBox = elements.readerChatForm?.querySelector(".ask-composer-box");
    if (!composerBox) return null;
    const menu = document.createElement("div");
    menu.className = "slash-command-menu";
    menu.id = "readerSlashCommandMenu";
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-label", "Slash commands");
    menu.hidden = true;
    composerBox.prepend(menu);
    menu.addEventListener("pointerdown", (event) => {
      event.preventDefault();
    });
    menu.addEventListener("click", (event) => {
      const button = event.target.closest("[data-slash-command]");
      if (!button || button.disabled) return;
      executeSlashCommand(button.dataset.slashCommand);
    });
    state.menu = menu;
    return menu;
  }

  function setSlashMenuOpen(open) {
    state.open = Boolean(open);
    const menu = ensureSlashCommandMenu();
    if (menu) menu.hidden = !state.open;
    elements.readerChatInput?.setAttribute("aria-expanded", String(state.open));
    if (!state.open) {
      state.query = "";
      state.items = [];
      state.activeIndex = -1;
      if (menu) menu.innerHTML = "";
    }
  }

  function slashInputQuery() {
    const input = elements.readerChatInput;
    if (!input) return null;
    const value = input.value || "";
    if (!value.startsWith("/") || value.includes("\n")) return null;
    const query = value.slice(1);
    if (/\s/.test(query)) return null;
    return query;
  }

  function firstEnabledSlashIndex(items) {
    const index = items.findIndex((item) => !item.disabled);
    return index >= 0 ? index : (items.length ? 0 : -1);
  }

  function renderSlashCommandMenu() {
    const menu = ensureSlashCommandMenu();
    if (!menu) return;
    const query = slashInputQuery();
    if (query === null) {
      setSlashMenuOpen(false);
      return;
    }

    const items = matchingSlashCommands(query).map((command) => ({
      ...command,
      ...slashCommandStatus(command),
    }));
    state.query = query;
    state.items = items;
    if (!items.length) {
      setSlashMenuOpen(false);
      return;
    }
    if (state.activeIndex < 0 || state.activeIndex >= items.length || items[state.activeIndex]?.disabled) {
      state.activeIndex = firstEnabledSlashIndex(items);
    }

    menu.innerHTML = items.map((item, index) => `
      <button class="slash-command-item${index === state.activeIndex ? " is-active" : ""}" type="button" role="option" data-slash-command="${escapeHtml(item.id)}" aria-selected="${index === state.activeIndex ? "true" : "false"}" ${item.disabled ? "disabled" : ""}>
        <span class="slash-command-mark" aria-hidden="true">${renderSlashIcon(item.icon)}</span>
        <span class="slash-command-title">${escapeHtml(item.title)}</span>
        <span class="slash-command-description">${escapeHtml(item.description)}</span>
      </button>
    `).join("");
    setSlashMenuOpen(true);
  }

  function setReaderChatInputValue(value) {
    if (!elements.readerChatInput) return;
    elements.readerChatInput.value = value;
    elements.readerChatInput.dispatchEvent(new Event("input", { bubbles: true }));
  }

  async function executeSlashCommand(commandId) {
    const command = SLASH_COMMANDS.find((item) => item.id === commandId);
    if (!command) return;
    const status = slashCommandStatus(command);
    if (status.disabled) {
      renderSlashCommandMenu();
      return;
    }
    setReaderChatInputValue("");
    setSlashMenuOpen(false);
    if (typeof closeReaderToolMenu === "function") closeReaderToolMenu();
    if (typeof closeReaderModelMenu === "function") closeReaderModelMenu();
    if (typeof setChatSessionMenuOpen === "function") setChatSessionMenuOpen(false);

    if (command.id === "new") {
      await createReaderChatSession();
    } else if (command.id === "compact") {
      await compactReaderContext();
    }
    elements.readerChatInput?.focus();
  }

  function moveSlashSelection(delta) {
    if (!state.open || !state.items.length) return;
    const enabled = state.items
      .map((item, index) => ({ item, index }))
      .filter((entry) => !entry.item.disabled);
    if (!enabled.length) return;
    const current = enabled.findIndex((entry) => entry.index === state.activeIndex);
    const nextPosition = current < 0
      ? 0
      : (current + delta + enabled.length) % enabled.length;
    state.activeIndex = enabled[nextPosition].index;
    renderSlashCommandMenu();
  }

  function handleSlashKeydown(event) {
    if (!state.open && event.key !== "/" && event.key !== "ArrowDown" && event.key !== "Enter") return;
    if (!state.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      setSlashMenuOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      event.stopImmediatePropagation();
      moveSlashSelection(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey && !event.isComposing) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const selected = state.items[state.activeIndex];
      if (selected && !selected.disabled) executeSlashCommand(selected.id);
    }
  }

  function handleSlashInput() {
    state.activeIndex = -1;
    renderSlashCommandMenu();
  }

  function initializeSlashCommands() {
    const input = elements.readerChatInput;
    if (!input) return;
    input.setAttribute("aria-controls", "readerSlashCommandMenu");
    input.setAttribute("aria-expanded", "false");
    input.addEventListener("input", handleSlashInput);
    input.addEventListener("keydown", handleSlashKeydown, true);
    input.addEventListener("blur", () => {
      window.setTimeout(() => setSlashMenuOpen(false), 120);
    });
  }

  initializeSlashCommands();
  window.renderSlashCommandMenu = renderSlashCommandMenu;
}());
