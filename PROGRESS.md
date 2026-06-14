# Paper Notes Progress

Updated: 2026-06-13

## Current Direction

Paper Notes is being rewritten as a new project under `src/`, using the legacy
code in `src_legacy/` only as migration reference.

The new architecture is:

- LangChain/LangGraph agent runtime.
- JSON/JSONL `agent_sessions` storage instead of SQLite checkpointers.
- Local library/media/data layers restored under `app_infra`, `library`, and
  `media`.
- RAG integrated as a retriever tool, not as a separate answer-generation LLM.
- Static legacy frontend restored under `src/ui/frontend` and served by the
  FastAPI backend.

## Completed In This Rewrite Pass

1. Model provider capability profiles migrated for OpenAI, Codex, Anthropic,
   Gemini, and DeepSeek.
2. Context handling split into `ContextCollapseMiddleware` and
   `ContextCompactionMiddleware`.
3. Compaction thresholds now use provider/model context windows and a 20,000
   token reserve.
4. Old SQLite checkpointer path removed from the active agent runtime.
5. `AgentService.run(...)` added as the single backend agent entry point.
6. Agent session metadata and transcripts now persist under
   `.paper-notes/sessions/`.
7. Library, media, storage, path, and note HTML data layers restored.
8. RAG backend added under `src/rag`.
9. `search_paper_rag` exposed as a LangChain tool.
10. PDF import saves papers and notes without automatic RAG indexing.
11. New backend routes added for agent sessions, context status, RAG status,
    RAG indexing, and library operations.
12. Legacy static frontend restored under `src/ui/frontend`.
13. Frontend API calls adapted to the current backend routes without a
    compatibility layer.
14. The app now runs as a single backend/static-frontend service on port 8765.
15. RAG indexing moved to Settings/RAG; unindexed papers fall back to
    `read_paper`.

## Current Frontend Status

Implemented:

- Static app shell.
- Library page with sidebar, paper grid, details panel, import controls, sort,
  search, rename, and summary edit.
- Reader page with PDF surface, note surface, related papers, and agent chat.
- Settings RAG panel with per-paper status plus Index/Rebuild actions.
- Existing Settings menu entries are preserved; unimplemented settings remain
  visible but are not forced onto new backend routes.
- Static serving for `/resources` and required frontend packages.

Stubbed:

- Backend persistence for collection management, tags, note moves, note
  deletion, and scratchpad sync.
- Settings pages whose backend routes have not been implemented yet.

## Current Backend Status

Implemented:

- `GET /health`
- `GET /api/library`
- `POST /api/library/import/pdf`
- `POST /api/library/import/url`
- `POST /api/library/notes/{note_id}/rename`
- `POST /api/library/notes/{note_id}/summary`
- `GET /api/rag/status`
- `POST /api/rag/index`
- `POST /api/agent/run`
- agent session list/read/context/rename/archive/state/delete routes
- `/resources` static mount for local paper files
- `/` static mount for the frontend
- selected `/node_modules/...` static mounts for legacy frontend assets

Intentional current shape:

- No legacy frontend compatibility layer.
- No SQLite checkpointer in the active agent flow.
- No separate `rag/llm_model.py`; RAG is retrieval only.
- RAG indexing is a Settings-managed action, not part of the PDF import path.

## Verification

Recent checks:

```bash
node --check src/ui/frontend/scripts/site/settings/rag.js
node --check src/ui/frontend/scripts/site/actions.js
node --check src/ui/frontend/scripts/site/events.js
node --check src/ui/frontend/scripts/site/library.js
node --check src/ui/frontend/scripts/shared/floating-pad.js
PYTHONPATH=src uv run python -m compileall src/app_infra/paths.py src/ui/backend/server.py src/ui/backend/library_api.py src/ui/backend/rag_api.py
PYTHONPATH=src uv run pytest tests/test_library.py tests/test_agent_api_langchain.py tests/test_rag_backend.py -q
```

Result:

```text
Static frontend and RAG Settings smoke checks passed locally.
```

Browser checks:

- `http://127.0.0.1:8765/` serves the static Paper Notes workspace.
- Settings contains Theme, Scratchpad, AI Provider, RAG, MCP, and Skills.
- Settings/RAG opens and calls `/api/rag/status`.

## Next Migration Candidates

1. Finish backend library mutations:
   collection create/rename/delete/reorder, tag update, note move, note delete.
2. Rebuild annotation endpoints and connect the reader annotation UI.
3. Add real settings routes for model provider selection and app config.
4. Migrate tests away from old frontend DOM ids and legacy runtime assumptions.
5. Continue wiring legacy frontend surfaces to implemented backend routes.
6. Revisit `config.json` and remove stale `checkpointer` configuration.

## Useful Commands

Backend:

```bash
PYTHONPATH=src uv run python main.py
```

Focused checks:

```bash
uv run ruff check src tests
PYTHONPATH=src uv run pytest tests/test_library.py tests/test_agent_api_langchain.py tests/test_rag_backend.py -q
```
