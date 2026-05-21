"""Runtime guardrail decisions for repeated or non-progressing tool calls.

This module is about *what the agent loop should do with a specific tool
call attempt, not about the inherent safety category of the tool itself.

`ToolGuardrailDecision.action` values:
- `allow`: run the tool normally.
- `warn`: run the tool, but append guidance to the tool result so the model
  knows it may be repeating a failed or non-progressing path.
- `block`: skip this specific tool call and return a synthetic tool result;
  the agent can continue and choose a different strategy.
- `halt`: stop the whole agent run because the tool loop appears stuck.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ToolGuardrailConfig:
    warnings_enabled: bool = True
    hard_stop_enabled: bool = True
    exact_failure_warn_after: int = 2
    exact_failure_block_after: int = 5
    same_tool_failure_warn_after: int = 3
    same_tool_failure_halt_after: int = 8
    no_progress_warn_after: int = 2
    no_progress_block_after: int = 5


@dataclass(frozen=True, slots=True)
class ToolCallSignature:
    tool_name: str
    args_hash: str

    @classmethod
    def from_call(cls, tool_name: str, args: Mapping[str, Any] | None) -> ToolCallSignature:
        return cls(
            tool_name=tool_name,
            args_hash=_sha256(canonical_tool_args(args or {})),
        )

    def to_metadata(self) -> dict[str, str]:
        return {
            "tool_name": self.tool_name,
            "args_hash": self.args_hash,
        }


@dataclass(frozen=True, slots=True)
class ToolGuardrailDecision:
    action: str = "allow"  # allow | warn | block | halt
    code: str = "allow"
    message: str = ""
    tool_name: str = ""
    count: int = 0
    signature: ToolCallSignature | None = None

    @property
    def allows_execution(self) -> bool:
        return self.action in {"allow", "warn"}

    @property
    def blocks_execution(self) -> bool:
        return self.action in {"block", "halt"}

    @property
    def halts_run(self) -> bool:
        return self.action == "halt"

    def to_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "action": self.action,
            "code": self.code,
            "message": self.message,
            "tool_name": self.tool_name,
            "count": self.count,
        }
        if self.signature is not None:
            data["signature"] = self.signature.to_metadata()
        return data


class ToolCallGuardrailController:
    """Detect repeated failed or non-progressing tool calls during one agent run."""

    def __init__(self, config: ToolGuardrailConfig | None = None) -> None:
        self.config = config or ToolGuardrailConfig()
        self._exact_failure_counts: dict[ToolCallSignature, int] = {}
        self._same_tool_failure_counts: dict[str, int] = {}
        self._no_progress_counts: dict[ToolCallSignature, tuple[str, int]] = {}
        self._halt_decision: ToolGuardrailDecision | None = None

    @property
    def halt_decision(self) -> ToolGuardrailDecision | None:
        return self._halt_decision

    def before_call(
        self,
        tool_name: str,
        args: Mapping[str, Any] | None,
        *,
        read_only: bool = False,
    ) -> ToolGuardrailDecision:
        signature = ToolCallSignature.from_call(tool_name, args)
        if not self.config.hard_stop_enabled:
            return ToolGuardrailDecision(tool_name=tool_name, signature=signature)

        exact_count = self._exact_failure_counts.get(signature, 0)
        if exact_count >= _positive_int(self.config.exact_failure_block_after, 5):
            return ToolGuardrailDecision(
                action="block",
                code="repeated_exact_failure_block",
                message=(
                    f"Blocked {tool_name}: the same tool call failed {exact_count} "
                    "times with identical arguments. Stop retrying it unchanged; "
                    "change strategy or explain the blocker."
                ),
                tool_name=tool_name,
                count=exact_count,
                signature=signature,
            )

        if read_only:
            record = self._no_progress_counts.get(signature)
            repeat_count = record[1] if record is not None else 0
            if repeat_count >= _positive_int(self.config.no_progress_block_after, 5):
                return ToolGuardrailDecision(
                    action="block",
                    code="idempotent_no_progress_block",
                    message=(
                        f"Blocked {tool_name}: this read-only call returned the same "
                        f"result {repeat_count} times. Use the result already provided "
                        "or try a different query."
                    ),
                    tool_name=tool_name,
                    count=repeat_count,
                    signature=signature,
                )

        return ToolGuardrailDecision(tool_name=tool_name, signature=signature)

    def after_call(
        self,
        tool_name: str,
        args: Mapping[str, Any] | None,
        result: str | None,
        *,
        failed: bool | None = None,
        read_only: bool = False,
    ) -> ToolGuardrailDecision:
        signature = ToolCallSignature.from_call(tool_name, args)
        if failed is None:
            failed = classify_tool_failure(result)

        if failed:
            exact_count = self._exact_failure_counts.get(signature, 0) + 1
            self._exact_failure_counts[signature] = exact_count
            self._no_progress_counts.pop(signature, None)

            same_count = self._same_tool_failure_counts.get(tool_name, 0) + 1
            self._same_tool_failure_counts[tool_name] = same_count

            if self.config.hard_stop_enabled and same_count >= _positive_int(self.config.same_tool_failure_halt_after, 8):
                decision = ToolGuardrailDecision(
                    action="halt",
                    code="same_tool_failure_halt",
                    message=(
                        f"Stopped {tool_name}: it failed {same_count} times in this run. "
                        "Stop retrying the same failing tool path and choose a different approach."
                    ),
                    tool_name=tool_name,
                    count=same_count,
                    signature=signature,
                )
                self._halt_decision = decision
                return decision

            if self.config.warnings_enabled and exact_count >= _positive_int(self.config.exact_failure_warn_after, 2):
                return ToolGuardrailDecision(
                    action="warn",
                    code="repeated_exact_failure_warning",
                    message=(
                        f"{tool_name} has failed {exact_count} times with identical arguments. "
                        "This looks like a loop; inspect the error and change strategy instead "
                        "of retrying it unchanged."
                    ),
                    tool_name=tool_name,
                    count=exact_count,
                    signature=signature,
                )

            if self.config.warnings_enabled and same_count >= _positive_int(self.config.same_tool_failure_warn_after, 3):
                return ToolGuardrailDecision(
                    action="warn",
                    code="same_tool_failure_warning",
                    message=(
                        f"{tool_name} has failed {same_count} times in this run. "
                        "This looks like a loop; change approach before retrying."
                    ),
                    tool_name=tool_name,
                    count=same_count,
                    signature=signature,
                )

            return ToolGuardrailDecision(tool_name=tool_name, count=exact_count, signature=signature)

        self._exact_failure_counts.pop(signature, None)
        self._same_tool_failure_counts.pop(tool_name, None)

        if not read_only:
            self._no_progress_counts.pop(signature, None)
            return ToolGuardrailDecision(tool_name=tool_name, signature=signature)

        result_hash = _result_hash(result)
        previous = self._no_progress_counts.get(signature)
        repeat_count = 1
        if previous is not None and previous[0] == result_hash:
            repeat_count = previous[1] + 1
        self._no_progress_counts[signature] = (result_hash, repeat_count)

        if self.config.warnings_enabled and repeat_count >= _positive_int(self.config.no_progress_warn_after, 2):
            return ToolGuardrailDecision(
                action="warn",
                code="idempotent_no_progress_warning",
                message=(
                    f"{tool_name} returned the same result {repeat_count} times. "
                    "Use the result already provided or change the query instead of repeating it unchanged."
                ),
                tool_name=tool_name,
                count=repeat_count,
                signature=signature,
            )

        return ToolGuardrailDecision(tool_name=tool_name, count=repeat_count, signature=signature)


def canonical_tool_args(args: Mapping[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def classify_tool_failure(result: str | None) -> bool:
    if result is None:
        return False
    parsed = _safe_json_loads(result)
    if isinstance(parsed, dict):
        if parsed.get("is_error") is True or parsed.get("success") is False:
            return True
        if "error" in parsed or "failed" in parsed:
            return True
    preview = result[:500].strip().lower()
    return preview.startswith("error:") or '"error"' in preview or '"failed"' in preview


def toolguard_synthetic_result(decision: ToolGuardrailDecision) -> str:
    return json.dumps(
        {
            "error": decision.message,
            "guardrail": decision.to_metadata(),
        },
        ensure_ascii=False,
    )


def append_toolguard_guidance(result: str, decision: ToolGuardrailDecision) -> str:
    if decision.action not in {"warn", "halt"} or not decision.message:
        return result
    label = "Tool loop hard stop" if decision.action == "halt" else "Tool loop warning"
    return (
        (result or "")
        + f"\n\n[{label}: {decision.code}; count={decision.count}; {decision.message}]"
    )


def _result_hash(result: str | None) -> str:
    parsed = _safe_json_loads(result or "")
    if parsed is not None:
        try:
            canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        except TypeError:
            canonical = str(parsed)
    else:
        canonical = result or ""
    return _sha256(canonical)


def _safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
