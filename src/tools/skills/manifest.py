"""说明：生成 skills 清单信息。

作用：把内置和用户 skills 汇总成前端/工具可展示的列表。
"""

from __future__ import annotations

TOOL_GROUP = {
    "name": "skills",
    "display_name": "Skills",
    "description": "Local Paper Notes skills.",
    "tools": ("skills_list", "skill_view"),
}
