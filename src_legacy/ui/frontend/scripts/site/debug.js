const debugPanel = createDebugPanel({
  state,
  elements: {
    dialog: elements.debugDialog,
    error: elements.debugError,
    runList: elements.debugRunList,
    runDetail: elements.debugRunDetail,
    cleanupButton: elements.cleanupDebugRuns,
    cleanupMenu: elements.cleanupDebugMenu
  },
  fetchJson,
  beforeOpen: () => closeSettingsMenu(),
  afterClose: () => clearSettingsPanelUrl(),
  copyError: "Could not copy debug JSON."
});

const renderDebugDialog = debugPanel.renderDebugPanel;
const setDebugCleanupMenuOpen = debugPanel.setDebugCleanupMenuOpen;
const loadDebugRuns = debugPanel.loadDebugRuns;
const loadDebugRunDetail = debugPanel.loadDebugRunDetail;
const openDebugDialog = debugPanel.openDebugPanel;
const closeDebugDialog = debugPanel.closeDebugPanel;
const cleanupDebugRunsAction = debugPanel.cleanupDebugRuns;
const copyActiveDebugRun = debugPanel.copyActiveDebugRun;
