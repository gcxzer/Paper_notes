# tools

LangChain-native tools for the new Paper Notes agent runtime.

The public entry point is `tools.create_tools(...)`. It returns
`langchain_core.tools.StructuredTool` instances and is used by
`agent_runtime.AgentService`.

## Current Tools

- `search_notes`: search or list local paper metadata.
- `get_note_context`: build compact note context from metadata, note HTML,
  annotations, and optional PDF snippets.
- `read_paper`: search PDF text, read pages, render pages, extract images, or
  analyze a registered image artifact when an analyzer is available.
- `read_workspace`: read, list, stat, or search files under the current
  Paper_Notes workspace.
- `search_paper_rag`: semantically retrieve passages from a note's ready local
  RAG index.
- `write_note`: update note HTML sections or note metadata.
- `manage_annotations`: create, update, or delete Paper Notes annotations.
- `write_note_media`: write note content from paper images or insert existing
  image artifacts.
- `review_note`: validate note HTML or preview a section diff without saving.

## Boundaries

- Tool schemas live in `tools.paper_notes.schemas`.
- Model-visible tool construction lives in `tools.paper_notes.tool`.
- Tool orchestration and action dispatch live in `tools.paper_notes.impl.facade`.
- Domain logic belongs in `library`, `media`, `rag`, and `app_infra`.
- The RAG system is exposed only as retrieval through `search_paper_rag`; it
  should not generate final answers by itself.
- PDF import does not build indexes. Use `read_paper` for unindexed papers and
  `search_paper_rag` only after Settings/RAG has created the index.
