# -*- coding: utf-8 -*-
"""Tool-guard mixin for SWEAgent.

Provides ``_acting`` and ``_reasoning`` overrides that intercept
sensitive tool calls before execution, implementing the deny /
guard / approve flow.

Separated from ``react_agent.py`` to keep the main agent class
focused on lifecycle management.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
import json as _json
import logging
import os
from pathlib import Path
import time
import uuid as _uuid
from typing import Any, Literal

from agentscope.message import Msg, ToolResultBlock

from ..constant import AGENT_WATCHDOG_TIMEOUT, QUERY_TIMEOUT_SECONDS
from ..app.runner.tool_output_frames import tool_output_invocation
from .hook_runtime import HookRuntime
from .hook_runtime.conversation_snapshot import capture_conversation_snapshot
from .hook_runtime.models import (
    HookConfig,
    HookContext,
    HookDecision,
    HookEventName,
    HookSessionState,
    MergedHookResult,
)
from .tool_failure import build_failed_tool_result_block
from ..security.tool_guard.models import TOOL_GUARD_DENIED_MARK
from ..tracing import has_trace_manager, get_trace_manager, get_current_trace

logger = logging.getLogger(__name__)


def _current_task_label() -> str:
    """返回当前 asyncio task 的诊断标识。"""
    task = asyncio.current_task()
    if task is None:
        return "no-task"
    return f"task-{id(task)}"


def _trace_field(trace_ctx: Any, field: str, default: Any = "") -> Any:
    """安全读取 trace 上下文字段，避免诊断日志反向打断 tracing。"""
    if trace_ctx is None:
        return default
    return getattr(trace_ctx, field, default)


_DEFAULT_LOCAL_TOOL_EXECUTION_HARD_TIMEOUT = min(
    QUERY_TIMEOUT_SECONDS,
    max(AGENT_WATCHDOG_TIMEOUT * 2.0, AGENT_WATCHDOG_TIMEOUT + 60.0),
)
try:
    LOCAL_TOOL_EXECUTION_HARD_TIMEOUT = max(
        float(
            os.environ.get(
                "SWE_LOCAL_TOOL_EXECUTION_HARD_TIMEOUT",
                str(_DEFAULT_LOCAL_TOOL_EXECUTION_HARD_TIMEOUT),
            ),
        ),
        1.0,
    )
except (TypeError, ValueError):
    LOCAL_TOOL_EXECUTION_HARD_TIMEOUT = (
        _DEFAULT_LOCAL_TOOL_EXECUTION_HARD_TIMEOUT
    )

_TOOLS_WITH_SPECIFIC_TIMEOUTS = {
    "execute_shell_command",
    "grep_search",
    "glob_search",
}
_APPROVAL_KIND_TOOL_GUARD = "tool_guard"
_APPROVAL_KIND_HOOK_PRE_TOOL_USE = "hook_pre_tool_use"


class _GuardAction:
    """Lightweight container for a guard decision made under lock."""

    __slots__ = ("kind", "tool_name", "tool_input", "guard_result")

    def __init__(
        self,
        kind: str,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        guard_result: Any = None,
    ) -> None:
        self.kind = kind
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.guard_result = guard_result


class ToolGuardMixin:
    """Mixin that adds tool-guard interception to a ReActAgent.

    At runtime this class is always combined with
    ``agentscope.agent.ReActAgent`` via MRO, so ``super()._acting``
    and ``super()._reasoning`` resolve to the concrete agent methods.
    """

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _init_tool_guard(self) -> None:
        """Lazy-init tool-guard components (called once)."""
        from swe.security.tool_guard.engine import get_guard_engine
        from swe.app.approvals import get_approval_service

        self._tool_guard_engine = get_guard_engine()
        self._tool_guard_approval_service = get_approval_service()
        self._tool_guard_pending_info: dict | None = None
        self._tool_guard_lock = asyncio.Lock()

    def _ensure_tool_guard(self) -> None:
        if not hasattr(self, "_tool_guard_engine"):
            self._init_tool_guard()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _agent_phase_context(
        self,
        phase: str,
        *,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        reason: str | None = None,
    ):
        enter_phase = getattr(self, "agent_phase", None)
        if enter_phase is None:
            return nullcontext()
        return enter_phase(
            phase,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            reason=reason,
        )

    def _tool_has_specific_timeout(self, tool_name: str) -> bool:
        if self._resolve_mcp_server(tool_name):
            return True
        return tool_name in _TOOLS_WITH_SPECIFIC_TIMEOUTS

    async def _run_tool_call_with_hard_timeout(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict | None:
        """Run a local tool under the generic hard timeout when applicable."""
        tool_call_id = str(tool_call.get("id") or "")
        with self._agent_phase_context(
            "tool_execution",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            reason="tool_execution",
        ):
            with tool_output_invocation(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
            ):
                if self._tool_has_specific_timeout(tool_name):
                    return await super()._acting(tool_call)  # type: ignore[misc]

                started_at = time.monotonic()
                try:
                    return await asyncio.wait_for(
                        super()._acting(tool_call),  # type: ignore[misc]
                        timeout=LOCAL_TOOL_EXECUTION_HARD_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - started_at
                    timeout_text = (
                        f"Error: Tool {tool_name} timed out after "
                        f"{LOCAL_TOOL_EXECUTION_HARD_TIMEOUT:.2f}s "
                        f"(elapsed {elapsed:.2f}s)."
                    )
                    logger.warning(
                        "Local tool hard timeout: tool_name=%s tool_call_id=%s "
                        "elapsed=%.3fs timeout=%.3fs",
                        tool_name,
                        tool_call_id,
                        elapsed,
                        LOCAL_TOOL_EXECUTION_HARD_TIMEOUT,
                    )
                    await self._persist_local_tool_timeout_result(
                        tool_call_id,
                        tool_name,
                        timeout_text,
                    )
                    return None

    async def _persist_local_tool_timeout_result(
        self,
        tool_call_id: str,
        tool_name: str,
        timeout_text: str,
    ) -> None:
        """Print and persist the timeout result seen by the next LLM turn."""
        timeout_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    **build_failed_tool_result_block(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        error_type="tool_timeout",
                        detail=timeout_text,
                    ),
                ),
            ],
            "system",
        )

        memory_content = getattr(getattr(self, "memory", None), "content", [])
        if memory_content:
            last_msg, marks = memory_content[-1]
            if (
                TOOL_GUARD_DENIED_MARK not in marks
                and last_msg.role == "system"
                and last_msg.get_content_blocks("tool_result")
                and last_msg.get_content_blocks("tool_result")[0].get("id")
                == tool_call_id
            ):
                last_msg.content = timeout_msg.content
                timeout_msg = last_msg
                await self.print(timeout_msg, True)
                return

        await self.print(timeout_msg, True)
        await self.memory.add(timeout_msg)

    def _should_require_approval(self) -> bool:
        """``True`` when a ``session_id`` is available for approval."""
        return bool(self._request_context.get("session_id"))

    def _last_tool_response_is_denied(self) -> bool:
        """Check if the last message is a guard-denied tool result."""
        if not self.memory.content:
            return False
        msg, marks = self.memory.content[-1]
        return (
            bool(marks)
            and TOOL_GUARD_DENIED_MARK in marks
            and msg.role == "system"
        )

    def _extract_sibling_tool_calls(self) -> list[dict[str, Any]]:
        """Extract all tool_use blocks from the last assistant message."""
        for msg, _ in reversed(self.memory.content):
            if msg.role == "assistant":
                return [
                    {
                        "id": b.get("id", ""),
                        "name": b.get("name", ""),
                        "input": b.get("input", {}),
                    }
                    for b in msg.get_content_blocks("tool_use")
                ]
        return []

    def _tool_result_exists_in_memory(self, tool_use_id: str) -> bool:
        """``True`` when a non-denied tool_result for *tool_use_id* exists."""
        for msg, marks in self.memory.content:
            if msg.role != "system" or TOOL_GUARD_DENIED_MARK in marks:
                continue
            for block in msg.get_content_blocks("tool_result"):
                if block.get("id") == tool_use_id:
                    return True
        return False

    def _extract_current_tool_response(
        self,
        tool_use_id: str,
        *,
        include_structured_failure: bool = False,
    ) -> Any | None:
        """Return the terminal output for the current tool result."""
        if not tool_use_id:
            return None

        content = getattr(getattr(self, "memory", None), "content", None)
        if not isinstance(content, list):
            return None
        memory_entries: list[Any] = content

        for entry in memory_entries[::-1]:
            message = (
                entry[0]
                if isinstance(entry, (tuple, list)) and entry
                else entry
            )
            blocks = getattr(message, "content", None)
            if not isinstance(blocks, list):
                continue
            for block in reversed(blocks):
                block_data = self._tool_result_block_to_dict(block)
                if not block_data:
                    continue
                if block_data.get("type") != "tool_result":
                    continue
                if block_data.get("id") != tool_use_id:
                    continue
                output = block_data.get("output")
                if self._is_structured_failure_output(output):
                    if include_structured_failure:
                        return output
                    return None
                return output
        return None

    @staticmethod
    def _is_structured_failure_output(output: Any) -> bool:
        return isinstance(output, dict) and output.get("isError") is True

    @staticmethod
    def _tool_result_block_to_dict(block: Any) -> dict[str, Any] | None:
        if isinstance(block, dict):
            return block

        model_dump = getattr(block, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(mode="json", exclude_none=True)
            return dumped if isinstance(dumped, dict) else None

        to_dict = getattr(block, "to_dict", None)
        if callable(to_dict):
            dumped = to_dict()
            return dumped if isinstance(dumped, dict) else None

        return None

    def _set_forced_tool_replay_approval(
        self,
        replay_approval: Any,
    ) -> None:
        if isinstance(replay_approval, dict):
            self._tool_guard_replay_approval = dict(replay_approval)
        elif hasattr(self, "_tool_guard_replay_approval"):
            self._tool_guard_replay_approval = None

    def _pop_forced_tool_call(  # pylint: disable=too-many-branches
        self,
    ) -> dict[str, Any] | None:
        """Pop and validate a forced tool call injected by the runner."""
        raw = self._request_context.pop("forced_tool_call_json", "")
        if not raw:
            return None

        try:
            tool_call = _json.loads(str(raw))
        except Exception:
            logger.warning(
                "Tool guard: invalid forced tool call payload",
                exc_info=True,
            )
            return None

        if not isinstance(tool_call, dict):
            logger.warning(
                "Tool guard: forced tool call payload is not a dict",
            )
            return None

        tool_name = tool_call.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            logger.warning(
                "Tool guard: forced tool call missing valid name",
            )
            return None

        tool_input = tool_call.get("input", {})
        if not isinstance(tool_input, dict):
            logger.warning(
                "Tool guard: forced tool call input is not a dict",
            )
            return None

        tool_id = tool_call.get("id")
        if not isinstance(tool_id, str) or not tool_id:
            tool_id = f"approved-{_uuid.uuid4().hex[:12]}"

        siblings = tool_call.pop("_sibling_tool_calls", None)
        remaining = tool_call.pop("_remaining_queue", None)
        thinking_blocks = tool_call.pop("_thinking_blocks", None)
        replay_approval = tool_call.pop("_approval_replay", None)
        self._set_forced_tool_replay_approval(replay_approval)

        if remaining is not None and isinstance(remaining, list):
            self._tool_guard_replay_queue = remaining
        elif siblings is not None and isinstance(siblings, list):
            found = False
            queue: list[dict[str, Any]] = []
            for s in siblings:
                if not found and s.get("id") == tool_id:
                    found = True
                    continue
                if found:
                    queue.append(s)
            self._tool_guard_replay_queue = queue
        else:
            self._tool_guard_replay_queue = []

        result = {
            "id": tool_id,
            "name": tool_name,
            "input": tool_input,
        }

        # Preserve thinking blocks for models that require reasoning_content
        if thinking_blocks is not None and isinstance(thinking_blocks, list):
            result["_thinking_blocks"] = thinking_blocks

        return result

    async def _get_pending_info_for_display(self) -> dict[str, Any]:
        """Return pending tool info aligned with approval queue head."""
        fallback = getattr(self, "_tool_guard_pending_info", None) or {}
        session_id = str(self._request_context.get("session_id") or "")
        if not session_id:
            return fallback

        try:
            pending = (
                await self._tool_guard_approval_service.get_pending_by_session(
                    session_id,
                )
            )
        except Exception:
            logger.warning(
                "Tool guard: failed to read pending queue head",
                exc_info=True,
            )
            return fallback

        if pending is None:
            return fallback

        tool_input: dict[str, Any] = {}
        extra = pending.extra if isinstance(pending.extra, dict) else {}
        tool_call = extra.get("tool_call") if isinstance(extra, dict) else {}
        if isinstance(tool_call, dict) and isinstance(
            tool_call.get("input"),
            dict,
        ):
            tool_input = tool_call["input"]

        return {
            "request_id": pending.request_id or fallback.get("request_id", ""),
            "tool_name": pending.tool_name
            or fallback.get("tool_name", "unknown"),
            "tool_input": tool_input or fallback.get("tool_input", {}),
            "guardians": fallback.get("guardians", []),
        }

    async def _cleanup_tool_guard_denied_messages(
        self,
        include_denial_response: bool = True,
    ) -> None:
        """Remove tool-guard denied messages from memory.

        Finds messages marked with ``TOOL_GUARD_DENIED_MARK`` and
        removes them.  When *include_denial_response* is ``True``,
        also removes the assistant message immediately following the
        last marked message (the LLM's denial explanation).

        When *include_denial_response* is ``False`` (approval granted),
        keeps the waiting-for-approval message but clears its
        ``approval_action`` metadata so the approval card won't render
        on reload, preserving the text content for conversation history.
        """
        ids_to_delete: list[str] = []
        last_marked_idx = -1

        for i, (msg, marks) in enumerate(self.memory.content):
            if TOOL_GUARD_DENIED_MARK in marks:
                ids_to_delete.append(msg.id)
                last_marked_idx = i

        if (
            include_denial_response
            and last_marked_idx >= 0
            and last_marked_idx + 1 < len(self.memory.content)
        ):
            next_msg, _ = self.memory.content[last_marked_idx + 1]
            if next_msg.role == "assistant":
                ids_to_delete.append(next_msg.id)

                # When approval is granted (include_denial_response=False),
        # clear approval_action metadata from the waiting message
        # instead of deleting it, preserving text content.
        if (
            not include_denial_response
            and last_marked_idx >= 0
            and last_marked_idx + 1 < len(self.memory.content)
        ):
            next_msg, marks = self.memory.content[last_marked_idx + 1]
            if next_msg.role == "assistant":
                metadata = getattr(next_msg, "metadata", None)
                if metadata and isinstance(metadata, dict):
                    # Clear approval_action so frontend won't render approval card
                    if "approval_action" in metadata:
                        del metadata["approval_action"]
                        logger.info(
                            "Tool guard: cleared approval_action metadata "
                            "from waiting message (approval granted)",
                        )

        if ids_to_delete:
            removed = await self.memory.delete(ids_to_delete)
            logger.info(
                "Tool guard: cleaned up %d denied message(s)",
                removed,
            )

    # ------------------------------------------------------------------
    # _acting override
    # ------------------------------------------------------------------

    def _resolve_mcp_server(self, tool_name: str) -> str | None:
        """Resolve MCP server name from toolkit registration.

        The tool_call dict from agentscope does not include mcp_server,
        so we look it up from the registered tool function.

        Args:
            tool_name: Name of the tool

        Returns:
            MCP server name if the tool is an MCP tool, None otherwise
        """
        try:
            toolkit = getattr(self, "toolkit", None)
            if toolkit is None:
                return None
            tool_func = toolkit.tools.get(tool_name)
            if tool_func is not None:
                return getattr(tool_func, "mcp_name", None)
        except Exception:
            pass
        return None

    async def _emit_tool_trace_start(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        mcp_server: str | None,
    ) -> str:
        """Emit tool call start trace event.

        Returns span_id or empty string.
        """
        if not has_trace_manager():
            return ""
        try:
            trace_ctx = self._resolve_trace_context_for_tracing()
            if trace_ctx:
                logger.debug(
                    "Tool trace start: trace_id=%s user_id=%s session_id=%s "
                    "source_id=%s tool=%s mcp_server=%s task=%s",
                    _trace_field(trace_ctx, "trace_id", None),
                    _trace_field(trace_ctx, "user_id", ""),
                    _trace_field(trace_ctx, "session_id", ""),
                    _trace_field(trace_ctx, "source_id", ""),
                    tool_name,
                    mcp_server,
                    _current_task_label(),
                )
                trace_mgr = get_trace_manager()
                return await trace_mgr.emit_tool_call_start(
                    trace_id=_trace_field(trace_ctx, "trace_id", ""),
                    tool_name=tool_name,
                    tool_input=tool_input,
                    source_id=_trace_field(trace_ctx, "source_id", ""),
                    user_id=_trace_field(trace_ctx, "user_id", ""),
                    session_id=_trace_field(trace_ctx, "session_id", ""),
                    channel=_trace_field(trace_ctx, "channel", ""),
                    mcp_server=mcp_server,
                    user_name=_trace_field(trace_ctx, "user_name", None),
                    bbk_id=_trace_field(trace_ctx, "bbk_id", None),
                )
        except Exception as e:
            logger.debug("Failed to emit tool start event: %s", e)
        return ""

    async def _emit_tool_trace_end(
        self,
        span_id: str,
        tool_output: dict | str | None,
        error: str | None = None,
    ) -> None:
        """Emit tool call end trace event.

        处理MCP工具返回的isError字段，确保错误信息正确记录到tracing。
        """
        if not span_id or not has_trace_manager():
            return
        try:
            trace_ctx = self._resolve_trace_context_for_tracing()
            if not trace_ctx:
                return

            logger.debug(
                "Tool trace end: trace_id=%s session_id=%s source_id=%s "
                "span_id=%s task=%s",
                _trace_field(trace_ctx, "trace_id", None),
                _trace_field(trace_ctx, "session_id", ""),
                _trace_field(trace_ctx, "source_id", ""),
                span_id,
                _current_task_label(),
            )
            trace_mgr = get_trace_manager()
            output_str, mcp_error = self._resolve_tool_output_and_error(
                tool_output,
                error,
            )

            await trace_mgr.emit_tool_call_end(
                trace_id=_trace_field(trace_ctx, "trace_id", ""),
                span_id=span_id,
                tool_output=output_str,
                error=mcp_error,
            )
        except Exception as e:
            logger.debug("Failed to emit tool end event: %s", e)

    def _resolve_trace_context_for_tracing(self) -> Any | None:
        """优先使用 request_context 绑定的 trace，上下文缺失时回退。"""
        request_context = getattr(self, "_request_context", {}) or {}
        bound_trace_id = str(request_context.get("trace_id") or "")
        if bound_trace_id:
            current_trace = get_current_trace()
            if current_trace is not None and getattr(
                current_trace,
                "trace_id",
                None,
            ) not in {None, bound_trace_id}:
                logger.warning(
                    "Tool tracing detected mismatched current trace; "
                    "using request-bound trace instead. current=%s bound=%s "
                    "task=%s",
                    getattr(current_trace, "trace_id", None),
                    bound_trace_id,
                    _current_task_label(),
                )
            return type(
                "_RequestTraceContext",
                (),
                {
                    "trace_id": bound_trace_id,
                    "user_id": str(request_context.get("user_id") or ""),
                    "session_id": str(
                        request_context.get("session_id") or "",
                    ),
                    "channel": str(request_context.get("channel") or ""),
                    "source_id": str(request_context.get("source_id") or ""),
                    "user_name": request_context.get("user_name"),
                    "bbk_id": request_context.get("bbk_id"),
                },
            )()
        return get_current_trace()

    def _resolve_tool_output_and_error(
        self,
        tool_output: dict | str | None,
        error: str | None,
    ) -> tuple[str | None, str | None]:
        """解析工具输出，处理MCP isError字段.

        Args:
            tool_output: 工具返回结果
            error: 已有的错误信息

        Returns:
            (output_str, resolved_error) 元组
        """
        if error is not None:
            return None, error

        if tool_output is None:
            return None, None

        # 处理MCP CallToolResult类型
        try:
            from mcp.types import CallToolResult

            if isinstance(tool_output, CallToolResult):
                if tool_output.isError:
                    return None, self._extract_mcp_error_content(tool_output)
                return self._extract_mcp_success_content(tool_output), None
        except ImportError:
            pass

        # 处理dict形式
        if isinstance(tool_output, dict):
            if tool_output.get("isError"):
                return None, self._extract_dict_error_content(tool_output)
            return tool_output.get("content") or str(tool_output), None

        return str(tool_output), None

    def _extract_mcp_error_content(self, result) -> str:
        """从MCP CallToolResult中提取错误信息.

        Args:
            result: CallToolResult对象，isError=True

        Returns:
            错误信息字符串
        """
        content = getattr(result, "content", [])
        error_parts = []
        for block in content:
            text = getattr(block, "text", None)
            if text:
                error_parts.append(text)
        return "\n".join(error_parts) if error_parts else "MCP tool error"

    def _extract_mcp_success_content(self, result) -> str:
        """从MCP CallToolResult中提取成功返回内容.

        Args:
            result: CallToolResult对象，isError=False

        Returns:
            内容字符串
        """
        content = getattr(result, "content", [])
        content_parts = []
        for block in content:
            text = getattr(block, "text", None)
            if text:
                content_parts.append(text)
        return "\n".join(content_parts) if content_parts else ""

    def _extract_dict_error_content(self, result: dict) -> str:
        """从dict形式的结果中提取错误信息.

        Args:
            result: 包含isError=True的dict

        Returns:
            错误信息字符串
        """
        content = result.get("content", [])
        if isinstance(content, list):
            error_parts = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text", "")
                else:
                    text = str(block)
                if text:
                    error_parts.append(text)
            return "\n".join(error_parts) if error_parts else "Tool error"
        return str(content) if content else "Tool error"

    def _load_tenant_hook_config(self) -> HookConfig:
        try:
            from swe.config.utils import get_tenant_config_path, load_config

            tenant_id = self._request_context.get("tenant_id")
            config_path = (
                get_tenant_config_path(tenant_id) if tenant_id else None
            )
            return load_config(config_path).hooks
        except Exception:
            logger.debug(
                "Tool hook: failed to load tenant config",
                exc_info=True,
            )
            return HookConfig()

    def _tool_hooks_enabled(self, tenant_hooks: HookConfig) -> bool:
        agent_hooks = getattr(self._agent_config, "hooks", None)
        session_state = self._get_hook_session_state()
        return bool(
            tenant_hooks.enabled
            or (agent_hooks is not None and agent_hooks.enabled)
            or session_state.has_loaded_skill_sources(),
        )

    def _get_hook_session_state(self) -> HookSessionState:
        overlay_ref = self._request_context.get("_hook_overlay_model")
        if isinstance(overlay_ref, HookSessionState):
            return overlay_ref
        try:
            return HookSessionState.model_validate(
                self._request_context.get("hook_overlay") or {},
            )
        except Exception:
            return HookSessionState()

    def _build_tool_hook_context(
        self,
        event_name: HookEventName,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_use_id: str | None = None,
        tool_response: Any = None,
        error: str | None = None,
    ) -> HookContext:
        from pathlib import Path

        from swe.config.context import get_current_effective_tenant_id
        from swe.constant import WORKING_DIR

        request_context = getattr(self, "_request_context", {}) or {}
        workspace_dir = Path(
            getattr(self, "_workspace_dir", None) or WORKING_DIR,
        )
        effective_tenant_id = (
            get_current_effective_tenant_id()
            or request_context.get("tenant_id")
            or "default"
        )
        return HookContext(
            session_id=str(request_context.get("session_id") or ""),
            transcript_path=str(request_context.get("transcript_path") or ""),
            cwd=str(workspace_dir),
            hook_event_name=event_name,
            tenant_id=str(
                request_context.get("tenant_id") or effective_tenant_id,
            ),
            effective_tenant_id=str(effective_tenant_id),
            user_id=str(request_context.get("user_id") or ""),
            agent_id=str(request_context.get("agent_id") or ""),
            channel=str(request_context.get("channel") or ""),
            source_id=request_context.get("source_id"),
            trace_id=request_context.get("trace_id"),
            workspace_dir=str(workspace_dir),
            chat_id=request_context.get("chat_id"),
            turn_id=request_context.get("turn_id"),
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_use_id,
            tool_response=tool_response,
            error=error,
        )

    async def _emit_tool_hook(
        self,
        event_name: HookEventName,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_use_id: str | None = None,
        tool_response: Any = None,
        error: str | None = None,
    ) -> MergedHookResult:
        tenant_hooks = self._load_tenant_hook_config()
        overlay = self._get_hook_session_state()
        if not self._tool_hooks_enabled(tenant_hooks):
            return MergedHookResult()
        agent_hooks = getattr(self._agent_config, "hooks", None)
        if not isinstance(agent_hooks, HookConfig):
            agent_hooks = HookConfig()
        runtime = HookRuntime(
            tenant_config=tenant_hooks,
            agent_config=agent_hooks,
            session_overlay=overlay,
        )
        context = self._build_tool_hook_context(
            event_name,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_use_id,
            tool_response=tool_response,
            error=error,
        )

        async def _conversation_snapshot_provider():
            return await capture_conversation_snapshot(
                getattr(self, "memory", None),
            )

        result = await runtime.emit(
            context,
            workspace_dir=Path(getattr(self, "_workspace_dir", None) or "."),
            conversation_snapshot_provider=_conversation_snapshot_provider,
        )
        self._request_context["hook_overlay"] = overlay.model_dump(
            mode="json",
            by_alias=True,
        )
        return result

    async def _notify_skill_detector_tool_call(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        mcp_server: str | None,
    ) -> None:
        detector = self._request_context.get("_skill_invocation_detector")
        if detector is None or not hasattr(detector, "on_tool_call"):
            return
        try:
            await detector.on_tool_call(
                tool_name=tool_name,
                tool_input=tool_input,
                mcp_server=mcp_server,
            )
        except Exception as exc:
            logger.debug("Skill detector tool notification failed: %s", exc)

    @staticmethod
    def _hook_ask_handler_ids(result: MergedHookResult) -> list[str]:
        return [
            item.handler_id
            for item in result.permission_decisions
            if item.decision == HookDecision.ASK
        ]

    def _approved_hook_ask_replay_matches(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        tool_input: dict[str, Any],
        result: MergedHookResult,
    ) -> bool:
        replay = getattr(self, "_tool_guard_replay_approval", None)
        if not isinstance(replay, dict):
            return False
        if replay.get("approval_kind") != _APPROVAL_KIND_HOOK_PRE_TOOL_USE:
            return False
        current_ask_ids = set(self._hook_ask_handler_ids(result))
        approved_ask_ids = set(replay.get("hook_ask_handler_ids") or [])
        if not current_ask_ids or not current_ask_ids.issubset(
            approved_ask_ids,
        ):
            return False
        if replay.get("tool_call_id") != tool_call.get("id"):
            return False
        if replay.get("tool_name") != tool_name:
            return False
        if replay.get("tool_input") != tool_input:
            return False
        self._tool_guard_replay_approval = None
        logger.info(
            "Tool hook approval: replaying approved ask for tool %s "
            "(request %s)",
            tool_name,
            str(replay.get("request_id") or "")[:8],
        )
        return True

    async def _acting_hook_denied(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        reason: str,
    ) -> dict | None:
        from agentscope.message import ToolResultBlock

        denied_text = (
            f"Tool `{tool_name}` blocked by hook runtime.\n"
            f"{reason or 'Hook denied tool execution.'}"
        )
        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    **build_failed_tool_result_block(
                        tool_call_id=tool_call["id"],
                        tool_name=tool_name,
                        error_type="hook_denied",
                        detail=denied_text,
                    ),
                ),
            ],
            "system",
        )
        await self.print(tool_res_msg, True)
        await self.memory.add(tool_res_msg)
        return None

    async def _record_tool_hook_result(
        self,
        result: MergedHookResult,
        *,
        event_name: HookEventName,
    ) -> None:
        lines = [
            f"[{item.handler_id}] {item.context}"
            for item in result.additional_context
        ]
        if result.blocked and result.reason:
            lines.append(f"[{event_name.value}] {result.reason}")
        if not lines:
            return
        msg = Msg(
            "system",
            "[Hook additional context]\n" + "\n".join(lines),
            "system",
        )
        await self.memory.add(msg)

    @staticmethod
    def _hook_guard_result(
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
    ):
        from swe.security.tool_guard.models import (
            GuardFinding,
            GuardSeverity,
            GuardThreatCategory,
            ToolGuardResult,
        )

        finding = GuardFinding(
            id=f"hook-{_uuid.uuid4().hex[:12]}",
            rule_id="unified_hook_runtime",
            category=GuardThreatCategory.CODE_EXECUTION,
            severity=GuardSeverity.HIGH,
            title="Hook approval requested",
            description=reason or "Hook requested approval before tool use.",
            tool_name=tool_name,
            guardian="unified_hook_runtime",
        )
        return ToolGuardResult(
            tool_name=tool_name,
            params=tool_input,
            findings=[finding],
            guardians_used=["unified_hook_runtime"],
        )

    async def _acting(self, tool_call) -> dict | None:  # noqa: C901
        """Intercept sensitive tool calls before execution.

        1. If tool is in *denied_tools*, auto-deny unconditionally.
        2. If tool is in the guarded scope, check for a one-shot
           pre-approval, then run all guardians.
        3. For non-guarded tools, run only ``always_run`` guardians
           (e.g. sensitive file path checks).
        4. If findings exist, enter the approval flow.
        5. Otherwise, delegate to ``super()._acting``.

        The guard *decision* block is serialised via ``_tool_guard_lock``
        so that ``parallel_tool_calls=True`` does not cause state races
        on shared mixin attributes.  Actual tool execution (both
        pre-approved and non-guarded) runs **outside** the lock for
        true parallelism.
        """
        self._ensure_tool_guard()

        tool_name = str(tool_call.get("name", ""))
        tool_input = tool_call.get("input", {})

        # Resolve mcp_server from toolkit registration since tool_call dict
        # (agentscope ToolUseBlock) does not carry mcp_server.
        mcp_server = self._resolve_mcp_server(tool_name)

        pre_hook_result = await self._emit_tool_hook(
            HookEventName.PRE_TOOL_USE,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=str(tool_call.get("id") or ""),
        )
        if pre_hook_result.updated_input is not None:
            tool_call = dict(tool_call)
            tool_call["input"] = pre_hook_result.updated_input
            tool_input = pre_hook_result.updated_input
        if pre_hook_result.decision in {
            HookDecision.BLOCK,
            HookDecision.DENY,
            HookDecision.STOP,
        }:
            return await self._acting_hook_denied(
                tool_call,
                tool_name,
                pre_hook_result.reason,
            )
        if pre_hook_result.decision == HookDecision.ASK:
            if self._approved_hook_ask_replay_matches(
                tool_call,
                tool_name,
                tool_input,
                pre_hook_result,
            ):
                await self._record_tool_hook_result(
                    pre_hook_result,
                    event_name=HookEventName.PRE_TOOL_USE,
                )
            else:
                return await self._acting_with_approval(
                    tool_call,
                    tool_name,
                    self._hook_guard_result(
                        tool_name,
                        tool_input,
                        pre_hook_result.reason,
                    ),
                    approval_kind=_APPROVAL_KIND_HOOK_PRE_TOOL_USE,
                    hook_ask_handler_ids=self._hook_ask_handler_ids(
                        pre_hook_result,
                    ),
                )

        await self._notify_skill_detector_tool_call(
            tool_name,
            tool_input,
            mcp_server,
        )

        span_id = await self._emit_tool_trace_start(
            tool_name,
            tool_input,
            mcp_server,
        )

        action: _GuardAction | None = None
        with self._agent_phase_context(
            "tool_guard",
            tool_name=tool_name,
            tool_call_id=str(tool_call.get("id") or ""),
            reason="guard_decision",
        ):
            async with self._tool_guard_lock:
                try:
                    action = await self._decide_guard_action(tool_call)
                except Exception as exc:
                    logger.warning(
                        "Tool guard check error (non-blocking): %s",
                        exc,
                        exc_info=True,
                    )

        if action is not None:
            result = await self._execute_guard_action(action, tool_call)
            await self._emit_tool_trace_end(span_id, result)
            return result

        try:
            result = await self._run_tool_call_with_hard_timeout(
                tool_call,
                tool_name,
                tool_input,
            )
            tool_use_id = str(tool_call.get("id") or "")
            tool_response = self._extract_current_tool_response(tool_use_id)
            trace_tool_output = result
            if trace_tool_output is None:
                # post hook 不应把结构化失败当作正常结果继续消费，
                # 但 tracing 仍需要读取原始失败 payload 来提取 error。
                trace_tool_output = self._extract_current_tool_response(
                    tool_use_id,
                    include_structured_failure=True,
                )
            post_hook_result = await self._emit_tool_hook(
                HookEventName.POST_TOOL_USE,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_use_id=tool_use_id,
                tool_response=tool_response,
            )
            await self._record_tool_hook_result(
                post_hook_result,
                event_name=HookEventName.POST_TOOL_USE,
            )
            await self._emit_tool_trace_end(span_id, trace_tool_output)

            if getattr(self, "_tool_guard_forced_replay_active", False):
                self._tool_guard_forced_replay_active = False
                self._tool_guard_replay_done = {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "remaining_queue": getattr(
                        self,
                        "_tool_guard_replay_queue",
                        [],
                    ),
                }
            return result

        except Exception as e:
            failure_hook_result = await self._emit_tool_hook(
                HookEventName.POST_TOOL_USE_FAILURE,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_use_id=str(tool_call.get("id") or ""),
                error=str(e),
            )
            await self._record_tool_hook_result(
                failure_hook_result,
                event_name=HookEventName.POST_TOOL_USE_FAILURE,
            )
            await self._emit_tool_trace_end(span_id, None, error=str(e))
            raise

    async def _decide_guard_action(
        self,
        tool_call: dict[str, Any],
    ) -> "_GuardAction | None":
        """Decide what guard action to take (runs under lock).

        Returns a ``_GuardAction`` describing what to do, or ``None``
        to fall through to the default ``super()._acting`` path.
        No actual tool execution happens here.
        """
        engine = self._tool_guard_engine
        tool_name = str(tool_call.get("name", ""))
        tool_input = tool_call.get("input", {})
        if not tool_name or not engine.enabled:
            return None

        if engine.is_denied(tool_name):
            logger.warning(
                "Tool guard: tool '%s' is in the denied set, auto-denying",
                tool_name,
            )
            denied_result = engine.guard(tool_name, tool_input)
            return _GuardAction(
                "auto_denied",
                tool_name,
                tool_input,
                guard_result=denied_result,
            )

        guarded = engine.is_guarded(tool_name)

        if guarded and await self._consume_preapproval(tool_name, tool_input):
            self._tool_guard_pending_info = None
            await self._cleanup_tool_guard_denied_messages(
                include_denial_response=False,
            )
            return _GuardAction("preapproved", tool_name, tool_input)

        guard_result = engine.guard(
            tool_name,
            tool_input,
            only_always_run=not guarded,
        )
        if guard_result is not None and guard_result.findings:
            from swe.security.tool_guard.utils import log_findings

            log_findings(tool_name, guard_result)
            if self._should_require_approval():
                return _GuardAction(
                    "needs_approval",
                    tool_name,
                    tool_input,
                    guard_result=guard_result,
                )
        return None

    async def _execute_guard_action(
        self,
        action: "_GuardAction",
        tool_call: dict[str, Any],
    ) -> dict | None:
        """Execute the guard action decided under lock (runs outside lock)."""
        if action.kind == "auto_denied":
            return await self._acting_auto_denied(
                tool_call,
                action.tool_name,
                action.guard_result,
            )
        if action.kind == "preapproved":
            return await self._run_approved_tool_call(
                tool_call,
                action.tool_name,
                action.tool_input,
            )
        if action.kind == "needs_approval":
            return await self._acting_with_approval(
                tool_call,
                action.tool_name,
                action.guard_result,
            )
        return None

    async def _consume_preapproval(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> bool:
        """Consume one matching approval token if present."""
        session_id = str(self._request_context.get("session_id") or "")
        if not session_id:
            return False

        svc = self._tool_guard_approval_service
        consumed = await svc.consume_approval(
            session_id,
            tool_name,
            tool_params=tool_input,
            approval_kind=_APPROVAL_KIND_TOOL_GUARD,
        )
        if consumed:
            logger.info(
                "Tool guard: pre-approved '%s' (session %s), skipping",
                tool_name,
                session_id[:8],
            )
        return bool(consumed)

    async def _run_approved_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict | None:
        """Execute approved call and persist replay state."""
        result = await self._run_tool_call_with_hard_timeout(
            tool_call,
            tool_name,
            tool_input,
        )
        if getattr(self, "_tool_guard_forced_replay_active", False):
            self._tool_guard_forced_replay_active = False
            self._tool_guard_replay_done = {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "remaining_queue": getattr(
                    self,
                    "_tool_guard_replay_queue",
                    [],
                ),
            }
        return result

    # ------------------------------------------------------------------
    # Denied / Approval responses
    # ------------------------------------------------------------------

    async def _acting_auto_denied(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        guard_result=None,
    ) -> dict | None:
        """Auto-deny a tool call without offering approval."""
        from agentscope.message import ToolResultBlock
        from swe.security.tool_guard.approval import (
            format_findings_summary,
        )

        if guard_result is not None and guard_result.findings:
            findings_text = format_findings_summary(guard_result)
            severity = guard_result.max_severity.value
            count = str(guard_result.findings_count)
        else:
            findings_text = "- Tool is in the denied list / 工具在禁止列表中"
            severity = "DENIED"
            count = "N/A"

        denied_text = (
            f"⛔ **Tool Blocked / 工具已拦截**\n\n"
            f"- Tool / 工具: `{tool_name}`\n"
            f"- Severity / 严重性: `{severity}`\n"
            f"- Findings / 发现: `{count}`\n\n"
            f"{findings_text}\n\n"
            f"This tool is blocked and cannot be approved.\n"
            f"该工具已被禁止，无法批准执行。"
        )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    **build_failed_tool_result_block(
                        tool_call_id=tool_call["id"],
                        tool_name=tool_name,
                        error_type="tool_guard_denied",
                        detail=denied_text,
                    ),
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(tool_res_msg)
        return None

    async def _acting_with_approval(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        guard_result,
        *,
        approval_kind: str = _APPROVAL_KIND_TOOL_GUARD,
        hook_ask_handler_ids: list[str] | None = None,
    ) -> dict | None:
        """Deny the tool call and record a pending approval."""
        from agentscope.message import ToolResultBlock
        from swe.security.tool_guard.approval import (
            format_findings_summary,
        )

        channel = str(self._request_context.get("channel") or "")

        # Find the original assistant message and extract thinking blocks
        original_msg = None
        for msg, marks in reversed(self.memory.content):
            if msg.role == "assistant":
                if TOOL_GUARD_DENIED_MARK not in marks:
                    marks.append(TOOL_GUARD_DENIED_MARK)
                original_msg = msg
                break

        extra: dict[str, Any] = {
            "approval_kind": approval_kind,
            "tool_call": tool_call,
        }
        if hook_ask_handler_ids:
            extra["hook_ask_handler_ids"] = list(hook_ask_handler_ids)

        # Preserve thinking blocks from the original message
        if original_msg is not None:
            thinking_blocks = [
                b
                for b in original_msg.get_content_blocks()
                if isinstance(b, dict) and b.get("type") == "thinking"
            ]
            if thinking_blocks:
                extra["thinking_blocks"] = thinking_blocks

        replay_queue = getattr(self, "_tool_guard_replay_queue", None)
        if replay_queue is not None:
            extra["remaining_queue"] = list(replay_queue)
            self._tool_guard_replay_queue = None
        else:
            siblings = self._extract_sibling_tool_calls()
            if siblings:
                extra["sibling_tool_calls"] = siblings

        session_id = str(
            self._request_context.get("session_id") or "",
        )
        tool_call_id = tool_call.get("id", "")
        svc = self._tool_guard_approval_service
        if session_id:
            if tool_call_id:
                await svc.cancel_stale_pending_for_tool_call(
                    session_id,
                    tool_call_id,
                )
            for queued in extra.get("remaining_queue", []):
                qid = queued.get("id", "")
                if qid:
                    await svc.cancel_stale_pending_for_tool_call(
                        session_id,
                        qid,
                    )

        pending_request = await svc.create_pending(
            session_id=session_id,
            user_id=str(
                self._request_context.get("user_id") or "",
            ),
            channel=channel,
            tool_name=tool_name,
            result=guard_result,
            extra=extra,
        )

        guardians = list(
            {f.guardian for f in guard_result.findings if f.guardian},
        )
        self._tool_guard_pending_info = {
            "request_id": pending_request.request_id,
            "tool_name": tool_name,
            "tool_input": tool_call.get("input", {}),
            "guardians": guardians,
        }

        findings_text = format_findings_summary(guard_result)
        denied_text = (
            f"⚠️ **Risk Detected / 检测到风险**\n\n"
            f"- Tool / 工具: `{tool_name}`\n"
            f"- Severity / 严重性: "
            f"`{guard_result.max_severity.value}`\n"
            f"- Findings / 发现: "
            f"`{guard_result.findings_count}`\n\n"
            f"{findings_text}\n\n"
            f"Type `/approve` to approve, "
            f"`/deny` to deny, or send any message to deny.\n"
            f"输入 `/approve` 批准执行，或发送任意消息拒绝。"
        )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    **build_failed_tool_result_block(
                        tool_call_id=tool_call["id"],
                        tool_name=tool_name,
                        error_type="approval_required",
                        detail=denied_text,
                    ),
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(
            tool_res_msg,
            marks=TOOL_GUARD_DENIED_MARK,
        )
        return None

    # ------------------------------------------------------------------
    # _reasoning override (guard-aware)
    # ------------------------------------------------------------------

    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ) -> Msg:
        """Short-circuit reasoning when awaiting guard approval.

        After a forced approved replay completes its ``_acting`` cycle,
        this method either continues with the next queued sibling tool
        call (returning a ``tool_use`` message) or returns a text-only
        completion message so the ``ReActAgent.reply`` loop exits
        naturally.
        """
        with self._agent_phase_context(
            "approval_replay",
            reason="approval_replay_done",
        ):
            replay_msg = await self._reason_about_replay_done()
        if replay_msg is not None:
            return replay_msg

        forced_tool_call = self._pop_forced_tool_call()
        if forced_tool_call is not None:
            with self._agent_phase_context(
                "approval_replay",
                tool_name=str(forced_tool_call.get("name") or ""),
                tool_call_id=str(forced_tool_call.get("id") or ""),
                reason="forced_tool_replay",
            ):
                replay_msg = await self._emit_forced_tool_use(
                    forced_tool_call,
                )
            if replay_msg is not None:
                return replay_msg

        if self._last_tool_response_is_denied():
            with self._agent_phase_context(
                "approval_replay",
                reason="waiting_for_approval",
            ):
                return await self._emit_waiting_for_approval()

        return await super()._reasoning(  # type: ignore[misc]
            tool_choice=tool_choice,
        )

    async def _reason_about_replay_done(self) -> Msg | None:
        """Emit replay continuation or completion message.

        When the replay queue is exhausted, all synthetic replay
        messages are cleaned from memory and ``None`` is returned so
        that ``_reasoning`` falls through to ``super()._reasoning()``.
        This lets the LLM respond naturally based on the actual tool
        results without leaving any approval-process artifacts in the
        conversation.
        """
        replay_info = getattr(self, "_tool_guard_replay_done", None)
        if not replay_info:
            return None

        self._tool_guard_replay_done = None
        remaining_queue = self._filter_pending_replay_queue(
            replay_info.get("remaining_queue") or [],
        )
        if not remaining_queue:
            return None
        return await self._emit_next_replay_tool_call(remaining_queue)

    def _filter_pending_replay_queue(
        self,
        queue: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drop replayed tool calls that already have tool results."""
        filtered: list[dict[str, Any]] = []
        for tool_call in list(queue):
            tc_id = tool_call.get("id", "")
            if self._tool_result_exists_in_memory(tc_id):
                continue
            filtered.append(tool_call)
        return filtered

    async def _emit_next_replay_tool_call(
        self,
        remaining_queue: list[dict[str, Any]],
    ) -> Msg:
        """Emit assistant message that chains to the next replayed call.

        Only the ``ToolUseBlock`` is included — no approval-process
        text is added so that the conversation history stays clean
        after the full replay sequence completes.
        """
        from agentscope.message import ToolUseBlock

        next_tc = remaining_queue[0]
        self._tool_guard_replay_queue = remaining_queue[1:]
        next_id = next_tc.get("id") or f"queued-{_uuid.uuid4().hex[:12]}"
        self._tool_guard_forced_replay_active = True
        msg = Msg(
            self.name,
            [
                ToolUseBlock(
                    type="tool_use",
                    id=next_id,
                    name=next_tc.get("name", "unknown"),
                    input=next_tc.get("input", {}),
                ),
            ],
            "assistant",
        )
        await self.print(msg, True)
        await self.memory.add(msg)
        return msg

    async def _emit_assistant_msg(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Msg:
        """Print and persist a plain assistant text message."""
        effective_metadata = metadata
        if effective_metadata is None:
            effective_metadata = getattr(
                self,
                "_tool_guard_pending_message_metadata",
                None,
            )
            if hasattr(self, "_tool_guard_pending_message_metadata"):
                self._tool_guard_pending_message_metadata = None
        msg = Msg(
            self.name,
            content,
            "assistant",
            metadata=effective_metadata,
        )
        await self.print(msg, True)
        await self.memory.add(msg)
        return msg

    async def _emit_forced_tool_use(
        self,
        forced_tool_call: dict[str, Any],
    ) -> Msg | None:
        """Emit a forced tool_use replay block, or ``None`` on failure."""
        try:
            from agentscope.message import ToolUseBlock

            self._tool_guard_forced_replay_active = True

            # Extract thinking blocks if present
            thinking_blocks = forced_tool_call.pop("_thinking_blocks", None)

            # Build content blocks
            content_blocks = []

            # Add thinking blocks first (if present)
            if thinking_blocks is not None and isinstance(
                thinking_blocks,
                list,
            ):
                content_blocks.extend(thinking_blocks)

            # Add tool use block
            content_blocks.append(
                ToolUseBlock(
                    type="tool_use",
                    id=forced_tool_call["id"],
                    name=forced_tool_call["name"],
                    input=forced_tool_call["input"],
                ),
            )

            msg = Msg(
                self.name,
                content_blocks,
                "assistant",
            )
            await self.print(msg, True)
            await self.memory.add(msg)
            return msg
        except Exception as exc:
            self._tool_guard_forced_replay_active = False
            logger.warning(
                "Tool guard: forced tool replay failed, "
                "falling back to normal reasoning: %s",
                exc,
                exc_info=True,
            )
            return None

    @staticmethod
    def _guardian_trigger_hint(guardians: list[str]) -> tuple[str, str]:
        """Return (trigger_label, settings_hint) for the guardian(s)."""
        has_file = "file_path_tool_guardian" in guardians
        has_tool = "rule_based_tool_guardian" in guardians
        if has_file and has_tool:
            label = "Tool Guard & File Guard / 工具护栏 & 文件护栏"
            hint_en = (
                "Triggered by tool guardrails "
                "(configurable in Security → Tool Guard / File Guard settings)"
            )
            hint_zh = "触发工具护栏 & 文件护栏（在安全-工具护栏 / 文件护栏页面可以更改设置）"
        elif has_file:
            label = "File Guard / 文件护栏"
            hint_en = (
                "Triggered by file guardrails "
                "(configurable in Security → File Guard settings)"
            )
            hint_zh = "触发文件护栏（在安全-文件护栏页面可以更改设置）"
        else:
            label = "Tool Guard / 工具护栏"
            hint_en = (
                "Triggered by tool guardrails "
                "(configurable in Security → Tool Guard settings)"
            )
            hint_zh = "触发工具护栏（在安全-工具护栏页面可以更改设置）"
        return label, f"💡 {hint_en}\n💡 {hint_zh}"

    async def _emit_waiting_for_approval(self) -> Msg:
        """Emit waiting-for-approval guidance when call is blocked."""
        pending = await self._get_pending_info_for_display()
        request_id = str(pending.get("request_id", "") or "")
        tool_name = pending.get("tool_name", "unknown")
        tool_input = pending.get("tool_input", {})
        guardians: list[str] = pending.get("guardians", [])
        params_text = _json.dumps(
            tool_input,
            ensure_ascii=False,
            indent=2,
        )
        trigger_label, _ = self._guardian_trigger_hint(guardians)
        metadata = {
            "approval_action": {
                "requestId": request_id,
                "toolName": tool_name,
                "toolInput": tool_input,
                "triggerLabel": trigger_label,
                "approveCommand": "/approve",
                "denyCommand": "/deny",
            },
        }
        if request_id:
            metadata["approval_action"][
                "approveCommand"
            ] = f"/approve {request_id}"
            metadata["approval_action"]["denyCommand"] = f"/deny {request_id}"
        self._tool_guard_pending_message_metadata = metadata
        return await self._emit_assistant_msg(
            f"⏳ `{tool_name}`调用需要审批\n" f"```json\n{params_text}\n```\n",
        )
