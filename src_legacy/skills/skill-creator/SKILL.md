---
name: skill-creator
description: Use when creating, updating, reviewing, or troubleshooting Paper Notes skills in src/skills, .paper-notes/skills, or external skill directories. Covers SKILL.md structure, frontmatter, linked files, discovery rules, and skill_view/skills_list compatibility.
tags: [skills, authoring, paper-notes]
---

# Skill Creator

Use this skill to create or improve Paper Notes skills. Paper Notes skills are local instruction folders loaded by the `skills_list` and `skill_view` tools.

## Folder Shape

Create each skill as a folder containing `SKILL.md`:

```text
skill-name/
├── SKILL.md
├── references/   optional supporting docs
├── templates/    optional reusable templates
├── assets/       optional images/config/examples
└── scripts/      optional helper scripts
```

Do not create Codex-specific `agents/openai.yaml` files for Paper Notes skills unless the user explicitly asks for Codex app metadata. Paper Notes does not need icon assets for ordinary skill discovery.

## Locations

Use the location the user requests. If they do not specify one:

- Project-bundled skills: `src/skills/<skill-name>`
- User/local skills: `.paper-notes/skills/<skill-name>`
- External skills: any folder configured under Skills > External directories

Keep folder names lowercase kebab-case. Match the frontmatter `name` to the folder name unless there is a strong compatibility reason not to.

## SKILL.md Frontmatter

Use simple YAML frontmatter:

```yaml
---
name: skill-name
description: Clear trigger description for when the agent should use this skill.
tags: [optional, short, labels]
---
```

Rules:

- `name` is required.
- `description` is required and should explain trigger conditions, not marketing copy.
- `tags` are optional.
- Avoid nested metadata formats from other systems unless Paper Notes explicitly supports them.
- Do not use `metadata.hermes`; Paper Notes reads top-level fields.

## Body Content

Keep the body concise and procedural. Include only instructions the model needs after the skill is loaded.

Good skill bodies usually include:

- When to use the skill.
- What context to inspect first.
- Step-by-step workflow.
- Safety or boundary rules.
- When to load linked files.
- Expected output shape.

Avoid:

- Long background essays.
- Product-specific Codex setup instructions.
- Duplicate content that belongs in linked files.
- Claims that the skill can run tools the Paper Notes runtime does not expose.

## Linked Files

Use linked folders when extra detail is useful but not always needed:

- `references/`: detailed docs, checklists, API notes, examples.
- `templates/`: reusable output templates.
- `assets/`: files the model may inspect or mention.
- `scripts/`: helper scripts only when the workflow genuinely benefits from deterministic execution.

In `SKILL.md`, mention exactly when to load a linked file. Example:

```markdown
If the user asks for the full checklist, load `references/checklist.md`.
```

Linked file access must stay inside the skill directory. Do not instruct the model to use `..` paths.

## Creation Workflow

1. Clarify the skill's trigger and intended task if it is ambiguous.
2. Choose a kebab-case folder name.
3. Write `SKILL.md` with required frontmatter and concise workflow instructions.
4. Add linked files only if they reduce clutter or support a real workflow.
5. Verify discovery with `skills_list`.
6. Verify loading with `skill_view(name)`.
7. If linked files exist, verify one with `skill_view(name, file_path)`.

## Review Checklist

Before finishing, check:

- The skill folder is in the requested root.
- `SKILL.md` has valid frontmatter.
- `name` and folder name align.
- Description says when to use the skill.
- Body is specific enough to guide behavior but short enough to load cheaply.
- Linked files are under supported folders and referenced from `SKILL.md`.
- No test-only skill remains unless the user asked for it.
- `skills_list` and `skill_view` pass for the new or changed skill.

## Example

```markdown
---
name: paper-reviewer
description: Use when reviewing a saved paper note for missing evidence, weak summaries, or unclear claims.
tags: [paper-notes, review]
---

# Paper Reviewer

Use this skill when the user asks to review or improve the quality of a saved paper note.

When invoked:

1. Inspect the current note context first.
2. Check whether summary claims are grounded in PDF text or annotations.
3. Identify missing evidence, unclear section titles, or stale tags.
4. Suggest concrete edits; only write changes when the user asks.
```
