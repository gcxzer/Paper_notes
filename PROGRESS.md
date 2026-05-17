# Paper Notes Progress

Updated: 2026-05-17

## Remaining Follow-Ups

- Cron
- Improve memory management and retrieval quality.
- Add a subagent system if the agent workflow grows beyond one session
  runner.
- Consider splitting large backend API modules once their route groups
  stabilize.
- Consider a stronger sandbox backend for Code Execution, such as Docker or
  another isolated execution backend.
- Keep README and this release brief aligned as tool behavior changes.
- MCP follow-ups from the Hermes Agent comparison:
  - P0 completed: dynamic `tools/list_changed` refresh,
    reconnection/keepalive recovery, and capability-aware resource/prompt
    utility tools for stdio and Streamable HTTP.
  - P1 completed: per-server include/exclude tool filters with wildcard support
    and Settings > MCP textarea configuration.
  - P2A completed: MCP `image/*` tool/resource/prompt results are materialized
    as Paper Notes media artifacts.
  - P2B completed: MCP safe text-like tool/resource/prompt results are
    materialized as Paper Notes file artifacts.
  - P2C/hardening completed: artifact-safe trimming, MCP prompt-injection
    warnings/sanitization, circuit breaker status, and best-effort stdio orphan
    cleanup.
  - P2D/status-smoke completed: Streamable HTTP cross-origin redirects strip
    configured/sensitive headers, Settings > MCP shows circuit/security status,
    and smoke coverage verifies MCP settings plus MCP artifact cards.
  - Post-1.2 hardening completed: MCP env/header secrets are externalized into
    `.paper-notes/secrets.env`, Settings > MCP has reconnect/reset/log actions,
    MCP security helpers were split out of `manager.py`, PDF results can become
    local artifacts, and MCP annotations/output schemas are preserved in tool
    metadata.
  - SSE transport and OAuth 2.1/PKCE are intentionally not planned for now.
  - Later candidates: MCP sampling/createMessage support, running Paper Notes as
    an MCP server, richer log/status UX, Office artifactization, archives, and
    arbitrary binary artifactization after safety review.

## Release 1.2.0

- Added MCP stdio and Streamable HTTP tool integration with dynamic
  `tools/list_changed` refresh, reconnect/keepalive recovery, and
  circuit-breaker status reporting.
- Added capability-aware MCP resource and prompt utility tools, plus
  per-server include/exclude filters in Settings > MCP.
- MCP image and safe text-like results now materialize as Paper Notes media
  artifacts while preserving artifact fields through result trimming.
- Added MCP prompt-injection warning/sanitization, redirect header stripping,
  stdio orphan cleanup, and Settings > MCP status/security warning display.
- Expanded MCP API, registry, media store, prompt, agent service, and Playwright
  smoke coverage; full backend and smoke suites pass for the release.

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
9. MCP, when at least one enabled MCP server exposes tools

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
- MCP currently connects enabled external servers at agent startup, registers
  discovered tools under the `mcp` toolset, supports stdio and Streamable HTTP,
  stores env/header secrets in `.paper-notes/secrets.env` rather than
  `.paper-notes/mcp-servers.json`, redacts settings responses, and maps MCP
  read-only/destructive/idempotent/open-world annotations into tool metadata.
- MCP refreshes the registry on `tools/list_changed`, recovers long-lived
  sessions with keepalive/reconnect, and exposes read-only resources/prompts
  utility tools when a server advertises those capabilities.
- MCP server settings can include or exclude ordinary tools and MCP utility
  tools per server, using exact names or `*` wildcards.
- MCP `image/*`, safe text-like, and PDF content returned by tools, resource
  reads, or prompt content is now stored as local `source="mcp"` media/file
  artifacts and attached to assistant messages through the existing artifact
  card pipeline.
- MCP preserves artifact, media error, and security warning fields when large
  tool results are trimmed or persisted as compact references.
- MCP treats external tool descriptions, schema descriptions, resources,
  prompts, and results as untrusted content: suspicious instruction-like
  descriptions are neutralized before model exposure, and suspicious result
  content carries `securityWarnings` without blocking the result.
- MCP long-lived servers report runtime state, failure counts, retry timing, and
  circuit-open status; repeated reconnect failures pause retries until cooldown,
  and circuit-open tool calls return `mcp_circuit_open`.
- Settings > MCP displays circuit-open/reconnecting/connecting status, retry
  timing, failure counts, and MCP security warning counts from the public status
  payload; it also exposes reconnect, reset circuit, and stderr-log actions for
  already configured servers.
- MCP Streamable HTTP keeps normal same-origin redirects but strips configured
  and standard sensitive headers on cross-origin redirects.
- MCP stdio servers are tracked during transport startup and cleaned up
  best-effort on shutdown, cancellation, or startup timeout.
- Current MCP limits, compared with `hermes-agent`, are intentional gaps for now:
  no SSE transport, OAuth, sampling, Paper Notes MCP-server mode,
  Office/archive artifactization, or arbitrary binary MCP file artifactization.
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
- Focused MCP coverage passes for settings persistence/redaction, stdio and
  Streamable HTTP fixtures, tool registration, timeout/error handling, and
  AgentService tool visibility.
- MCP P0 coverage passes for dynamic tool refresh, `tools/list_changed`
  notification handling, reconnect retry on expired sessions, keepalive-triggered
  reconnect, and capability-aware resources/prompts utility tools.
- 2026-05-17 MCP P0 verification:
  - `uv run python -m py_compile src/tools/mcp/manager.py src/tools/registry.py`
    passed.
  - `uv run pytest tests/test_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_agent_service.py -q`
    passed with 19 tests.
  - `uv run pytest tests/test_tool_catalog.py tests/test_ai_settings_api.py tests/test_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_agent_service.py -q`
    passed with 60 tests.
  - `npm run test:e2e -- tests/e2e/paper-notes-smoke.spec.js -g "MCP"`
    passed with 1 Playwright smoke test.
- 2026-05-17 MCP P2C/hardening verification:
  - `uv run python -m py_compile src/tools/registry.py src/tools/result_storage.py src/tools/mcp/manager.py src/tools/executor.py src/agent_prompts/builder.py`
    passed.
  - `uv run pytest tests/test_tool_registry.py tests/test_mcp_tool.py tests/test_agent_prompts.py -q`
    passed with 70 tests.
  - `uv run pytest tests/test_tool_registry.py tests/test_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_agent_service.py tests/test_agent_prompts.py tests/test_agent_service.py -q`
    passed with 131 tests.
- 2026-05-17 MCP P2D/status-smoke verification:
  - `uv run python -m py_compile src/tools/mcp/manager.py src/tools/mcp/settings.py`
    passed.
  - `node --check src/ui/frontend/scripts/site/settings/mcp.js` passed.
  - `uv run pytest tests/test_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_agent_service.py tests/test_agent_prompts.py tests/test_agent_service.py -q`
    passed with 118 tests.
  - `npm run test:e2e -- tests/e2e/paper-notes-smoke.spec.js -g "MCP|artifact"`
    passed with 2 Playwright smoke tests.
- 2026-05-17 MCP closure verification:
  - `uv run pytest -q` passed with 528 tests.
  - `npm run test:e2e -- tests/e2e/paper-notes-smoke.spec.js` passed with
    48 Playwright smoke tests.
  - `git diff --check` passed.
- 2026-05-17 MCP P1 verification:
  - `uv run python -m py_compile src/tools/mcp/settings.py src/tools/mcp/manager.py src/tools/registry.py`
    passed.
  - `node --check src/ui/frontend/scripts/site/settings/mcp.js && node --check src/ui/frontend/scripts/site/events.js`
    passed.
  - `uv run pytest tests/test_mcp_tool.py tests/test_mcp_api.py -q`
    passed with 22 tests.
  - `uv run pytest tests/test_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_agent_service.py tests/test_tool_catalog.py tests/test_ai_settings_api.py -q`
    passed with 64 tests.
  - `npm run test:e2e -- tests/e2e/paper-notes-smoke.spec.js -g "MCP"`
    passed with 1 Playwright smoke test.
- 2026-05-17 MCP P2A verification:
  - `uv run python -m py_compile src/tools/mcp/manager.py src/media/store.py src/agent_runtime/service.py`
    passed.
  - `uv run pytest tests/test_mcp_tool.py tests/test_media_store.py tests/test_agent_service.py tests/test_mcp_agent_service.py -q`
    passed with 98 tests.
  - `uv run pytest tests/test_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_agent_service.py tests/test_agent_service.py tests/test_media_store.py -q`
    passed with 102 tests.
- 2026-05-17 MCP P2B verification:
  - `uv run python -m py_compile src/tools/mcp/manager.py src/media/store.py src/agent_runtime/service.py`
    passed.
  - `uv run pytest tests/test_mcp_tool.py tests/test_media_store.py tests/test_mcp_api.py tests/test_mcp_agent_service.py tests/test_agent_service.py -q`
    passed with 116 tests.
- 2026-05-17 MCP post-1.2 hardening verification:
  - `uv run python -m py_compile src/tools/mcp/manager.py src/tools/mcp/security.py src/tools/mcp/settings.py src/media/store.py src/ui/backend/mcp_api.py src/ui/backend/server.py src/agent_runtime/service.py src/tools/registry.py src/tools/result_storage.py src/agent_prompts/builder.py`
    passed.
  - `node --check src/ui/frontend/scripts/site/settings/mcp.js && node --check src/ui/frontend/scripts/site/settings/ai.js && node --check src/ui/frontend/scripts/site/events.js && node --check src/ui/frontend/scripts/site/page_state.js && node --check tests/e2e/paper-notes-smoke.spec.js`
    passed.
  - `uv run pytest tests/test_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_agent_service.py tests/test_media_store.py tests/test_tool_registry.py tests/test_agent_prompts.py tests/test_agent_service.py tests/test_tool_catalog.py tests/test_ai_settings_api.py -q`
    passed with 204 tests and 5 PyMuPDF deprecation warnings, including
    circuit reset interrupting circuit-open cooldown.
  - `npm run test:e2e -- tests/e2e/paper-notes-smoke.spec.js -g "MCP|artifact|home settings"`
    passed with 3 Playwright smoke tests.
  - `uv run pytest -q` passed with 534 tests and 5 PyMuPDF deprecation
    warnings.
  - `npm run test:e2e -- tests/e2e/paper-notes-smoke.spec.js` passed with
    48 Playwright smoke tests.
  - Manual rendered smoke on `http://localhost:4174` passed for desktop/mobile
    Model capabilities modal bounds and Settings > MCP empty-state rendering;
    console warnings/errors were clean.
  - `git diff --check` passed.
- 2026-05-17 MCP env-header settings follow-up:
  - Added Streamable HTTP `bearerTokenEnvVar` and `headerEnvVars` support. Runtime
    resolves declared env names from `os.environ`, `.paper-notes/secrets.env`,
    `.env.local`, and `.env`, then sends only the requested headers.
  - Settings > MCP now exposes `Bearer token env var` and `Headers from
    environment variables` for HTTP servers; Test/Save payloads preserve the
    fields without storing secret values.
  - Added concise Settings hints for env-backed HTTP headers and standardized
    MCP timeout cancellation by sending `notifications/cancelled` before
    cancelling a pending request locally.
  - `uv run python -m py_compile src/tools/mcp/settings.py src/tools/mcp/manager.py`
    passed.
  - `node --check src/ui/frontend/scripts/site/settings/mcp.js && node --check src/ui/frontend/scripts/site/events.js && node --check tests/e2e/paper-notes-smoke.spec.js`
    passed.
  - `uv run pytest tests/test_mcp_api.py tests/test_mcp_tool.py -q`
    passed with 49 tests and 5 PyMuPDF deprecation warnings.
  - `uv run pytest tests/test_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_agent_service.py tests/test_agent_prompts.py tests/test_agent_service.py -q`
    passed with 125 tests and 5 PyMuPDF deprecation warnings.
  - `npm run test:e2e -- tests/e2e/paper-notes-smoke.spec.js -g "MCP settings"`
    passed with 2 Playwright smoke tests.
  - `git diff --check` passed.

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
