const STORAGE_KEY = "paper-notes-library-v14";
const EXPANDED_KEY = "paper-notes-expanded-v1";
const LAYOUT_KEY = "paper-notes-layout-v1";
const SORT_KEY = "paper-notes-sort-v1";
const CHAT_SESSION_KEY = "paper-notes-agent-session-v1";
const ALL_CATEGORY_ID = "all";
const UNCATEGORIZED_ID = "uncategorized";
const LEGACY_STORAGE_KEYS = ["paper-notes-library-v5", "paper-notes-library-v6", "paper-notes-library-v7", "paper-notes-library-v8", "paper-notes-library-v9", "paper-notes-library-v10", "paper-notes-library-v11", "paper-notes-library-v12", "paper-notes-library-v13"];
const MODEL = window.PaperNotesModel;

LEGACY_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));

const DEFAULT_LIBRARY = {
  categories: [
    { id: ALL_CATEGORY_ID, name: "All Notes", parentId: null, order: 0, system: true },
    { id: UNCATEGORIZED_ID, name: "Uncategorized", parentId: null, order: 1, system: true }
  ],
  notes: []
};

const GENERIC_AGENT_ERROR = "I could not reach the assistant. Check that the local server is running and try again.";
const SENSITIVE_AGENT_ERROR_PATTERN = /(SSL validation failed|ValidationException|AccessDeniedException|runtimeClientError|\[Errno\s+\d+\]|No such file or directory|api[_ -]?key|secret|token)/i;
const ASSISTANT_UNAVAILABLE_MESSAGE = "The assistant backend is not enabled in this build.";

const state = {
  library: null,
  activeCategoryId: ALL_CATEGORY_ID,
  selectedNoteId: null,
  query: "",
  pendingCategoryId: null,
  pendingParentId: null,
  pendingRenameNoteId: null,
  confirmAction: null,
  contextCategoryId: null,
  draggedCategoryId: null,
  dragTarget: null,
  pdfObjectUrls: new Map(),
  sortMode: localStorage.getItem(SORT_KEY) || "date-desc",
  expandedCategoryIds: new Set(),
  panelWidths: {
    sidebar: 320,
    details: 320
  },
  dataSource: "default",
  chatSessionId: localStorage.getItem(CHAT_SESSION_KEY) || "",
  chatMessages: [],
  chatPending: false
};

const summarySaveTimers = new Map();
let librarySyncQueue = Promise.resolve();
let librarySyncVersion = 0;

const elements = {
  body: document.body,
  sidebarSection: document.querySelector("#sidebarSection"),
  categoryList: document.querySelector("#categoryList"),
  notesGrid: document.querySelector("#notesGrid"),
  libraryStatus: document.querySelector("#libraryStatus"),
  searchInput: document.querySelector("#searchInput"),
  emptyState: document.querySelector("#emptyState"),
  newCategoryButton: document.querySelector("#newCategoryButton"),
  detailsPanel: document.querySelector("#detailsPanel"),
  detailsCard: document.querySelector("#detailsCard"),
  leftResizer: document.querySelector("#leftResizer"),
  rightResizer: document.querySelector("#rightResizer"),
  contentTitle: document.querySelector("#contentTitle"),
  contentKicker: document.querySelector("#contentKicker"),
  addPdfButton: document.querySelector("#addPdfButton"),
  pdfInput: document.querySelector("#pdfInput"),
  askAgentButton: document.querySelector("#askAgentButton"),
  sortButton: document.querySelector("#sortButton"),
  sortMenu: document.querySelector("#sortMenu"),
  contextMenu: document.querySelector("#contextMenu"),
  categoryDialog: document.querySelector("#categoryDialog"),
  categoryForm: document.querySelector("#categoryForm"),
  categoryDialogEyebrow: document.querySelector("#categoryDialogEyebrow"),
  categoryDialogTitle: document.querySelector("#categoryDialogTitle"),
  categoryNameInput: document.querySelector("#categoryNameInput"),
  categoryDialogError: document.querySelector("#categoryDialogError"),
  closeCategoryDialog: document.querySelector("#closeCategoryDialog"),
  cancelCategoryDialog: document.querySelector("#cancelCategoryDialog"),
  confirmDialog: document.querySelector("#confirmDialog"),
  confirmDialogTitle: document.querySelector("#confirmDialogTitle"),
  confirmDialogBody: document.querySelector("#confirmDialogBody"),
  confirmDialogAction: document.querySelector("#confirmDialogAction"),
  closeConfirmDialog: document.querySelector("#closeConfirmDialog"),
  cancelConfirmDialog: document.querySelector("#cancelConfirmDialog"),
  renameNoteDialog: document.querySelector("#renameNoteDialog"),
  renameNoteForm: document.querySelector("#renameNoteForm"),
  renameNoteInput: document.querySelector("#renameNoteInput"),
  renameNoteError: document.querySelector("#renameNoteError"),
  closeRenameNoteDialog: document.querySelector("#closeRenameNoteDialog"),
  cancelRenameNoteDialog: document.querySelector("#cancelRenameNoteDialog"),
  chatDialog: document.querySelector("#chatDialog"),
  chatForm: document.querySelector("#chatForm"),
  chatMessages: document.querySelector("#chatMessages"),
  chatInput: document.querySelector("#chatInput"),
  chatError: document.querySelector("#chatError"),
  sendChatButton: document.querySelector("#sendChatButton"),
  clearChatButton: document.querySelector("#clearChatButton"),
  closeChatDialog: document.querySelector("#closeChatDialog"),
  settingsButton: document.querySelector("#settingsButton"),
  settingsMenu: document.querySelector("#settingsMenu"),
  messageDialog: document.querySelector("#messageDialog"),
  messageDialogEyebrow: document.querySelector("#messageDialogEyebrow"),
  messageDialogTitle: document.querySelector("#messageDialogTitle"),
  messageDialogBody: document.querySelector("#messageDialogBody"),
  messageDialogAction: document.querySelector("#messageDialogAction"),
  closeMessageDialog: document.querySelector("#closeMessageDialog")
};
