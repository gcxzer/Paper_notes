import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArrowLeft,
  Bot,
  BrainCircuit,
  FileText,
  Gauge,
  Highlighter,
  Layers3,
  List,
  MessageSquare,
  PanelRightClose,
  RotateCcw,
  Search,
  Send,
  StickyNote,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import {
  fetchAgentContext,
  fetchAgentSessions,
  fetchRagStatus,
  resourceUrl,
  runAgentMessage,
} from "../api/client.js";
import IconButton from "../components/IconButton.jsx";
import { DEFAULT_READER_MESSAGE } from "../data/defaultLibrary.js";

export default function ReaderView({ library, note, noteId, navigate, onShellAction }) {
  const [activePane, setActivePane] = useState("split");
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState([DEFAULT_READER_MESSAGE]);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [context, setContext] = useState(null);
  const [ragStatus, setRagStatus] = useState(null);
  const [sending, setSending] = useState(false);

  const activeNote = note || (library.notes || []).find((entry) => entry.id === noteId) || null;
  const relatedNotes = useMemo(() => {
    if (!activeNote) return [];
    return (library.notes || []).filter((entry) => entry.categoryId === activeNote.categoryId && entry.id !== activeNote.id).slice(0, 5);
  }, [activeNote, library.notes]);

  useEffect(() => {
    fetchAgentSessions()
      .then(setSessions)
      .catch(() => setSessions([]));
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    fetchAgentContext(sessionId)
      .then(setContext)
      .catch(() => setContext(null));
  }, [sessionId, messages.length]);

  useEffect(() => {
    if (!activeNote?.id) return;
    fetchRagStatus(activeNote.id)
      .then(setRagStatus)
      .catch(() => setRagStatus(null));
  }, [activeNote?.id]);

  async function sendMessage(event) {
    event.preventDefault();
    const content = chatInput.trim();
    if (!content || sending) return;
    setChatInput("");
    setSending(true);
    setMessages((current) => [...current, { role: "user", content }]);
    try {
      const result = await runAgentMessage({
        message: content,
        sessionId: sessionId || undefined,
        title: activeNote?.title || "Paper chat",
        noteId: activeNote?.id,
        metadata: { surface: "reader" },
      });
      if (result.sessionId) setSessionId(result.sessionId);
      setMessages(normalizeMessages(result.messages, result.response));
      fetchAgentSessions()
        .then(setSessions)
        .catch(() => {});
    } catch (error) {
      setMessages((current) => [...current, { role: "assistant", content: error.message }]);
    } finally {
      setSending(false);
    }
  }

  if (!activeNote) {
    return (
      <div className="reader-missing">
        <button className="button" type="button" onClick={() => navigate("/")}>
          <ArrowLeft size={16} aria-hidden="true" />
          Library
        </button>
        <h1>Paper not found</h1>
      </div>
    );
  }

  return (
    <div className="reader-shell">
      <header className="reader-topbar">
        <button className="button" type="button" onClick={() => navigate("/")}>
          <ArrowLeft size={16} aria-hidden="true" />
          Library
        </button>
        <div className="reader-title-block">
          <span className="kicker">Reader</span>
          <h1>{activeNote.title}</h1>
        </div>
        <div className="reader-topbar-actions">
          <IconButton icon={Search} label="" aria-label="Search" onClick={() => onShellAction("Reader search opened")} />
          <IconButton icon={PanelRightClose} label="" aria-label="Toggle assistant" onClick={() => onShellAction("Assistant layout toggled")} />
        </div>
      </header>

      <main className="reader-grid">
        <aside className="reader-rail">
          <section className="rail-section">
            <h2>Paper</h2>
            <button className="rail-row is-active" type="button">
              <FileText size={16} aria-hidden="true" />
              Source
            </button>
            <button className="rail-row" type="button" onClick={() => onShellAction("Annotation list opened")}>
              <Highlighter size={16} aria-hidden="true" />
              Marks
            </button>
            <button className="rail-row" type="button" onClick={() => onShellAction("Note outline opened")}>
              <List size={16} aria-hidden="true" />
              Outline
            </button>
          </section>

          <section className="rail-section">
            <h2>Related</h2>
            {relatedNotes.map((entry) => (
              <button className="related-row" key={entry.id} type="button" onClick={() => navigate(`/reader/${encodeURIComponent(entry.id)}`)}>
                <span>{entry.title}</span>
              </button>
            ))}
            {relatedNotes.length === 0 ? <p className="rail-muted">None</p> : null}
          </section>
        </aside>

        <section className="reader-workbench">
          <div className="reader-toolstrip">
            <div className="segmented-control" role="group" aria-label="Reader panes">
              {["split", "pdf", "note"].map((pane) => (
                <button className={activePane === pane ? "is-active" : ""} key={pane} type="button" onClick={() => setActivePane(pane)}>
                  {paneLabel(pane)}
                </button>
              ))}
            </div>
            <div className="tool-cluster">
              <IconButton icon={StickyNote} label="" aria-label="Sticky note" onClick={() => onShellAction("Annotation note created")} />
              <IconButton icon={RotateCcw} label="" aria-label="Undo" onClick={() => onShellAction("Annotation undo")} />
              <IconButton icon={ZoomOut} label="" aria-label="Zoom out" onClick={() => onShellAction("Zoom out")} />
              <IconButton icon={ZoomIn} label="" aria-label="Zoom in" onClick={() => onShellAction("Zoom in")} />
            </div>
          </div>

          <div className={`paper-stage is-${activePane}`}>
            <section className="pdf-surface" aria-label="PDF">
              {activeNote.href ? (
                <object data={resourceUrl(activeNote.href)} type="application/pdf" title={activeNote.title}>
                  <a href={resourceUrl(activeNote.href)}>Open PDF</a>
                </object>
              ) : (
                <div className="surface-empty">
                  <FileText size={24} aria-hidden="true" />
                  <strong>No PDF</strong>
                </div>
              )}
            </section>

            <section className="note-surface" aria-label="Note">
              {activeNote.htmlHref ? (
                <iframe src={resourceUrl(activeNote.htmlHref)} title={`${activeNote.title} note`} />
              ) : (
                <article>
                  <span className="kicker">{activeNote.date || "No date"}</span>
                  <h2>{activeNote.title}</h2>
                  <p>{activeNote.summary || "No note body saved."}</p>
                </article>
              )}
            </section>
          </div>
        </section>

        <aside className="assistant-panel">
          <header className="assistant-header">
            <div>
              <span className="kicker">Agent</span>
              <h2>Paper Chat</h2>
            </div>
            <div className="assistant-actions">
              <IconButton icon={Archive} label="" aria-label="Archived chats" onClick={() => onShellAction("Archived chats opened")} />
              <IconButton icon={Bot} label="" aria-label="Model" onClick={() => onShellAction("Model switcher opened")} />
            </div>
          </header>

          <ContextMeter context={context} />

          <section className="rag-status">
            <BrainCircuit size={17} aria-hidden="true" />
            <span>
              <strong>RAG</strong>
              <small>{ragStatus?.ready ? "Ready" : ragStatus ? "Pending" : "Unknown"}</small>
            </span>
            <button type="button" onClick={() => onShellAction("RAG indexing queued")}>
              Index
            </button>
          </section>

          <section className="session-strip" aria-label="Chat sessions">
            {sessions.slice(0, 4).map((session) => (
              <button
                className={session.sessionId === sessionId ? "is-active" : ""}
                key={session.sessionId}
                type="button"
                onClick={() => setSessionId(session.sessionId)}
              >
                <MessageSquare size={14} aria-hidden="true" />
                <span>{session.title || "New chat"}</span>
              </button>
            ))}
          </section>

          <section className="message-list" aria-label="Messages">
            {messages.map((message, index) => (
              <article className={`message message-${message.role || "assistant"}`} key={`${message.role}-${index}`}>
                <span>{message.role === "user" ? "You" : "Agent"}</span>
                <p>{message.content}</p>
              </article>
            ))}
          </section>

          <form className="composer" onSubmit={sendMessage}>
            <textarea
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder="Ask anything"
              rows={2}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) sendMessage(event);
              }}
            />
            <button className="send-button" type="submit" disabled={sending || !chatInput.trim()} aria-label="Send">
              <Send size={17} aria-hidden="true" />
            </button>
          </form>
        </aside>
      </main>
    </div>
  );
}

function ContextMeter({ context }) {
  const used = context?.estimatedTokens || 0;
  const total = context?.contextWindow || 0;
  const percent = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
  return (
    <section className="context-meter">
      <Gauge size={17} aria-hidden="true" />
      <span>
        <strong>Context</strong>
        <small>{total ? `${used.toLocaleString()} / ${total.toLocaleString()}` : "No session"}</small>
      </span>
      <div aria-hidden="true">
        <i style={{ width: `${percent}%` }} />
      </div>
    </section>
  );
}

function normalizeMessages(messages, fallbackResponse) {
  if (!Array.isArray(messages) || messages.length === 0) {
    return [{ role: "assistant", content: fallbackResponse || "Done." }];
  }
  return messages
    .map((message) => {
      const role = message.role || message.type || "assistant";
      const content = messageText(message.content);
      return { role: role === "human" ? "user" : role === "ai" ? "assistant" : role, content };
    })
    .filter((message) => message.content);
}

function messageText(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(messageText).filter(Boolean).join("\n");
  if (value && typeof value === "object") return value.text || value.content || JSON.stringify(value);
  return "";
}

function paneLabel(pane) {
  if (pane === "pdf") return "PDF";
  if (pane === "note") return "Note";
  return "Split";
}
