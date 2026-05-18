const pdfjsLib = globalThis.pdfjsLib;

if (pdfjsLib) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "/node_modules/pdfjs-dist/legacy/build/pdf.worker.mjs";
}

const STORAGE_KEY = "paper-notes-library-v14";
const FILE_DB_NAME = "paper-notes-files-v1";
const FILE_STORE_NAME = "paper-files";
const READER_SPLIT_KEY = "paper-notes-reader-split-v1";
const ANNOTATION_SIDEBAR_KEY = "paper-notes-annotation-sidebar-v1";
const ANNOTATION_SIDEBAR_WIDTH_KEY = "paper-notes-annotation-sidebar-width-v1";
const HTML_PANE_KEY = "paper-notes-html-pane-v1";
const ASK_PANE_KEY = "paper-notes-ask-pane-v1";
const ASK_WIDTH_KEY = "paper-notes-ask-width-v1";
const HTML_ZOOM_KEY = "paper-notes-html-zoom-v1";
const PDF_SCROLL_KEY = "paper-notes-pdf-scroll-v1";
const NOTE_SCROLL_KEY = "paper-notes-note-scroll-v1";
const CHAT_SESSION_STORE_KEY = "paper-notes-agent-session-by-note-v1";
const ACTIVE_CHAT_RUN_STORE_KEY = "paper-notes-agent-active-run-by-session-v1";
const WRITE_TOOL_MODE_KEY = "paper-notes-agent-write-tool-mode-v1";
const READER_MODEL_SELECTION_KEY = "paper-notes-reader-model-selection-v1";
const DEEPSEEK_THINK_MODE_KEY = "paper-notes-deepseek-think-mode-v1";
const GPT_THINK_MODE_KEY = "paper-notes-gpt-think-mode-v1";
const GEMINI_THINK_MODE_KEY = "paper-notes-gemini-think-mode-v1";
const ANTHROPIC_THINK_MODE_KEY = "paper-notes-anthropic-think-mode-v1";
const SAVED_PROMPTS_KEY = "paper-notes-saved-prompts-v1";
const ALL_CATEGORY_ID = "all";
const UNCATEGORIZED_ID = "uncategorized";
const MODEL = window.PaperNotesModel;
const PDF_MIN_SCALE = 0.7;
const PDF_MAX_SCALE = 4;
const PDF_SCALE_STEP = 0.1;
const ANNOTATION_SIDEBAR_DEFAULT_WIDTH = 218;
const ANNOTATION_SIDEBAR_MIN_WIDTH = 176;
const ANNOTATION_SIDEBAR_MAX_WIDTH = 360;
const GENERIC_AGENT_ERROR = "The assistant request failed. Check the selected model and try again.";
const SENSITIVE_AGENT_ERROR_PATTERN = /(SSL validation failed|ValidationException|AccessDeniedException|runtimeClientError|\[Errno\s+\d+\]|No such file or directory|api[_ -]?key|secret|token)/i;
const FILE_GENERATION_FORMATS = new Set(["markdown", "text", "json", "csv", "html"]);

const elements = {
  layout: document.querySelector("#readerLayout"),
  error: document.querySelector("#readerError"),
  title: document.querySelector("#readerTitle"),
  kicker: document.querySelector("#readerKicker"),
  pdfViewer: document.querySelector("#pdfViewer"),
  notePane: document.querySelector(".note-pane"),
  askPane: document.querySelector("#askPane"),
  notePage: document.querySelector("#notePage"),
  resizer: document.querySelector("#readerResizer"),
  askResizer: document.querySelector("#askResizer"),
  annotationStatus: document.querySelector("#annotationStatus"),
  annotationList: document.querySelector("#annotationList"),
  annotationCount: document.querySelector("#annotationCount"),
  annotationSidebarToolbarToggle: document.querySelector("#annotationSidebarToolbarToggle"),
  annotationSidebarToggle: document.querySelector("#annotationSidebarToggle"),
  annotationSidebarResizer: document.querySelector("#annotationSidebarResizer"),
  pdfBody: document.querySelector(".pdf-body"),
  htmlPaneToggle: document.querySelector("#htmlPaneToggle"),
  askPaneToggle: document.querySelector("#askPaneToggle"),
  closeAskPane: document.querySelector("#closeAskPane"),
  chatSessionMenuButton: document.querySelector("#chatSessionMenuButton"),
  chatSessionArchivedButton: document.querySelector("#chatSessionArchivedButton"),
  chatSessionTrashButton: document.querySelector("#chatSessionTrashButton"),
  chatSessionViewButtons: Array.from(document.querySelectorAll("[data-session-view]")),
  chatSessionPopover: document.querySelector("#chatSessionPopover"),
  chatSessionPopoverTitle: document.querySelector("#chatSessionPopoverTitle"),
  newChatSession: document.querySelector("#newChatSession"),
  readerContextButton: document.querySelector("#readerContextButton"),
  readerContextPopover: document.querySelector("#readerContextPopover"),
  readerModelMenuButton: document.querySelector("#readerModelMenuButton"),
  readerModelPopover: document.querySelector("#readerModelPopover"),
  readerToolMenuButton: document.querySelector("#readerToolMenuButton"),
  readerToolPopover: document.querySelector("#readerToolPopover"),
  readerToolBack: document.querySelector("#readerToolBack"),
  readerToolTitle: document.querySelector("#readerToolTitle"),
  readerToolSubtitle: document.querySelector("#readerToolSubtitle"),
  readerToolRoot: document.querySelector("#readerToolRoot"),
  readerToolNoteWriting: document.querySelector("#readerToolNoteWriting"),
  readerToolSnapshots: document.querySelector("#readerToolSnapshots"),
  readerToolFileGeneration: document.querySelector("#readerToolFileGeneration"),
  readerToolSavedPrompts: document.querySelector("#readerToolSavedPrompts"),
  readerSnapshotList: document.querySelector("#readerSnapshotList"),
  readerToolStatus: document.querySelector("#readerToolStatus"),
  readerModelBack: document.querySelector("#readerModelBack"),
  readerModelTitle: document.querySelector("#readerModelTitle"),
  readerModelProvider: document.querySelector("#readerModelProvider"),
  readerProviderList: document.querySelector("#readerProviderList"),
  readerModelList: document.querySelector("#readerModelList"),
  readerModelStatus: document.querySelector("#readerModelStatus"),
  clearTrashSessions: document.querySelector("#clearTrashSessions"),
  chatSessionSearch: document.querySelector("#chatSessionSearch"),
  chatSessionList: document.querySelector("#chatSessionList"),
  readerChatForm: document.querySelector("#readerChatForm"),
  readerChatMessages: document.querySelector("#readerChatMessages"),
  readerChatInput: document.querySelector("#readerChatInput"),
  readerAttachmentInput: document.querySelector("#readerAttachmentInput"),
  readerImageInput: document.querySelector("#readerAttachmentInput") || document.querySelector("#readerImageInput"),
  readerAttachmentTray: document.querySelector("#readerAttachmentTray"),
  readerChatError: document.querySelector("#readerChatError"),
  sendReaderChat: document.querySelector("#sendReaderChat"),
  clearReaderChat: document.querySelector("#clearReaderChat"),
  savedPromptDialog: document.querySelector("#readerSavedPromptDialog"),
  savedPromptDialogTitle: document.querySelector("#readerSavedPromptDialogTitle"),
  savedPromptForm: document.querySelector("#readerSavedPromptForm"),
  savedPromptIdInput: document.querySelector("#readerSavedPromptId"),
  savedPromptTitleInput: document.querySelector("#readerSavedPromptTitle"),
  savedPromptContentInput: document.querySelector("#readerSavedPromptContent"),
  savedPromptStatus: document.querySelector("#readerSavedPromptStatus"),
  savedPromptIconButton: document.querySelector("#readerSavedPromptIconButton"),
  savedPromptIconPreview: document.querySelector("#readerSavedPromptIconPreview"),
  savedPromptIconPanel: document.querySelector("#readerSavedPromptIconPanel"),
  savedPromptIconGrid: document.querySelector("#readerSavedPromptIconGrid"),
  savedPromptIconSearch: document.querySelector("#readerSavedPromptIconSearch"),
  saveSavedPrompt: document.querySelector("#readerSaveSavedPrompt"),
  savedPromptToolButton: document.querySelector("#readerSavedPromptToolButton"),
  savedPromptToolLabel: document.querySelector("#readerSavedPromptToolLabel"),
  savedPromptToolChip: document.querySelector("#readerSavedPromptToolChip"),
  savedPromptToolChipLabel: document.querySelector("#readerSavedPromptToolChipLabel"),
  savedPromptToolPanel: document.querySelector("#readerSavedPromptToolPanel"),
  savedPromptFormatOptions: document.querySelector("#readerSavedPromptFormatOptions"),
  closeSavedPromptDialog: document.querySelector("#readerCloseSavedPromptDialog"),
  cancelSavedPromptDialog: document.querySelector("#readerCancelSavedPromptDialog"),
  savedPromptManageDialog: document.querySelector("#readerSavedPromptManageDialog"),
  savedPromptManageList: document.querySelector("#readerSavedPromptManageList"),
  closeSavedPromptManageDialog: document.querySelector("#readerCloseSavedPromptManageDialog"),
  savedPromptDeleteDialog: document.querySelector("#readerSavedPromptDeleteDialog"),
  savedPromptDeleteMessage: document.querySelector("#readerSavedPromptDeleteMessage"),
  cancelSavedPromptDelete: document.querySelector("#readerCancelSavedPromptDelete"),
  confirmSavedPromptDelete: document.querySelector("#readerConfirmSavedPromptDelete"),
  clearTrashDialog: document.querySelector("#readerClearTrashDialog"),
  clearTrashMessage: document.querySelector("#readerClearTrashMessage"),
  cancelClearTrash: document.querySelector("#readerCancelClearTrash"),
  confirmClearTrash: document.querySelector("#readerConfirmClearTrash"),
  debugDialog: document.querySelector("#debugDialog"),
  closeDebugDialog: document.querySelector("#closeDebugDialog"),
  cancelDebugDialog: document.querySelector("#cancelDebugDialog"),
  saveDebugDialog: document.querySelector("#saveDebugDialog"),
  refreshDebugRuns: document.querySelector("#refreshDebugRuns"),
  cleanupDebugRuns: document.querySelector("#cleanupDebugRuns"),
  cleanupDebugMenu: document.querySelector("#cleanupDebugMenu"),
  copyDebugRun: document.querySelector("#copyDebugRun"),
  debugRunList: document.querySelector("#debugRunList"),
  debugRunDetail: document.querySelector("#debugRunDetail"),
  debugError: document.querySelector("#debugError"),
  htmlZoomIn: document.querySelector("#htmlZoomIn"),
  htmlZoomOut: document.querySelector("#htmlZoomOut"),
  htmlZoomLabel: document.querySelector("#htmlZoomLabel"),
  zoomIn: document.querySelector("#zoomIn"),
  zoomOut: document.querySelector("#zoomOut"),
  zoomLabel: document.querySelector("#zoomLabel"),
  pdfPageInput: document.querySelector("#pdfPageInput"),
  pdfPageTotal: document.querySelector("#pdfPageTotal"),
  pdfSearchControl: document.querySelector("#pdfSearchControl"),
  pdfSearchInput: document.querySelector("#pdfSearchInput"),
  pdfSearchCount: document.querySelector("#pdfSearchCount"),
  pdfSearchPrev: document.querySelector("#pdfSearchPrev"),
  pdfSearchNext: document.querySelector("#pdfSearchNext"),
  pdfSearchClose: document.querySelector("#pdfSearchClose"),
  annotationUndo: document.querySelector("#annotationUndo"),
  annotationRedo: document.querySelector("#annotationRedo"),
  pdfLinkReturn: document.querySelector("#pdfLinkReturn"),
  pdfLinkBack: document.querySelector("#pdfLinkBack"),
  pdfLinkDismiss: document.querySelector("#pdfLinkDismiss"),
  modeButtons: Array.from(document.querySelectorAll("[data-pdf-mode]")),
  colorButtons: Array.from(document.querySelectorAll("[data-pdf-color]"))
};

const splitState = {
  dragging: false,
  askDragging: false,
  annotationSidebarDragging: false,
  minPdfWidth: 280,
  minNoteWidth: 320,
  minAskWidth: 320
};

const pdfState = {
  document: null,
  noteId: "",
  url: "",
  mode: "pan",
  color: "yellow",
  scale: 2.15,
  renderToken: 0,
  annotations: [],
  historyPast: [],
  historyFuture: [],
  historyLimit: 80,
  suppressScrollSave: false,
  scrollSaveTimer: 0,
  scrollRestoreFrame: 0,
  scrollRestoreTimer: 0,
  scrollRestoreGeneration: 0,
  scrollRestoreInterrupted: false,
  scrollRestoreOverridePosition: null,
  suppressNoteScrollSave: false,
  noteScrollSaveTimer: 0,
  saveTimer: 0,
  annotationClickTimer: 0,
  noteDrag: null,
  noteDragSuppressClick: false,
  openEditor: null,
  selectedAnnotationId: "",
  selectionOutlineAnnotationId: "",
  selectionOutlineTimer: 0,
  linkReturnPosition: null,
  pageRenderObserver: null,
  pageRenderPromises: new Map(),
  searchQuery: "",
  searchMatches: [],
  searchIndex: -1,
  selectionRenderFrame: 0
};

function readStoredWriteToolMode() {
  try {
    const value = String(localStorage.getItem(WRITE_TOOL_MODE_KEY) || "ask").trim().toLowerCase();
    return ["auto", "warn", "ask", "readonly"].includes(value) ? value : "ask";
  } catch (error) {
    return "ask";
  }
}

function readStoredDeepSeekThinkMode() {
  try {
    const value = String(localStorage.getItem(DEEPSEEK_THINK_MODE_KEY) || "").trim().toLowerCase();
    if (!value || value === "off" || value === "none" || value === "false") return { enabled: false, effort: "high" };
    return { enabled: true, effort: ["high", "max"].includes(value) ? value : "high" };
  } catch (error) {
    return { enabled: false, effort: "high" };
  }
}

function readStoredGptThinkMode() {
  try {
    const value = String(localStorage.getItem(GPT_THINK_MODE_KEY) || "").trim().toLowerCase();
    if (!value || value === "off" || value === "none" || value === "false") return { enabled: false, effort: "medium" };
    return { enabled: true, effort: ["low", "medium", "high", "xhigh"].includes(value) ? value : "medium" };
  } catch (error) {
    return { enabled: false, effort: "medium" };
  }
}

function readStoredGeminiThinkMode() {
  try {
    const value = String(localStorage.getItem(GEMINI_THINK_MODE_KEY) || "").trim().toLowerCase();
    if (!value || value === "off" || value === "minimal" || value === "none" || value === "false") {
      return { enabled: false, effort: "medium" };
    }
    return { enabled: true, effort: ["low", "medium", "high"].includes(value) ? value : "medium" };
  } catch (error) {
    return { enabled: false, effort: "medium" };
  }
}

function readStoredAnthropicThinkMode() {
  try {
    const value = String(localStorage.getItem(ANTHROPIC_THINK_MODE_KEY) || "").trim().toLowerCase();
    if (!value || value === "off" || value === "none" || value === "false") {
      return { enabled: false, effort: "medium" };
    }
    return { enabled: true, effort: ["low", "medium", "high", "xhigh", "max"].includes(value) ? value : "medium" };
  } catch (error) {
    return { enabled: false, effort: "medium" };
  }
}

function releasePointerCaptureSafely(element, pointerId) {
  try {
    if (element?.hasPointerCapture?.(pointerId)) element.releasePointerCapture(pointerId);
  } catch (error) {
    console.warn("Failed to release resize pointer capture.", error);
  }
}

function setReaderResizerActive(element, active) {
  element?.classList.toggle("is-active", active);
  const hasActiveResizer = Boolean(document.querySelector(".reader-resizer.is-active"));
  document.body.classList.toggle("is-resizing-reader", hasActiveResizer);
}

const readerState = {
  library: null,
  note: null,
  chatSessionId: "",
  currentChatSession: null,
  chatSessions: [],
  chatSessionsLoading: false,
  chatSessionMenuOpen: false,
  chatSessionView: "active",
  chatSessionQuery: "",
  openSessionActionMenuId: "",
  confirmingDeleteSessionId: "",
  renamingSessionId: "",
  chatMessages: [],
  chatProgress: null,
  chatProgressBySession: {},
  chatProgressTimer: 0,
  chatProgressTimersBySession: {},
  chatProgressRequestId: "",
  chatProgressRequestIdsBySession: {},
  chatAbortController: null,
  chatAbortControllersBySession: {},
  chatStreamRenderTimer: 0,
  chatPending: false,
  chatPendingBySession: {},
  chatEditingIndex: -1,
  chatEditingText: "",
  runSummaryOpen: {},
  chatAttachments: [],
  selectedPdfText: "",
  selectedPdfPage: "",
  selectedPdfRanges: [],
  selectedPdfPointerRegion: "",
  preservePdfSelectionUntil: 0,
  pendingSelectedTextContext: null,
  imageUploadPending: false,
  attachmentUploadPending: false,
  runtimeSettings: null,
  runtimeSettingsLoading: false,
  aiSettings: null,
  aiSettingsLoading: false,
  modelCatalog: null,
  modelCatalogLoading: false,
  modelMenuOpen: false,
  modelMenuLevel: "providers",
  modelDraftProvider: "",
  pendingChatProvider: "",
  pendingChatModel: "",
  deepSeekThinkMode: readStoredDeepSeekThinkMode(),
  gptThinkMode: readStoredGptThinkMode(),
  geminiThinkMode: readStoredGeminiThinkMode(),
  anthropicThinkMode: readStoredAnthropicThinkMode(),
  modelSaving: false,
  modelStatus: "",
  toolSettings: null,
  toolSettingsLoading: false,
  toolMenuOpen: false,
  toolMenuLevel: "root",
  savedPrompts: [],
  savedPromptDraftToolMode: "",
  savedPromptDraftFileFormat: "markdown",
  savedPromptFileFormatMenuOpen: false,
  savedPromptDraftIconType: "icon",
  savedPromptDraftIconValue: "bookmark",
  savedPromptIconTab: "emoji",
  savedPromptIconQuery: "",
  pendingDeleteSavedPromptId: "",
  generationMode: "",
  fileGenerationFormat: "markdown",
  writeToolMode: readStoredWriteToolMode(),
  toolSnapshots: [],
  toolSnapshotsLoading: false,
  toolSnapshotStatus: "",
  toolSnapshotStatusLevel: "",
  toolSnapshotActionId: "",
  toolDiffActionId: "",
  toolDiffs: {},
  toolDiffOpen: {},
  toolDiffCollapsed: {},
  toolUndoStates: {},
  toolApprovalActionId: "",
  toolSnapshotConflicts: {},
  contextStatus: null,
  contextStatusLoading: false,
  contextCompacting: false,
  contextCompactFocus: "",
  contextCompactStatus: "",
  contextPopoverOpen: false,
  contextRefreshTimer: 0,
  debugRuns: [],
  activeDebugRun: null,
  debugLoading: false,
  debugError: "",
  debugCleanupMenuOpen: false
};

const PDF_ANNOTATION_TYPES = new Set(["highlight", "underline", "area", "note"]);
const PDF_COLORS = {
  yellow: { label: "Yellow", hex: "#f2c94c", rgb: "242, 201, 76" },
  green: { label: "Green", hex: "#70c787", rgb: "112, 199, 135" },
  blue: { label: "Blue", hex: "#6aa9ff", rgb: "106, 169, 255" },
  red: { label: "Red", hex: "#ff7a7a", rgb: "255, 122, 122" },
  purple: { label: "Purple", hex: "#b996ff", rgb: "185, 150, 255" }
};
const PDF_NOTE_MARKER_SIZE = 24;
const ASSISTANT_UNAVAILABLE_MESSAGE = "The assistant backend is not enabled in this build.";
