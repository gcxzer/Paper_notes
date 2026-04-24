# Paper Notes

Paper Notes is a local HTML-first paper reading workspace. It keeps PDFs and notes as plain files, then opens them in a split reader: PDF on the left, rendered HTML note on the right.

## Preview

The HTML note area supports regular images and diagrams. For example, this architecture image is embedded from the local `assets/` folder:

![Claude Code architecture overview](assets/claude_code_architecture.png)

## Quick Start

Run the local server:

```bash
npm start
```

Open:

```text
http://localhost:4173
```

On macOS, you can also double-click `Open Paper Notes.command`.

The local server is required for PDF import because the browser cannot write files into this folder when `index.html` is opened directly.

## Import PDFs

1. Open `http://localhost:4173`.
2. Click the `+` button in the main toolbar.
3. Choose one or more PDF files.

For each imported PDF, the app creates:

- `Papers/<same name>.pdf`
- `Paper-html/<same name>.html`
- one note entry in `notes.json`

The generated HTML note starts with the paper title and metadata, then an empty note body:

```html
<section class="note-body"></section>
```

No default summary, fake sections, or placeholder text is inserted.

## Read And Edit Notes

Click a paper card or `Open Note` to open the split reader.

- Left pane: the PDF.
- Right pane: the rendered HTML note.
- Drag the middle divider to resize the PDF and note panes.
- The PDF pane and HTML note pane scroll independently on desktop.
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

## Note Menu

HTML notes include a left-side contents menu. The menu is generated automatically from headings inside `.note-body`.

- `h2` becomes a top-level menu item.
- `h3` becomes an indented menu item.
- A small floating menu button appears over the note without taking layout space.
- Clicking a menu item jumps to that section.
- If the note has no `h2` or `h3`, the menu button stays minimal and no placeholder text is shown.

This works both when opening the HTML file directly and inside the split reader.

## Images In Notes

Use normal relative paths when adding images to a note:

```html
<section class="note-body">
  <h2>Overview</h2>
  <img src="../assets/claude_code_architecture.png" alt="Claude Code architecture overview">
</section>
```

When a note is rendered inside `reader.html`, embedded image and media paths are resolved relative to the original `Paper-html/<paper>.html` file, so the same HTML also works when opened directly.

## Library Actions

The library page supports:

- Importing PDFs with the `+` button.
- Opening a note, PDF, or HTML from the details panel.
- Renaming a paper from the paper card.
- Moving a paper between collections from the details panel.
- Creating, renaming, reordering, and deleting collections from the sidebar.

Renaming a paper updates `notes.json`. If the note HTML exists, the app also updates the HTML `<title>` and first `<h1>`.

## File Structure

```text
.
├── index.html                 # Library page
├── reader.html                # Split PDF / HTML reader
├── server.js                  # Local server and file-writing API
├── notes.json                 # Library metadata
├── note-template.html         # Manual note template
├── Papers/                    # Imported PDFs
├── Paper-html/                # HTML note files
└── assets/
    ├── site.js / site.css     # Library UI
    ├── reader.js / reader.css # Split reader
    └── note.js / note.css     # Note rendering and contents menu
```

## Development Notes

- The app has no build step.
- The only npm script is `npm start`, which runs `node server.js`.
- Default port: `4173`.
- Static files are served with `Cache-Control: no-store` so note edits show up after refresh.
- `Papers/` and `Paper-html/` are intentionally not ignored by git because they are part of the paper library.
