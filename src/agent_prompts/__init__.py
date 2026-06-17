"""说明：导出 agent 提示词模块的公共入口。

作用：让其他模块通过统一包接口使用提示词构建器和阅读上下文类型。
"""

from agent_prompts.builder import (
    build_agent_instructions,
    extract_tool_names,
)
from agent_prompts.reading_context import (
    AgentPromptContext,
    build_context_section,
)

__all__ = [
    "AgentPromptContext",
    "build_agent_instructions",
    "build_context_section",
    "extract_tool_names",
]
