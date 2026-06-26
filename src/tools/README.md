# tools

LangChain-native tools for the new Paper Notes agent runtime.

The public entry point is `tools.create_tools(ToolContext(...))`. It returns
the model-visible tools for one request, including `langchain_core.tools.StructuredTool`
instances and provider-native server tools such as OpenAI web search.
The request-level visibility resolver lives in `tools.visibility`; `tools.__init__`
only re-exports the public API.

## Current Tools

- `get_paper_context`: search/list local paper metadata or build compact context
  for one paper from metadata, note HTML, annotations, and local paper index status.
- `inspect_paper_visuals`: render PDF pages, extract figures/images, or analyze registered paper images.
- `read_paper`: directly search or read extracted local PDF page text without RAG.
- `query_paper_content`: semantic retrieval
  over a note's ready local paper index.
- `write_note`: update note HTML sections or note metadata.
- `manage_annotations`: create, update, or delete Paper Notes annotations.
- `write_note_media`: insert existing image artifacts into notes.
- `review_note`: validate note HTML or preview a section diff without saving.

## Boundaries

- Tool schemas live in `tools.paper_notes.schemas`.
- Model/tool capability gating lives in `tools.visibility`.
- Model-visible tool construction lives in `tools.paper_notes.tool`.
- Tool orchestration and action dispatch live in `tools.paper_notes.impl.facade`.
- Domain logic belongs in `library`, `media`, `rag`, and `app_infra`.
- The RAG system is exposed only as paper-content retrieval through `query_paper_content`;
  it should not generate final answers by itself. `rag.enabled=false` or
  `rag.retrieval.enabled=false` hides this semantic retrieval tool while keeping
  direct PDF text reading available through `read_paper`.
- PDF import does not build indexes. Use `query_paper_content` for paper content
  only after Settings/RAG has created the index and RAG querying is enabled. Use
  `read_paper` for exact text/page fallback, and use `inspect_paper_visuals` only
  for visual page/figure rendering, extraction, and image analysis.
