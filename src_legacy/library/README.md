# library

Paper library domain logic: notes metadata, imported PDFs, generated HTML notes,
and PDF annotations.

## Files

- `__init__.py`: Public exports for library, note HTML, and annotation helpers.
- `annotations.py`: Reads and writes per-paper PDF annotation JSON files.
- `note_html.py`: Creates and updates generated HTML notes, titles, headings, summaries, and safe note sections.
- `store.py`: Loads `notes.json`, imports PDFs, manages categories, summaries, renames, and metadata updates.
