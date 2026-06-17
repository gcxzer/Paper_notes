"""说明：封装 Codex Responses API 的低层 HTTP 调用。

作用：负责发起请求、处理认证头、流式读取和基础错误转换。
"""

from __future__ import annotations

from model_providers.providers.codex.response_common import get_attr
from model_providers.providers.codex.response_parser import message_from_responses_response
from model_providers.providers.codex.response_payload import (
    codex_tool_spec,
    create_responses_response,
    responses_payload,
)
from model_providers.providers.codex.response_stream import (
    backfill_stream_output,
    final_generation_chunk_from_response,
    stream_chunk_from_responses_event,
    tool_call_chunks_from_tool_calls,
)

__all__ = [
    "backfill_stream_output",
    "codex_tool_spec",
    "create_responses_response",
    "final_generation_chunk_from_response",
    "get_attr",
    "message_from_responses_response",
    "responses_payload",
    "stream_chunk_from_responses_event",
    "tool_call_chunks_from_tool_calls",
]
