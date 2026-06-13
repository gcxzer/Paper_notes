import { useMemo, useRef, useState } from "react";
import {
  ArrowUpDown,
  BookOpen,
  ChevronRight,
  FilePlus2,
  FolderPlus,
  MoreHorizontal,
  Plus,
  Search,
  Settings,
  Tags,
  Upload,
} from "lucide-react";

import IconButton from "../components/IconButton.jsx";
import Modal from "../components/Modal.jsx";

export default function LibraryView({
  library,
  loading,
  selectedCollectionId,
  selectedNote,
  selectedNoteId,
  onSelectCollection,
  onSelectNote,
  onOpenNote,
  onImportFile,
  onImportUrl,
  onRenameNote,
  onUpdateSummary,
  onOpenSettings,
  onShellAction,
}) {
  const fileInputRef = useRef(null);
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState("recent");
  const [urlDialogOpen, setUrlDialogOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [paperUrl, setPaperUrl] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftSummary, setDraftSummary] = useState("");

  const categories = useMemo(() => sortCategories(library.categories || []), [library.categories]);
  const notes = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = (library.notes || []).filter((note) => {
      const inCollection = selectedCollectionId === "all" || note.categoryId === selectedCollectionId;
      if (!inCollection) return false;
      if (!normalizedQuery) return true;
      return [note.title, note.venue, note.summary, ...(note.tags || [])]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    });
    return filtered.sort((left, right) => {
      if (sortMode === "title") return left.title.localeCompare(right.title);
      if (sortMode === "category") return String(left.categoryId || "").localeCompare(String(right.categoryId || ""));
      return String(right.date || "").localeCompare(String(left.date || ""));
    });
  }, [library.notes, query, selectedCollectionId, sortMode]);

  const counts = useMemo(() => {
    const next = new Map();
    for (const note of library.notes || []) {
      next.set("all", (next.get("all") || 0) + 1);
      next.set(note.categoryId, (next.get(note.categoryId) || 0) + 1);
    }
    return next;
  }, [library.notes]);

  function openRename() {
    setDraftTitle(selectedNote?.title || "");
    setRenameOpen(true);
  }

  function openSummary() {
    setDraftSummary(selectedNote?.summary || "");
    setSummaryOpen(true);
  }

  return (
    <div className="workspace-shell">
      <aside className="sidebar-panel">
        <header className="brand-row">
          <div className="brand-mark">PN</div>
          <div>
            <strong>Paper Notes</strong>
            <span>Research Workspace</span>
          </div>
        </header>

        <div className="sidebar-actions">
          <button className="button button-primary" type="button" onClick={() => fileInputRef.current?.click()}>
            <Upload size={16} aria-hidden="true" />
            Import PDF
          </button>
          <IconButton icon={FolderPlus} label="" aria-label="New collection" onClick={() => onShellAction("Collection draft opened")} />
        </div>

        <label className="search-box">
          <Search size={16} aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search papers" type="search" />
        </label>

        <nav className="collection-list" aria-label="Collections">
          {categories.map((category) => (
            <button
              className={`collection-row ${selectedCollectionId === category.id ? "is-active" : ""}`}
              key={category.id}
              type="button"
              onClick={() => onSelectCollection(category.id)}
            >
              <BookOpen size={16} aria-hidden="true" />
              <span>{category.name}</span>
              <small>{counts.get(category.id) || 0}</small>
            </button>
          ))}
        </nav>

        <footer className="sidebar-footer">
          <button type="button" onClick={onOpenSettings}>
            <Settings size={16} aria-hidden="true" />
            Settings
          </button>
          <button type="button" onClick={() => onShellAction("Workspace diagnostics opened")}>
            <MoreHorizontal size={16} aria-hidden="true" />
          </button>
        </footer>
      </aside>

      <main className="content-panel">
        <header className="content-header">
          <div>
            <span className="kicker">{loading ? "Loading" : `${notes.length} papers`}</span>
            <h1>{collectionTitle(categories, selectedCollectionId)}</h1>
          </div>
          <div className="header-actions">
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf"
              hidden
              onChange={(event) => {
                onImportFile(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <IconButton icon={FilePlus2} label="Link" onClick={() => setUrlDialogOpen(true)} />
            <IconButton icon={Upload} label="PDF" onClick={() => fileInputRef.current?.click()} />
            <label className="select-control">
              <ArrowUpDown size={15} aria-hidden="true" />
              <select value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
                <option value="recent">Recent</option>
                <option value="title">Title</option>
                <option value="category">Collection</option>
              </select>
            </label>
          </div>
        </header>

        <section className="notes-grid" aria-label="Papers">
          {notes.map((note) => (
            <article
              className={`note-card ${selectedNoteId === note.id ? "is-selected" : ""}`}
              key={note.id}
              onClick={() => onSelectNote(note.id)}
            >
              <header>
                <span>{note.date || "No date"}</span>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onOpenNote(note.id);
                  }}
                  aria-label={`Open ${note.title}`}
                >
                  <ChevronRight size={17} aria-hidden="true" />
                </button>
              </header>
              <h2>{note.title}</h2>
              <p>{note.summary || note.sourceUrl || "No summary saved."}</p>
              <footer>
                {(note.tags || []).slice(0, 3).map((tag) => (
                  <span className="tag" key={tag}>
                    {tag}
                  </span>
                ))}
              </footer>
            </article>
          ))}
          {!loading && notes.length === 0 ? (
            <div className="empty-state">
              <BookOpen size={22} aria-hidden="true" />
              <strong>No papers</strong>
            </div>
          ) : null}
        </section>
      </main>

      <aside className="details-panel">
        {selectedNote ? (
          <>
            <header className="details-header">
              <span className="kicker">Selected Paper</span>
              <h2>{selectedNote.title}</h2>
            </header>
            <div className="detail-actions">
              <button className="button button-primary" type="button" onClick={() => onOpenNote(selectedNote.id)}>
                <BookOpen size={16} aria-hidden="true" />
                Open
              </button>
              <IconButton icon={Tags} label="" aria-label="Tags" onClick={() => onShellAction("Tag editor opened")} />
              <IconButton icon={MoreHorizontal} label="" aria-label="More" onClick={openRename} />
            </div>
            <dl className="meta-list">
              <div>
                <dt>Date</dt>
                <dd>{selectedNote.date || "None"}</dd>
              </div>
              <div>
                <dt>Venue</dt>
                <dd>{selectedNote.venue || "None"}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{selectedNote.sourceUrl || selectedNote.href || "None"}</dd>
              </div>
            </dl>
            <section className="summary-box">
              <header>
                <strong>Summary</strong>
                <button type="button" onClick={openSummary}>
                  Edit
                </button>
              </header>
              <p>{selectedNote.summary || "No summary saved."}</p>
            </section>
            <div className="tag-list">
              {(selectedNote.tags || []).map((tag) => (
                <span className="tag tag-strong" key={tag}>
                  {tag}
                </span>
              ))}
            </div>
          </>
        ) : (
          <div className="empty-state details-empty">
            <Plus size={22} aria-hidden="true" />
            <strong>Select a paper</strong>
          </div>
        )}
      </aside>

      {urlDialogOpen ? (
        <Modal
          title="Import Link"
          onClose={() => setUrlDialogOpen(false)}
          footer={
            <>
              <button className="button" type="button" onClick={() => setUrlDialogOpen(false)}>
                Cancel
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={() => {
                  onImportUrl(paperUrl);
                  setPaperUrl("");
                  setUrlDialogOpen(false);
                }}
              >
                Import
              </button>
            </>
          }
        >
          <label className="field">
            <span>DOI, arXiv, or PDF URL</span>
            <input value={paperUrl} onChange={(event) => setPaperUrl(event.target.value)} autoFocus />
          </label>
        </Modal>
      ) : null}

      {renameOpen ? (
        <Modal
          title="Rename Note"
          onClose={() => setRenameOpen(false)}
          footer={
            <>
              <button className="button" type="button" onClick={() => setRenameOpen(false)}>
                Cancel
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={() => {
                  onRenameNote(selectedNote.id, draftTitle);
                  setRenameOpen(false);
                }}
              >
                Save
              </button>
            </>
          }
        >
          <label className="field">
            <span>Title</span>
            <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} autoFocus />
          </label>
        </Modal>
      ) : null}

      {summaryOpen ? (
        <Modal
          title="Edit Summary"
          onClose={() => setSummaryOpen(false)}
          footer={
            <>
              <button className="button" type="button" onClick={() => setSummaryOpen(false)}>
                Cancel
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={() => {
                  onUpdateSummary(selectedNote.id, draftSummary);
                  setSummaryOpen(false);
                }}
              >
                Save
              </button>
            </>
          }
        >
          <label className="field">
            <span>Summary</span>
            <textarea rows={6} value={draftSummary} onChange={(event) => setDraftSummary(event.target.value)} />
          </label>
        </Modal>
      ) : null}
    </div>
  );
}

function sortCategories(categories) {
  return [...categories].sort((left, right) => {
    const leftOrder = Number.isFinite(left.order) ? left.order : 999;
    const rightOrder = Number.isFinite(right.order) ? right.order : 999;
    return leftOrder - rightOrder || String(left.name || "").localeCompare(String(right.name || ""));
  });
}

function collectionTitle(categories, selectedCollectionId) {
  return categories.find((category) => category.id === selectedCollectionId)?.name || "Library";
}
