const debugPanel = createDebugPanel({
  state: readerState,
  elements: {
    dialog: elements.debugDialog,
    error: elements.debugError,
    runList: elements.debugRunList,
    runDetail: elements.debugRunDetail,
    cleanupButton: elements.cleanupDebugRuns,
    cleanupMenu: elements.cleanupDebugMenu
  },
  fetchJson: fetchAgentJson,
  copyError: "Could not copy debug JSON."
});

const renderDebugDialog = debugPanel.renderDebugPanel;
const normalizeDebugRun = debugPanel.normalizeDebugRun;
const setDebugCleanupMenuOpen = debugPanel.setDebugCleanupMenuOpen;
const loadDebugRuns = debugPanel.loadDebugRuns;
const loadDebugRunDetail = debugPanel.loadDebugRunDetail;
const openDebugDialog = debugPanel.openDebugPanel;
const closeDebugDialog = debugPanel.closeDebugPanel;
const cleanupDebugRunsAction = debugPanel.cleanupDebugRuns;
const copyActiveDebugRun = debugPanel.copyActiveDebugRun;
