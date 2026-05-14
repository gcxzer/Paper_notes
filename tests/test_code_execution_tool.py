from __future__ import annotations

import json
import socket
import time

from tools.code_execution import register_code_execution_tool
from tools.code_execution.rpc import CodeExecutionRpcServer
from tools.code_execution.runner import run_python_code
from tools.registry import ToolDefinition, ToolRegistry


def test_execute_code_rejects_invalid_and_large_code() -> None:
    registry = _registry()
    register_code_execution_tool(registry)

    non_string = _dispatch_execute_code(registry, 123)
    empty = _dispatch_execute_code(registry, "   ")
    too_large = _dispatch_execute_code(registry, "x = 1\n" * 9000)

    assert non_string["success"] is False
    assert non_string["code"] == "invalid_code"
    assert empty["code"] == "empty_code"
    assert too_large["code"] == "code_too_large"


def test_execute_code_prints_stdout_and_reports_runtime_errors() -> None:
    registry = _registry()
    register_code_execution_tool(registry)

    ok = _dispatch_execute_code(registry, 'print("hello")')
    failed = _dispatch_execute_code(registry, 'raise RuntimeError("boom")')

    assert ok["success"] is True
    assert ok["status"] == "success"
    assert ok["output"] == "hello\n"
    assert failed["success"] is False
    assert failed["status"] == "error"
    assert "RuntimeError: boom" in failed["error"]


def test_execute_code_timeout_kills_child_process() -> None:
    registry = _registry()

    started = time.monotonic()
    result = run_python_code(
        "import time\nwhile True:\n    time.sleep(0.1)\n",
        registry=registry,
        allowed_tools=set(),
        timeout_seconds=0.2,
    )

    assert time.monotonic() - started < 2
    assert result["success"] is False
    assert result["status"] == "timeout"


def test_execute_code_truncates_stdout_and_stderr() -> None:
    registry = _registry()
    result = run_python_code(
        "import sys\nprint('o' * 70000)\nprint('e' * 20000, file=sys.stderr)\n",
        registry=registry,
        allowed_tools=set(),
    )

    assert result["status"] == "success"
    assert "[truncated" in result["output"]
    assert "[truncated" in result["error"]
    assert len(result["output"].encode("utf-8")) < 55_000
    assert len(result["error"].encode("utf-8")) < 12_000


def test_execute_code_scrubs_secret_env_and_uses_fake_home(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_NOTES_TEST_SECRET_TOKEN", "should-not-leak")
    registry = _registry()
    register_code_execution_tool(registry)

    result = _dispatch_execute_code(
        registry,
        "import os\nprint(os.environ.get('PAPER_NOTES_TEST_SECRET_TOKEN'))\nprint(os.environ['HOME'])\nprint(os.environ['PAPER_NOTES_RPC_TOKEN'])\n",
    )

    assert result["success"] is True
    assert "should-not-leak" not in result["output"]
    assert "None" in result["output"].splitlines()[0]
    assert "paper_notes_code_" in result["output"]
    assert "[redacted_rpc_token]" in result["output"]


def test_execute_code_child_can_call_allowed_readonly_parent_tool() -> None:
    registry = _registry()
    registry.register(ToolDefinition(
        name="paper_notes_search",
        description="Search.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        handler=lambda args: {"success": True, "query": args.get("query")},
        toolset="paper_notes",
        read_only=True,
        risk="read",
        kind="search",
    ))
    register_code_execution_tool(
        registry,
        available_tool_names_provider=lambda: ("execute_code", "paper_notes_search"),
    )

    result = _dispatch_execute_code(
        registry,
        "from paper_notes_tools import paper_notes_search\nprint(paper_notes_search(query='rag'))\n",
    )

    assert result["success"] is True
    assert result["tool_calls_made"] == 1
    assert "'query': 'rag'" in result["output"]


def test_execute_code_child_can_call_paper_notes_edit_helper() -> None:
    registry = _registry()
    registry.register(ToolDefinition(
        name="paper_notes_context",
        description="Context.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        read_only=True,
        risk="read",
        kind="read",
    ))
    registry.register(ToolDefinition(
        name="paper_notes_edit",
        description="Edit.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        handler=lambda args: {"success": True, "action": args.get("action"), "html": args.get("html")},
        toolset="paper_notes",
        mutating=True,
        risk="write",
        kind="write",
    ))
    register_code_execution_tool(
        registry,
        available_tool_names_provider=lambda: ("execute_code", "paper_notes_context"),
    )

    result = _dispatch_execute_code(
        registry,
        (
            "from paper_notes_tools import paper_notes_edit\n"
            "print(paper_notes_edit('append_section', 'n1', heading='Notes', html='<p>x</p>'))\n"
        ),
    )

    assert result["success"] is True
    assert result["tool_calls_made"] == 1
    assert "'action': 'append_section'" in result["output"]
    assert "'html': '<p>x</p>'" in result["output"]


def test_execute_code_rpc_returns_full_inner_tool_result_not_truncated_preview() -> None:
    registry = _registry()
    annotations = [{"id": f"a{i}", "quote": "x" * 20} for i in range(8)]
    registry.register(ToolDefinition(
        name="paper_notes_context",
        description="Context.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        handler=lambda args: {"success": True, "annotations": annotations, "large": "y" * 1000},
        toolset="paper_notes",
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=200,
    ))
    register_code_execution_tool(
        registry,
        available_tool_names_provider=lambda: ("execute_code", "paper_notes_context"),
    )

    result = _dispatch_execute_code(
        registry,
        (
            "from paper_notes_tools import paper_notes_context\n"
            "res = paper_notes_context(note_id='note-1')\n"
            "print(len(res.get('annotations', [])))\n"
            "print(res.get('truncated'))\n"
        ),
    )

    assert result["success"] is True
    assert result["tool_calls_made"] == 1
    assert result["output"].splitlines() == ["8", "None"]


def test_execute_code_child_can_call_allowed_skill_tools() -> None:
    registry = _registry()
    registry.register(ToolDefinition(
        name="skills_list",
        description="List skills.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        handler=lambda args: {"success": True, "skills": [{"name": "paper-skim"}], "category": args.get("category", "")},
        toolset="skills",
        read_only=True,
        risk="read",
        kind="read",
    ))
    registry.register(ToolDefinition(
        name="skill_view",
        description="View skill.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        handler=lambda args: {"success": True, "name": args.get("name"), "file_path": args.get("file_path", "")},
        toolset="skills",
        read_only=True,
        risk="read",
        kind="read",
    ))
    register_code_execution_tool(
        registry,
        available_tool_names_provider=lambda: ("execute_code", "skills_list", "skill_view"),
    )

    result = _dispatch_execute_code(
        registry,
        "from paper_notes_tools import skills_list, skill_view\nprint(skills_list())\nprint(skill_view('paper-skim'))\n",
    )

    assert result["success"] is True
    assert result["tool_calls_made"] == 2
    assert "paper-skim" in result["output"]


def test_execute_code_rpc_rejects_mutating_and_recursive_tools() -> None:
    registry = _registry()
    registry.register(ToolDefinition(
        name="paper_notes_search",
        description="Search.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        mutating=True,
        risk="write",
    ))
    mutating_result = run_python_code(
        "from paper_notes_tools import _call\nprint(_call('paper_notes_search', {}))\n",
        registry=registry,
        allowed_tools={"paper_notes_search"},
    )
    register_code_execution_tool(
        registry,
        available_tool_names_provider=lambda: ("execute_code", "paper_notes_search"),
    )
    recursive_result = _dispatch_execute_code(
        registry,
        "from paper_notes_tools import _call\nprint(_call('execute_code', {'code': 'print(1)'}))\n",
    )

    assert mutating_result["success"] is True
    assert "unsafe_inner_tool" in mutating_result["output"]
    assert recursive_result["success"] is True
    assert "tool_not_allowed" in recursive_result["output"]


def test_execute_code_rpc_enforces_tool_call_limit() -> None:
    registry = _registry()
    registry.register(ToolDefinition(
        name="paper_notes_search",
        description="Search.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        read_only=True,
        risk="read",
    ))

    result = run_python_code(
        "from paper_notes_tools import paper_notes_search\nfor i in range(27):\n    print(paper_notes_search(query=str(i)))\n",
        registry=registry,
        allowed_tools={"paper_notes_search"},
        max_tool_calls=25,
    )

    assert result["success"] is True
    assert result["tool_calls_made"] == 25
    assert "tool_call_limit_exceeded" in result["output"]


def test_execute_code_rpc_rejects_bad_token() -> None:
    registry = _registry()
    server = CodeExecutionRpcServer(
        registry=registry,
        allowed_tools=set(),
        token="good-token",
        max_tool_calls=25,
    ).start()
    try:
        response = _rpc_call(server.port, {"token": "bad-token", "tool": "paper_notes_search", "args": {}})
    finally:
        server.stop()

    assert response["success"] is False
    assert response["code"] == "invalid_rpc_token"


def _registry() -> ToolRegistry:
    return ToolRegistry(availability_ttl_seconds=0)


def _dispatch_execute_code(registry: ToolRegistry, code: object) -> dict:
    result = registry.dispatch("execute_code", {"code": code})
    return json.loads(result.content)


def _rpc_call(port: int, payload: dict) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        raw = b""
        while not raw.endswith(b"\n"):
            raw += sock.recv(65536)
    return json.loads(raw.decode("utf-8"))
