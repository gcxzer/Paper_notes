"""Verify Paper Notes prompt assembly, memory insertion, and tool guidance."""

from __future__ import annotations

import tools.visibility as tools_visibility
import agent_prompts.builder as prompt_builder
from agent_prompts import AgentPromptContext, build_agent_instructions, build_context_section, extract_tool_names
from memory import build_memory_section, build_paper_memory_section, paper_memory_path, write_paper_memory_file
from app_config.ai_settings import ResolvedValue
from media import MediaStore
from tools import ToolContext, create_tools


CURRENT_PAPER_NOTES_TOOLS = {
    "get_paper_context",
    "inspect_paper_visuals",
    "manage_annotations",
    "query_paper_content",
    "review_note",
    "skill_view",
    "skills_list",
    "web_fetch",
    "web_search",
    "write_note",
    "write_note_media",
}


def test_prompt_includes_only_current_paper_notes_tool_guidance():
    tools = create_tools(ToolContext(provider_name="openai", model="gpt-5.5"))
    names = extract_tool_names(tools)

    prompt = build_agent_instructions(tools=tools, model="gpt-5.4")

    assert names == CURRENT_PAPER_NOTES_TOOLS
    assert "search_paper_rag" not in names
    assert "search_notes" not in names
    assert "get_note_context" not in names
    assert "You are Paper Notes Agent" in prompt
    assert "Available local tools:" in prompt
    for tool_name in CURRENT_PAPER_NOTES_TOOLS:
        assert tool_name in prompt
    assert "# Tool use and grounding" in prompt
    assert "default and primary tool for questions about a paper's actual PDF content" in prompt
    assert "user 'what does Figure 3 show?' -> query 'Figure 3'" in prompt
    assert "user 'what is picture 8 in the paper?' -> query 'Figure 8'" in prompt
    assert "not extracted image index N" in prompt
    assert "Do not expand numbered figure/table/equation questions into broad" in prompt
    assert "# Paper library search queries" in prompt
    assert "# External web lookup" in prompt
    assert "# Paper note-writing workflow" in prompt
    assert "Paper_Notes/.paper-notes/media" in prompt


def test_prompt_includes_generated_artifact_tools_when_media_store_and_credentials_are_available(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tools_visibility,
        "resolve_openai_api_key",
        lambda: ResolvedValue("sk-test", "test"),
    )
    tools = create_tools(ToolContext(
        media_store=MediaStore(tmp_path / "media"),
        provider_name="openai",
        model="gpt-5.5",
    ))
    names = extract_tool_names(tools)

    prompt = build_agent_instructions(tools=tools, model="gpt-5.5")

    assert {"create_file_artifact", "create_image_artifact"} <= names
    assert "# Generated artifacts" in prompt
    assert "create_file_artifact" in prompt
    assert "create_image_artifact" in prompt


def test_prompt_without_tools_does_not_claim_retrieval_capability():
    prompt = build_agent_instructions(tools=[])

    assert "No Paper Notes retrieval tools are currently available" in prompt
    assert "Do not claim that you searched the local library" in prompt
    assert "Available local tools:" not in prompt


def test_prompt_includes_extra_instructions():
    prompt = build_agent_instructions(extra_instructions="Use the current selection first.")

    assert "Use the current selection first." in prompt


def test_prompt_places_context_after_extra_instructions():
    prompt = build_agent_instructions(
        extra_instructions="Use the current selection first.",
        context={"current_note": {"id": "note-1", "title": "Graph RAG"}},
    )

    assert prompt.index("Use the current selection first.") < prompt.index("# Current Reading Context")


def test_prompt_places_memory_before_context(monkeypatch):
    monkeypatch.setattr(prompt_builder, "build_memory_section", lambda: "# Memory\n\n## System Memory\n\n- Use local rules.")
    monkeypatch.setattr(prompt_builder, "build_paper_memory_section", lambda _note_id: "")
    prompt = build_agent_instructions(
        context={"current_note": {"id": "note-1", "title": "Graph RAG"}},
    )

    assert "# Memory" in prompt
    assert "## System Memory" in prompt
    assert prompt.index("# Memory") < prompt.index("# Current Reading Context")


def test_memory_section_reads_system_then_user_files(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "user.md").write_text("## User Memory\n\n- Prefer concise answers.", encoding="utf-8")
    (memory_dir / "system.md").write_text("## System Memory\n\n- Use local evidence.", encoding="utf-8")
    (memory_dir / "other.md").write_text("## Ignored\n\n- Do not load me.", encoding="utf-8")

    section = build_memory_section(memory_dir)

    assert "# Memory" in section
    assert "persistent, file-based memory system" in section
    assert section.index("## System Memory") < section.index("## User Memory")
    assert "Use local evidence" in section
    assert "Prefer concise answers" in section
    assert "Do not load me" not in section


def test_prompt_places_current_paper_memory_between_memory_and_context(monkeypatch):
    monkeypatch.setattr(prompt_builder, "build_memory_section", lambda: "# Memory\n\n## System Memory\n\n- Use local rules.")
    monkeypatch.setattr(
        prompt_builder,
        "build_paper_memory_section",
        lambda note_id: "# Current Paper Memory\n\n- Loaded note-1 memory." if note_id == "note-1" else "",
    )
    prompt = build_agent_instructions(
        context={"current_note": {"id": "note-1", "title": "Graph RAG"}},
    )

    assert "# Memory" in prompt
    assert "# Current Paper Memory" in prompt
    assert prompt.index("# Memory") < prompt.index("# Current Paper Memory")
    assert prompt.index("# Current Paper Memory") < prompt.index("# Current Reading Context")


def test_paper_memory_section_reads_only_current_paper(tmp_path):
    memory_dir = tmp_path / "paper-memory"
    write_paper_memory_file(
        paper_memory_path(memory_dir, "note-1"),
        "# Paper Memory: Note 1\n\n- Current paper memory.",
        metadata={"note_id": "note-1"},
    )
    write_paper_memory_file(
        paper_memory_path(memory_dir, "note-2"),
        "# Paper Memory: Note 2\n\n- Other paper memory.",
        metadata={"note_id": "note-2"},
    )

    section = build_paper_memory_section("note-1", memory_dir)

    assert "# Current Paper Memory" in section
    assert "file-based memory for the current paper/note only" in section
    assert "Memory records can become stale or incomplete" in section
    assert "verify against the current paper content or note context" in section
    assert "Current paper memory" in section
    assert "Other paper memory" not in section
    assert "<!-- paper-memory" not in section


def test_context_section_includes_current_note_selection_and_annotations():
    context = AgentPromptContext.from_note(
        {
            "id": "note-1",
            "title": "Attention Is All You Need",
            "summary": "Transformer paper.",
            "tags": ["transformer", "attention"],
            "collectionPath": "Models / Transformers",
        },
        current_page=3,
        selection_text="Scaled dot-product attention",
        visible_annotations=[{"id": "a1", "page": 3, "comment": "Important equation"}],
        session_title="Reading session",
    )

    section = build_context_section(context)

    assert "# Current Reading Context" in section
    assert "id: note-1" in section
    assert "title: Attention Is All You Need" in section
    assert "collection: Models / Transformers" in section
    assert "Current page: 3" in section
    assert "treat it as the primary focus" in section
    assert "> Scaled dot-product attention" in section
    assert "id=a1; page=3: Important equation" in section


def test_prompt_accepts_canonical_context_dict():
    prompt = build_agent_instructions(
        context={
            "current_note": {"id": "note-1", "title": "Graph RAG"},
            "current_page": 7,
            "selection_text": "retrieval graph",
        }
    )

    assert "title: Graph RAG" in prompt
    assert "Current page: 7" in prompt
    assert "> retrieval graph" in prompt


def test_extract_tool_names_supports_openai_shapes_and_langchain_tools():
    names = extract_tool_names(
        [
            {"type": "function", "function": {"name": "get_paper_context"}},
            {"type": "function", "name": "inspect_paper_visuals"},
            {"type": "web_search"},
            {"type": "web_search_20260209", "name": "web_search"},
            {"not": "a tool"},
            create_tools(ToolContext(provider_name="openai", model="gpt-5.5"))[1],
        ]
    )

    assert names == {"get_paper_context", "inspect_paper_visuals", "web_search"}
