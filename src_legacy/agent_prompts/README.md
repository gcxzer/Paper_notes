# agent_prompts

This package builds the model-facing instructions for Paper Notes agent runs.
Keep prompt composition centralized here, but keep request-specific runtime
facts in `agent_runtime.service`.

## Files

- `__init__.py`: Public exports for prompt context and instruction builders.
- `builder.py`: Composes the final instructions string from identity, response discipline, memory/todo guidance, available tools, and reading context.
- `reading_context.py`: Normalizes Reader context and renders current paper, page, selected text, and visible annotation context.
- `defaults.py`: Static instruction blocks and per-tool guidance used by the prompt builder.

## Prompt Flow

`AgentService` builds per-run inputs in this order:

1. Select model-visible tools for the request.
2. Build request-specific extras such as attachment instructions and generation
   mode instructions.
3. Call `build_agent_instructions(...)` from this package.
4. Add ephemeral runtime context as a system message, not inside this package.

## Boundaries

- Runtime context (`# Runtime context`, current date, provider, model, session)
  is generated in `agent_runtime.service`.
- `Generate image` / `Generate file` mode instructions are generated in
  `agent_runtime.service`, because they depend on the current request payload.
- Tool schemas and tool availability live under `tools/`.
- Do not add hidden chain-of-thought instructions. Visible work status belongs
  to runtime events and progress serialization, not this package.
