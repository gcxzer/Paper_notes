# Paper Notes HTML Site

This is an HTML-first research library. Note bodies stay as individual `.html` files. Library structure lives in `notes.json`.

## Manage the library

1. Run `npm start`.
2. Open `http://localhost:4173`.
3. Use `Manage` to create, rename, delete, and reorder categories.
4. Change a note's category directly in the site.
5. Use `Export JSON` to save the latest library file.
6. Use `Import JSON` to restore or switch libraries.

## Import a PDF

1. Click the plus button in the main toolbar.
2. Choose one or more PDF files.
3. The local server saves the PDF into `Papers/` and creates a same-name HTML file in `Paper-html/`.
4. Open the note to view the PDF on the left and the rendered HTML note on the right.

## Add a new note body

1. Copy `note-template.html` and rename it.
2. Edit the HTML content directly.
3. Add the new note entry through the site after importing your latest `notes.json`, or edit `notes.json` manually.

Typora-exported HTML files can also be linked from `notes.json`. If the export includes images, keep the images inside this folder and use relative paths such as `assets/my-image.png`.
