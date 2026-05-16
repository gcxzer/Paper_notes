from __future__ import annotations

from agent_prompts import AgentPromptContext, build_agent_instructions, build_context_section, extract_tool_names
from tools.catalog import ToolCatalog, ToolSelection
from tools.paper_notes import create_paper_notes_registry


def test_prompt_includes_identity_and_available_tool_names():
    registry = create_paper_notes_registry()
    tools = ToolCatalog(registry).get_model_tools(ToolSelection.from_values())

    prompt = build_agent_instructions(tools=tools, model="gpt-5.4")

    assert "You are Paper Notes Agent" in prompt
    assert "Available local tools:" in prompt
    assert "search_notes" in prompt
    assert "get_note_context" in prompt
    assert "paper_notes_edit" not in extract_tool_names(tools)
    assert "write_note" in extract_tool_names(tools)
    assert "search_library" not in prompt
    assert "# Tool use and grounding" in prompt
    assert "If local Paper Notes context is insufficient" in prompt
    assert "external search is unavailable" in prompt
    assert "# Paper library search queries" in prompt
    assert "English-first paper keywords" in prompt
    assert "# Paper note-writing workflow" in prompt
    assert "do not change h2 to h1" in prompt
    assert "Preserve existing heading levels" in prompt
    assert "Paper_Notes/.paper-notes/media" in prompt
    assert "do not ask them for an upload artifact id" in prompt
    assert "refresh that information with the appropriate available tool" in prompt


def test_prompt_without_tools_does_not_claim_retrieval_capability():
    prompt = build_agent_instructions(tools=[])

    assert "No Paper Notes retrieval tools are currently available" in prompt
    assert "Do not claim that you searched the local library" in prompt
    assert "Available local tools:" not in prompt


def test_prompt_includes_fenced_memory_context_when_available():
    prompt = build_agent_instructions(
        tools=[],
        memory_context="<memory-context>\nremembered fact\n</memory-context>",
    )

    assert "# Persistent memory" in prompt
    assert "not as the user's current message" in prompt
    assert "remembered fact" in prompt


def test_prompt_includes_memory_guidance_when_memory_tool_available_without_context():
    prompt = build_agent_instructions(
        tools=[{"type": "function", "function": {"name": "persistent_memory"}}],
    )

    assert "# Persistent memory" in prompt
    assert "Write memories as declarative facts" in prompt
    assert "\n<memory-context>\n" not in prompt


def test_prompt_includes_session_todo_context_when_available():
    prompt = build_agent_instructions(
        tools=[],
        todo_context="[Your active session task list was preserved]\n- [>] 1. Read intro (in_progress)",
    )

    assert "# Active session todo" in prompt
    assert "<todo-context>" in prompt
    assert "Read intro" in prompt
    assert "not durable memory" in prompt


def test_prompt_includes_todo_guidance_when_todo_tool_available_without_context():
    prompt = build_agent_instructions(
        tools=[{"type": "function", "function": {"name": "todo"}}],
    )

    assert "# Active session todo" in prompt
    assert "Keep at most one item in_progress" in prompt
    assert "\n<todo-context>\n" not in prompt


def test_openai_persistence_guidance_only_mentions_available_tools():
    prompt = build_agent_instructions(
        tools=[{"type": "function", "function": {"name": "search_notes"}}],
        model="gpt-5.4",
    )

    assert "# Tool use and grounding" in prompt
    assert "# Paper library search queries" in prompt
    assert "English-first paper keywords" in prompt
    assert "search_notes" in prompt
    assert "paper_notes_edit" not in prompt
    assert "session_search" not in prompt
    assert "# Paper note-writing workflow" not in prompt


def test_prompt_includes_custom_web_search_guidance_when_tool_available():
    prompt = build_agent_instructions(
        tools=[
            {"type": "function", "function": {"name": "web_search"}},
            {"type": "function", "function": {"name": "web_fetch"}},
        ],
        model="gpt-5.4",
    )

    assert "web_search" in prompt
    assert "configured custom web search tool" in prompt
    assert "Tavily, then Brave Search" in prompt
    assert "runtime provider priority is Tavily, then Brave Search" in prompt
    assert "web_fetch" in prompt
    assert "read a specific public URL" in prompt


def test_prompt_includes_skill_list_vs_view_guidance():
    prompt = build_agent_instructions(
        tools=[
            {"type": "function", "function": {"name": "skills_list"}},
            {"type": "function", "function": {"name": "skill_view"}},
        ],
        model="gpt-5.4",
    )

    assert "Do not call it when the user names an exact skill" in prompt
    assert "Use skill_view directly when the user names a specific skill" in prompt
    assert "use skills_list first only when discovering or choosing among skills" in prompt


def test_prompt_includes_code_execution_boundaries_when_tool_available():
    prompt = build_agent_instructions(
        tools=[{"type": "function", "function": {"name": "execute_code"}}],
        model="gpt-5.4",
    )

    assert "# Code execution" in prompt
    assert "bounded Python work" in prompt
    assert "not Docker or OS-level isolation" in prompt
    assert "Paper Notes content, or other durable state" in prompt
    assert "Paper Notes or skill data" in prompt
    assert "paper_notes_tools" in prompt


def test_prompt_includes_provider_native_web_search_guidance_when_enabled():
    prompt = build_agent_instructions(
        tools=[],
        native_web_search_enabled=True,
    )

    assert "# Provider-native web search" in prompt
    assert "current or external web facts" in prompt
    assert "Prefer local Paper Notes tools" in prompt
    assert "Available local tools:" not in prompt


def test_prompt_includes_web_fetch_flow_with_native_web_search():
    prompt = build_agent_instructions(
        tools=[{"type": "function", "function": {"name": "web_fetch"}}],
        model="gpt-5.4",
        native_web_search_enabled=True,
    )

    assert "# Provider-native web search" in prompt
    assert "web_fetch" in prompt
    assert "read a specific public URL supplied by the user" in prompt
    assert "web search or web fetch" in prompt


def test_prompt_includes_tool_use_enforcement_and_grounding_rules():
    prompt = build_agent_instructions(
        tools=[
            {"type": "function", "function": {"name": "get_note_context"}},
            {"type": "function", "function": {"name": "session_search"}},
            {"type": "function", "function": {"name": "web_search"}},
        ],
        model="gpt-5.4",
    )

    assert "# Tool use and grounding" in prompt
    assert "call it immediately" in prompt
    assert "Local paper library facts" in prompt
    assert "Previous chat/session history requires an available session history search tool" in prompt
    assert "Current external facts" in prompt
    assert "# Runtime context" not in prompt


def test_prompt_includes_native_web_search_grounding_even_without_local_tools():
    prompt = build_agent_instructions(
        tools=[],
        native_web_search_enabled=True,
    )

    assert "# Provider-native web search" in prompt
    assert "# Tool use and grounding" in prompt
    assert "Current external facts" in prompt


def test_prompt_omits_search_query_rewrite_when_search_tool_unavailable():
    prompt = build_agent_instructions(
        tools=[{"type": "function", "function": {"name": "get_note_context"}}],
        model="gpt-5.4",
    )

    assert "# Paper library search queries" not in prompt
    assert "English-first paper keywords" not in prompt


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
    prompt = build_agent_instructions(context={
        "note": {"id": "note-1", "title": "Graph RAG"},
        "page": 7,
        "selection": "retrieval graph",
    })

    assert "title: Graph RAG" in prompt
    assert "Current page: 7" in prompt
    assert "> retrieval graph" in prompt


def test_extract_tool_names_supports_openai_and_responses_shapes():
    names = extract_tool_names([
        {"type": "function", "function": {"name": "search_library"}},
        {"type": "function", "name": "read_annotations"},
        {"not": "a tool"},
    ])

    assert names == {"search_library", "read_annotations"}
