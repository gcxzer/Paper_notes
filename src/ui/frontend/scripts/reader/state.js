const pdfjsLib = globalThis.pdfjsLib;

if (pdfjsLib) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "node_modules/pdfjs-dist/build/pdf.worker.js";
}

const STORAGE_KEY = "paper-notes-library-v14";
const FILE_DB_NAME = "paper-notes-files-v1";
const FILE_STORE_NAME = "paper-files";
const READER_SPLIT_KEY = "paper-notes-reader-split-v1";
const ANNOTATION_SIDEBAR_KEY = "paper-notes-annotation-sidebar-v1";
const HTML_PANE_KEY = "paper-notes-html-pane-v1";
const ASK_PANE_KEY = "paper-notes-ask-pane-v1";
const ASK_WIDTH_KEY = "paper-notes-ask-width-v1";
const HTML_ZOOM_KEY = "paper-notes-html-zoom-v1";
const PDF_SCROLL_KEY = "paper-notes-pdf-scroll-v1";
const NOTE_SCROLL_KEY = "paper-notes-note-scroll-v1";
const CHAT_SESSION_STORE_KEY = "paper-notes-agent-session-by-note-v1";
const ALL_CATEGORY_ID = "all";
const UNCATEGORIZED_ID = "uncategorized";
const MODEL = window.PaperNotesModel;
const PDF_MIN_SCALE = 0.7;
const PDF_MAX_SCALE = 4;
const PDF_SCALE_STEP = 0.1;
const GENERIC_AGENT_ERROR = "I could not reach the assistant. Check that the local server is running and try again.";
const SENSITIVE_AGENT_ERROR_PATTERN = /(SSL validation failed|ValidationException|AccessDeniedException|runtimeClientError|\[Errno\s+\d+\]|No such file or directory|api[_ -]?key|secret|token)/i;

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
  pdfBody: document.querySelector(".pdf-body"),
  htmlPaneToggle: document.querySelector("#htmlPaneToggle"),
  askPaneToggle: document.querySelector("#askPaneToggle"),
  closeAskPane: document.querySelector("#closeAskPane"),
  chatSessionMenuButton: document.querySelector("#chatSessionMenuButton"),
  chatSessionPopover: document.querySelector("#chatSessionPopover"),
  newChatSession: document.querySelector("#newChatSession"),
  exportChatSession: document.querySelector("#exportChatSession"),
  toggleChatSessionTrash: document.querySelector("#toggleChatSessionTrash"),
  chatSessionSearch: document.querySelector("#chatSessionSearch"),
  chatSessionList: document.querySelector("#chatSessionList"),
  readerChatForm: document.querySelector("#readerChatForm"),
  readerChatMessages: document.querySelector("#readerChatMessages"),
  readerChatInput: document.querySelector("#readerChatInput"),
  readerChatError: document.querySelector("#readerChatError"),
  sendReaderChat: document.querySelector("#sendReaderChat"),
  clearReaderChat: document.querySelector("#clearReaderChat"),
  htmlZoomIn: document.querySelector("#htmlZoomIn"),
  htmlZoomOut: document.querySelector("#htmlZoomOut"),
  htmlZoomLabel: document.querySelector("#htmlZoomLabel"),
  zoomIn: document.querySelector("#zoomIn"),
  zoomOut: document.querySelector("#zoomOut"),
  zoomLabel: document.querySelector("#zoomLabel"),
  pdfPageInput: document.querySelector("#pdfPageInput"),
  pdfPageTotal: document.querySelector("#pdfPageTotal"),
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
  suppressNoteScrollSave: false,
  noteScrollSaveTimer: 0,
  saveTimer: 0,
  openEditor: null,
  selectedAnnotationId: "",
  linkReturnPosition: null
};

const readerState = {
  library: null,
  note: null,
  chatSessionId: "",
  chatSessions: [],
  chatSessionsLoading: false,
  chatSessionMenuOpen: false,
  chatSessionTrashOpen: false,
  chatSessionQuery: "",
  confirmingDeleteSessionId: "",
  renamingSessionId: "",
  chatMessages: [],
  chatProgress: null,
  chatProgressTimer: 0,
  chatProgressRequestId: "",
  chatPending: false
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
