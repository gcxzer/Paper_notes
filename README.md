# Paper Notes

Paper Notes is a local research workspace for importing PDFs, keeping editable
paper notes, and asking a LangChain agent to work with the paper library.

This repository is currently being rewritten from the legacy implementation in
`src_legacy/` into the new LangChain-based implementation in `src/`. The new
project intentionally does not keep legacy frontend compatibility layers.

## Current Shape

- Backend: FastAPI routes in `src/ui/backend`.
- Agent runtime: LangChain/LangGraph flow in `src/agent_runtime`.
- Sessions: JSON/JSONL session storage in `.paper-notes/sessions/`.
- Tools: LangChain `StructuredTool` instances from `src/tools`.
- RAG: local Qdrant/BM25 indexes under `.paper-notes/rag/`, exposed to the
  agent as the `search_paper_rag` tool.
- Frontend: React + Vite SPA in `src/ui/frontend`.
- Legacy reference: old code remains in `src_legacy/` only as migration source.

## Requirements

- Python 3.12+
- `uv`
- Node.js and npm
- For the default RAG embedding path, a local Ollama embedding model or an
  explicit embedding provider/model override

Install dependencies:

```bash
npm install
uv sync
```

## Development

Start the backend:

```bash
PYTHONPATH=src uv run python main.py
```

Backend default URL:

```text
http://127.0.0.1:8765
```

Start the React frontend:

```bash
npm run dev
```

Frontend default URL:

```text
http://127.0.0.1:5173
```

Vite proxies `/api` and `/resources` to the backend during development.

Build the frontend:

```bash
npm run build
```

The build output is written to `dist/frontend`.

## Frontend

The current frontend is a new React implementation, not the old static
HTML/CSS/JS frontend.

Implemented now:

- Library workspace shell with collections, search, sorting, paper cards, and a
  details panel.
- PDF import, link import, note rename, and summary save wired to new backend
  routes.
- Reader workspace with paper navigation, PDF surface, note surface, related
  papers, RAG status, session list, and agent chat.
- Responsive desktop/mobile layout.

Stubbed for later wiring:

- Collection creation and collection editing.
- Tags editor.
- Annotation editing UI.
- Model/provider switcher.
- Settings pages beyond the current shell.
- Reader search and detailed PDF toolbar behavior.

## Backend API

Current new backend routes:

- `GET /health`
- `GET /api/library`
- `POST /api/library/import/pdf`
- `POST /api/library/import/url`
- `POST /api/library/notes/{note_id}/rename`
- `POST /api/library/notes/{note_id}/summary`
- `GET /api/rag/status`
- `POST /api/rag/index`
- `POST /api/agent/run`
- `GET /api/agent/sessions`
- `GET /api/agent/sessions/{session_id}`
- `GET /api/agent/sessions/{session_id}/context`
- `POST /api/agent/sessions/{session_id}/rename`
- `POST /api/agent/sessions/{session_id}/archive`
- `POST /api/agent/sessions/{session_id}/state`
- `DELETE /api/agent/sessions/{session_id}`

`/resources` is mounted for local PDFs and generated HTML notes.

## Import And RAG

Imported PDFs are stored under `resources/Papers/`. Matching HTML notes are
created under `resources/Paper-html/`, and note metadata is stored in
`notes.json`.

When a PDF is imported through the backend, Paper Notes attempts to build a RAG
index for that note. RAG indexing can also be triggered manually through
`POST /api/rag/index`.

The agent does not load the whole RAG system by default. RAG retrieval is a
normal model-visible tool:

```text
search_paper_rag
```

The model can call that tool when it needs semantic retrieval from a paper.

## Agent Runtime

The new agent entry point is `AgentService.run(...)` in
`src/agent_runtime/service.py`. It:

- creates or continues local sessions,
- converts stored transcript messages into LangChain messages,
- runs `run_agent_loop`,
- exposes Paper Notes tools,
- persists final messages back to JSONL transcripts,
- exposes context budget status for the UI.

SQLite checkpointers are not part of the new runtime path. Session persistence
is handled by `src/agent_sessions`.

## Context Management

Long context handling is split into two stages:

- `ContextCollapseMiddleware` preserves existing `[summary]` messages and uses
  LangChain summarization for ordinary messages.
- `ContextCompactionMiddleware` only runs after summaries already exist and the
  remaining context is still too large.

Compaction thresholds use each provider/model capability profile from
`src/model_providers/profiles`. The default reserve is 20,000 tokens, so the
trigger point is:

```text
model_context_window - 20,000
```

## Tools

Current Paper Notes tools:

- `search_notes`
- `get_note_context`
- `read_paper`
- `search_paper_rag`
- `write_note`
- `manage_annotations`
- `write_note_media`
- `review_note`

See `src/tools/README.md` for the tool boundary.

## Local Data

User data is local:

- `notes.json`: library metadata
- `resources/Papers/`: imported PDFs
- `resources/Paper-html/`: editable HTML notes
- `resources/Paper-annotations/`: annotation JSON
- `.paper-notes/sessions/`: session index and JSONL transcripts
- `.paper-notes/media/`: uploads and generated media artifacts
- `.paper-notes/rag/`: Qdrant/BM25 RAG indexes and derived image data

These runtime folders are ignored by Git.

## File Structure

```text
.
├── main.py                     # Backend entry point
├── config.json                 # Local model defaults
├── notes.json                  # Local paper library metadata
├── package.json                # React/Vite scripts and frontend dependencies
├── pyproject.toml              # Python runtime dependencies
├── vite.config.mjs             # Vite config and backend proxy
├── src/
│   ├── agent_prompts/          # Prompt composition
│   ├── agent_runtime/          # LangChain agent service and loop
│   ├── agent_sessions/         # JSON/JSONL session store
│   ├── app_config/             # Config loader
│   ├── app_infra/              # Paths, formatting, atomic storage
│   ├── library/                # Library metadata, note HTML, annotations
│   ├── media/                  # Media artifact store
│   ├── middleware/             # Context collapse and compaction
│   ├── model_providers/        # Provider factories and model capabilities
│   ├── rag/                    # Indexing, retriever, RAG service
│   ├── tools/                  # LangChain tools
│   └── ui/
│       ├── backend/            # FastAPI routes
│       └── frontend/           # React app
├── src_legacy/                 # Old implementation, migration reference only
├── resources/                  # Local paper files
└── .paper-notes/               # Local runtime state
```

## Verification

Useful focused checks:

```bash
npm run build
uv run ruff check src tests
PYTHONPATH=src uv run pytest tests/test_library.py tests/test_agent_api_langchain.py tests/test_rag_backend.py -q
```

Useful broader checks:

```bash
npm run lint
npm run test
npm run test:e2e
```

Some older tests still target the legacy frontend/runtime shape and are not the
source of truth for the new rewrite until they are migrated.

## License

MIT License. If you use or redistribute this project, keep the copyright and
license notice.
