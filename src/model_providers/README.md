# model_providers

Provider boundary for model calls, image generation routing, and model/provider
metadata.

## Files

- `__init__.py`: Public exports for provider factories and shared types.
- `base.py`: Provider protocol shared by OpenAI API key and Codex OAuth providers.
- `errors.py`: Provider-specific exception types.
- `factory.py`: Builds the active provider from local AI settings.
- `image_routing.py`: Chooses whether image generation should use OpenAI API key or Codex OAuth.
- `resolver.py`: Resolves provider/model settings into runtime provider selections.
- `responses_adapter.py`: Converts Paper Notes model requests into Responses-style payloads and normalizes responses.
- `types.py`: Dataclasses for provider requests, results, usage, tool calls, and attachments.

## Subdirectories

- `codex/`: Codex OAuth auth flow, credentials, provider implementation, and types.
- `openai/`: OpenAI API key provider implementation.
- `profiles/`: Built-in provider/model capability metadata and registry helpers.
