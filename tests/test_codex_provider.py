from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from model_providers.providers import codex_provider
from model_providers.providers.codex_provider import CodexChatModel


def _lookup_note(query: str) -> str:
    """Look up note content."""
    return f"note: {query}"


class _FakeResponses:
    def __init__(self, response):
        self.response = response
        self.payloads: list[dict] = []

    def create(self, **payload):
        self.payloads.append(payload)
        return self.response

    def stream(self, **payload):
        self.payloads.append(payload)
        return _FakeStream(self.response)


class _FakeClient:
    def __init__(self, response):
        self.responses = _FakeResponses(response)


class _FakeMediaStore:
    def __init__(self):
        self.calls: list[dict] = []

    def create_generated_image(self, image_data: str, **kwargs):
        self.calls.append({"image_data": image_data, **kwargs})
        return SimpleNamespace(to_dict=lambda: {
            "id": "gen_1",
            "kind": "image",
            "source": "generated",
            "mimeType": "image/png",
            "fileName": "gen_1.png",
            "url": "/api/media/gen_1",
            "downloadUrl": "/api/media/gen_1/download",
        })


class _FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return None

    def __iter__(self):
        return iter([
            SimpleNamespace(type="response.output_text.delta", delta="Hel"),
            SimpleNamespace(type="response.output_text.delta", delta="lo"),
            SimpleNamespace(type="response.reasoning_summary_text.delta", delta="Reading context."),
        ])

    def get_final_response(self):
        return self.response


def _message_response(text: str, *, usage=None):
    return SimpleNamespace(
        id="resp-1",
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                status="completed",
                content=[SimpleNamespace(type="output_text", text=text)],
            )
        ],
        usage=usage,
    )


def _tool_call_response():
    return SimpleNamespace(
        id="resp-tool",
        status="completed",
        output=[
            SimpleNamespace(
                type="function_call",
                id="fc_1",
                call_id="call-1",
                name="lookup_note",
                arguments='{"query":"DeepSeek"}',
                status="completed",
            )
        ],
        usage=None,
    )


def _image_generation_response():
    return SimpleNamespace(
        id="resp-image",
        status="completed",
        output=[
            SimpleNamespace(
                type="image_generation_call",
                id="ig_1",
                status="completed",
                result="iVBORw0KGgo=",
                revised_prompt="A diagram",
            )
        ],
        usage=None,
    )


def test_codex_chat_model_uses_responses_api_and_strengthened_host_tool_prompt():
    client = _FakeClient(_message_response("Final answer."))
    tool = StructuredTool.from_function(_lookup_note, name="lookup_note")
    model = CodexChatModel(model="gpt-5.3-codex-spark", client=client).bind_tools([tool])

    message = model.invoke([HumanMessage(content="Use the local note tool.")])

    payload = client.responses.payloads[0]
    assert message.content == "Final answer."
    assert payload["model"] == "gpt-5.3-codex-spark"
    assert payload["store"] is False
    assert payload["tools"][0]["name"] == "lookup_note"
    assert "Do not use or try to discover Codex built-in tools" in payload["instructions"]
    assert "list_mcp_resources" in payload["instructions"]


def test_codex_chat_model_maps_image_generation_to_artifact():
    media_store = _FakeMediaStore()
    client = _FakeClient(_image_generation_response())
    model = CodexChatModel(
        model="gpt-5.5",
        client=client,
        options={
            "_paper_notes_image_generation": {
                "enabled": True,
                "size": "1024x1024",
                "quality": "auto",
                "format": "png",
            },
            "_write_note_media_store": media_store,
            "_paper_notes_session_id": "session-1",
        },
    )

    message = model.invoke([HumanMessage(content="Generate an image.")])

    payload = client.responses.payloads[0]
    image_tool = next(tool for tool in payload["tools"] if tool["type"] == "image_generation")
    assert image_tool["size"] == "1024x1024"
    assert image_tool["quality"] == "auto"
    assert image_tool["output_format"] == "png"
    assert message.content == ""
    assert message.response_metadata["artifacts"][0]["id"] == "gen_1"
    assert media_store.calls[0]["session_id"] == "session-1"
    assert media_store.calls[0]["file_format"] == "png"
    assert message.response_metadata["codex_work_trace"][0]["data"]["result"] == "[image data omitted]"


def test_codex_chat_model_returns_langchain_tool_calls():
    client = _FakeClient(_tool_call_response())
    tool = StructuredTool.from_function(_lookup_note, name="lookup_note")
    model = CodexChatModel(model="gpt-5.3-codex-spark", client=client).bind_tools([tool])

    message = model.invoke([HumanMessage(content="Look up DeepSeek.")])

    assert message.content == ""
    assert message.tool_calls == [{
        "name": "lookup_note",
        "args": {"query": "DeepSeek"},
        "id": "call-1",
        "type": "tool_call",
    }]


def test_codex_chat_model_replays_tool_results_as_function_call_output():
    client = _FakeClient(_message_response("Final answer from tool output."))
    tool = StructuredTool.from_function(_lookup_note, name="lookup_note")
    model = CodexChatModel(model="gpt-5.3-codex-spark", client=client).bind_tools([tool])

    message = model.invoke([
        HumanMessage(content="Use the lookup tool."),
        AIMessage(content="", tool_calls=[{"name": "lookup_note", "args": {"query": "DeepSeek"}, "id": "call-1"}]),
        ToolMessage(content="DeepSeek details", name="lookup_note", tool_call_id="call-1"),
    ])

    payload = client.responses.payloads[0]
    assert message.content == "Final answer from tool output."
    assert {"type": "function_call_output", "call_id": "call-1", "output": "DeepSeek details"} in payload["input"]


def test_codex_chat_model_exposes_usage_and_reasoning_trace():
    response = SimpleNamespace(
        id="resp-trace",
        status="completed",
        output=[
            SimpleNamespace(type="reasoning", summary=[SimpleNamespace(text="Reading the visible page.")]),
            SimpleNamespace(
                type="message",
                status="completed",
                content=[SimpleNamespace(type="output_text", text="Answer.")],
            ),
        ],
        usage=SimpleNamespace(input_tokens=1234, output_tokens=56, total_tokens=1290),
    )
    model = CodexChatModel(model="gpt-5.3-codex-spark", client=_FakeClient(response))

    message = model.invoke([HumanMessage(content="Explain.")])

    assert message.content == "Answer."
    assert message.response_metadata["usage"] == {
        "input_tokens": 1234,
        "output_tokens": 56,
        "total_tokens": 1290,
    }
    assert message.response_metadata["codex_model_trace"][0]["text"] == "Reading the visible page."


def test_codex_chat_model_streams_answer_and_trace_delta():
    client = _FakeClient(_message_response("Hello"))
    model = CodexChatModel(model="gpt-5.3-codex-spark", client=client)

    chunks = list(model._stream([HumanMessage(content="Say hello.")]))

    assert "".join(str(chunk.message.content or "") for chunk in chunks) == "Hello"
    traces = [
        chunk.message.response_metadata["paper_notes_trace"][0]
        for chunk in chunks
        if chunk.message.response_metadata.get("paper_notes_trace")
    ]
    assert traces[0]["delta"] == "Reading context."


def test_codex_auth_store_reads_current_codex_tokens(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "id_token": "id-token",
            "account_id": "account-1",
        },
    }), encoding="utf-8")

    credentials = codex_provider._runtime_codex_credentials(auth_path=auth_path)

    assert credentials.access_token == "access-token"
    assert credentials.refresh_token == "refresh-token"
    assert credentials.account_id == "account-1"
