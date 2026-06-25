# -*- coding: utf-8 -*-
"""技能可执行性应用服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import (
    OwnerLookupStatus,
    SkillReadinessConfig,
    SkillReadinessConfigCheckSummary,
    SkillReadinessOverview,
    SkillReadinessOwnerSnapshot,
    SkillReadinessOwnerSummary,
    SkillReadinessResultsPage,
    SkillReadinessRunProgress,
    SkillReadinessRunSummary,
    SkillReadinessStartRunResponse,
)
from .owner_resolver import SkillOwnerResolver
from .runner import SkillReadinessRunner
from .store import SkillReadinessStore
from .strategies import SkillReadinessStrategyRegistry


class SkillReadinessConfigMissing(ValueError):
    """技能没有配置自检项。"""


class SkillReadinessConfigNotStartable(ValueError):
    """技能自检配置存在但没有启用项。"""


class SkillReadinessRunNotFound(ValueError):
    """运行记录不存在。"""


class SkillReadinessService:
    """组合存储、owner 查询和运行器的业务服务。"""

    def __init__(
        self,
        store: SkillReadinessStore,
        registry: SkillReadinessStrategyRegistry,
        runner: SkillReadinessRunner,
    ):
        self.store = store
        self.registry = registry
        self.runner = runner

    async def get_overview(
        self,
        source_id: str,
        skill_id: str,
    ) -> SkillReadinessOverview:
        config_record = await self.store.get_config(skill_id)
        owner_snapshot = await self.store.get_owner_snapshot(source_id, skill_id)
        latest_run = await self.store.get_latest_run(source_id, skill_id)
        latest_summary = await self._build_run_summary(latest_run)

        config = config_record.config if config_record else None
        owner_summary = (
            owner_snapshot.owner_summary
            if owner_snapshot is not None
            else SkillReadinessOwnerSummary()
        )
        return SkillReadinessOverview(
            skill_id=skill_id,
            config_found=config is not None,
            startable=bool(config and config.is_startable),
            config_message=_config_message(config),
            config_checks=self._config_check_summaries(config),
            owner_summary=owner_summary,
            owners=owner_snapshot.owners if owner_snapshot is not None else [],
            owner_lookup_status=_owner_lookup_status(
                owner_snapshot,
                latest_summary,
            ),
            owner_lookup_updated_at=_owner_snapshot_data_time(owner_snapshot),
            latest_run=latest_summary,
        )

    async def start_run(
        self,
        source_id: str,
        skill_id: str,
    ) -> SkillReadinessStartRunResponse:
        config_record = await self.store.get_config(skill_id)
        if config_record is None:
            return self._start_owner_lookup_only(source_id, skill_id)
        config = config_record.config
        if not config.is_startable:
            return self._start_owner_lookup_only(source_id, skill_id)

        run, reused = await self.store.get_or_create_running_run(
            source_id,
            skill_id,
            config,
        )
        if reused:
            return SkillReadinessStartRunResponse(run=run, reused=True)

        self.runner.schedule(
            run_id=run.run_id,
            source_id=source_id,
            skill_id=skill_id,
            config=config,
        )
        return SkillReadinessStartRunResponse(run=run, reused=False)

    def _start_owner_lookup_only(
        self,
        source_id: str,
        skill_id: str,
    ) -> SkillReadinessStartRunResponse:
        task = self.runner.schedule_owner_refresh(
            source_id=source_id,
            skill_id=skill_id,
        )
        return SkillReadinessStartRunResponse(
            owner_lookup_only=True,
            owner_lookup_scheduled=task is not None,
        )

    async def get_results(
        self,
        run_id: str,
        *,
        source_id: str,
        page: int = 1,
        page_size: int = 20,
        status: str = "all",
        check_name: str | None = None,
        check_status: str | None = None,
    ) -> SkillReadinessResultsPage:
        run = await self.store.get_run(run_id)
        if run is None:
            raise SkillReadinessRunNotFound(run_id)
        if run.source_id != source_id:
            raise SkillReadinessRunNotFound(run_id)
        items, total = await self.store.list_user_results(
            run_id,
            page=page,
            page_size=page_size,
            status=status,
            check_name=check_name,
            check_status=check_status,
        )
        return SkillReadinessResultsPage(
            run=run,
            items=items,
            total=total,
            page=max(page, 1),
            page_size=min(max(page_size, 1), 100),
        )

    def _config_check_summaries(
        self,
        config: SkillReadinessConfig | None,
    ) -> list[SkillReadinessConfigCheckSummary]:
        if config is None:
            return []
        return [
            SkillReadinessConfigCheckSummary(
                name=check.name,
                display_name=self.registry.display_name_for(check.name),
                enabled=check.enabled,
                params=check.params,
            )
            for check in config.checks
        ]

    async def _build_run_summary(
        self,
        run: SkillReadinessRunProgress | None,
    ) -> SkillReadinessRunSummary | None:
        if run is None:
            return None
        return SkillReadinessRunSummary(
            **run.model_dump(),
            check_summaries=await self.store.get_check_summaries(run.run_id),
        )


def _config_message(config: SkillReadinessConfig | None) -> str:
    if config is None:
        return "未查询到自检配置"
    if not config.is_startable:
        return "自检配置没有启用的检查项"
    return "已查询到自检配置"


def _owner_snapshot_data_time(
    owner_snapshot: SkillReadinessOwnerSnapshot | None,
) -> datetime | None:
    if owner_snapshot is None:
        return None
    if owner_snapshot.status != "running":
        return owner_snapshot.updated_at
    if (
        owner_snapshot.total_users
        or owner_snapshot.owners
        or owner_snapshot.failed_users
    ):
        return owner_snapshot.updated_at
    return None


def _owner_lookup_status(
    owner_snapshot: SkillReadinessOwnerSnapshot | None,
    latest_run: SkillReadinessRunSummary | None,
) -> OwnerLookupStatus:
    if owner_snapshot is not None:
        return owner_snapshot.status
    if latest_run is not None and latest_run.status == "running":
        return "running"
    return "idle"


def build_skill_readiness_service(
    store: SkillReadinessStore,
    *,
    multi_agent_manager: Any | None = None,
) -> SkillReadinessService:
    """构造默认技能可执行性服务。"""
    from .strategies import build_default_strategy_registry

    registry = build_default_strategy_registry()
    owner_resolver = SkillOwnerResolver()
    runner = SkillReadinessRunner(
        store,
        registry,
        owner_resolver=owner_resolver,
        multi_agent_manager=multi_agent_manager,
    )
    return SkillReadinessService(
        store=store,
        registry=registry,
        runner=runner,
    )
