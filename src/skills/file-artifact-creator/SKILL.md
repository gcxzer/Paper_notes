---
name: "file-artifact-creator"
description: "Use when the user wants Paper Notes to create a downloadable text file artifact through Reader Create file mode, including Markdown, plain text, JSON, CSV, or HTML files."
tags: [file-generation, artifacts, paper-notes]
---

# File Artifact Creator

Use this skill when the user asks to create a downloadable file in Paper Notes. Paper Notes creates files through the `create_file_artifact` tool and returns downloadable `/api/media/{id}` artifacts.

## When To Use

Use this skill for requests like:

- Create a Markdown summary file.
- Export note content as JSON.
- Make a CSV table from extracted information.
- Generate a simple HTML file.
- Save a reusable prompt, checklist, or template as a file.

Do not use this skill when the user only wants an answer in chat.

## Required Behavior

If file creation is enabled for the current turn:

1. Call `create_file_artifact`.
2. Put a safe file name in `file_name`.
3. Put the selected or requested MIME type in `mime_type`.
4. Put the complete file contents in `content`.
5. Do not only paste the file contents in chat.

If file creation is not enabled, tell the user to choose `Create file` from the Reader `+` menu before sending the request.

## File Names

Use a safe file name only:

- No path segments.
- No `..`.
- No hidden file names.
- Include the right extension.

Recommended extensions:

- Markdown: `.md`, MIME `text/markdown`
- Text: `.txt`, MIME `text/plain`
- JSON: `.json`, MIME `application/json`
- CSV: `.csv`, MIME `text/csv`
- HTML: `.html`, MIME `text/html`

If the UI-selected format conflicts with the model arguments, Paper Notes will force the UI-selected format. Still choose the correct name and MIME type yourself.

## Content Rules

- Markdown should be readable and structured.
- JSON must be valid JSON, not Markdown-wrapped JSON.
- CSV must include a header row when the data has columns.
- HTML must be a complete document when the user asks for a standalone file.
- Plain text should avoid Markdown-only formatting unless requested.

Do not include placeholder text unless the user asked for a template.

## Output

After the tool returns, summarize briefly:

- What file was created.
- The format.
- That the downloadable artifact is attached in the response.

Do not claim the file was saved unless the tool result says `success: true`.
