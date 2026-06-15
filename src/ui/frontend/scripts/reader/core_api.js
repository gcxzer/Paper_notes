function normalizeText(value) {
  return MODEL.normalizeText(value);
}

function sanitizeVisibleAgentError(value) {
  const text = normalizeText(value);
  if (!text) return GENERIC_AGENT_ERROR;
  return SENSITIVE_AGENT_ERROR_PATTERN.test(text) ? GENERIC_AGENT_ERROR : text;
}

function sanitizeChatProgressDetail(value) {
  const text = normalizeText(value);
  if (!text) return "";
  return SENSITIVE_AGENT_ERROR_PATTERN.test(text) ? "The assistant hit a connection issue." : text;
}

function normalizeResourceHref(value) {
  return MODEL.normalizeResourceHref(value);
}

function escapeHtml(value) {
  return MODEL.escapeHtml(value);
}

function getApiUrl(path) {
  return MODEL.getApiUrl(path);
}

function createRequestId(prefix = "reader-chat") {
  if (globalThis.crypto?.randomUUID) return `${prefix}-${globalThis.crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function copyTextWithSelectionFallback(value) {
  const textarea = document.createElement("textarea");
  const activeElement = document.activeElement;
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-1000px";
  textarea.style.left = "-1000px";
  textarea.style.width = "1px";
  textarea.style.height = "1px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus({ preventScroll: true });
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    textarea.remove();
    if (activeElement && typeof activeElement.focus === "function") {
      try {
        activeElement.focus({ preventScroll: true });
      } catch (_error) {
        activeElement.focus();
      }
    }
  }
  if (!copied) throw new Error("Clipboard copy failed.");
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value) return;
  let clipboardError = null;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch (error) {
      clipboardError = error;
    }
  }
  try {
    copyTextWithSelectionFallback(value);
  } catch (error) {
    if (clipboardError && typeof error === "object" && error) {
      error.cause = clipboardError;
    }
    throw error;
  }
}

function normalizeClipboardPlainText(value) {
  return String(value || "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function elementChildIndex(element) {
  if (!element?.parentElement) return 0;
  return Array.from(element.parentElement.children).filter((child) => child.tagName === element.tagName).indexOf(element);
}

function listItemMarkerForCopy(item, context = null) {
  const queuedMarker = context?.listItemMarkers?.shift?.();
  if (queuedMarker) return queuedMarker;
  const list = item?.parentElement;
  if (!list || list.tagName !== "OL") return "- ";
  const value = Number(item.getAttribute("value"));
  if (Number.isFinite(value) && value > 0) return `${value}. `;
  const start = Number(list.getAttribute("start"));
  const base = Number.isFinite(start) && start > 0 ? start : 1;
  return `${base + elementChildIndex(item)}. `;
}

function serializeCopiedListItem(item, context = null) {
  const pieces = [];
  item.childNodes.forEach((child) => {
    if (child.nodeType === Node.ELEMENT_NODE && ["OL", "UL"].includes(child.tagName)) return;
    pieces.push(serializeCopiedSelectionNode(child, context));
  });
  const text = normalizeClipboardPlainText(pieces.join(""));
  return text ? `${listItemMarkerForCopy(item, context)}${text}` : "";
}

function serializeCopiedSelectionNode(node, context = null) {
  if (!node) return "";
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || "";
  if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return "";
  if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
    return Array.from(node.childNodes).map((child) => serializeCopiedSelectionNode(child, context)).join("");
  }

  const tag = node.tagName;
  if (tag === "BR") return "\n";
  if (tag === "OL" || tag === "UL") {
    return Array.from(node.children)
      .filter((child) => child.tagName === "LI")
      .map((child) => serializeCopiedListItem(child, context))
      .filter(Boolean)
      .join("\n") + "\n";
  }
  if (tag === "LI") return `${serializeCopiedListItem(node, context)}\n`;
  const text = Array.from(node.childNodes).map((child) => serializeCopiedSelectionNode(child, context)).join("");
  if (["P", "DIV", "SECTION", "ARTICLE", "BLOCKQUOTE", "PRE", "H1", "H2", "H3", "H4", "H5", "H6"].includes(tag)) {
    return `${text}\n`;
  }
  if (tag === "TR") return `${text}\n`;
  if (tag === "TD" || tag === "TH") return `${text}\t`;
  return text;
}

function elementFromSelectionNode(node) {
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
}

function listItemMarkerFromOriginalItem(item) {
  const list = item?.parentElement;
  if (!list || list.tagName !== "OL") return "- ";
  const value = Number(item.getAttribute("value"));
  if (Number.isFinite(value) && value > 0) return `${value}. `;
  const start = Number(list.getAttribute("start"));
  const base = Number.isFinite(start) && start > 0 ? start : 1;
  return `${base + elementChildIndex(item)}. `;
}

function copiedSelectionContext(range) {
  const root = elementFromSelectionNode(range.commonAncestorContainer);
  const list = root?.closest?.("ol, ul") || root?.querySelector?.("ol, ul") || null;
  const items = list
    ? Array.from(list.children).filter((child) => child.tagName === "LI" && range.intersectsNode(child))
    : [];
  return {
    listItemMarkers: items.map(listItemMarkerFromOriginalItem)
  };
}

function copiedSelectionTextWithListMarkers(selection) {
  if (!selection || selection.rangeCount <= 0 || selection.isCollapsed) return "";
  const chunks = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    chunks.push(serializeCopiedSelectionNode(range.cloneContents(), copiedSelectionContext(range)));
  }
  return normalizeClipboardPlainText(chunks.join("\n"));
}

function scopedSelectionRange(range, container) {
  if (!range || !container || !range.intersectsNode(container)) return null;
  const scoped = range.cloneRange();
  if (!container.contains(range.startContainer)) {
    scoped.setStart(container, 0);
  }
  if (!container.contains(range.endContainer)) {
    scoped.setEnd(container, container.childNodes.length);
  }
  return scoped;
}

function copiedSelectionTextWithinContainer(selection, container) {
  if (!container || !selection || selection.rangeCount <= 0 || selection.isCollapsed) return "";
  const chunks = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = scopedSelectionRange(selection.getRangeAt(index), container);
    if (!range) continue;
    chunks.push(serializeCopiedSelectionNode(range.cloneContents(), copiedSelectionContext(range)));
  }
  return normalizeClipboardPlainText(chunks.join("\n"));
}

function handleRichTextCopy(event) {
  if (event.defaultPrevented || event.target?.closest?.("input, textarea, [contenteditable='true']")) return;
  const selection = window.getSelection();
  const container = event.currentTarget?.nodeType === Node.ELEMENT_NODE ? event.currentTarget : null;
  const text = container
    ? copiedSelectionTextWithinContainer(selection, container)
    : copiedSelectionTextWithListMarkers(selection);
  if (!text || !event.clipboardData) return;
  event.preventDefault();
  event.clipboardData.setData("text/plain", text);
}

const copyFeedbackTimers = new WeakMap();

function showCopyFeedback(button) {
  if (!button) return;
  const existingTimer = copyFeedbackTimers.get(button);
  if (existingTimer) window.clearTimeout(existingTimer);
  button.classList.add("is-copied");
  button.setAttribute("aria-label", "Copied");
  button.setAttribute("title", "Copied");
  const timer = window.setTimeout(() => {
    button.classList.remove("is-copied");
    button.setAttribute("aria-label", "Copy message");
    button.setAttribute("title", "Copy");
    copyFeedbackTimers.delete(button);
  }, 2500);
  copyFeedbackTimers.set(button, timer);
}

function addReaderActionMenuOption(menu, {
  className = "",
  text = "",
  html = "",
  ariaLabel = "",
  dataset = {},
  onClick = () => {},
}) {
  const button = document.createElement("button");
  button.className = `ask-session-menu-option ${className}`.trim();
  button.type = "button";
  if (html) {
    button.innerHTML = html;
  } else {
    button.textContent = text;
  }
  if (ariaLabel) button.setAttribute("aria-label", ariaLabel);
  Object.entries(dataset || {}).forEach(([key, value]) => {
    button.dataset[key] = normalizeText(value);
  });
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  menu.appendChild(button);
  return button;
}

function positionReaderActionMenu(menu, row, {
  popover,
  buttonSelector,
  gap = 8,
  maxHeight = 0,
} = {}) {
  if (!popover || !row) return;
  const popoverRect = popover.getBoundingClientRect();
  const rowRect = row.getBoundingClientRect();
  const buttonRect = row.querySelector(buttonSelector)?.getBoundingClientRect() || rowRect;
  if (maxHeight) {
    menu.style.maxHeight = `${Math.round(maxHeight)}px`;
  }
  const menuRect = menu.getBoundingClientRect();
  const left = Math.max(
    8,
    Math.min(
      buttonRect.left - popoverRect.left - menuRect.width - gap,
      popoverRect.width - menuRect.width - 8
    )
  );
  const top = Math.max(
    8,
    Math.min(
      rowRect.top - popoverRect.top,
      popoverRect.height - menuRect.height - 8
    )
  );
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
  menu.style.visibility = "";
}

class AgentRequestError extends Error {
  constructor(message, { status = 0, code = "", payload = null } = {}) {
    super(message);
    this.name = "AgentRequestError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

async function fetchAgentJson(path, { method = "GET", body = null } = {}) {
  const options = {
    method,
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  };
  const response = await fetch(getApiUrl(path), options);
  if (!response.ok) {
    throw await readAgentError(response);
  }
  return response.json();
}

async function fetchAgentEventStream(path, { body, onEvent, signal } = {}) {
  const response = await fetch(getApiUrl(path), {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    signal
  });
  if (!response.ok) {
    throw await readAgentError(response);
  }
  if (!response.body || typeof response.body.getReader !== "function") {
    throw new AgentRequestError("Streaming is not supported by this browser.", { code: "stream_unsupported" });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = drainSseBuffer(buffer, onEvent);
  }
  buffer += decoder.decode();
  drainSseBuffer(`${buffer}\n\n`, onEvent);
}

function drainSseBuffer(buffer, onEvent) {
  let remaining = buffer;
  while (true) {
    const boundary = remaining.indexOf("\n\n");
    if (boundary < 0) return remaining;
    const frame = remaining.slice(0, boundary);
    remaining = remaining.slice(boundary + 2);
    const parsed = parseSseFrame(frame);
    if (parsed) onEvent(parsed);
  }
}

function parseSseFrame(frame) {
  const lines = String(frame || "").split(/\r?\n/);
  let event = "message";
  const dataLines = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = normalizeText(line.slice(6)) || "message";
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }
  if (!dataLines.length) return { event, data: {} };
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch (error) {
    return { event, data: { text: dataLines.join("\n") } };
  }
}

async function readAgentError(response) {
  try {
    const payload = await response.clone().json();
    return new AgentRequestError(
      normalizeText(payload?.error) || `Agent request failed (${response.status})`,
      {
        status: response.status,
        code: normalizeText(payload?.code),
        payload
      }
    );
  } catch (error) {
    const text = await response.text().catch(() => "");
    return new AgentRequestError(
      normalizeText(text) || `Agent request failed (${response.status})`,
      { status: response.status }
    );
  }
}
