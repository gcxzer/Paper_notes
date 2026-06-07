"""Model-visible tool catalog.

Adapted from Nous Research Hermes Agent ``model_tools.py`` (MIT License).
Paper Notes keeps the registry small and moves model schema selection, toolset
resolution, availability filtering, and schema caching into this catalog layer.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable

from tools.registry import ToolRegistry
from tools.toolsets import BUILTIN_TOOL_GROUPS, normalize_toolset_names, resolve_toolsets
from tools.types import ToolGroupDefinition


_WRITE_MODES = {"auto", "warn", "ask", "readonly", "block", "halt", "disabled"}
_HIDE_MUTATING_MODES = {"readonly", "block", "halt", "disabled"}
_SETTINGS_GROUP_ORDER = (
    "paper_notes",
    "code_execution",
    "persistent_memory",
    "session_search",
    "todo",
    "skills",
    "web_search",
    "mcp",
    "generated_artifacts",
)


@dataclass(frozen=True, slots=True)
class ToolSelection:
    enable_tools: bool = True
    enabled_toolsets: tuple[str, ...] = ()
    disabled_toolsets: tuple[str, ...] = ()
    disabled_tools: tuple[str, ...] = ()
    write_tool_mode: str = "auto"
    tool_write_modes: tuple[tuple[str, str], ...] = ()
    settings_fingerprint: str = ""
    default_toolsets: tuple[str, ...] | None = ("default",)

    @classmethod
    def from_values(
        cls,
        *,
        enable_tools: bool = True,
        toolset: str | None = None,
        enabled_toolsets: str | Iterable[str] | None = None,
        disabled_toolsets: str | Iterable[str] | None = None,
        disabled_tools: str | Iterable[str] | None = None,
        write_tool_mode: str = "auto",
        tool_write_modes: dict[str, str] | None = None,
        settings_fingerprint: str = "",
        default_toolsets: str | Iterable[str] | None = ("default",),
    ) -> "ToolSelection":
        requested_toolsets = list(normalize_toolset_names(enabled_toolsets))
        if toolset:
            requested_toolsets.insert(0, str(toolset).strip())
        per_tool_modes = {
            _clean_tool_name(name): _normalize_write_mode(mode)
            for name, mode in (tool_write_modes or {}).items()
            if _clean_tool_name(name)
        }
        return cls(
            enable_tools=bool(enable_tools),
            enabled_toolsets=tuple(dict.fromkeys(name for name in requested_toolsets if name)),
            disabled_toolsets=normalize_toolset_names(disabled_toolsets),
            disabled_tools=tuple(sorted({_clean_tool_name(name) for name in normalize_toolset_names(disabled_tools)} - {""})),
            write_tool_mode=_normalize_write_mode(write_tool_mode),
            tool_write_modes=tuple(sorted(per_tool_modes.items())),
            settings_fingerprint=str(settings_fingerprint or ""),
            default_toolsets=None if default_toolsets is None else normalize_toolset_names(default_toolsets),
        )

    @property
    def per_tool_write_modes(self) -> dict[str, str]:
        return dict(self.tool_write_modes)


@dataclass(slots=True)
class ToolCatalogSnapshot:
    tool_names: tuple[str, ...] = ()
    model_tools: list[dict[str, Any]] = field(default_factory=list)
    groups: tuple[ToolGroupDefinition, ...] = ()
    unknown_toolsets: tuple[str, ...] = ()
    unavailable_tools: tuple[dict[str, Any], ...] = ()
    disabled_tools: tuple[str, ...] = ()
    hidden_tools: tuple[str, ...] = ()
    tool_write_modes: dict[str, str] = field(default_factory=dict)
    generation: int = 0


class ToolCatalog:
    """Single source of truth for model-visible tool definitions."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._cache: dict[tuple[Any, ...], tuple[float, ToolCatalogSnapshot]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    def describe_groups(self) -> list[ToolGroupDefinition]:
        groups = {group.name: group for group in self.registry.groups()}
        for name in _SETTINGS_GROUP_ORDER:
            if name not in groups and self._group_has_registered_tools(name):
                groups[name] = BUILTIN_TOOL_GROUPS[name]
        ordered = [groups[name] for name in _SETTINGS_GROUP_ORDER if name in groups]
        extras = [group for name, group in sorted(groups.items()) if name not in _SETTINGS_GROUP_ORDER]
        return [*ordered, *extras]

    def get_model_tools(self, selection: ToolSelection) -> list[dict[str, Any]]:
        return self.resolve(selection).model_tools

    def resolve(self, selection: ToolSelection) -> ToolCatalogSnapshot:
        normalized = _normalize_selection(selection)
        cache_key = self._cache_key(normalized)
        cached = self._cache.get(cache_key)
        if cached is not None:
            cached_at, snapshot = cached
            if self._cache_entry_is_fresh(cached_at):
                return _copy_snapshot(snapshot)

        snapshot = self._resolve_uncached(normalized)
        self._cache[cache_key] = (time.monotonic(), _copy_snapshot(snapshot))
        return snapshot

    def _resolve_uncached(self, selection: ToolSelection) -> ToolCatalogSnapshot:
        groups = tuple(self.describe_groups())
        if not selection.enable_tools:
            return ToolCatalogSnapshot(groups=groups, generation=self.registry.generation)

        resolution = self._resolve_names(selection)
        selected = set(resolution.tool_names)
        disabled = set(selection.disabled_tools)
        hidden: set[str] = set()
        per_tool_modes = selection.per_tool_write_modes

        selected.difference_update(disabled)
        if selection.write_tool_mode in _HIDE_MUTATING_MODES:
            hidden.update(_mutating_tools(self.registry, selected))
        for name, mode in per_tool_modes.items():
            definition = self.registry.get(name)
            if definition is not None and definition.mutating and mode in _HIDE_MUTATING_MODES:
                hidden.add(name)
        selected.difference_update(hidden)

        available_names: set[str] = set()
        unavailable: list[dict[str, Any]] = []
        for name in sorted(selected):
            available, details = self.registry.availability(name)
            if available:
                available_names.add(name)
            else:
                unavailable.append({
                    "name": name,
                    "availability": details,
                })

        model_tools = self.registry.get_definitions(available_names, quiet=True)
        tool_names = tuple(tool["function"]["name"] for tool in model_tools if isinstance(tool.get("function"), dict))
        return ToolCatalogSnapshot(
            tool_names=tool_names,
            model_tools=model_tools,
            groups=groups,
            unknown_toolsets=resolution.unknown_toolsets,
            unavailable_tools=tuple(unavailable),
            disabled_tools=tuple(sorted(disabled)),
            hidden_tools=tuple(sorted(hidden)),
            tool_write_modes=per_tool_modes,
            generation=self.registry.generation,
        )

    def _resolve_names(self, selection: ToolSelection):
        if selection.default_toolsets is None and not selection.enabled_toolsets:
            selected = set(self.registry.names())
            disabled_resolution = resolve_toolsets(
                self.registry,
                enabled_toolsets=selection.disabled_toolsets,
                default_toolsets=None,
            )
            selected.difference_update(disabled_resolution.tool_names)
            return _ResolvedNames(tuple(sorted(selected)), disabled_resolution.unknown_toolsets)
        return resolve_toolsets(
            self.registry,
            enabled_toolsets=selection.enabled_toolsets,
            disabled_toolsets=selection.disabled_toolsets,
            default_toolsets=selection.default_toolsets,
        )

    def _group_has_registered_tools(self, group: str) -> bool:
        group_definition = BUILTIN_TOOL_GROUPS.get(group)
        if group_definition is None:
            return bool(self.registry.tool_names_for_toolset(group))
        return (
            any(self.registry.get(name) is not None for name in group_definition.tools)
            or bool(self.registry.tool_names_for_toolset(group))
        )

    def _cache_key(self, selection: ToolSelection) -> tuple[Any, ...]:
        return (
            selection,
            self.registry.generation,
            self.registry.availability_generation,
        )

    def _cache_entry_is_fresh(self, cached_at: float) -> bool:
        ttl = self.registry.availability_ttl_seconds
        return ttl == 0 or time.monotonic() - cached_at <= ttl


@dataclass(frozen=True, slots=True)
class _ResolvedNames:
    tool_names: tuple[str, ...] = ()
    unknown_toolsets: tuple[str, ...] = ()


def _copy_snapshot(snapshot: ToolCatalogSnapshot) -> ToolCatalogSnapshot:
    return ToolCatalogSnapshot(
        tool_names=tuple(snapshot.tool_names),
        model_tools=deepcopy(snapshot.model_tools),
        groups=tuple(snapshot.groups),
        unknown_toolsets=tuple(snapshot.unknown_toolsets),
        unavailable_tools=deepcopy(tuple(snapshot.unavailable_tools)),
        disabled_tools=tuple(snapshot.disabled_tools),
        hidden_tools=tuple(snapshot.hidden_tools),
        tool_write_modes=dict(snapshot.tool_write_modes),
        generation=snapshot.generation,
    )


def _normalize_selection(selection: ToolSelection) -> ToolSelection:
    return ToolSelection.from_values(
        enable_tools=selection.enable_tools,
        enabled_toolsets=selection.enabled_toolsets,
        disabled_toolsets=selection.disabled_toolsets,
        disabled_tools=selection.disabled_tools,
        write_tool_mode=selection.write_tool_mode,
        tool_write_modes=dict(selection.tool_write_modes),
        settings_fingerprint=selection.settings_fingerprint,
        default_toolsets=selection.default_toolsets,
    )


def _mutating_tools(registry: ToolRegistry, names: set[str]) -> set[str]:
    result: set[str] = set()
    for name in names:
        definition = registry.get(name)
        if definition is not None and definition.mutating:
            result.add(name)
    return result


def _clean_tool_name(value: object) -> str:
    return str(value or "").strip()


def _normalize_write_mode(value: object) -> str:
    normalized = str(value or "auto").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in _WRITE_MODES else "auto"


__all__ = [
    "ToolCatalog",
    "ToolCatalogSnapshot",
    "ToolSelection",
]
