"""Deprecated import shim for the historical misspelled module name.

New code should import :mod:`middleware.tool_output_truncation`. This file is
kept so older config/tests using ``tool_output_trunction`` continue to work.
"""

from __future__ import annotations

from middleware.tool_output_truncation import (
    DEFAULT_TOOL_OUTPUT_MAX_TOKENS,
    ToolOutputTruncationMiddleware,
    create_tool_output_truncation_middleware,
)


__all__ = [
    "DEFAULT_TOOL_OUTPUT_MAX_TOKENS",
    "ToolOutputTruncationMiddleware",
    "create_tool_output_truncation_middleware",
]
