# Paper Notes Progress

Updated: 2026-05-14

## Current Status

Paper Notes is now a local research workspace with a PDF reader, editable HTML
notes, a paper library, and an agent-backed Ask panel. The app runs from a local
Python server and keeps user data on disk instead of relying on a hosted service.

Current user-facing capabilities include:

- Import PDFs into a local library.
- Read a PDF beside its matching HTML note.
- Add highlights, underlines, and sticky notes with saved PDF annotations.
- Drag existing sticky note markers in any annotation mode.
- Edit paper summaries, collections, and tags from the library details panel.
- Add and remove tags from the library UI.
- Chat with an agent that can inspect papers, notes, annotations, sessions,
  skills, memory, web results, and bounded Python execution output.
- Review and apply safe note edits through Paper Notes tools.
- View debug logs, tool activity, note diffs, and undo/redo write snapshots.
- Generate local image and file artifacts.
- Configure AI providers, tool permissions, memory, skills, and web search from
  Settings.

## Architecture

The codebase is organized around a few stable boundaries:

- `main.py` starts the local server.
- `src/ui/backend` contains HTTP routes and the static file server.
- `src/ui/frontend` contains the library page, reader page, settings UI, PDF
  annotation UI, and chat UI.
- `src/library` owns paper metadata, note HTML helpers, and annotation storage.
- `src/agent_runtime` owns the local agent loop, session execution, cancellation,
  and progress events.
- `src/agent_prompts` builds model instructions and runtime context.
- `src/agent_sessions` stores chat session metadata and transcripts.
- `src/model_providers` isolates OpenAI API key and Codex OAuth providers.
- `src/tools` contains the tool registry and built-in tools.
- `src/tool_safety` handles approvals, write policies, snapshots, and restore
  safety.
- `src/telemetry` stores debug logs, run records, progress state, and tool
  result records.
- `src/app_config` and `.paper-notes/` hold local settings, secrets, and auth
  state.

Frontend files are split by surface:

- `src/ui/frontend/scripts/site` for the library and settings pages.
- `src/ui/frontend/scripts/reader` for the reader shell, panes, PDF tools, and
  chat.
- `src/ui/frontend/styles/site` and `src/ui/frontend/styles/reader` for CSS
  modules.

## Tools

The agent exposes these visible tool groups:

1. Paper Notes
2. Native Web Search
3. Code Execution
4. Persistent Memory
5. Session Search
6. Todo
7. Skills
8. Custom Web Search

Important current behavior:

- `web_search` and `web_fetch` are enabled by default through Custom Web Search.
- `paper_notes_edit` is not exposed as a top-level chat tool.
- Code Execution can import `paper_notes_tools.py` helpers for approved inner
  tools, including the controlled `paper_notes_edit` helper when Paper Notes
  read/review tools are visible.
- Code Execution still blocks recursive `execute_code`, non-allowlisted tools,
  artifact writes, memory writes, and todo writes through the RPC layer.
- Built-in mutating tools are governed by the same Settings > Tools access
  model as the rest of the app.

## Local Data

Runtime data is kept local:

- `notes.json` stores paper metadata.
- `resources/Papers/` stores imported PDFs.
- `resources/Paper-html/` stores editable HTML notes.
- `resources/Paper-annotations/` stores PDF annotation JSON.
- `.paper-notes/sessions/` stores chat sessions and transcripts.
- `.paper-notes/logs/` stores debug logs and tool result records.
- `.paper-notes/memory/` stores curated memory.
- `.paper-notes/media/` stores generated and uploaded media.
- `.paper-notes/tool-settings.json` stores tool permissions.
- `.paper-notes/secrets.env` and `.paper-notes/auth/` store local provider
  secrets and auth state.

These runtime folders are ignored by Git.

## Verification

Recent focused verification:

- Tool catalog, registry, prompt, service, Paper Notes tool, snapshot, and Code
  Execution tests passed in focused runs.
- Frontend syntax checks passed for modified JavaScript files.
- Browser checks passed for the library and reader surfaces after recent UI
  changes.
- Sticky note marker dragging was tested in the reader and restored with
  annotation undo.
- Tag add/remove UI was checked in the library page with no console errors.

Useful full checks:

```bash
uv run --group dev pytest
npm run lint
npm run test:e2e
```

Useful focused syntax checks:

```bash
uv run python -m py_compile $(find src -name '*.py' -not -path '*/__pycache__/*') main.py
find src/ui/frontend/scripts -name '*.js' -print0 | xargs -0 -n1 node --check
```

## Remaining Follow-Ups

- Add focused browser regression tests for PDF selection overlays, annotation
  interactions, sticky note dragging, and tag editing.
- Improve memory management and retrieval quality.
- Add a future subagent system if the agent workflow grows beyond one session
  runner.
- Consider splitting large backend API modules once their route groups stabilize.
- Consider a stronger sandbox backend for Code Execution, such as Docker or
  another isolated execution backend.
- Keep README and this progress brief aligned as tool behavior changes.
