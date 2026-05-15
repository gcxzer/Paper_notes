# Paper Notes Progress

Updated: 2026-05-15

## Remaining Follow-Ups

- Cron function
- channals ？
- Improve memory management and retrieval quality.
- Add a subagent system if the agent workflow grows beyond one session
  runner.
- Consider splitting large backend API modules once their route groups
  stabilize.
- Consider a stronger sandbox backend for Code Execution, such as Docker or
  another isolated execution backend.
- Keep README and this release brief aligned as tool behavior changes.

## Release 1.1.2

- PDF selections now appear in Ask as a compact `Text selected: x words`
  context badge, are sent with chat requests, and remain available even when
  focus moves into the chat input.
- Highlight and underline annotation flows keep the selected PDF text active
  after creating the mark, so the same passage can be annotated and then asked
  about without reselecting it.
- The Ask attachment menu can add the current PDF page as an image attachment
  through `Add page`, with provider capability checks for image input.
- Image generation controls now respect the active provider/model capability
  matrix, including disabling unsupported Codex Spark image generation.
- Selected-text chips use stable rendering and hover previews so tooltip and
  remove-button interactions do not flicker or resurrect cleared selections.

## Current Status

Paper Notes is now a local research workspace with a PDF reader, editable HTML
notes, a paper library, and an agent-backed Ask panel. The app runs from a local
Python server, can be installed as a local background service, and keeps user
data on disk instead of relying on a hosted service.

Current user-facing capabilities include:

- Import PDFs into a local library.
- Read a PDF beside its matching HTML note.
- Add highlights, underlines, and sticky notes with saved PDF annotations.
- Send selected PDF text to Ask as explicit model context.
- Drag existing sticky note markers in any annotation mode.
- Edit paper summaries, collections, and tags from the library details panel.
- Add and remove tags from the library UI.
- Chat with an agent that can inspect papers, notes, annotations, sessions,
  skills, memory, uploaded attachments, web results, and bounded Python
  execution output.
- Review and apply safe note edits through Paper Notes tools.
- View debug logs, tool activity, progress events, note diffs, and undo/redo
  write snapshots.
- Generate local image and file artifacts, including image generation routed
  through supported provider/model settings.
- Add the current PDF page to Ask as an image attachment when the active model
  supports image input.
- Upload chat attachments, extract supported text-like content, and attach
  images to model requests when the selected provider supports vision.
- Configure OpenAI, Codex OAuth, Anthropic, Gemini, and DeepSeek providers,
  tool permissions, memory, skills, and native/custom web search from Settings.
- Monitor context budget, manually compact long sessions, and continue from
  persisted compression checkpoints when sessions grow large.

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
- `src/model_providers` isolates OpenAI API key, Codex OAuth, Anthropic,
  Gemini, and DeepSeek providers plus model capability profiles.
- `src/tools` contains the tool registry and built-in tools.
- `src/tool_safety` handles approvals, write policies, snapshots, and restore
  safety.
- `src/telemetry` stores debug logs, run records, progress state, and tool
  result records.
- `src/context_compression` owns context budget estimation, tool-result
  pruning, summary generation, and reusable compression checkpoints.
- `src/agent_memory` owns local user/project memory and memory prompt sync.
- `src/media` owns uploaded/generated media, extracted attachment text, and
  local artifact serving.
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
3. Custom Web Search
4. Code Execution
5. Persistent Memory
6. Session Search
7. Todo
8. Skills

Important current behavior:

- Provider-native web search is a settings-controlled provider capability for
  supported model providers, not a normal function tool.
- `web_search` and `web_fetch` are enabled by default through Custom Web Search;
  configured custom providers prefer Tavily before Brave when both are present.
- `paper_notes_edit` is not exposed as a top-level chat tool.
- Code Execution can import `paper_notes_tools.py` helpers for approved inner
  tools, including the controlled `paper_notes_edit` helper when Paper Notes
  read/review tools are visible.
- Code Execution still blocks recursive `execute_code`, non-allowlisted tools,
  artifact writes, memory writes, and todo writes through the RPC layer.
- Built-in mutating tools are governed by the same Settings > Tools access
  model as the rest of the app.
- `generated_artifacts` registers `create_file_artifact` and
  `create_image_artifact`, but the group is hidden from normal tool settings and
  only selected for explicit generation flows.
- Large tool outputs are stored under `.paper-notes/logs/tool-results/` and
  replaced with compact references when needed.

## Model Providers

Current provider boundary:

- OpenAI API key provider uses the public Responses API and supports tools,
  vision, provider-native web search, and image generation.
- Codex OAuth uses the Codex Responses backend, supports tools, vision, and
  provider-native web search, but rejects image generation.
- Anthropic uses the native Claude Messages API with tools, vision, and native
  web-search normalization.
- Gemini uses the native Gemini API with tools, vision, and native web-search
  normalization.
- DeepSeek uses the OpenAI-compatible chat-completions API with tools, but no
  vision or web-search capability profile.

Settings can store local API keys and model selections in `.paper-notes/`, while
Codex OAuth stores local auth state under `.paper-notes/auth/`. Provider/model
selection can also be overridden per chat request.

## Local Data

Runtime data is kept local:

- `notes.json` stores paper metadata.
- `resources/Papers/` stores imported PDFs.
- `resources/Paper-html/` stores editable HTML notes.
- `resources/Paper-annotations/` stores PDF annotation JSON.
- `resources/Paper-text/` stores extracted PDF text cache.
- `resources/Paper-pages/` stores rendered PDF page image cache.
- `resources/Paper-images/` stores extracted PDF image cache.
- `.paper-notes/sessions/` stores chat sessions and transcripts.
- `.paper-notes/compression/` stores context compression checkpoints.
- `.paper-notes/snapshots/` stores write snapshots for tool undo/redo.
- `.paper-notes/approvals/` stores local tool approval history.
- `.paper-notes/logs/` stores debug logs and tool result records.
- `.paper-notes/memory/` stores curated memory.
- `.paper-notes/media/` stores generated and uploaded media.
- `.paper-notes/skills/` stores user-installed or user-authored skills.
- `.paper-notes/tool-settings.json` stores tool permissions.
- `.paper-notes/secrets.env` and `.paper-notes/auth/` store local provider
  secrets and auth state.

These runtime folders are ignored by Git.

## Verification

Recent focused verification:

- Tool catalog, registry, prompt, service, context compression, memory, provider,
  Paper Notes tool, snapshot, media, generated artifact, web search/fetch, and
  Code Execution tests have focused coverage.
- Frontend syntax checks passed for modified JavaScript files.
- Browser checks passed for the library and reader surfaces after recent UI
  changes.
- Focused browser regression tests now cover sticky note marker dragging with
  annotation undo, library tag add/remove flows, attachment upload/tray
  behavior, and manual context compaction controls.
- Provider-native web search support is complete for the supported providers,
  and image-generation support now follows the current provider matrix with
  enforced runtime and UI routing.

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
