# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from .conversation_snapshot import build_handler_conversation_snapshot
from .executor import execute_handler
from .merge import merge_hook_results
from .models import (
    EffectiveHookPlan,
    HookDecision,
    HookHandlerResult,
    HookConfig,
    HookContext,
    HookSessionOverlay,
    MergedHookResult,
)
from .resolver import HookResolver, once_key
from swe.tracing.sanitizer import sanitize_string

logger = logging.getLogger(__name__)

_TELEMETRY_PREFIX = "HOOK_TELEMETRY "
_TELEMETRY_SCHEMA = "hook_telemetry.v1"
_PREVIEW_MAX_LENGTH = 500


class HookRuntime:
    """Event-boundary resolver and concurrent handler executor."""

    def __init__(
        self,
        *,
        tenant_config: HookConfig | None = None,
        agent_config: HookConfig | None = None,
        session_overlay: HookSessionOverlay | None = None,
    ) -> None:
        self.tenant_config = tenant_config or HookConfig()
        self.agent_config = agent_config or HookConfig()
        self.session_overlay = session_overlay or HookSessionOverlay()

    async def emit(
        self,
        context: HookContext,
        *,
        workspace_dir: Path,
        conversation_snapshot_provider: (
            Callable[[], Awaitable[dict[str, Any] | None]] | None
        ) = None,
    ) -> MergedHookResult:
        started_at = time.perf_counter()
        plan = HookResolver(
            tenant_config=self.tenant_config,
            agent_config=self.agent_config,
            session_overlay=self.session_overlay,
        ).resolve_event_plan(context)
        if not plan.handlers:
            return merge_hook_results(plan, [])
        conversation_snapshot = await self._capture_conversation_snapshot(
            plan,
            conversation_snapshot_provider,
        )

        async def _run(item):
            handler_started_at = time.perf_counter()
            handler_context = self._context_for_handler(
                context,
                item.handler,
                conversation_snapshot,
            )
            result = await execute_handler(
                item.handler,
                handler_context,
                workspace_dir=workspace_dir,
            )
            result.order = item.order
            return result, _duration_ms(handler_started_at)

        executed = await asyncio.gather(
            *(_run(item) for item in plan.handlers),
        )
        results = [item[0] for item in executed]
        handler_durations = {
            result.order: duration_ms for result, duration_ms in executed
        }
        self._mark_once_executed(context, plan.handlers)
        merged = merge_hook_results(plan, results)
        try:
            _log_hook_telemetry(
                plan,
                results,
                handler_durations,
                merged,
                duration_ms=_duration_ms(started_at),
            )
        except Exception as exc:
            logger.warning("Failed to emit hook telemetry: %s", exc)
        return merged

    async def _capture_conversation_snapshot(
        self,
        plan: EffectiveHookPlan,
        provider: Callable[[], Awaitable[dict[str, Any] | None]] | None,
    ) -> dict[str, Any] | None:
        if not any(
            item.handler.include_conversation_snapshot
            for item in plan.handlers
        ):
            return None
        if provider is None:
            return None
        try:
            return await provider()
        except Exception as exc:
            logger.warning(
                "Failed to capture hook conversation snapshot: %s",
                exc,
            )
            return None

    @staticmethod
    def _context_for_handler(
        context: HookContext,
        handler,
        conversation_snapshot: dict[str, Any] | None,
    ) -> HookContext:
        if not handler.include_conversation_snapshot:
            return context
        snapshot_payload = build_handler_conversation_snapshot(
            conversation_snapshot,
            limit=handler.conversation_snapshot_limit,
        )
        return context.model_copy(update=snapshot_payload)

    def _mark_once_executed(self, context: HookContext, handlers) -> None:
        for item in handlers:
            if not item.handler.once:
                continue
            self.session_overlay.once_executed[
                once_key(
                    context.effective_tenant_id,
                    context.user_id,
                    context.session_id,
                    str(
                        getattr(
                            context.hook_event_name,
                            "value",
                            context.hook_event_name,
                        ),
                    ),
                    item.handler.id,
                )
            ] = True


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _preview(value: Any) -> str:
    if value is None:
        return ""
    return sanitize_string(str(value), _PREVIEW_MAX_LENGTH) or ""


def _event_name_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _handler_ids_with_specific_key(
    results: list[HookHandlerResult],
    key: str,
) -> list[str]:
    ids: list[str] = []
    for result in sorted(results, key=lambda item: item.order):
        specific = result.output.hook_specific_output or {}
        if specific.get(key) is not None:
            ids.append(result.handler_id)
    return ids


def _handler_ids_with_system_messages(
    results: list[HookHandlerResult],
) -> list[str]:
    return [
        result.handler_id
        for result in sorted(results, key=lambda item: item.order)
        if result.output.system_message
    ]


def _permission_decisions_payload(
    merged: MergedHookResult,
) -> list[dict[str, str]]:
    return [
        {
            "handler_id": item.handler_id,
            "decision": _event_name_value(item.decision),
            "reason_preview": _preview(item.reason),
        }
        for item in merged.permission_decisions
    ]


def _handlers_payload(
    plan: EffectiveHookPlan,
    results: list[HookHandlerResult],
    handler_durations: dict[int, int],
) -> list[dict[str, Any]]:
    result_by_order = {result.order: result for result in results}
    handlers: list[dict[str, Any]] = []
    for item in plan.handlers:
        result = result_by_order.get(item.order)
        handlers.append(
            {
                "handler_id": item.handler.id,
                "group_id": item.group_id,
                "type": item.handler.type,
                "order": item.order,
                "duration_ms": handler_durations.get(item.order, 0),
                "decision": (
                    _event_name_value(result.decision)
                    if result is not None
                    else _event_name_value(HookDecision.NONE)
                ),
                "failed": bool(result.failed) if result is not None else False,
                "failure_type": (
                    result.failure_type if result is not None else ""
                ),
                "reason_preview": (
                    _preview(result.reason) if result is not None else ""
                ),
            },
        )
    return handlers


def _log_hook_telemetry(
    plan: EffectiveHookPlan,
    results: list[HookHandlerResult],
    handler_durations: dict[int, int],
    merged: MergedHookResult,
    *,
    duration_ms: int,
) -> None:
    if not plan.handlers:
        return

    context_payload = plan.context.to_handler_payload()
    updated_input_handler_ids = _handler_ids_with_specific_key(
        results,
        "updatedInput",
    )
    additional_context_handler_ids = _handler_ids_with_specific_key(
        results,
        "additionalContext",
    )
    system_message_handler_ids = _handler_ids_with_system_messages(results)
    payload = {
        "schema": _TELEMETRY_SCHEMA,
        "hook_event_name": _event_name_value(plan.event_name),
        "trace_id": context_payload.get("trace_id"),
        "tenant_id": context_payload.get("tenant_id"),
        "effective_tenant_id": context_payload.get("effective_tenant_id"),
        "source_id": context_payload.get("source_id"),
        "user_id": context_payload.get("user_id"),
        "session_id": context_payload.get("session_id"),
        "chat_id": context_payload.get("chat_id"),
        "turn_id": context_payload.get("turn_id"),
        "agent_id": context_payload.get("agent_id"),
        "channel": context_payload.get("channel"),
        "tool_name": context_payload.get("tool_name"),
        "tool_use_id": context_payload.get("tool_use_id"),
        "handler_count": len(plan.handlers),
        "duration_ms": duration_ms,
        "decision": _event_name_value(merged.decision),
        "blocked": merged.blocked,
        "reason_preview": _preview(merged.reason),
        "has_updated_input": bool(updated_input_handler_ids),
        "updated_input_handler_ids": updated_input_handler_ids,
        "has_additional_context": bool(additional_context_handler_ids),
        "additional_context_handler_ids": additional_context_handler_ids,
        "has_system_messages": bool(system_message_handler_ids),
        "system_message_handler_ids": system_message_handler_ids,
        "permission_decisions": _permission_decisions_payload(merged),
        "handlers": _handlers_payload(plan, results, handler_durations),
    }
    logger.info(
        "%s%s",
        _TELEMETRY_PREFIX,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
