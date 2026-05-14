# context_compression

Context window management for long agent sessions.

## Files

- `__init__.py`: Public exports for compressors, checkpoints, estimators, and errors.
- `checkpoint.py`: Saves and loads reusable compression checkpoints per session.
- `compressor.py`: Decides when to compress and builds compact message history.
- `errors.py`: Detects model context overflow errors.
- `estimator.py`: Estimates token usage from text and message content.
- `model_context.py`: Resolves model context length defaults.
- `summary.py`: Builds summary prompts and redacts sensitive text from compression inputs.
- `tool_pruning.py`: Truncates or summarizes old tool results to fit the context budget.
- `types.py`: Dataclasses for compression config, checkpoints, and status snapshots.
