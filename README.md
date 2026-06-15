# Paper Notes

Paper Notes is a local research workspace for reading PDFs, annotating papers,
building HTML notes, and using an agent to work with your paper library.

## Preview

Paper Notes opens a PDF and its matching HTML note side by side:

![Paper Notes split reader preview](assets/paper-notes-reader-preview.png)

The library view keeps imported papers, summaries, tags, collections, and paper
actions in one place:

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

Open `http://127.0.0.1:4173`.

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

1. Open `http://127.0.0.1:4173`.
2. Click the `+` button in the library toolbar.
3. Choose one or more PDF files.

For each imported PDF, Paper Notes creates:

- `resources/Papers/<same name>.pdf`
- `resources/Paper-html/<same name>.html`
- `resources/Paper-annotations/<note id>.json` after annotations exist
- one note entry in `notes.json`

The generated HTML note starts with the paper title and metadata, then seeds
`.note-body` with the PDF outline when one is available. If the PDF has no
embedded outline, Paper Notes tries to infer common section headings from the
first pages.

No fake summary, placeholder prose, or default section text is inserted.

## Reader And Notes

Click a paper card or `Open Note` to open the split reader.

- Left pane: PDF.js paper reader.
- Middle pane: rendered HTML note.
- Right pane: agent chat.
- PDF and note panes scroll independently on desktop.
- The dividers resize the PDF, note, and chat panes.
- The PDF toolbar supports page jumping, zoom, internal PDF links, highlights,
  underlines, sticky notes, annotation undo/redo, and PDF text copy.
- Existing sticky note markers can be dragged to reposition them in any PDF
  annotation mode.
- HTML notes include an automatic contents menu from `h2`, `h3`, and `h4`
  headings inside `.note-body`.

To edit a note manually, open the matching file in `resources/Paper-html/` and
write normal HTML inside `.note-body`.

```html
<section class="note-body">
  <h2>Main Idea</h2>
  <p>Write your notes here.</p>

  <h2>Method</h2>
  <h3>Training Setup</h3>
  <p>Details...</p>
</section>
```

Refresh the reader after editing the file. Static files are served with
`Cache-Control: no-store`, so local note edits show up after refresh.

## PDF Annotations

The split reader uses PDF.js instead of the browser's read-only PDF iframe.
Use the PDF toolbar to switch modes:

- `Browse`: normal reading and scrolling.
- `Highlight`: drag across PDF text to create a color highlight.
- `Underline`: drag across text to add a colored underline.
- `Note`: click a PDF page to add a sticky note.

Existing sticky note markers can be dragged in any annotation mode. Annotation
undo/redo covers created, deleted, edited, and repositioned annotations.

Annotations are saved as JSON in `resources/Paper-annotations/`. The original
PDF is not modified.

## Agent Assistant

The Reader `Ask` panel is backed by the local agent runtime. It can use local
tools to search papers, read PDF text, inspect note HTML, render or extract PDF
images, review safe note edits, generate image/file artifacts, search past
sessions, maintain session todos, read/write curated memory, load skills, and
run bounded Python code.

Configuration lives in Settings:

- `AI Provider`: choose the model provider and local auth/secrets.
- `Tools`: change built-in tools between ask, read-only, block, or disabled.
- `MCP`: connect external stdio or Streamable HTTP MCP servers. Enabled servers
  appear under the `MCP` tool group, and secrets stay local in
  `.paper-notes/secrets.env`.

Current MCP support includes tool refresh, reconnect handling, per-server tool
filters, and local artifact creation for MCP image, PDF, and safe text-like
results. SSE transport, MCP OAuth, and running Paper Notes itself as an MCP
server are out of scope for now.

## Local Data

Paper Notes keeps user data local:

Core library data:

- `notes.json`: paper library metadata
- `resources/Papers/`: imported PDFs
- `resources/Paper-html/`: editable HTML notes
- `resources/Paper-annotations/`: PDF annotation JSON

Derived paper caches:

- `resources/Paper-pages/`: rendered PDF page image cache
- `resources/Paper-images/`: extracted PDF image cache

Agent and app runtime state:

- `.paper-notes/sessions/`: chat sessions and transcripts
- `.paper-notes/compression/`: context compression checkpoints
- `.paper-notes/snapshots/`: write snapshots used for undo/redo
- `.paper-notes/approvals/`: local tool approval history
- `.paper-notes/memory/`: curated user/project memory
- `.paper-notes/media/`: uploads and generated artifacts
- `.paper-notes/skills/`: user-installed or user-authored skills
- `.paper-notes/mcp-servers.json`: local MCP server configuration
- `.paper-notes/tool-settings.json`: local tool permissions
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
│   ├── agent_memory/           # Curated local memory
│   ├── agent_prompts/          # System prompt and context builder
│   ├── agent_runtime/          # Agent service, loop, runner, control
│   ├── agent_sessions/         # Chat session metadata and transcripts
│   ├── app_config/             # AI settings and local secrets
│   ├── app_infra/              # Paths, storage, shared formatting
│   ├── context_compression/    # Context pruning and summaries
│   ├── library/                # Library, note HTML, annotations
│   ├── media/                  # Upload and generated media store
│   ├── model_providers/        # OpenAI/Codex provider boundary
│   ├── skills/                 # Local Paper Notes skills
│   ├── tool_safety/            # Approvals, guardrails, snapshots
│   ├── tools/                  # Tool registry and built-in tools
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

Default port: `4173`.

## License

MIT License. If you use or redistribute this project, keep the copyright and
license notice.
