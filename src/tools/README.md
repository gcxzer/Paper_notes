# tools

LangChain-native tool skeletons for Paper Notes.

Each tool package exposes `create_tools()` and returns `langchain_core.tools`
instances. The current migration only recreates the tool folders and model
visible tool names from `src_legacy/tools`; runtime wiring, permissions, and
full handlers will be filled in incrementally.
