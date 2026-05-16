const readerDebugPanel = createDebugPanel({
  state: readerState,
  elements: {
    dialog: elements.readerDebugDialog,
    error: elements.readerDebugError,
    runList: elements.readerDebugRunList,
    runDetail: elements.readerDebugRunDetail,
    cleanupButton: elements.readerCleanupDebugRuns,
    cleanupMenu: elements.readerCleanupDebugMenu
  },
  fetchJson: fetchAgentJson,
  copyError: "Could not copy debug log."
});

const renderReaderDebugDialog = readerDebugPanel.renderDebugPanel;
const normalizeDebugRun = readerDebugPanel.normalizeDebugRun;
const setReaderDebugCleanupMenuOpen = readerDebugPanel.setDebugCleanupMenuOpen;
const loadReaderDebugRuns = readerDebugPanel.loadDebugRuns;
const loadReaderDebugRunDetail = readerDebugPanel.loadDebugRunDetail;
const openReaderDebugDialog = readerDebugPanel.openDebugPanel;
const closeReaderDebugDialog = readerDebugPanel.closeDebugPanel;
const cleanupReaderDebugRunsAction = readerDebugPanel.cleanupDebugRuns;
const copyActiveReaderDebugRun = readerDebugPanel.copyActiveDebugRun;
