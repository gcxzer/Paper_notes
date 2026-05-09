# Paper Notes

Paper Notes turns a folder of PDFs into a clean, local research workspace: read the paper on the left, build a beautiful HTML note on the right.

The HTML notes are designed to be generated or refined with an LLM, then kept as plain editable files you can version, customize, and reopen anytime.

## Preview

Paper Notes opens a PDF and its matching HTML note side by side:

![Paper Notes split reader preview](assets/images/paper-notes-reader-preview.png)

The library view keeps imported papers, summaries, collections, and paper actions in one place:

![Paper Notes library preview](assets/images/paper-notes-library-preview.png)

## Quick Start

Install the Python and browser dependencies:

```bash
uv sync
npm install
```

Create your local environment file:

```bash
cp .env.example .env
```

Edit `.env` with your AWS resource names, then verify the AWS profile:

```bash
aws sso login --profile <your-profile>
uv run python scripts/check-aws-env.py
```

Recommended macOS setup: install the local background service once.

```bash
scripts/install-autostart.sh
```

Then bookmark and open:

```text
http://127.0.0.1:4173
```

After that, Paper Notes starts automatically when you log in. You can open the bookmark directly without manually starting the server.

Manual fallback:

```bash
uv run uvicorn paper_notes_server.main:app --host 127.0.0.1 --port 4173
```

Then open `http://localhost:4173`.

On macOS, you can also double-click `open-paper-notes.command`.

The local server is required because the browser cannot write PDFs, HTML notes, annotations, or `notes.json` updates into this folder when `index.html` is opened directly.

To remove the background service:

```bash
scripts/uninstall-autostart.sh
```

## AWS Configuration

Paper Notes reads AWS settings from `.env`. The file is intentionally ignored by git; commit `.env.example`, not your local `.env`.

Required local tooling:

- `uv` for the Python backend.
- Node/npm only for the browser PDF.js dependency.
- AWS CLI v2 with an SSO or credential profile.
- AgentCore CLI when deploying the MCP server to AgentCore Runtime.
- Bedrock model access in the same region as your Harness and Knowledge Base.

Required AWS resources:

- S3 bucket for PDFs, HTML notes, annotations, KB documents, and metadata.
- DynamoDB table for paper metadata.
- Bedrock Knowledge Base with an S3 data source.
- AgentCore Harness for Ask responses.
- AgentCore Gateway with one MCP target that points to the Paper Notes MCP server.
- AgentCore Runtime hosting the Paper Notes MCP server.
- AgentCore Memory is optional, but recommended for cross-session preferences and context.
- IAM access for the configured profile to call S3 `PutObject`, DynamoDB `PutItem`, Bedrock Knowledge Base ingestion/retrieval, AgentCore Harness, AgentCore Gateway, and STS identity checks.

The default chat path is AgentCore Harness. The Harness should use the Gateway tool first; the Gateway target points to the Python MCP server in `paper_notes_mcp/`. Lambda is not required.

`.env` keys:

```dotenv
HOST=127.0.0.1
PORT=4173
AWS_PROFILE=your-profile
AWS_REGION=your-region
PAPER_NOTES_OWNER_ID=personal
PAPER_NOTES_BUCKET=your-paper-notes-bucket
PAPER_NOTES_METADATA_TABLE=your-metadata-table
PAPER_NOTES_KNOWLEDGE_BASE_ID=your-knowledge-base-id
PAPER_NOTES_KB_DATA_SOURCE_ID=your-kb-data-source-id
PAPER_NOTES_KB_NUMBER_OF_RESULTS=5
PAPER_NOTES_CHAT_BACKEND=agentcore
PAPER_NOTES_AGENTCORE_HARNESS_ARN=arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:harness/Harness-Name
PAPER_NOTES_MEMORY_ACTOR_ID=your-user-id
PAPER_NOTES_MEMORY_ARN=
PAPER_NOTES_AGENTCORE_GATEWAY_ID=your-gateway-id
PAPER_NOTES_AGENTCORE_GATEWAY_ARN=
PAPER_NOTES_AGENTCORE_MCP_RUNTIME_ARN=arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:runtime/paper-notes-mcp-runtime
PAPER_NOTES_AGENTCORE_RUNTIME_QUALIFIER=DEFAULT
PAPER_NOTES_GATEWAY_TARGET_NAME=paper-notes-mcp
PAPER_NOTES_WEB_SEARCH_MAX_RESULTS=5
PAPER_NOTES_TAVILY_SEARCH_DEPTH=basic
TAVILY_API_KEY=
BRAVE_SEARCH_API_KEY=
PAPER_NOTES_GENERATION_MODEL_ARN=arn:aws:bedrock:REGION:ACCOUNT_ID:inference-profile/YOUR_MODEL_PROFILE
PAPER_NOTES_DISABLE_CLOUD_SYNC=0
```

For local-only testing, set `PAPER_NOTES_DISABLE_CLOUD_SYNC=1`. Chat still needs AgentCore Harness access unless you avoid the Ask panel.

### AgentCore MCP Server

The MCP server lives in `paper_notes_mcp/server.py`. It exposes two tools:

- `search_paper_notes(query, max_results=5)`: retrieves snippets from the Bedrock Knowledge Base and returns source URIs.
- `web_search(query, max_results=5)`: searches the public web through Tavily or Brave Search when configured.

The tools do not generate the final answer. Harness receives tool results and uses the Harness system prompt/model to answer.

Public web search is optional. To enable it, set a key in `.env`:

```dotenv
TAVILY_API_KEY=your-tavily-api-key
```

or:

```dotenv
BRAVE_SEARCH_API_KEY=your-brave-search-api-key
```

If both keys are present, Paper Notes uses Tavily.

Local smoke test:

```bash
uv run python -m paper_notes_mcp.server
```

Deploy it to AgentCore Runtime with the helper script:

```bash
npm install -g @aws/agentcore
uv run python scripts/deploy-agentcore-mcp-runtime.py
```

The script copies the checked-in AgentCore template into `.paper-notes-local/`, injects your local `.env` values there, and runs `agentcore deploy`. Real AWS IDs stay out of committed files.

After deployment, put the Runtime ARN in `.env` as `PAPER_NOTES_AGENTCORE_MCP_RUNTIME_ARN`, then create the Gateway MCP target:

```bash
uv run python scripts/create-agentcore-mcp-target.py
```

In the AWS Console, open the Gateway target and sync it so Gateway discovers the MCP tools.

The checked-in `agentcore-runtime/` directory is a deployment template. The deploy script copies it into `.paper-notes-local/agentcore-runtime/` and injects local `.env` values there. Commit the template, not the generated `.paper-notes-local/` workspace.

### AgentCore Memory

If you attach AgentCore Memory to the Harness, set a stable actor ID in `.env`:

```dotenv
PAPER_NOTES_MEMORY_ACTOR_ID=your-user-id
```

The Reader's chat session ID is used as the Harness runtime session ID, and this actor ID scopes long-term memory to one user.

After Memory is attached to the Harness, the Harness execution role must be allowed to read and write that Memory. The helper script infers the Harness role and Memory ARN from AWS:

```bash
uv run python scripts/attach-agentcore-memory-policy.py
```

If the Memory is not yet attached to the Harness, set `PAPER_NOTES_MEMORY_ARN` in `.env` before running the script.

## Import PDFs

1. Open `http://localhost:4173`.
2. Click the `+` button in the main toolbar.
3. Choose one or more PDF files.

For each imported PDF, the app creates:

- `Papers/<same name>.pdf`
- `Paper-html/<same name>.html`
- one note entry in `notes.json`

The generated HTML note starts with the paper title and metadata, then a placeholder note body:

```html
<section class="note-body">
  <p>No extracted text is available yet.</p>
</section>
```

No default summary or fake sections are inserted.

## Read And Edit Notes

Click a paper card or `Open Note` to open the split reader.

- Left pane: the PDF.
- Right pane: the rendered HTML note.
- Drag the middle divider to resize the PDF and note panes.
- The PDF pane and HTML note pane scroll independently on desktop.
- The PDF pane supports Zotero-style local annotations: highlights, underlines, and sticky notes.
- The PDF toolbar supports page number jumping, internal PDF links, larger zoom levels, undo/redo for annotation changes, and a temporary back button after PDF link jumps.
- The library theme setting controls the library, reader chrome, PDF reading background, and rendered HTML note.
- Refresh the reader after editing `Paper-html/<paper>.html`; the app reloads the latest HTML with caching disabled.

To edit a note, open the matching file in `Paper-html/` and write normal HTML inside `.note-body`.

Example:

```html
<section class="note-body">
  <h2>Main Idea</h2>
  <p>Write your notes here.</p>

  <h2>Method</h2>
  <h3>Training Setup</h3>
  <p>Details...</p>
</section>
```

## PDF Annotations

The split reader uses PDF.js instead of the browser's read-only PDF iframe. Use the PDF toolbar to switch annotation modes:

- `Highlight`: drag a rectangle on a PDF page to create a color highlight.
- `Underline`: drag across text to add a colored underline.
- `Note`: click a PDF page to add a sticky note.

Click the active annotation mode again to return to normal reading and scrolling.

Choose a color from the toolbar before creating an annotation. The annotation sidebar lists every annotation by page; click an item to jump back to its position, edit its comment, or delete it.

Annotations are saved as JSON files in `Paper-annotations/`. The original PDF is not modified.

## Themes

Paper Notes has one global theme control. The `Light` / `Dark` setting in the library controls the library, reader chrome, PDF reading background, and rendered HTML note.

Theme choices are stored locally in the browser and do not change `notes.json`.

## Note Menu

HTML notes include a left-side contents menu. The menu is generated automatically from headings inside `.note-body`.

- `h2` becomes a top-level menu item.
- `h3` becomes an indented menu item.
- `h4` becomes a deeper indented menu item.
- A small floating menu button appears over the note without taking layout space.
- `h2`, `h3`, and `h4` sections can be collapsed from the heading.
- Clicking a menu item jumps to that section.
- If the note has no `h2`, `h3`, or `h4`, the menu button stays minimal and no placeholder text is shown.

This works both when opening the HTML file directly and inside the split reader.

## Images In Notes

Use normal relative paths when adding images to a note:

```html
<section class="note-body">
  <h2>Overview</h2>
  <img src="../assets/images/your-image.png" alt="Describe this image">
</section>
```

When a note is rendered inside `reader.html`, embedded image and media paths are resolved relative to the original `Paper-html/<paper>.html` file, so the same HTML also works when opened directly.

## Library Actions

The library page supports:

- Importing PDFs with the `+` button.
- Opening a note, PDF, or HTML from the details panel.
- Renaming a paper from the paper card.
- Deleting a paper from the website list. This removes the note entry from `notes.json`; it does not delete the local PDF or HTML file.
- Writing a short summary in the details panel.
- Moving a paper between collections from the details panel.
- Creating, renaming, reordering, and deleting collections from the sidebar.

Renaming a paper updates `notes.json`. If the note HTML exists, the app also updates the HTML `<title>` and first `<h1>`.

Collection changes are also written back to `notes.json` when the local server is running, so a refresh keeps newly created collections, renamed collections, drag order, and paper moves.

## File Structure

```text
.
├── index.html                 # Library page
├── reader.html                # Split PDF / HTML reader
├── paper_notes_server/        # FastAPI server and AWS integration
├── pyproject.toml             # Python backend dependencies
├── open-paper-notes.command   # macOS one-click launcher
├── notes.json                 # Local library metadata, created/updated at runtime
├── note-template.html         # Manual note template
├── scripts/                   # macOS auto-start install/uninstall helpers
├── Papers/                    # Imported PDFs
├── Paper-html/                # HTML note files
├── Paper-annotations/         # PDF highlight and sticky-note JSON files
└── assets/
    ├── scripts/               # Browser JavaScript
    ├── styles/                # CSS
    └── images/                # Preview and note images
```

## Development Notes

- The app has no build step.
- The local backend runs with FastAPI: `uv run uvicorn paper_notes_server.main:app --host 127.0.0.1 --port 4173`.
- npm is only used for browser-side dependencies such as `pdfjs-dist`.
- `scripts/install-autostart.sh` registers a macOS LaunchAgent named `com.paper-notes.local`.
- PDF rendering uses `pdfjs-dist`.
- Default port: `4173`.
- Static files are served with `Cache-Control: no-store` so note edits show up after refresh.
- `notes.json`, `Papers/`, `Paper-html/`, and `Paper-annotations/` are local user data and are ignored by git.

## License

MIT License. If you use or redistribute this project, keep the copyright and license notice.
