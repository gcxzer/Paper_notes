"""Tool output budget configuration.

This module defines how Paper Notes decides whether a tool result is too large to
pass through the model context directly. It does not persist or inspect content
itself; it only provides thresholds used by persistence layers.

Data flow:
1. A ToolResultStore asks `resolve_threshold(tool_name, explicit=...)`.
2. If explicit is given, it always wins.
3. If explicit is omitted, per-tool overrides are checked.
4. If no override exists, the default result size threshold is used.
5. If the result is longer than the threshold, ToolResultStore persists it and
   returns a compact reference instead.

Input/Output examples:

```python
from tools.output_limits import DEFAULT_TOOL_RESULT_BUDGET

DEFAULT_TOOL_RESULT_BUDGET.resolve_threshold("search_docs")
# => 100_000

DEFAULT_TOOL_RESULT_BUDGET.resolve_threshold("search_docs", explicit=3000)
# => 3000

custom_budget = ToolResultBudget(
    default_result_size=2048,
    turn_budget=5000,
    preview_size=200,
    tool_overrides={"export_notes": 50_000},
)

custom_budget.resolve_threshold("export_notes")
# => 50_000
```
"""

from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_RESULT_SIZE_CHARS = 100_000
DEFAULT_TURN_BUDGET_CHARS = 200_000
DEFAULT_PREVIEW_SIZE_CHARS = 1_500


@dataclass(frozen=True, slots=True)
class ToolResultBudget:
    """Container for tool result size configuration."""
    default_result_size: int = DEFAULT_RESULT_SIZE_CHARS
    turn_budget: int = DEFAULT_TURN_BUDGET_CHARS
    preview_size: int = DEFAULT_PREVIEW_SIZE_CHARS
    tool_overrides: dict[str, int] = field(default_factory=dict)

    def resolve_threshold(self, tool_name: str, *, explicit: int | None = None) -> int:
        """Return the effective max size for a tool result in characters."""
        if explicit is not None:
            return max(1, int(explicit))
        override = self.tool_overrides.get(str(tool_name or ""))
        if override is not None:
            return max(1, int(override))
        return max(1, int(self.default_result_size))


DEFAULT_TOOL_RESULT_BUDGET = ToolResultBudget()
