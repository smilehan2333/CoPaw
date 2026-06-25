# -*- coding: utf-8 -*-
"""技能可执行性 HTTP API。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .models import (
    SkillReadinessOverview,
    SkillReadinessResultsPage,
    SkillReadinessStartRunResponse,
)
from .service import (
    SkillReadinessConfigMissing,
    SkillReadinessConfigNotStartable,
    SkillReadinessRunNotFound,
    SkillReadinessService,
)
from .store import SkillReadinessStoreUnavailable

router = APIRouter(prefix="/skill-readiness", tags=["skill-readiness"])

MANAGER_ROLES = frozenset({"manager", "admin"})
_SKILL_ID_SAFE_CHARS = frozenset("_.:-")


@router.get(
    "/skills/{skill_id:path}/overview",
    response_model=SkillReadinessOverview,
)
async def get_skill_readiness_overview(
    skill_id: str,
    request: Request,
) -> SkillReadinessOverview:
    """读取当前 source 下某个技能的 owner 和最近检查概览。"""
    _require_manager(request)
    source_id = _get_source_id(request)
    skill_id = _validate_skill_id(skill_id)
    try:
        return await _get_service(request).get_overview(source_id, skill_id)
    except SkillReadinessStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Skill readiness storage unavailable",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Skill readiness data is invalid",
        ) from exc


@router.post(
    "/skills/{skill_id:path}/runs",
    response_model=SkillReadinessStartRunResponse,
)
async def start_skill_readiness_run(
    skill_id: str,
    request: Request,
) -> SkillReadinessStartRunResponse:
    """显式启动某个技能的全量 owner 可执行性检查。"""
    _require_manager(request)
    source_id = _get_source_id(request)
    skill_id = _validate_skill_id(skill_id)
    try:
        return await _get_service(request).start_run(source_id, skill_id)
    except SkillReadinessConfigMissing as exc:
        raise HTTPException(
            status_code=404,
            detail="Skill readiness config not found",
        ) from exc
    except SkillReadinessConfigNotStartable as exc:
        raise HTTPException(
            status_code=400,
            detail="Skill readiness config has no enabled checks",
        ) from exc
    except SkillReadinessStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Skill readiness storage unavailable",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Skill readiness data is invalid",
        ) from exc


@router.get(
    "/runs/{run_id}/results",
    response_model=SkillReadinessResultsPage,
)
async def get_skill_readiness_results(
    run_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Literal["all", "normal", "abnormal"] = "all",
    check_name: str | None = None,
    check_status: Literal["fail"] | None = None,
) -> SkillReadinessResultsPage:
    """读取某次运行的分页用户结果。"""
    _require_manager(request)
    source_id = _get_source_id(request)
    try:
        return await _get_service(request).get_results(
            run_id,
            source_id=source_id,
            page=page,
            page_size=page_size,
            status=status,
            check_name=check_name,
            check_status=check_status,
        )
    except SkillReadinessRunNotFound as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except SkillReadinessStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Skill readiness storage unavailable",
        ) from exc


def _get_service(request: Request) -> SkillReadinessService:
    service = getattr(request.app.state, "skill_readiness_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Skill readiness service unavailable",
        )
    return service


def _require_manager(request: Request) -> None:
    role = request.headers.get("X-User-Role", "").strip().lower()
    if role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Manager role required")


def _get_source_id(request: Request) -> str:
    _reject_source_query_override(request)
    source_id = (
        getattr(request.state, "source_id", None)
        or request.headers.get("X-Source-Id")
        or ""
    )
    source_id = source_id.strip() if isinstance(source_id, str) else ""
    if not source_id:
        raise HTTPException(status_code=400, detail="Source context missing")
    return source_id


def _reject_source_query_override(request: Request) -> None:
    if "source_id" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="source_id query override is not supported",
        )


def _validate_skill_id(skill_id: str) -> str:
    normalized = skill_id.strip() if isinstance(skill_id, str) else ""
    if not normalized or not all(_is_skill_id_char(ch) for ch in normalized):
        raise HTTPException(status_code=400, detail="Invalid skill_id format")
    return normalized


def _is_skill_id_char(value: str) -> bool:
    return value.isalnum() or value in _SKILL_ID_SAFE_CHARS
