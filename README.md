# Paper Notes

Paper Notes is a local research workspace for reading PDFs, annotating papers, building HTML notes, and using an agent to work with your paper library.

## Preview

Paper Notes opens a PDF and its matching HTML note side by side:

![Paper Notes split reader preview](assets/paper-notes-reader-preview.png)

The library view keeps imported papers, summaries, tags, collections, and paper actions in one place:

![Paper Notes library preview](assets/paper-notes-library-preview.png)

## Getting Started

Clone the repository:

```bash
git clone https://github.com/gcxzer/Paper_notes.git
cd Paper_notes
```

## Local Runtime

Requirements:

- Python 3.12+
- `uv`
- Node.js and npm

On macOS:

```bash
brew install uv
brew install node
```

On other systems, install `uv` from [astral.sh/uv](https://docs.astral.sh/uv/)
and install Node.js from [nodejs.org](https://nodejs.org/).

Install dependencies:

```bash
npm install
uv sync
```

Install and start the local background service:

```bash
scripts/install-autostart.sh
```

Open `http://127.0.0.1:8765`.

After pulling new code:

```bash
git pull
npm install
uv sync
scripts/install-autostart.sh
```

Remove the local background service:

```bash
scripts/uninstall-autostart.sh
```

To also remove the generated Python environment:

```bash
scripts/uninstall-autostart.sh --remove-venv
```

## Import PDFs

1. Open `http://127.0.0.1:8765`.
2. Click the `+` button in the library toolbar.
3. Choose one or more PDF files.

## Reader And Notes

Click a paper card or `Open Note` to open the split reader.

- Left pane: PDF.js paper reader.
- Middle pane: rendered HTML note.
- Right pane: agent chat.
- HTML notes include an automatic contents menu from `h2`, `h3`, and `h4`headings inside `.note-body`.


## PDF Annotations

Use the PDF toolbar to switch modes:

- `Browse`: normal reading and scrolling.
- `Highlight`: drag across PDF text to create a color highlight.
- `Underline`: drag across text to add a colored underline.
- `Note`: click a PDF page to add a sticky note.


Annotations are saved as JSON in `resources/Paper-annotations/`. The original PDF is not modified.

## Agent Assistant

Configuration lives in Settings:

- `AI Provider`: choose the model provider and local auth/secrets.
- `Tools`: change built-in tools between ask, read-only, block, or disabled.
- `MCP`: connect external stdio or Streamable HTTP MCP servers. Enabled servers appear under the `MCP` tool group, and secrets stay local inm`.paper-notes/secrets.env`.

## Paper RAG

The current default pipeline uses:

- LlamaParse for paper parsing, layout-aware Markdown, figure/table captions, and extracted paper images.
- DashScope `text-embedding-v4` for vector embeddings through
  `DASHSCOPE_API_KEY`.
- Local Qdrant for vector search and a persisted BM25 index for keyword search.
- DashScope reranking after hybrid retrieval.

Important RAG settings live in `config.json` under `rag.embedding`, `rag.retrieval`, `rag.reranking`, `rag.llamaparse`, and `rag.image_captioning`. 

## Local Data

Paper Notes keeps user data local:

Core library data:

- `notes.json`: paper library metadata
- `resources/Papers/`: imported PDFs
- `resources/Paper-html/`: editable HTML notes
- `resources/Paper-annotations/`: PDF annotation JSON

Derived paper caches:

- `resources/Paper-visuals/`: rendered PDF pages and extracted visual cache
- `.paper-notes/rag/indexes/`: local Qdrant and BM25 paper indexes
- `.paper-notes/rag/images/`: extracted paper images used by RAG and captioning

Agent and app runtime state:

- `.paper-notes/sessions/`: chat sessions and transcripts
- `.paper-notes/media/`: uploads and generated artifacts
- `.paper-notes/tool-outputs/`: downloadable tool-generated files
- `.paper-notes/skills/`: user-installed or user-authored skills
- `.paper-notes/skill-settings.json`: local skill settings
- `.paper-notes/mcp-servers.json`: local MCP server configuration
- `.paper-notes/tool-settings.json`: local tool permissions
- `.paper-notes/scratchpads.json`: floating scratchpad content
- `.paper-notes/logs/`: local runtime logs, including MCP stderr
- `.paper-notes/secrets.env` and `.paper-notes/auth/`: local provider secrets/auth

These runtime folders are ignored by Git.

## File Structure

```text
.
├── main.py                     # Local server entry point
├── notes.json                  # Local library metadata, generated at runtime
├── package.json                # Frontend scripts and PDF.js dependency
├── pyproject.toml              # Python runtime dependencies
├── scripts/                    # install/uninstall service helpers
├── src/
│   ├── agent_prompts/          # System prompt and context builder
│   ├── agent_runtime/          # Agent service, loop, runner, control
│   ├── agent_sessions/         # Chat session metadata and transcripts
│   ├── app_config/             # AI settings and local secrets
│   ├── app_infra/              # Paths, storage, shared formatting
│   ├── library/                # Library, note HTML, annotations
│   ├── media/                  # Upload and generated media store
│   ├── middleware/             # LangChain middleware and agent controls
│   ├── model_providers/        # Model provider integrations and profiles
│   ├── rag/                    # Paper parsing, indexing, retrieval, reranking
│   ├── skills/                 # Local Paper Notes skills
│   ├── tools/                  # Tool registry, visibility, and built-in tools
│   └── ui/
│       ├── backend/            # HTTP API and static server routes
│       └── frontend/
│           ├── index.html
│           ├── reader.html
│           ├── note-template.html
│           ├── scripts/
│           │   ├── reader/     # Reader, PDF, and chat modules
│           │   ├── site/       # Library page and settings modules
│           │   ├── shared/     # Shared browser helpers
│           │   └── note/       # Standalone note behavior
│           └── styles/
│               ├── reader/     # Reader CSS modules
│               └── site/       # Library/settings CSS modules
├── assets/                     # README/static image assets
└── resources/                  # Local paper workspace data, ignored by Git
```

## Development

Start the local server:

```bash
uv run python main.py
```

or:

```bash
npm start
```

Useful checks:

```bash
uv run --group dev pytest
npm run lint
npm run test:e2e
```

Focused syntax checks:

```bash
uv run python -m py_compile $(find src -name '*.py' -not -path '*/__pycache__/*') main.py
find src/ui/frontend/scripts -name '*.js' -print0 | xargs -0 -n1 node --check
```

Default port: `8765`.

## License

MIT License. If you use or redistribute this project, keep the copyright and
license notice.
