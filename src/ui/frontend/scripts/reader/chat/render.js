function renderChatToolActivity(toolActivity, { showActions = true, activityScope = "" } = {}) {
  const items = groupToolActivityItems(collapseIntermediateToolActivity(normalizeToolActivity(toolActivity)));
  if (!items.length) return "";
  return `
    <div class="ask-tool-activity" aria-label="Tool activity">
      ${items.map((item) => {
        const showView = toolActivityChangesHtmlNote(item);
        const viewNoteId = normalizeText(item.noteId) || (showView ? currentChatNoteId() : "");
        const viewHeading = toolActivityViewHeading(item);
        const viewAddedHeadings = toolActivityAddedHeadings(item);
        return `
        <div class="ask-tool-activity-item">
          <div class="ask-tool-activity-copy">
            <strong>${escapeHtml(toolDisplayName(item.name))}</strong>
            <span>${escapeHtml(toolActivitySummary(item))}</span>
          </div>
          ${showActions && showView && viewNoteId ? `
            <div class="ask-tool-activity-actions">
              <button
                class="ask-tool-action"
                type="button"
                data-tool-view-note="${escapeHtml(viewNoteId)}"
                data-tool-view-heading="${escapeHtml(viewHeading)}"
                data-tool-view-position="${escapeHtml(item.position)}"
                data-tool-view-added-headings="${escapeHtml(JSON.stringify(viewAddedHeadings))}"
              >View</button>
            </div>
          ` : ""}
        </div>
      `;
      }).join("")}
    </div>
  `;
}

function collapseIntermediateToolActivity(items) {
  const latestByWriteTarget = new Map();
  items.forEach((item, index) => {
    const key = intermediateToolActivityKey(item);
    if (!key) return;
    latestByWriteTarget.set(key, index);
  });
  return items.filter((item, index) => {
    const key = intermediateToolActivityKey(item);
    return !key || latestByWriteTarget.get(key) === index;
  });
}

function intermediateToolActivityKey(item) {
  if (!item || !["write_note", "manage_annotations", "write_note_media"].includes(item.name)) return "";
  const fileKey = toolActivityChangedFileKey(item);
  if (!fileKey) return "";
  return [
    item.name,
    normalizeText(item.sessionId),
    normalizeText(item.noteId) || currentChatNoteId(),
    fileKey
  ].join("|");
}

function groupToolActivityItems(items) {
  const grouped = [];
  items.forEach((item) => {
    const previous = grouped[grouped.length - 1];
    if (canMergeToolActivity(previous, item)) {
      previous.count += 1;
      previous.changedFiles = mergeToolActivityChangedFiles(previous.changedFiles, item.changedFiles);
      return;
    }
    grouped.push({
      ...item,
      count: 1
    });
  });
  return grouped;
}

function canMergeToolActivity(previous, item) {
  if (!previous || !item) return false;
  if (!isAnnotationDeleteActivity(previous) || !isAnnotationDeleteActivity(item)) return false;
  if (previous.sessionId !== item.sessionId || previous.noteId !== item.noteId) return false;
  return toolActivityChangedFileKey(previous) === toolActivityChangedFileKey(item);
}

function isAnnotationDeleteActivity(item) {
  if (!item || item.name !== "manage_annotations") return false;
  const text = normalizeText(item.summary || item.toolMessage || item.message).toLowerCase();
  return text === "deleted annotation." && toolActivityChangesAnnotations(item);
}

function toolActivityChangedFileKey(item) {
  return (item.changedFiles || []).map((file) => normalizeText(file.path)).sort().join("|");
}

function toolActivityAddedHeadings(item) {
  return (Array.isArray(item?.addedHeadings) ? item.addedHeadings : [])
    .map(normalizeText)
    .filter(Boolean);
}

function toolActivityViewHeading(item) {
  const addedHeadings = toolActivityAddedHeadings(item);
  return addedHeadings[addedHeadings.length - 1] || normalizeText(item?.heading);
}

function mergeToolActivityChangedFiles(left, right) {
  const byPath = new Map();
  [...(left || []), ...(right || [])].forEach((file) => {
    const path = normalizeText(file?.path);
    if (!path) return;
    byPath.set(path, {
      path,
      beforeBytes: Math.max(Number(byPath.get(path)?.beforeBytes) || 0, Number(file.beforeBytes) || 0),
      afterBytes: Math.max(Number(byPath.get(path)?.afterBytes) || 0, Number(file.afterBytes) || 0)
    });
  });
  return [...byPath.values()];
}

function toolActivityChangesHtmlNote(item) {
  return (item.changedFiles || []).some((file) => {
    const path = normalizeText(file?.path).toLowerCase();
    return path.endsWith(".html") && (path.includes("paper-html/") || path.includes("paper-html\\") || path.includes("/paper-html") || path.includes("\\paper-html"));
  });
}

function toolActivityChangesAnnotations(item) {
  return (item.changedFiles || []).some((file) => {
    const path = normalizeText(file?.path).toLowerCase();
    return path.endsWith(".json") && (path.includes("annotations/") || path.includes("annotations\\"));
  });
}

function chatPayloadChangesAnnotations(payload) {
  return normalizeToolActivity(payload?.message?.toolActivity).some(toolActivityChangesAnnotations);
}

function chatPayloadChangesHtmlNote(payload) {
  const messageActivities = normalizeToolActivity(payload?.message?.toolActivity);
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  const historyActivities = messages.flatMap((message) => normalizeToolActivity(message?.toolActivity));
  return [...messageActivities, ...historyActivities].some(toolActivityChangesHtmlNote);
}

function chatPayloadWritesHtmlNote(payload) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  const eventGroups = [
    payload?.events,
    payload?.runTrace?.events,
    payload?.message?.runTrace?.events,
    ...messages.map((message) => message?.runTrace?.events),
  ];
  if (eventGroups.some((events) => (Array.isArray(events) ? events : []).some(workTraceItemWritesHtmlNote))) {
    return true;
  }
  const workTraces = [
    payload?.message?.workTrace,
    ...messages.map((message) => message?.workTrace),
  ];
  return workTraces.some((trace) => (
    (Array.isArray(trace?.items) ? trace.items : []).some(workTraceItemWritesHtmlNote)
  ));
}

function workTraceItemWritesHtmlNote(item) {
  const type = normalizeText(item?.type || item?.traceType || item?.stage);
  if (type && type !== "tool" && !type.includes("tool")) return false;
  const data = item?.data && typeof item.data === "object" ? item.data : {};
  const nested = data.data && typeof data.data === "object" ? data.data : {};
  const toolName = normalizeText(
    item?.toolName
    || data.toolName
    || nested.toolName
    || item?.name
  );
  if (!["write_note", "write_note_media"].includes(toolName)) return false;
  const text = normalizeText(item?.text || item?.message || item?.detail).toLowerCase();
  return item?.complete === true
    || data.complete === true
    || nested.complete === true
    || data.statusComplete === true
    || nested.statusComplete === true
    || text.startsWith("tool completed:");
}

function toolActivitySummary(item) {
  if (isAnnotationDeleteActivity(item) && Number(item.count) > 1) {
    return `Deleted ${Math.round(Number(item.count))} annotations.`;
  }
  if (item.summary) return item.summary;
  if (item.toolMessage) return item.toolMessage;
  if (item.message) return item.message;
  const files = item.changedFiles.map((file) => file.path).join(", ");
  return files || "Local note files changed.";
}

function toolDisplayName(name) {
  if (name === "write_note") return "Updated note";
  if (name === "manage_annotations") return "Updated annotation";
  if (name === "write_note_media") return "Updated note media";
  if (name === "append_note_section") return "Appended note section";
  if (name === "replace_note_section") return "Replaced note section";
  if (name === "write_note_section") return "Updated note section";
  if (name === "update_note_metadata") return "Updated note metadata";
  if (name === "update_annotation") return "Updated annotation";
  if (name === "create_annotation") return "Created annotation";
  if (name === "delete_annotation") return "Deleted annotation";
  if (name === "create_image_artifact") return "Generated image";
  if (name === "create_file_artifact") return "Created file";
  return name;
}


function latestReaderUserMessageIndex() {
  for (let index = readerState.chatMessages.length - 1; index >= 0; index -= 1) {
    if (readerState.chatMessages[index]?.role === "user") return index;
  }
  return -1;
}


function renderReaderUserMessageActions(message, index, latestUserIndex) {
  if (message.role !== "user" || !message.text) return "";
  const canEdit = index === latestUserIndex && !isChatSessionPending();
  const editButton = canEdit
    ? `<button type="button" class="ask-message-action ask-message-action-edit" data-user-message-edit="${index}" aria-label="Edit latest message" title="Edit latest message">
        <span aria-hidden="true">✎</span>
        <span>Edit</span>
      </button>`
    : "";
  return `
    <div class="ask-message-actions">
      ${editButton}
      <button type="button" class="ask-message-action ask-message-action-copy" data-user-message-copy="${index}" aria-label="Copy message" title="Copy">
        <span aria-hidden="true">⧉</span>
        <span class="copy-feedback" aria-hidden="true">Copied</span>
        <span class="sr-only">Copy</span>
      </button>
    </div>
  `;
}

function renderReaderUserMessageEdit(message, index) {
  const value = readerState.chatEditingIndex === index ? readerState.chatEditingText : message.text;
  return `
    <form class="ask-message-edit" data-user-message-edit-form="${index}">
      <textarea data-user-message-edit-input="${index}" rows="2">${escapeHtml(value)}</textarea>
      <div class="ask-message-edit-actions">
        <button type="submit">Send</button>
        <button type="button" data-user-message-edit-cancel="${index}">Cancel</button>
      </div>
    </form>
  `;
}

function readerChatIsNearBottom(container = elements.readerChatMessages) {
  if (!container) return true;
  const distance = container.scrollHeight - container.clientHeight - container.scrollTop;
  return distance < 96;
}

function renderReaderChatMessages({ scrollToBottom = false, forceScrollToBottom = false, preserveScrollTop = false } = {}) {
  if (!elements.readerChatMessages) return;
  const previousScrollTop = elements.readerChatMessages.scrollTop;
  const wasNearBottom = readerChatIsNearBottom(elements.readerChatMessages);
  const manualContextCompactionHtml = renderManualContextCompactionProgress();
  if (!readerState.chatMessages.length && !isChatSessionPending() && !manualContextCompactionHtml) {
    elements.readerChatMessages.innerHTML = `
      <div class="ask-empty-chat">
        <p>Ask about this paper, or tell me what to do.</p>
      </div>
    `;
    return;
  }

  const latestUserIndex = latestReaderUserMessageIndex();
  const chatProgressHtml = `${renderChatProgress()}${manualContextCompactionHtml}`;
  const streamingAssistantIndex = isChatSessionPending()
    ? readerState.chatMessages.findIndex((message, index) => (
      index > latestUserIndex
      && message?.role === "assistant"
      && message.streaming
    ))
    : -1;
  let insertedProgress = false;
  const messagesHtml = readerState.chatMessages.map((rawMessage, index) => {
    const message = normalizeChatMessage(rawMessage);
    const progressBeforeMessage = !insertedProgress && index === streamingAssistantIndex ? chatProgressHtml : "";
    if (progressBeforeMessage) insertedProgress = true;
    if (message.role === "divider") {
      return `${progressBeforeMessage}${renderChatDivider(message)}`;
    }
    const nextCompactionMarkerHtml = message.role === "user"
      ? messageContextCompactionMarker(readerState.chatMessages[index + 1])
      : "";
    const sourcesHtml = message.role === "assistant" ? renderChatSources(message.sources) : "";
    const imageHtml = renderChatImages([...(message.attachments || []), ...(message.artifacts || [])]);
    const toolActivityHtml = message.role === "assistant" ? renderChatToolActivity(message.toolActivity, { activityScope: `message-${index}` }) : "";
    const previousMessage = normalizeChatMessage(readerState.chatMessages[index - 1]);
    const moveCompactionMarkerToPreviousUser = message.role === "assistant"
      && previousMessage.role === "user"
      && Boolean(renderContextCompactionMarker(message.runTrace?.events));
    const compactionMarkerHtml = message.role === "assistant" && !moveCompactionMarkerToPreviousUser
      ? renderContextCompactionMarker(message.runTrace?.events)
      : "";
    const traceHtml = message.role === "assistant" ? renderRunTraceSummary(message.runTrace, message.workTrace) : "";
    const editing = message.role === "user" && readerState.chatEditingIndex === index;
    const userContextBadgesHtml = message.role === "user" ? renderUserContextBadges(message) : "";
    const userActionsHtml = renderReaderUserMessageActions(message, index, latestUserIndex);
    const bubbleHtml = editing
      ? renderReaderUserMessageEdit(message, index)
      : message.text
        ? `<div class="ask-bubble">${rawMessage.streaming ? renderStreamingChatText(message.text) : renderChatMarkdown(message.text)}</div>`
        : "";
    return `${progressBeforeMessage}${nextCompactionMarkerHtml}${compactionMarkerHtml}
    <div class="ask-message ask-message-${message.role}${message.error ? " ask-message-error" : ""}" data-chat-message-index="${index}">
      <div class="ask-message-stack">
        ${traceHtml}
        ${bubbleHtml}
        ${imageHtml}
        ${userContextBadgesHtml}
        ${editing ? "" : userActionsHtml}
        ${sourcesHtml}
        ${toolActivityHtml}
      </div>
    </div>
  `;
  }).join("");
  elements.readerChatMessages.innerHTML = `${messagesHtml}${insertedProgress ? "" : chatProgressHtml}`;
  const keepScrolledToBottom = forceScrollToBottom || (scrollToBottom && wasNearBottom);
  if (keepScrolledToBottom) {
    elements.readerChatMessages.scrollTop = elements.readerChatMessages.scrollHeight;
  } else if (preserveScrollTop || scrollToBottom) {
    elements.readerChatMessages.scrollTop = previousScrollTop;
    requestAnimationFrame(() => {
      if (elements.readerChatMessages) elements.readerChatMessages.scrollTop = previousScrollTop;
    });
  }
  scheduleChatMermaidRender(elements.readerChatMessages, { keepScrolledToBottom });
}

function latestReaderStreamingAssistantMessageIndex() {
  for (let index = readerState.chatMessages.length - 1; index >= 0; index -= 1) {
    const message = readerState.chatMessages[index];
    if (message?.role === "user") return -1;
    if (message?.role === "assistant" && message.streaming) return index;
  }
  return -1;
}

function renderReaderStreamingAssistantMessage({ scrollToBottom = false } = {}) {
  const container = elements.readerChatMessages;
  if (!container) return false;
  const index = latestReaderStreamingAssistantMessageIndex();
  if (index < 0) return false;
  const rawMessage = readerState.chatMessages[index];
  const message = normalizeChatMessage(rawMessage);
  const messageElement = container.querySelector(`.ask-message[data-chat-message-index="${index}"]`);
  const bubble = messageElement?.querySelector(".ask-message-stack > .ask-bubble");
  if (!messageElement || !bubble) return false;

  const previousScrollTop = container.scrollTop;
  const wasNearBottom = readerChatIsNearBottom(container);
  bubble.innerHTML = renderStreamingChatText(message.text);

  const keepScrolledToBottom = scrollToBottom && wasNearBottom;
  if (keepScrolledToBottom) {
    container.scrollTop = container.scrollHeight;
  } else {
    container.scrollTop = previousScrollTop;
    requestAnimationFrame(() => {
      if (container.isConnected) container.scrollTop = previousScrollTop;
    });
  }
  scheduleChatMermaidRender(bubble, { keepScrolledToBottom });
  return true;
}

function renderUserGenerationBadge(generation, attachments = []) {
  const label = generationRequestLabel(generation, attachments);
  if (!label) return "";
  return `<div class="ask-user-generation-badge">${escapeHtml(label)}</div>`;
}

function renderUserSelectedTextBadge(selectedTextContext) {
  const context = normalizeSelectedTextContext(selectedTextContext);
  if (!context) return "";
  const wordCount = Number(context.wordCount) || context.text.split(/\s+/).filter(Boolean).length;
  return `<div class="ask-user-generation-badge ask-user-selected-text-badge" data-selected-text-preview="${escapeHtml(context.text)}" aria-label="Selected text preview">Text selected: ${wordCount} ${wordCount === 1 ? "word" : "words"}</div>`;
}

function renderUserContextBadges(message) {
  return [
    renderUserGenerationBadge(message.generation, message.attachments),
    renderUserSelectedTextBadge(message.selectedTextContext)
  ].filter(Boolean).join("");
}

function renderChatDivider(message) {
  const text = ["context_compaction_marker", "context_compaction"].includes(message.markerType)
    ? "Context compacted"
    : (message.text || "Divider");
  return `
    <div class="ask-message-divider" role="status">
      <span></span>
      <strong>${escapeHtml(text)}</strong>
      <span></span>
    </div>
  `;
}

function renderStreamingChatText(text) {
  return `${renderChatMarkdown(text)}<span class="ask-stream-caret" aria-hidden="true"></span>`;
}

function preserveReaderChatScrollTop(callback) {
  const container = elements.readerChatMessages;
  if (!container) {
    callback();
    return;
  }
  const previousScrollTop = container.scrollTop;
  callback();
  container.scrollTop = previousScrollTop;
  requestAnimationFrame(() => {
    container.scrollTop = previousScrollTop;
  });
}

function handleChatProgressClick(event) {
  const button = event.target.closest("[data-chat-cancel]");
  if (!button) return;
  event.preventDefault();
  cancelReaderChatRequest();
}

async function refreshCurrentNoteAfterToolUndo() {
  const noteId = currentChatNoteId();
  if (!noteId) return;
  const library = await readDefaultLibrary().catch(() => null);
  if (library) {
    readerState.library = library;
    const nextNote = library.notes.find((entry) => entry.id === noteId);
    if (nextNote) updateCurrentNote(nextNote);
  }
  const noteBody = await fetchGeneratedNoteBody(readerState.note);
  if (noteBody && elements.notePage) {
    elements.notePage.innerHTML = noteBody;
    if (typeof window.buildNoteMenu === "function") window.buildNoteMenu(elements.notePage);
    mountReaderNoteMenu();
  }
  await refreshAnnotationsFromServer({ preserveOpenEditor: true, statusText: "" });
}

function parseToolActivityAddedHeadings(value) {
  try {
    const parsed = JSON.parse(normalizeText(value) || "[]");
    return (Array.isArray(parsed) ? parsed : []).map(normalizeText).filter(Boolean);
  } catch (_error) {
    return [];
  }
}

function normalizeToolActivityViewTarget(target) {
  if (target && typeof target === "object") {
    const addedHeadings = (Array.isArray(target.addedHeadings) ? target.addedHeadings : [])
      .map(normalizeText)
      .filter(Boolean);
    return {
      noteId: normalizeText(target.noteId),
      heading: normalizeText(target.heading),
      position: normalizeText(target.position),
      addedHeadings
    };
  }
  return {
    noteId: normalizeText(target),
    heading: "",
    position: "",
    addedHeadings: []
  };
}

function noteHeadingVisibleText(heading) {
  if (!heading) return "";
  const clone = heading.cloneNode(true);
  clone.querySelectorAll("button, .note-heading-toggle").forEach((node) => node.remove());
  return normalizeText(clone.textContent || heading.textContent).toLowerCase();
}

function findNoteHeadingByText(text, { prefer = "first" } = {}) {
  const target = normalizeText(text).toLowerCase();
  if (!target || !elements.notePage) return null;
  const matches = Array.from(elements.notePage.querySelectorAll("h1, h2, h3, h4"))
    .filter((heading) => noteHeadingVisibleText(heading) === target);
  if (!matches.length) return null;
  return prefer === "last" ? matches[matches.length - 1] : matches[0];
}

function scrollNotePaneToElement(element, behavior = "smooth") {
  const pane = elements.notePane;
  if (!pane || !element) return false;
  const paneBox = pane.getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  const anchorOffset = typeof noteScrollAnchorOffset === "function"
    ? noteScrollAnchorOffset()
    : Math.round(Math.min(Math.max(pane.clientHeight * 0.16, 56), 150));
  const maxScroll = Math.max(0, pane.scrollHeight - pane.clientHeight);
  const targetTop = pane.scrollTop + rect.top - paneBox.top - anchorOffset;
  pane.scrollTo({
    top: Math.min(Math.max(targetTop, 0), maxScroll),
    behavior
  });
  return true;
}

function scrollNotePaneToToolActivityTarget(target) {
  const addedHeadings = (Array.isArray(target.addedHeadings) ? target.addedHeadings : [])
    .map(normalizeText)
    .filter(Boolean);
  const heading = addedHeadings[addedHeadings.length - 1] || normalizeText(target.heading);
  const position = normalizeText(target.position);
  const prefer = addedHeadings.length && position !== "prepend" ? "last" : "first";
  const headingElement = findNoteHeadingByText(heading, { prefer });
  if (headingElement && scrollNotePaneToElement(headingElement, "smooth")) return true;
  if (position === "append" && elements.notePane) {
    elements.notePane.scrollTo({
      top: Math.max(0, elements.notePane.scrollHeight - elements.notePane.clientHeight),
      behavior: "smooth"
    });
    return false;
  }
  elements.notePane?.scrollTo({ top: 0, behavior: "smooth" });
  return false;
}

async function viewToolActivityNote(target) {
  const viewTarget = normalizeToolActivityViewTarget(target);
  const targetNoteId = viewTarget.noteId;
  if (!targetNoteId) return;
  if (targetNoteId && targetNoteId !== currentChatNoteId()) {
    setReaderChatError("Open that note from the library to view the change.");
    return;
  }
  await refreshCurrentNoteAfterToolUndo();
  setHtmlPaneVisible(true);
  await new Promise((resolve) => window.requestAnimationFrame(resolve));
  scrollNotePaneToToolActivityTarget(viewTarget);
}

async function handleToolActivityClick(event) {
  const viewButton = event.target.closest("[data-tool-view-note]");
  if (viewButton) {
    event.preventDefault();
    await viewToolActivityNote({
      noteId: viewButton.dataset.toolViewNote,
      heading: viewButton.dataset.toolViewHeading,
      position: viewButton.dataset.toolViewPosition,
      addedHeadings: parseToolActivityAddedHeadings(viewButton.dataset.toolViewAddedHeadings)
    });
    return;
  }
}
