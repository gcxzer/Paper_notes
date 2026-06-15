from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from tools.mcp.content import decode_mcp_file_content, decoded_media_size, tool_result_payload
from tools.mcp.errors import mcp_error_payload
from tools.mcp.names import mcp_tool_name
from tools.mcp.schema import normalize_mcp_input_schema
from tools.mcp.summaries import prompt_message_summary, resource_summary, server_tool_summaries
from tools.mcp.transport import mcp_http_request_hook


def test_mcp_schema_conversion_repairs_common_sdk_shapes():
    assert normalize_mcp_input_schema(None) == {"type": "object", "properties": {}}
    assert normalize_mcp_input_schema({}) == {"type": "object", "properties": {}}

    normalized = normalize_mcp_input_schema({
        "properties": {
            "item": {"$ref": "#/definitions/Item"},
            "maybe": {"anyOf": [{"type": "null"}, {"type": "string"}]},
        },
        "required": ["item", "missing"],
        "definitions": {
            "Item": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name", "dangling"],
            }
        },
    })

    assert normalized["type"] == "object"
    assert normalized["required"] == ["item"]
    assert "definitions" not in normalized
    assert normalized["properties"]["item"]["$ref"] == "#/$defs/Item"
    assert normalized["properties"]["maybe"]["type"] == "string"
    assert "anyOf" not in normalized["properties"]["maybe"]
    assert normalized["$defs"]["Item"]["required"] == ["name"]


def test_mcp_error_payload_classifies_timeout_and_rate_limit_guidance():
    timeout = mcp_error_payload("Error: API timed out after 15000ms", server_id="arxiv")

    assert timeout["success"] is False
    assert timeout["code"] == "mcp_timeout"
    assert timeout["retry"] == {"allowed": True, "immediate": False, "reason": "timeout"}
    assert "Do not retry repeatedly" in timeout["recovery"]

    limited = mcp_error_payload(
        "Error: rate limit exceeded.",
        server_id="arxiv",
        details={"error": {"data": {"retryAfter": 42}}},
    )

    assert limited["success"] is False
    assert limited["code"] == "mcp_rate_limited"
    assert limited["retry"] == {
        "allowed": True,
        "immediate": False,
        "reason": "rate_limited",
        "afterSeconds": 42,
    }
    assert "Do not retry immediately" in limited["recovery"]


def test_mcp_content_payload_preserves_text_structured_content_and_redacts_errors():
    success = tool_result_payload(
        SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(text="ok")],
            structuredContent={"answer": 42},
        ),
        server_id="filesystem",
    )

    assert success == {
        "success": True,
        "server_id": "filesystem",
        "result": "ok",
        "structuredContent": {"answer": 42},
    }

    failed = tool_result_payload(
        SimpleNamespace(
            isError=True,
            content=[SimpleNamespace(text="failed with token=secret-value")],
            structuredContent=None,
        ),
        server_id="filesystem",
    )

    assert failed["success"] is False
    assert failed["code"] == "mcp_tool_error"
    assert "[REDACTED]" in failed["error"]
    assert "secret-value" not in failed["error"]


def test_mcp_file_content_decodes_data_url_with_shared_base64_parser():
    data_url = "data:text/plain;base64,SGVsbG8="

    assert decode_mcp_file_content(data_url) == "Hello"
    assert decoded_media_size(data_url) == len(b"Hello")


def test_mcp_summaries_cover_resources_prompts_and_filtered_utilities():
    resource = resource_summary(SimpleNamespace(
        uri="file:///paper.md",
        name="paper.md",
        description="Paper note",
        mimeType="text/markdown",
        size=123,
    ))
    prompt_message = prompt_message_summary(SimpleNamespace(role="user", content=SimpleNamespace(text="Summarize.")))

    server = SimpleNamespace(
        id="filesystem",
        name="Filesystem",
        server={"includeTools": ["read_*", "list_resources"], "excludeTools": ["write_*"]},
        tools=[
            SimpleNamespace(name="read_file", description="Read.", annotations={"readOnlyHint": True}),
            SimpleNamespace(name="write_file", description="Write.", annotations={}),
        ],
        initialize_result=SimpleNamespace(capabilities=SimpleNamespace(resources=SimpleNamespace(), prompts=None)),
    )
    summaries = server_tool_summaries(server)

    assert resource == {
        "uri": "file:///paper.md",
        "name": "paper.md",
        "description": "Paper note",
        "mimeType": "text/markdown",
        "size": 123,
    }
    assert prompt_message == {"role": "user", "content": "Summarize."}
    assert [item["generatedName"] for item in summaries] == [
        "mcp_filesystem_read_file",
        "mcp_filesystem_list_resources",
        "mcp_filesystem_read_resource",
    ]


def test_streamable_http_cross_origin_redirect_strips_configured_and_sensitive_headers():
    request = httpx.Request(
        "GET",
        "https://redirect.example/mcp",
        headers={
            "Authorization": "Bearer secret",
            "X-Fixture-Token": "fixture-secret",
            "Cookie": "session=secret",
            "MCP-Session-Id": "session-secret",
            "mcp-protocol-version": "2025-03-26",
        },
    )
    hook = mcp_http_request_hook(
        "https://origin.example/mcp",
        {"Authorization": "Bearer secret", "X-Fixture-Token": "fixture-secret"},
    )

    asyncio.run(hook(request))

    assert "authorization" not in request.headers
    assert "x-fixture-token" not in request.headers
    assert "cookie" not in request.headers
    assert "mcp-session-id" not in request.headers
    assert request.headers["mcp-protocol-version"] == "2025-03-26"
    assert mcp_tool_name("filesystem-prod", "read.file") == "mcp_filesystem_prod_read_file"
