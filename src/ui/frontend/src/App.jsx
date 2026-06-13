import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Database, ServerCog } from "lucide-react";

import {
  fetchLibrary,
  importPaperUrl,
  importPdfFile,
  renameNote,
  updateNoteSummary,
} from "./api/client.js";
import Modal from "./components/Modal.jsx";
import { DEFAULT_LIBRARY } from "./data/defaultLibrary.js";
import LibraryView from "./views/LibraryView.jsx";
import ReaderView from "./views/ReaderView.jsx";

function currentRoute() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  const readerMatch = path.match(/^\/reader\/([^/]+)$/);
  if (readerMatch) {
    return { name: "reader", noteId: decodeURIComponent(readerMatch[1]) };
  }
  if (path === "/settings") return { name: "settings" };
  return { name: "library" };
}

export default function App() {
  const [route, setRoute] = useState(currentRoute);
  const [library, setLibrary] = useState(DEFAULT_LIBRARY);
  const [selectedCollectionId, setSelectedCollectionId] = useState("all");
  const [selectedNoteId, setSelectedNoteId] = useState("");
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [toast, setToast] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const refreshLibrary = useCallback(async () => {
    setLoadingLibrary(true);
    try {
      const nextLibrary = await fetchLibrary();
      setLibrary(nextLibrary || DEFAULT_LIBRARY);
      const firstNoteId = nextLibrary?.notes?.[0]?.id || "";
      setSelectedNoteId((current) => current || firstNoteId);
    } catch (error) {
      setLibrary(DEFAULT_LIBRARY);
      showToast(setToast, {
        tone: "warning",
        title: "Library API unavailable",
        detail: error.message,
      });
    } finally {
      setLoadingLibrary(false);
    }
  }, []);

  useEffect(() => {
    refreshLibrary();
  }, [refreshLibrary]);

  useEffect(() => {
    const handlePopState = () => setRoute(currentRoute());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const notesById = useMemo(() => new Map((library.notes || []).map((note) => [note.id, note])), [library.notes]);
  const routeNote = route.name === "reader" ? notesById.get(route.noteId) : null;
  const selectedNote = notesById.get(selectedNoteId) || library.notes?.[0] || null;

  const navigate = useCallback((to) => {
    window.history.pushState({}, "", to);
    setRoute(currentRoute());
  }, []);

  const openReader = useCallback(
    (noteId) => {
      if (!noteId) return;
      navigate(`/reader/${encodeURIComponent(noteId)}`);
    },
    [navigate],
  );

  async function handleImportFile(file) {
    if (!file) return;
    showToast(setToast, { tone: "busy", title: "Importing PDF", detail: file.name });
    try {
      const payload = await importPdfFile(file, selectedCollectionId);
      await refreshLibrary();
      const noteId = payload.note?.id || payload.id;
      if (noteId) setSelectedNoteId(noteId);
      showToast(setToast, { tone: "success", title: "PDF imported", detail: payload.note?.title || payload.title || file.name });
    } catch (error) {
      showToast(setToast, { tone: "danger", title: "Import failed", detail: error.message });
    }
  }

  async function handleImportUrl(url) {
    showToast(setToast, { tone: "busy", title: "Importing paper", detail: url });
    try {
      const payload = await importPaperUrl(url, selectedCollectionId);
      await refreshLibrary();
      const noteId = payload.note?.id || payload.id;
      if (noteId) setSelectedNoteId(noteId);
      showToast(setToast, { tone: "success", title: "Paper imported", detail: payload.note?.title || payload.title || url });
    } catch (error) {
      showToast(setToast, { tone: "danger", title: "Import failed", detail: error.message });
    }
  }

  async function handleRenameNote(noteId, title) {
    try {
      const payload = await renameNote(noteId, title);
      await refreshLibrary();
      setSelectedNoteId(payload.note?.id || noteId);
      showToast(setToast, { tone: "success", title: "Note renamed", detail: title });
    } catch (error) {
      showToast(setToast, { tone: "danger", title: "Rename failed", detail: error.message });
    }
  }

  async function handleUpdateSummary(noteId, summary) {
    try {
      await updateNoteSummary(noteId, summary);
      await refreshLibrary();
      showToast(setToast, { tone: "success", title: "Summary saved" });
    } catch (error) {
      showToast(setToast, { tone: "danger", title: "Save failed", detail: error.message });
    }
  }

  function handleShellAction(title, detail = "") {
    showToast(setToast, { tone: "neutral", title, detail });
  }

  return (
    <>
      {route.name === "reader" ? (
        <ReaderView
          library={library}
          note={routeNote}
          noteId={route.noteId}
          navigate={navigate}
          onRefreshLibrary={refreshLibrary}
          onShellAction={handleShellAction}
        />
      ) : (
        <LibraryView
          library={library}
          loading={loadingLibrary}
          selectedCollectionId={selectedCollectionId}
          selectedNote={selectedNote}
          selectedNoteId={selectedNoteId}
          onSelectCollection={setSelectedCollectionId}
          onSelectNote={setSelectedNoteId}
          onOpenNote={openReader}
          onImportFile={handleImportFile}
          onImportUrl={handleImportUrl}
          onRenameNote={handleRenameNote}
          onUpdateSummary={handleUpdateSummary}
          onOpenSettings={() => setSettingsOpen(true)}
          onShellAction={handleShellAction}
        />
      )}

      {settingsOpen ? (
        <Modal
          title="Workspace Settings"
          onClose={() => setSettingsOpen(false)}
          footer={
            <button className="button button-primary" type="button" onClick={() => setSettingsOpen(false)}>
              Done
            </button>
          }
        >
          <div className="settings-grid">
            <SettingTile icon={ServerCog} title="Models" value="Provider routing" />
            <SettingTile icon={Database} title="RAG" value="Indexes and embeddings" />
            <SettingTile icon={AlertCircle} title="Tools" value="Approval policy" />
          </div>
        </Modal>
      ) : null}

      {toast ? <Toast toast={toast} onClose={() => setToast(null)} /> : null}
    </>
  );
}

function SettingTile({ icon: Icon, title, value }) {
  return (
    <button className="setting-tile" type="button">
      <Icon size={18} aria-hidden="true" />
      <span>
        <strong>{title}</strong>
        <small>{value}</small>
      </span>
    </button>
  );
}

function Toast({ toast, onClose }) {
  const Icon = toast.tone === "success" ? CheckCircle2 : toast.tone === "danger" || toast.tone === "warning" ? AlertCircle : Database;
  useEffect(() => {
    if (toast.tone === "busy") return undefined;
    const timer = window.setTimeout(onClose, 4200);
    return () => window.clearTimeout(timer);
  }, [toast, onClose]);

  return (
    <div className={`toast toast-${toast.tone || "neutral"}`} role="status">
      <Icon size={18} aria-hidden="true" />
      <span>
        <strong>{toast.title}</strong>
        {toast.detail ? <small>{toast.detail}</small> : null}
      </span>
      <button type="button" onClick={onClose} aria-label="Dismiss">
        ×
      </button>
    </div>
  );
}

function showToast(setToast, toast) {
  setToast({ tone: "neutral", detail: "", ...toast });
}
