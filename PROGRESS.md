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
- React/Vite frontend, replacing the old static frontend.

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
10. PDF import now attempts RAG indexing after saving the paper.
11. New backend routes added for agent sessions, context status, RAG status,
    RAG indexing, and library operations.
12. Old frontend files under `src/ui/frontend` deleted.
13. New React/Vite frontend added with library and reader workspaces.

## Current Frontend Status

Implemented:

- React app shell.
- Library page with sidebar, paper grid, details panel, import controls, sort,
  search, rename, and summary edit.
- Reader page with paper rail, PDF surface, note surface, related papers, RAG
  status, session strip, context meter, and agent chat.
- Vite dev proxy for `/api` and `/resources`.
- Desktop and mobile layout checks.

Stubbed:

- Collection management.
- Tag editor.
- Annotation editing UI.
- Full PDF toolbar behavior.
- Settings pages.
- Model/provider switcher.
- Archived/trash session views.

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

Intentional current shape:

- No legacy frontend compatibility layer.
- No SQLite checkpointer in the active agent flow.
- No separate `rag/llm_model.py`; RAG is retrieval only.
- Frontend upload/indexing workflow is still minimal and should be expanded
  after the backend stabilizes.

## Verification

Recent checks:

```bash
npm run build
uv run ruff check src/ui/backend src/library
PYTHONPATH=src uv run pytest tests/test_library.py tests/test_agent_api_langchain.py tests/test_rag_backend.py -q
```

Result:

```text
19 passed, 5 warnings
```

Browser checks:

- `http://127.0.0.1:5173/` renders the React library workspace.
- `/reader/pdf-deepseek-v4-mp7dz7db` renders the React reader workspace.
- Mobile width check at 390px has no horizontal overflow after the reader
  layout fix.

## Next Migration Candidates

1. Finish backend library mutations:
   collection create/rename/delete/reorder, tag update, note move, note delete.
2. Rebuild annotation endpoints and connect the React reader annotation UI.
3. Add real settings routes for model provider selection and app config.
4. Replace old autostart scripts or remove them from the main path.
5. Migrate tests away from old frontend DOM ids and legacy runtime assumptions.
6. Add production serving for the built React frontend if the app should run as
   one process.
7. Revisit `config.json` and remove stale `checkpointer` configuration.

## Useful Commands

Backend:

```bash
PYTHONPATH=src uv run python main.py
```

Frontend:

```bash
npm run dev
```

Focused checks:

```bash
npm run build
uv run ruff check src tests
PYTHONPATH=src uv run pytest tests/test_library.py tests/test_agent_api_langchain.py tests/test_rag_backend.py -q
```
