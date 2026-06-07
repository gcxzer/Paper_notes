# tool_safety

Safety layer for mutating tools: approvals, guardrails, snapshots, and restore
recovery.

## Files

- `__init__.py`: Public exports for approvals, guardrails, snapshots, and recovery helpers.
- `approvals.py`: Persists approval history and manages pending tool approval records.
- `guardrails.py`: Validates tool write attempts and write-mode policy decisions.
- `recovery.py`: Restores files from snapshots and reports conflicts.
- `snapshots.py`: Captures before/after snapshots for Paper Notes writes and supports undo/redo.
