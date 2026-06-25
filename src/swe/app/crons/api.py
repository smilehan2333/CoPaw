# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...config.context import (
    resolve_request_effective_tenant_id,
    resolve_runtime_tenant_id,
    resolve_scope_id,
    resolve_scope_preferred_tenant_id,
    resolve_storage_tenant_id,
)
from ...config.utils import list_logical_tenant_ids
from ...providers.provider_manager import ProviderManager
from ..identity_resolver import resolve_user_identity
from .broadcast import (
    DEFAULT_BROADCAST_OFFSET_WINDOW_HOURS,
    MAX_BROADCAST_OFFSET_WINDOW_HOURS,
    MIN_BROADCAST_OFFSET_WINDOW_HOURS,
    compute_broadcast_offsets,
    shift_cron_expression,
)
from .broadcast_children_store import (
    BroadcastChildrenLookupStatus,
    CronBroadcastChildrenSnapshot,
    CronBroadcastChildrenStore,
)
from .manager import CronManager
from .models import CronJobListItem, CronJobSpec, CronJobView

router = APIRouter(prefix="/cron", tags=["cron"])

BROADCAST_MODEL_SLOT_WARNING = (
    "model_slot not copied: provider/model unavailable in target tenant"
)
BROADCAST_CRON_FALLBACK_WARNING = (
    "cron offset not applied: unsupported cron, using original schedule"
)
BROADCAST_ORIGINAL_MODEL_SLOT_META_KEY = "broadcast_original_model_slot"
BROADCAST_MODEL_SLOT_FALLBACK_REASON_META_KEY = (
    "broadcast_model_slot_fallback_reason"
)
CHILD_RUN_SKIPPED_PAUSED_MESSAGE = "paused, not executed"
CHILD_NOT_FROM_SOURCE_MESSAGE = "child job does not belong to source job"
CRON_BROADCAST_CONCURRENCY_ENV = "CRON_BROADCAST_CONCURRENCY"
DEFAULT_CRON_BROADCAST_CONCURRENCY = 4

PRESERVED_CHILD_META_KEYS = (
    "task_chat_id",
    "task_session_id",
    "task_has_scheduled_result",
    "task_last_scheduled_preview",
    "task_unread_execution_count",
    "task_last_scheduled_run_at",
    "pause_reason",
    "auto_paused_at",
    "unread_count_at_pause",
)


def _positive_int_or_default(value: str | None, default: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _get_cron_broadcast_concurrency() -> int:
    return _positive_int_or_default(
        os.getenv(CRON_BROADCAST_CONCURRENCY_ENV),
        DEFAULT_CRON_BROADCAST_CONCURRENCY,
    )


class BroadcastTenantListResponse(BaseModel):
    tenant_ids: list[str] = Field(default_factory=list)


class CronBroadcastTarget(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    bbk_id: str | None = None


class CronBroadcastRequest(BaseModel):
    target_tenant_ids: list[str] = Field(default_factory=list)
    targets: list[CronBroadcastTarget] = Field(default_factory=list)
    enable_offset: bool = True
    offset_window_hours: int = Field(
        default=DEFAULT_BROADCAST_OFFSET_WINDOW_HOURS,
        ge=MIN_BROADCAST_OFFSET_WINDOW_HOURS,
        le=MAX_BROADCAST_OFFSET_WINDOW_HOURS,
    )


class CronBroadcastTenantResult(BaseModel):
    tenant_id: str
    success: bool
    job_id: str = ""
    cron: str = ""
    timezone: str = ""
    offset_minutes: int = 0
    notification_timezone: str = ""
    error: str = ""
    warning: str = ""


class CronBroadcastResponse(BaseModel):
    results: list[CronBroadcastTenantResult] = Field(default_factory=list)


class CronBroadcastChildItem(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    bbk_id: str | None = None
    job_id: str
    job_name: str = ""
    enabled: bool = False
    cron: str = ""
    timezone: str = ""
    offset_minutes: int = 0
    last_status: str | None = None
    last_run_at: str | None = None
    last_error: str | None = None


class CronBroadcastChildrenResponse(BaseModel):
    items: list[CronBroadcastChildItem] = Field(default_factory=list)
    status: BroadcastChildrenLookupStatus = "idle"
    tenant_count: int = 0
    failed_tenants: int = 0
    failure_summary: str | None = None
    updated_at: datetime | None = None


class CronBroadcastChildrenRefreshResponse(CronBroadcastChildrenResponse):
    reused: bool = False


class CronBroadcastChildRef(BaseModel):
    tenant_id: str
    job_id: str


class CronBroadcastChildrenBatchRequest(BaseModel):
    items: list[CronBroadcastChildRef] = Field(default_factory=list)


class CronBroadcastChildOperationResult(BaseModel):
    tenant_id: str
    job_id: str
    success: bool
    status: str
    message: str = ""


class CronBroadcastChildrenBatchResponse(BaseModel):
    results: list[CronBroadcastChildOperationResult] = Field(
        default_factory=list,
    )


@dataclass(frozen=True)
class _BroadcastContext:
    """保存一次广播请求内所有目标租户共享的执行上下文。"""

    source_job: CronJobSpec
    offsets: list[int]
    multi_agent_manager: Any
    tenant_workspace_pool: Any | None
    agent_id: str
    source_id: str | None
    timezone_name: str
    target_identity_by_tenant: dict[str, dict[str, str | None]]


@dataclass(frozen=True)
class _BroadcastSchedule:
    """保存目标租户最终使用的 cron 表达式和偏移信息。"""

    cron: str
    timezone: str
    offset_minutes: int
    warning: str


async def _resolve_broadcast_target_identity(
    tenant_id: str,
    source_id: str | None,
) -> tuple[str | None, str | None]:
    """解析广播目标租户的身份信息。"""
    resolved = await resolve_user_identity(
        tenant_id=tenant_id,
        source_id=source_id,
        user_name=None,
        bbk_id=None,
        allow_remote_lookup=False,
    )
    return resolved.user_name, resolved.bbk_id


async def get_cron_manager(
    request: Request,
) -> CronManager:
    """Get cron manager for the active agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    if workspace.cron_manager is None:
        raise HTTPException(
            status_code=500,
            detail="CronManager not initialized",
        )
    return workspace.cron_manager


def _inject_request_tenant(spec: CronJobSpec, request: Request) -> CronJobSpec:
    """确保定时任务租户字段跟随当前请求上下文。"""
    tenant_id = getattr(request.state, "tenant_id", None)
    bbk_id = getattr(request.state, "bbk_id", None)
    source_id = getattr(request.state, "source_id", None)
    scope_id = getattr(request.state, "scope_id", None)
    user_name = getattr(request.state, "user_name", None)
    return spec.model_copy(
        update={
            "tenant_id": tenant_id,
            "bbk_id": bbk_id,
            "source_id": source_id,
            "scope_id": scope_id,
            "tenant_name": user_name,
        },
    )


def _get_request_user_id(request: Request) -> str | None:
    state_user_id = getattr(request.state, "user_id", None)
    if state_user_id:
        return state_user_id
    return request.headers.get("X-User-Id")


def _inject_creator_user(
    spec: CronJobSpec,
    request: Request,
    existing: CronJobSpec | None = None,
) -> CronJobSpec:
    if spec.task_type not in {"agent", "text"}:
        return spec
    meta = dict(spec.meta or {})
    existing_creator = (
        (existing.meta or {}).get("creator_user_id") if existing else None
    )
    creator_user_id = (
        existing_creator
        or meta.get("creator_user_id")
        or _get_request_user_id(request)
    )
    if creator_user_id:
        meta["creator_user_id"] = creator_user_id
    return spec.model_copy(update={"meta": meta})


def _validate_cron_job_model_slot(
    request: Request,
    spec: CronJobSpec,
) -> None:
    if spec.task_type != "agent" or spec.model_slot is None:
        return
    tenant_id = resolve_request_effective_tenant_id(
        getattr(request.state, "tenant_id", None),
        getattr(request.state, "source_id", None),
        getattr(request.state, "scope_id", None),
    )
    manager_tenant_id = tenant_id or "default"
    manager = _get_provider_manager(manager_tenant_id)
    provider = manager.get_provider(spec.model_slot.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=(f"Provider '{spec.model_slot.provider_id}' not found."),
        )
    if not provider.has_model(spec.model_slot.model):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{spec.model_slot.model}' not found in provider "
                f"'{spec.model_slot.provider_id}'."
            ),
        )


def _get_provider_manager(manager_tenant_id: str):
    storage_tenant_id = resolve_storage_tenant_id(manager_tenant_id, None)
    ProviderManager.ensure_tenant_provider_storage(storage_tenant_id)
    return ProviderManager.get_instance(storage_tenant_id)


def _resolve_broadcast_model_slot(
    runtime_tenant_id: str,
    source_job: CronJobSpec,
):
    if source_job.model_slot is None:
        return None, "", ""
    manager = _get_provider_manager(runtime_tenant_id)
    provider = manager.get_provider(source_job.model_slot.provider_id)
    if provider is None:
        return (
            None,
            BROADCAST_MODEL_SLOT_WARNING,
            "provider_not_found",
        )
    if not provider.has_model(source_job.model_slot.model):
        return (
            None,
            BROADCAST_MODEL_SLOT_WARNING,
            "model_not_found",
        )
    return source_job.model_slot, "", ""


def _join_broadcast_warnings(*warnings: str) -> str:
    return "; ".join(item for item in warnings if item)


async def _ensure_task_binding_for_read(
    spec: CronJobSpec,
    request: Request,
    mgr: CronManager,
) -> CronJobSpec:
    if spec.task_type not in {"agent", "text"}:
        return spec

    meta = dict(spec.meta or {})
    has_binding = bool(
        meta.get("task_chat_id") and meta.get("task_session_id"),
    )
    has_creator = bool(meta.get("creator_user_id"))
    if has_binding and has_creator:
        return spec

    rebound = _inject_creator_user(spec, request, existing=spec)
    await mgr.create_or_replace_job(rebound)
    saved = await mgr.get_job(spec.id)
    return saved or rebound


def _serialize_state(state):
    if hasattr(state, "model_dump"):
        return state.model_dump(mode="json")
    return state


def _request_source_id(request: Request) -> str | None:
    return getattr(request.state, "source_id", None)


def _request_agent_id(request: Request) -> str:
    return getattr(request.state, "agent_id", None) or "default"


def _broadcast_children_key_parts(
    request: Request,
    source_job: CronJobSpec,
) -> dict[str, str]:
    return {
        "agent_id": _request_agent_id(request),
        "source_id": _request_source_id(request) or source_job.source_id or "",
        "tenant_id": (
            getattr(request.state, "tenant_id", None)
            or source_job.tenant_id
            or ""
        ),
        "job_id": source_job.id,
    }


def _broadcast_children_task_key(parts: dict[str, str]) -> str:
    return "|".join(
        [
            parts["agent_id"],
            parts["source_id"],
            parts["tenant_id"],
            parts["job_id"],
        ],
    )


def _get_broadcast_children_store(request: Request) -> CronBroadcastChildrenStore:
    store = getattr(
        request.app.state,
        "cron_broadcast_children_store",
        None,
    )
    if store is None:
        store = CronBroadcastChildrenStore()
        request.app.state.cron_broadcast_children_store = store
    return store


def _get_broadcast_children_tasks(
    request: Request,
) -> dict[str, asyncio.Task]:
    tasks = getattr(
        request.app.state,
        "cron_broadcast_children_tasks",
        None,
    )
    if tasks is None:
        tasks = {}
        request.app.state.cron_broadcast_children_tasks = tasks
    return tasks


async def _get_broadcast_children_snapshot_response(
    request: Request,
    source_job: CronJobSpec,
    *,
    status_fallback: BroadcastChildrenLookupStatus = "idle",
) -> CronBroadcastChildrenResponse:
    store = _get_broadcast_children_store(request)
    parts = _broadcast_children_key_parts(request, source_job)
    snapshot = await store.get_snapshot(**parts)
    if snapshot is None:
        return CronBroadcastChildrenResponse(status=status_fallback)
    return _snapshot_to_response(snapshot)


async def _schedule_broadcast_children_refresh(
    request: Request,
    source_job: CronJobSpec,
    context: _BroadcastContext,
    tenant_ids: list[str],
) -> tuple[CronBroadcastChildrenResponse, bool]:
    store = _get_broadcast_children_store(request)
    tasks = _get_broadcast_children_tasks(request)
    parts = _broadcast_children_key_parts(request, source_job)
    claimed = await store.mark_running(
        **parts,
        tenant_count=len(tenant_ids),
    )
    snapshot = await store.get_snapshot(**parts)
    response = _snapshot_to_response(snapshot) if snapshot else (
        CronBroadcastChildrenResponse(
            status="running",
            tenant_count=len(tenant_ids),
        )
    )
    if not claimed:
        return response, True

    task_key = _broadcast_children_task_key(parts)
    refresh_task = asyncio.create_task(
        _refresh_broadcast_children_snapshot(
            store,
            parts,
            context,
            tenant_ids,
        ),
        name=f"cron-broadcast-children-refresh-{context.source_job.id}",
    )
    tasks[task_key] = refresh_task
    refresh_task.add_done_callback(lambda _task: tasks.pop(task_key, None))
    return response, False


async def _refresh_broadcast_children_snapshot(
    store: CronBroadcastChildrenStore,
    parts: dict[str, str],
    context: _BroadcastContext,
    tenant_ids: list[str],
) -> None:
    try:
        items = await _list_broadcast_children_for_tenants(
            context,
            tenant_ids,
        )
        await store.record_completed(
            **parts,
            items=[
                item.model_dump(mode="json")
                for item in items
            ],
            tenant_count=len(tenant_ids),
            failed_tenants=0,
        )
    except Exception as exc:  # pylint: disable=broad-except
        await store.record_failed(
            **parts,
            tenant_count=len(tenant_ids),
            failure_summary=str(exc),
        )


def _snapshot_to_response(
    snapshot: CronBroadcastChildrenSnapshot,
) -> CronBroadcastChildrenResponse:
    items: list[CronBroadcastChildItem] = []
    for item in snapshot.items:
        try:
            items.append(CronBroadcastChildItem.model_validate(item))
        except Exception:
            continue
    return CronBroadcastChildrenResponse(
        items=items,
        status=snapshot.status,
        tenant_count=snapshot.tenant_count,
        failed_tenants=snapshot.failed_tenants,
        failure_summary=snapshot.failure_summary,
        updated_at=snapshot.updated_at,
    )


def _validate_target_tenant_id(tenant_id: str) -> str:
    value = str(tenant_id or "").strip()
    if not value:
        raise ValueError("tenant_id is required")
    if len(value) > 256:
        raise ValueError(f"Invalid tenant ID format: {value}")
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"Invalid tenant ID format: {value}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"Invalid tenant ID format: {value}")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_broadcast_job(
    source_job: CronJobSpec,
    *,
    job_id: str,
    target_tenant_id: str,
    target_tenant_name: str | None,
    target_bbk_id: str | None,
    source_id: str | None,
    cron: str,
    timezone_name: str,
    offset_minutes: int,
    model_slot,
    model_slot_fallback_reason: str,
    tenant_name: str | None = None,
    bbk_id: str | None = None,
) -> CronJobSpec:
    resolved_scope_id = None
    if not (target_tenant_id == "default" and source_id is not None):
        resolved_scope_id = resolve_scope_id(target_tenant_id, source_id)
    meta = dict(source_job.meta or {})
    for key in (
        *PRESERVED_CHILD_META_KEYS,
        "external_job_id",
        BROADCAST_ORIGINAL_MODEL_SLOT_META_KEY,
        BROADCAST_MODEL_SLOT_FALLBACK_REASON_META_KEY,
    ):
        meta.pop(key, None)
    meta.update(
        {
            "creator_user_id": target_tenant_id,
            "broadcast_source_job_id": source_job.id,
            "broadcast_source_job_name": source_job.name,
            "broadcast_source_tenant_id": source_job.tenant_id,
            "broadcast_source_tenant_name": source_job.tenant_name,
            "broadcast_source_bbk_id": source_job.bbk_id,
            "broadcast_original_cron": source_job.schedule.cron,
            "broadcast_original_timezone": source_job.schedule.timezone,
            "broadcast_offset_minutes": offset_minutes,
            "broadcast_notification_policy": "original_schedule",
        },
    )
    if source_job.model_slot is not None and model_slot is None:
        meta[BROADCAST_ORIGINAL_MODEL_SLOT_META_KEY] = (
            source_job.model_slot.model_dump(mode="json")
        )
        meta[BROADCAST_MODEL_SLOT_FALLBACK_REASON_META_KEY] = (
            model_slot_fallback_reason
        )

    request_spec = source_job.request
    if request_spec is not None:
        request_spec = request_spec.model_copy(
            update={
                "user_id": target_tenant_id,
                "session_id": f"cron-task:{job_id}",
            },
        )

    dispatch = source_job.dispatch.model_copy(
        update={
            "target": source_job.dispatch.target.model_copy(
                update={
                    "user_id": target_tenant_id,
                    "session_id": f"cron-task:{job_id}",
                },
            ),
        },
    )

    return source_job.model_copy(
        update={
            "id": job_id,
            "enabled": True,
            "tenant_id": target_tenant_id,
            "bbk_id": target_bbk_id,
            "source_id": source_id,
            "tenant_name": target_tenant_name,
            "scope_id": resolved_scope_id,
            "schedule": source_job.schedule.model_copy(
                update={
                    "cron": cron,
                    "timezone": timezone_name,
                },
            ),
            "request": request_spec,
            "model_slot": model_slot,
            "dispatch": dispatch,
            "meta": meta,
        },
    )


async def _find_existing_broadcast_child_job(
    mgr: CronManager,
    source_job_id: str,
) -> CronJobSpec | None:
    for job in await mgr.list_jobs():
        if (job.meta or {}).get("broadcast_source_job_id") == source_job_id:
            return job
    return None


def _normalize_broadcast_targets(
    body: CronBroadcastRequest,
) -> tuple[list[str], dict[str, dict[str, str | None]]]:
    if body.targets:
        raw_targets = body.targets
    else:
        raw_targets = [
            CronBroadcastTarget(tenant_id=tenant_id)
            for tenant_id in body.target_tenant_ids
        ]

    normalized_tenants: list[str] = []
    identity_by_tenant: dict[str, dict[str, str | None]] = {}
    seen: set[str] = set()
    try:
        for target in raw_targets:
            tenant_id = _validate_target_tenant_id(target.tenant_id)
            if tenant_id in seen:
                continue
            seen.add(tenant_id)
            normalized_tenants.append(tenant_id)
            identity_by_tenant[tenant_id] = {
                "tenant_name": _optional_text(target.tenant_name),
                "bbk_id": _optional_text(target.bbk_id),
            }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return normalized_tenants, identity_by_tenant


def _get_broadcast_multi_agent_manager(request: Request):
    multi_agent_manager = getattr(
        request.app.state,
        "multi_agent_manager",
        None,
    )
    if multi_agent_manager is None:
        raise HTTPException(
            status_code=500,
            detail="multi_agent_manager missing",
        )
    return multi_agent_manager


def _build_broadcast_context(
    request: Request,
    source_job: CronJobSpec,
    normalized_tenants: list[str],
    target_identity_by_tenant: dict[str, dict[str, str | None]],
    *,
    enable_offset: bool = True,
    offset_window_hours: int = DEFAULT_BROADCAST_OFFSET_WINDOW_HOURS,
) -> _BroadcastContext:
    source_id = _request_source_id(request)
    offsets = (
        compute_broadcast_offsets(
            len(normalized_tenants),
            window_hours=offset_window_hours,
        )
        if enable_offset
        else [0] * len(normalized_tenants)
    )
    return _BroadcastContext(
        source_job=source_job,
        offsets=offsets,
        multi_agent_manager=_get_broadcast_multi_agent_manager(request),
        tenant_workspace_pool=getattr(
            request.app.state,
            "tenant_workspace_pool",
            None,
        ),
        agent_id=_request_agent_id(request),
        source_id=source_id,
        timezone_name=source_job.schedule.timezone or "UTC",
        target_identity_by_tenant=target_identity_by_tenant,
    )


def _resolve_broadcast_schedule(
    source_job: CronJobSpec,
    timezone_name: str,
    offset: int,
) -> _BroadcastSchedule:
    if offset <= 0:
        return _BroadcastSchedule(
            cron=source_job.schedule.cron,
            timezone=timezone_name,
            offset_minutes=0,
            warning="",
        )
    shifted = shift_cron_expression(
        source_job.schedule.cron,
        timezone_name,
        offset_minutes=offset,
    )
    if shifted.error:
        return _BroadcastSchedule(
            cron=source_job.schedule.cron,
            timezone=timezone_name,
            offset_minutes=0,
            warning=BROADCAST_CRON_FALLBACK_WARNING,
        )
    return _BroadcastSchedule(
        cron=shifted.cron,
        timezone=shifted.timezone,
        offset_minutes=offset,
        warning="",
    )


async def _get_broadcast_target_cron_manager(
    context: _BroadcastContext,
    tenant_id: str,
    tenant_name: str | None = None,
    bbk_id: str | None = None,
) -> tuple[CronManager, str | None]:
    return await _get_target_cron_manager(
        context,
        tenant_id,
        bootstrap=True,
        tenant_name=tenant_name,
        bbk_id=bbk_id,
    )


async def _get_target_cron_manager(
    context: _BroadcastContext,
    tenant_id: str,
    *,
    bootstrap: bool,
    tenant_name: str | None = None,
    bbk_id: str | None = None,
) -> tuple[CronManager, str | None]:
    if bootstrap and context.tenant_workspace_pool is not None:
        await context.tenant_workspace_pool.ensure_bootstrap(
            tenant_id,
            source_id=context.source_id,
            tenant_name=tenant_name,
            bbk_id=bbk_id,
        )
    runtime_tenant_id = resolve_runtime_tenant_id(
        tenant_id,
        context.source_id,
    )
    workspace = await context.multi_agent_manager.get_agent(
        context.agent_id,
        tenant_id=runtime_tenant_id,
    )
    if workspace.cron_manager is None:
        raise RuntimeError("CronManager not initialized")
    return workspace.cron_manager, runtime_tenant_id


def _merge_existing_child_with_source(
    existing_child_job: CronJobSpec,
    source_child_job: CronJobSpec,
) -> CronJobSpec:
    preserved_meta = {
        key: (existing_child_job.meta or {}).get(key)
        for key in PRESERVED_CHILD_META_KEYS
        if key in (existing_child_job.meta or {})
    }
    merged_meta = {
        **(source_child_job.meta or {}),
        **preserved_meta,
    }

    request_spec = source_child_job.request
    if request_spec is not None and existing_child_job.request is not None:
        request_spec = request_spec.model_copy(
            update={
                "user_id": existing_child_job.request.user_id,
                "session_id": existing_child_job.request.session_id,
            },
        )

    dispatch = source_child_job.dispatch.model_copy(
        update={
            "target": existing_child_job.dispatch.target,
        },
    )

    return source_child_job.model_copy(
        update={
            "id": existing_child_job.id,
            "enabled": existing_child_job.enabled,
            "tenant_id": existing_child_job.tenant_id,
            "tenant_name": existing_child_job.tenant_name,
            "bbk_id": existing_child_job.bbk_id,
            "source_id": existing_child_job.source_id,
            "scope_id": existing_child_job.scope_id,
            "request": request_spec,
            "dispatch": dispatch,
            "meta": merged_meta,
        },
    )


async def _create_broadcast_child_job(
    context: _BroadcastContext,
    tenant_id: str,
    target_cron_manager: CronManager,
    runtime_tenant_id: str | None,
    schedule: _BroadcastSchedule,
    target_tenant_name: str | None,
    target_bbk_id: str | None,
) -> CronBroadcastTenantResult:
    target_job_id = str(uuid.uuid4())
    model_slot, warning, model_slot_fallback_reason = (
        _resolve_broadcast_model_slot(
            runtime_tenant_id or "default",
            context.source_job,
        )
    )
    target_job = _build_broadcast_job(
        context.source_job,
        job_id=target_job_id,
        target_tenant_id=tenant_id,
        target_tenant_name=target_tenant_name,
        target_bbk_id=target_bbk_id,
        source_id=context.source_id,
        cron=schedule.cron,
        timezone_name=schedule.timezone,
        offset_minutes=schedule.offset_minutes,
        model_slot=model_slot,
        model_slot_fallback_reason=model_slot_fallback_reason,
        tenant_name=target_tenant_name,
        bbk_id=target_bbk_id,
    )
    await target_cron_manager.create_or_replace_job(target_job)
    saved = await target_cron_manager.get_job(target_job_id)
    result_job = saved or target_job
    return CronBroadcastTenantResult(
        tenant_id=tenant_id,
        success=True,
        job_id=target_job_id,
        cron=result_job.schedule.cron,
        timezone=result_job.schedule.timezone,
        offset_minutes=schedule.offset_minutes,
        notification_timezone=context.timezone_name,
        warning=_join_broadcast_warnings(
            warning,
            schedule.warning,
        ),
    )


async def _refresh_existing_broadcast_child_job(
    context: _BroadcastContext,
    tenant_id: str,
    target_cron_manager: CronManager,
    runtime_tenant_id: str | None,
    schedule: _BroadcastSchedule,
    existing_child_job: CronJobSpec,
) -> CronBroadcastTenantResult:
    model_slot, warning, model_slot_fallback_reason = (
        _resolve_broadcast_model_slot(
            runtime_tenant_id or "default",
            context.source_job,
        )
    )
    source_child_job = _build_broadcast_job(
        context.source_job,
        job_id=existing_child_job.id,
        target_tenant_id=existing_child_job.tenant_id or tenant_id,
        target_tenant_name=existing_child_job.tenant_name,
        target_bbk_id=existing_child_job.bbk_id,
        source_id=existing_child_job.source_id or context.source_id,
        cron=schedule.cron,
        timezone_name=schedule.timezone,
        offset_minutes=schedule.offset_minutes,
        model_slot=model_slot,
        model_slot_fallback_reason=model_slot_fallback_reason,
        tenant_name=existing_child_job.tenant_name,
        bbk_id=existing_child_job.bbk_id,
    )
    refreshed_job = _merge_existing_child_with_source(
        existing_child_job,
        source_child_job,
    )
    await target_cron_manager.create_or_replace_job(refreshed_job)
    saved = await target_cron_manager.get_job(existing_child_job.id)
    result_job = saved or refreshed_job
    return CronBroadcastTenantResult(
        tenant_id=tenant_id,
        success=True,
        job_id=result_job.id,
        cron=result_job.schedule.cron,
        timezone=result_job.schedule.timezone,
        offset_minutes=schedule.offset_minutes,
        notification_timezone=context.timezone_name,
        warning=_join_broadcast_warnings(
            warning,
            schedule.warning,
        ),
    )


async def _broadcast_to_tenant(
    context: _BroadcastContext,
    tenant_id: str,
    offset: int,
) -> CronBroadcastTenantResult:
    schedule = _resolve_broadcast_schedule(
        context.source_job,
        context.timezone_name,
        offset,
    )
    target_identity = context.target_identity_by_tenant.get(tenant_id, {})
    target_tenant_name = _optional_text(target_identity.get("tenant_name"))
    target_bbk_id = _optional_text(target_identity.get("bbk_id"))
    if not target_tenant_name or not target_bbk_id:
        fallback_name, fallback_bbk_id = (
            await _resolve_broadcast_target_identity(
                tenant_id,
                context.source_id,
            )
        )
        target_tenant_name = target_tenant_name or fallback_name
        target_bbk_id = target_bbk_id or fallback_bbk_id
    try:
        target_cron_manager, runtime_tenant_id = (
            await _get_broadcast_target_cron_manager(
                context,
                tenant_id,
                tenant_name=target_tenant_name,
                bbk_id=target_bbk_id,
            )
        )
        existing_child_job = await _find_existing_broadcast_child_job(
            target_cron_manager,
            context.source_job.id,
        )
        if existing_child_job is not None:
            return await _refresh_existing_broadcast_child_job(
                context,
                tenant_id,
                target_cron_manager,
                runtime_tenant_id,
                schedule,
                existing_child_job,
            )
        return await _create_broadcast_child_job(
            context,
            tenant_id,
            target_cron_manager,
            runtime_tenant_id,
            schedule,
            target_tenant_name,
            target_bbk_id,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return CronBroadcastTenantResult(
            tenant_id=tenant_id,
            success=False,
            cron=schedule.cron,
            timezone=schedule.timezone,
            offset_minutes=schedule.offset_minutes,
            notification_timezone=context.timezone_name,
            error=repr(exc),
            warning=schedule.warning,
        )


async def _broadcast_to_tenants(
    context: _BroadcastContext,
    tenant_ids: list[str],
) -> list[CronBroadcastTenantResult]:
    semaphore = asyncio.Semaphore(_get_cron_broadcast_concurrency())

    async def _run(
        tenant_id: str,
        offset: int,
    ) -> CronBroadcastTenantResult:
        async with semaphore:
            return await _broadcast_to_tenant(context, tenant_id, offset)

    return list(
        await asyncio.gather(
            *[
                _run(tenant_id, offset)
                for tenant_id, offset in zip(tenant_ids, context.offsets)
            ],
        ),
    )


def _is_broadcast_child_of(
    job: CronJobSpec | None,
    source_job_id: str,
) -> bool:
    if job is None:
        return False
    return (job.meta or {}).get("broadcast_source_job_id") == source_job_id


def _build_broadcast_child_item(
    *,
    tenant_id: str,
    job: CronJobSpec,
    state: Any,
) -> CronBroadcastChildItem:
    state_payload = _serialize_state(state) or {}
    meta = job.meta or {}
    return CronBroadcastChildItem(
        tenant_id=tenant_id,
        tenant_name=job.tenant_name,
        bbk_id=job.bbk_id,
        job_id=job.id,
        job_name=job.name,
        enabled=job.enabled,
        cron=job.schedule.cron,
        timezone=job.schedule.timezone,
        offset_minutes=int(meta.get("broadcast_offset_minutes", 0) or 0),
        last_status=state_payload.get("last_status"),
        last_run_at=state_payload.get("last_run_at"),
        last_error=state_payload.get("last_error"),
    )


async def _get_source_job_or_404(
    mgr: CronManager,
    job_id: str,
) -> CronJobSpec:
    source_job = await mgr.get_job(job_id)
    if not source_job:
        raise HTTPException(status_code=404, detail="job not found")
    return source_job


async def _build_child_management_context(
    request: Request,
    source_job: CronJobSpec,
    tenant_ids: list[str],
) -> _BroadcastContext:
    return _build_broadcast_context(
        request,
        source_job,
        tenant_ids,
        {},
    )


async def _list_broadcast_children_for_tenant(
    context: _BroadcastContext,
    tenant_id: str,
) -> list[CronBroadcastChildItem]:
    try:
        target_cron_manager, _ = await _get_target_cron_manager(
            context,
            tenant_id,
            bootstrap=False,
        )
        items: list[CronBroadcastChildItem] = []
        for job in await target_cron_manager.list_jobs():
            if _is_broadcast_child_of(job, context.source_job.id):
                items.append(
                    _build_broadcast_child_item(
                        tenant_id=tenant_id,
                        job=job,
                        state=target_cron_manager.get_state(job.id),
                    ),
                )
        return items
    except Exception:
        return []


async def _list_broadcast_children_for_tenants(
    context: _BroadcastContext,
    tenant_ids: list[str],
) -> list[CronBroadcastChildItem]:
    semaphore = asyncio.Semaphore(_get_cron_broadcast_concurrency())

    async def _run(tenant_id: str) -> list[CronBroadcastChildItem]:
        async with semaphore:
            return await _list_broadcast_children_for_tenant(
                context,
                tenant_id,
            )

    batches = await asyncio.gather(
        *[_run(tenant_id) for tenant_id in tenant_ids],
    )
    return [item for batch in batches for item in batch]


async def _list_source_tenant_ids(request: Request) -> list[str]:
    return await list_logical_tenant_ids(
        _request_source_id(request),
        source_filter=True,
    )


def _failure_result(
    item: CronBroadcastChildRef,
    message: str,
) -> CronBroadcastChildOperationResult:
    return CronBroadcastChildOperationResult(
        tenant_id=item.tenant_id,
        job_id=item.job_id,
        success=False,
        status="failed",
        message=message,
    )


async def _get_batch_child_job(
    context: _BroadcastContext,
    item: CronBroadcastChildRef,
) -> tuple[CronManager, CronJobSpec] | CronBroadcastChildOperationResult:
    try:
        tenant_id = _validate_target_tenant_id(item.tenant_id)
        job_id = str(item.job_id or "").strip()
        if not job_id:
            return _failure_result(item, "job_id is required")
        target_cron_manager, _ = await _get_target_cron_manager(
            context,
            tenant_id,
            bootstrap=False,
        )
        child_job = await target_cron_manager.get_job(job_id)
        if child_job is None:
            return _failure_result(item, "child job not found")
        if not _is_broadcast_child_of(child_job, context.source_job.id):
            return _failure_result(item, CHILD_NOT_FROM_SOURCE_MESSAGE)
        return target_cron_manager, child_job
    except Exception as exc:  # pylint: disable=broad-except
        return _failure_result(item, str(exc))


@router.get("/jobs", response_model=list[CronJobListItem])
async def list_jobs(
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    user_id = _get_request_user_id(request)
    jobs = [
        await _ensure_task_binding_for_read(job, request, mgr)
        for job in await mgr.list_jobs()
    ]
    # 实时刷新每个 job 的 next_run_at（原依赖 APScheduler，现按需计算）
    for job in jobs:
        await mgr.refresh_next_run_at(job)
    return [
        CronJobListItem(
            **job.model_dump(mode="json"),
            state=_serialize_state(mgr.get_state(job.id)),
            task=mgr.build_task_view(job, user_id),
        )
        for job in jobs
    ]


@router.get(
    "/broadcast/tenants",
    response_model=BroadcastTenantListResponse,
)
async def list_broadcast_tenants(
    request: Request,
) -> BroadcastTenantListResponse:
    """获取可广播定时任务的目标租户。"""
    return BroadcastTenantListResponse(
        tenant_ids=await list_logical_tenant_ids(
            _request_source_id(request),
            source_filter=True,
            include_templates=True,
        ),
    )


@router.post(
    "/jobs/{job_id}/broadcast",
    response_model=CronBroadcastResponse,
)
async def broadcast_job(
    request: Request,
    job_id: str,
    body: CronBroadcastRequest,
    mgr: CronManager = Depends(get_cron_manager),
) -> CronBroadcastResponse:
    """将当前定时任务广播到多个租户。"""
    source_job = await mgr.get_job(job_id)
    if not source_job:
        raise HTTPException(status_code=404, detail="job not found")
    if not body.target_tenant_ids and not body.targets:
        raise HTTPException(
            status_code=400,
            detail="No target tenant IDs provided",
        )

    normalized_tenants, target_identity_by_tenant = (
        _normalize_broadcast_targets(
            body,
        )
    )
    context = _build_broadcast_context(
        request,
        source_job,
        normalized_tenants,
        target_identity_by_tenant,
        enable_offset=body.enable_offset,
        offset_window_hours=body.offset_window_hours,
    )
    results = await _broadcast_to_tenants(context, normalized_tenants)
    return CronBroadcastResponse(results=results)


@router.get(
    "/jobs/{job_id}/broadcast/children",
    response_model=CronBroadcastChildrenResponse,
)
async def list_broadcast_children(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
) -> CronBroadcastChildrenResponse:
    source_job = await _get_source_job_or_404(mgr, job_id)
    return await _get_broadcast_children_snapshot_response(
        request,
        source_job,
    )


@router.post(
    "/jobs/{job_id}/broadcast/children/refresh",
    response_model=CronBroadcastChildrenRefreshResponse,
)
async def refresh_broadcast_children(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
) -> CronBroadcastChildrenRefreshResponse:
    source_job = await _get_source_job_or_404(mgr, job_id)
    tenant_ids = await _list_source_tenant_ids(request)
    context = await _build_child_management_context(
        request,
        source_job,
        tenant_ids,
    )
    snapshot, reused = await _schedule_broadcast_children_refresh(
        request,
        source_job,
        context,
        tenant_ids,
    )
    return CronBroadcastChildrenRefreshResponse(
        **snapshot.model_dump(),
        reused=reused,
    )


@router.post(
    "/jobs/{job_id}/broadcast/children/delete",
    response_model=CronBroadcastChildrenBatchResponse,
)
async def delete_broadcast_children(
    request: Request,
    job_id: str,
    body: CronBroadcastChildrenBatchRequest,
    mgr: CronManager = Depends(get_cron_manager),
) -> CronBroadcastChildrenBatchResponse:
    source_job = await _get_source_job_or_404(mgr, job_id)
    context = await _build_child_management_context(
        request,
        source_job,
        [item.tenant_id for item in body.items],
    )
    results: list[CronBroadcastChildOperationResult] = []
    for item in body.items:
        resolved = await _get_batch_child_job(context, item)
        if isinstance(resolved, CronBroadcastChildOperationResult):
            results.append(resolved)
            continue
        target_cron_manager, child_job = resolved
        deleted = await target_cron_manager.delete_job(child_job.id)
        results.append(
            CronBroadcastChildOperationResult(
                tenant_id=item.tenant_id,
                job_id=child_job.id,
                success=bool(deleted),
                status="deleted" if deleted else "failed",
                message="" if deleted else "delete failed",
            ),
        )
    return CronBroadcastChildrenBatchResponse(results=results)


@router.post(
    "/jobs/{job_id}/broadcast/children/run",
    response_model=CronBroadcastChildrenBatchResponse,
)
async def run_broadcast_children(
    request: Request,
    job_id: str,
    body: CronBroadcastChildrenBatchRequest,
    mgr: CronManager = Depends(get_cron_manager),
) -> CronBroadcastChildrenBatchResponse:
    source_job = await _get_source_job_or_404(mgr, job_id)
    context = await _build_child_management_context(
        request,
        source_job,
        [item.tenant_id for item in body.items],
    )
    results: list[CronBroadcastChildOperationResult] = []
    for item in body.items:
        resolved = await _get_batch_child_job(context, item)
        if isinstance(resolved, CronBroadcastChildOperationResult):
            results.append(resolved)
            continue
        target_cron_manager, child_job = resolved
        if not child_job.enabled or (child_job.meta or {}).get("pause_reason"):
            results.append(
                CronBroadcastChildOperationResult(
                    tenant_id=item.tenant_id,
                    job_id=child_job.id,
                    success=True,
                    status="skipped",
                    message=CHILD_RUN_SKIPPED_PAUSED_MESSAGE,
                ),
            )
            continue
        try:
            await target_cron_manager.run_job(child_job.id)
            results.append(
                CronBroadcastChildOperationResult(
                    tenant_id=item.tenant_id,
                    job_id=child_job.id,
                    success=True,
                    status="started",
                ),
            )
        except Exception as exc:  # pylint: disable=broad-except
            results.append(_failure_result(item, str(exc)))
    return CronBroadcastChildrenBatchResponse(results=results)


@router.get("/jobs/{job_id}", response_model=CronJobView)
async def get_job(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job = await _ensure_task_binding_for_read(job, request, mgr)
    await mgr.refresh_next_run_at(job)
    return CronJobView(
        spec=job,
        state=_serialize_state(mgr.get_state(job_id)),
        task=mgr.build_task_view(job, _get_request_user_id(request)),
    )


@router.post("/jobs", response_model=CronJobSpec)
async def create_job(
    request: Request,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
):
    # server generates id; ignore client-provided spec.id
    job_id = str(uuid.uuid4())
    created = spec.model_copy(update={"id": job_id})
    created = _inject_request_tenant(created, request)
    created = _inject_creator_user(created, request)
    _validate_cron_job_model_slot(request, created)
    await mgr.create_or_replace_job(created)
    saved = await mgr.get_job(job_id)
    return saved or created


@router.put("/jobs/{job_id}", response_model=CronJobSpec)
async def replace_job(
    request: Request,
    job_id: str,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
):
    if spec.id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    existing = await mgr.get_job(job_id)
    spec = _inject_request_tenant(spec, request)
    spec = _inject_creator_user(spec, request, existing=existing)
    _validate_cron_job_model_slot(request, spec)
    await mgr.create_or_replace_job(spec)
    saved = await mgr.get_job(job_id)
    return saved or spec


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    ok = await mgr.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": True}


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, mgr: CronManager = Depends(get_cron_manager)):
    ok = await mgr.pause_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"paused": True}


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    ok = await mgr.resume_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"resumed": True}


@router.post("/jobs/{job_id}/run")
async def run_job(job_id: str, mgr: CronManager = Depends(get_cron_manager)):
    try:
        await mgr.run_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    # Note: run_job is a manual execution, not a schedule mutation
    # No reload signal needed
    return {"started": True}


@router.get("/jobs/{job_id}/state")
async def get_job_state(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return mgr.get_state(job_id).model_dump(mode="json")


@router.post("/jobs/{job_id}/task/mark-read")
async def mark_task_read(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    user_id = _get_request_user_id(request)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id missing")
    ok = await mgr.mark_task_read(job_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="task job not found")
    return {"marked_read": True}
