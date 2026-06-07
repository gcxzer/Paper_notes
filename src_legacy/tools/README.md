# tools

Tool definitions, registry, settings metadata, execution adapter, and built-in
tool groups.

## Files

- `__init__.py`: Package marker for tool modules.
- `catalog.py`: Builds UI-facing tool catalog data from registered tools and groups.
- `executor.py`: Adapts model tool calls to the registry, approvals, write modes, snapshots, and result storage.
- `output_limits.py`: Central result size budgets and per-tool overrides.
- `registry.py`: Registers tool definitions, groups, middleware, and dispatch handlers.
- `result_storage.py`: Stores large tool results under `.paper-notes/logs/tool-results/`.
- `schema_sanitizer.py`: Normalizes tool schemas before sending them to model providers.
- `toolsets.py`: Defines built-in toolsets, visible groups, defaults, and resolution logic.
- `types.py`: Shared dataclasses for tool definitions, groups, results, and execution context.

## Subdirectories

- `code_execution/`: Guarded local Python execution and parent-tool RPC helpers.
- `generated_files/`: Tool for creating generated file artifacts.
- `generated_images/`: Tool for creating generated image artifacts.
- `paper_notes/`: Paper search, context, reading, review, and safe edit tools.
- `persistent_memory/`: Tool wrapper for local persistent memory.
- `session_search/`: Tool for searching previous chat sessions.
- `skills/`: Tooling for discovering and reading local skills.
- `todo/`: Session-local planning/todo tool.
- `web_fetch/`: Public URL fetching and extraction helpers.
- `web_search/`: Tavily, Brave, and native-provider web search integrations.
