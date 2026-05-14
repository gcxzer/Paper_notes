# agent_runtime

The local agent execution layer. It turns a chat request into model calls, tool
calls, progress events, persisted sessions, and final responses.

## Files

- `__init__.py`: Public exports for the service, runner, run control, and runtime types.
- `agent_loop.py`: Core model/tool loop, including tool call execution and message updates.
- `agent_runner.py`: Higher-level run wrapper that invokes the loop and returns structured results.
- `model_messages.py`: Helpers for normalizing and sanitizing model-facing messages.
- `run_control.py`: Cancellation and run-state control primitives.
- `service.py`: Main application service used by HTTP routes; wires providers, tools, memory, sessions, compression, media, and debug state.
- `types.py`: Request, response, event, tool, and model provider dataclasses/protocols.
