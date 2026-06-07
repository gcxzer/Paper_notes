from __future__ import annotations

from agent_prompts import AgentPromptContext, build_agent_instructions, build_context_section, extract_tool_names
from tools import create_tools


CURRENT_PAPER_NOTES_TOOLS = {
    "get_note_context",
    "manage_annotations",
    "read_paper",
    "review_note",
    "search_notes",
    "write_note",
    "write_note_media",
}


def test_prompt_includes_only_current_paper_notes_tool_guidance():
    tools = create_tools()
    names = extract_tool_names(tools)

    prompt = build_agent_instructions(tools=tools, model="gpt-5.4")

    assert names == CURRENT_PAPER_NOTES_TOOLS
    assert "You are Paper Notes Agent" in prompt
    assert "Available local tools:" in prompt
    for tool_name in CURRENT_PAPER_NOTES_TOOLS:
        assert tool_name in prompt
    assert "# Tool use and grounding" in prompt
    assert "# Paper library search queries" in prompt
    assert "# Paper note-writing workflow" in prompt
    assert "Paper_Notes/.paper-notes/media" in prompt


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
        context={"note": {"id": "note-1", "title": "Graph RAG"}},
    )

    assert prompt.index("Use the current selection first.") < prompt.index("# Current Reading Context")


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


def test_prompt_accepts_context_dict():
    prompt = build_agent_instructions(
        context={
            "note": {"id": "note-1", "title": "Graph RAG"},
            "page": 7,
            "selection": "retrieval graph",
        }
    )

    assert "title: Graph RAG" in prompt
    assert "Current page: 7" in prompt
    assert "> retrieval graph" in prompt


def test_extract_tool_names_supports_openai_shapes_and_langchain_tools():
    names = extract_tool_names(
        [
            {"type": "function", "function": {"name": "search_notes"}},
            {"type": "function", "name": "read_paper"},
            {"not": "a tool"},
            create_tools()[1],
        ]
    )

    assert names == {"search_notes", "read_paper", "get_note_context"}
