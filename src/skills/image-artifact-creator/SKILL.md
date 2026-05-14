---
name: "image-artifact-creator"
description: "Use when the user wants Paper Notes to generate or edit a downloadable image artifact through Reader Generate image mode, including paper diagrams, concept visuals, note illustrations, or image edits based on uploaded image attachments."
tags: [image-generation, artifacts, paper-notes]
---

# Image Artifact Creator

Use this skill when the user asks to generate or edit an image in Paper Notes. Paper Notes creates images through the `create_image_artifact` tool and returns downloadable `/api/media/{id}` artifacts.

## When To Use

Use this skill for requests like:

- Generate a paper concept diagram.
- Create an illustration for a note.
- Make a visual comparison between two methods.
- Turn an uploaded image into a cleaner version.
- Edit or restyle an attached image.

Do not use this skill for deterministic diagrams that are better created as Markdown, Mermaid, SVG, HTML, or note text.

## Required Behavior

If image generation is enabled for the current turn:

1. Call `create_image_artifact`.
2. Put the full visual instruction in `prompt`.
3. Use `mode: "generate"` when no input image is needed.
4. Use `mode: "edit"` when the user wants to transform an attached image.
5. Use `mode: "auto"` when attachments are references or the intent is ambiguous.
6. Do not only describe the image in chat.

If image generation is not enabled, tell the user to choose `Generate image` from the Reader `+` menu before sending the request.

## Prompt Guidelines

Write prompts as concrete visual specs:

- Subject and purpose.
- Layout and composition.
- Style, fidelity, and background.
- Exact visible text, if any.
- Constraints and things to avoid.
- Intended use, such as "fits in a paper note" or "readable as a small card".

For scientific or paper-related visuals:

- Prefer clean, labeled diagrams over decorative art.
- Keep labels short and readable.
- Avoid inventing paper facts not present in the note or attachments.
- Use neutral visual language when the source evidence is incomplete.

## Attachments

When the user attached image files and wants an edit:

- Let `create_image_artifact` use current image attachments automatically unless specific artifact IDs are needed.
- Mention in the prompt what each attachment should be used for: edit target, style reference, content reference, or comparison input.
- Preserve important content unless the user explicitly asks to remove or replace it.

## Output

After the tool returns, summarize briefly:

- What image was created.
- Any important limitation or assumption.
- That the downloadable artifact is attached in the response.

Do not mention Codex built-in `image_gen`, `$CODEX_HOME`, or local generated image folders. Paper Notes handles storage through MediaStore artifacts.
