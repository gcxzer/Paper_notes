# telemetry

Runtime observability for agent runs, debug logs, progress updates, and
background run state.

## Files

- `__init__.py`: Public exports for debug log and run state stores.
- `agent_background_runs.py`: Tracks background agent run metadata.
- `agent_progress.py`: Converts runtime events and tool calls into user-visible progress updates.
- `agent_runs.py`: Tracks active agent run state for polling and cancellation.
- `debug_logs.py`: Stores sanitized request, response, tool, and trace records under `.paper-notes/logs/`.
