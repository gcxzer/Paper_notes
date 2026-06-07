# agent_sessions

Persistent chat session metadata and transcripts.

## Files

- `__init__.py`: Public exports for session models, stores, transcript helpers, and errors.
- `models.py`: Dataclasses for sessions, metadata, transcript entries, and branch/archive state.
- `session_store.py`: Creates, lists, updates, branches, archives, and deletes session records under `.paper-notes/sessions/`.
- `transcripts.py`: Reads, writes, and locates JSONL transcript files for each session.
