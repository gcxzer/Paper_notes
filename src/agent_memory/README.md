# agent_memory

Local persistent memory used by the agent across chat sessions.

## Files

- `__init__.py`: Public exports for memory providers, managers, stores, and data types.
- `local_provider.py`: Adapts the local memory manager to the agent prompt/runtime interface.
- `manager.py`: Coordinates memory prefetch, turn syncing, and user/project memory updates.
- `store.py`: Reads, writes, validates, and lists memory entries under `.paper-notes/memory/`.
- `types.py`: Dataclasses and protocol types shared by the memory manager and tools.
