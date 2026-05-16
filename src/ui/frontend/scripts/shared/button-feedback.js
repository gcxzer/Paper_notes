(function () {
  const FEEDBACK_SELECTOR = [
    "button:not(:disabled)",
    "a.toolbar-button[href]",
    "a.settings-menu-item[href]",
    "a.note-menu-link[href]",
    ".back a[href]",
    "[role='button']:not([aria-disabled='true'])"
  ].join(",");
  const EXCLUDED_SELECTOR = ".pdf-link-hitbox, .pdf-annotation";
  const PRESS_CLASS = "is-pressing";

  function elementFromEvent(event) {
    const target = event.target?.nodeType === Node.ELEMENT_NODE
      ? event.target
      : event.target?.parentElement;
    const element = target?.closest?.(FEEDBACK_SELECTOR);
    if (!element || element.matches(EXCLUDED_SELECTOR)) return null;
    if (element.matches(":disabled, [aria-disabled='true']")) return null;
    return element;
  }

  function clearPressing() {
    document.querySelectorAll(`.${PRESS_CLASS}`).forEach((element) => {
      element.classList.remove(PRESS_CLASS);
    });
  }

  document.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const element = elementFromEvent(event);
    if (element) element.classList.add(PRESS_CLASS);
  }, true);

  document.addEventListener("pointerup", clearPressing, true);
  document.addEventListener("pointercancel", clearPressing, true);
  document.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    const element = elementFromEvent(event);
    if (element) element.classList.add(PRESS_CLASS);
  }, true);
  document.addEventListener("mouseup", clearPressing, true);
  document.addEventListener("mouseleave", clearPressing, true);
  document.addEventListener("dragstart", clearPressing, true);
}());
