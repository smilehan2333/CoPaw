# -*- coding: utf-8 -*-
"""技能可执行性服务测试。"""

from __future__ import annotations

from datetime import datetime

import pytest

from swe.app.skill_readiness.models import (
    SkillReadinessConfig,
    SkillReadinessConfigRecord,
    SkillReadinessOwner,
    SkillReadinessOwnerSnapshot,
    SkillReadinessRunProgress,
)
from swe.app.skill_readiness.service import (
    SkillReadinessRunNotFound,
    SkillReadinessService,
)
from swe.app.skill_readiness.strategies import build_default_strategy_registry


class _Store:
    def __init__(self):
        self.config = SkillReadinessConfigRecord(
            skill_id="skill-a",
            config=SkillReadinessConfig.model_validate(
                {
                    "checks": [
                        {
                            "name": "cron_auth_valid",
                            "params": {"required": True},
                        },
                    ],
                },
            ),
            updated_at=datetime.now(),
        )
        self.running = None
        self.created = []
        self.latest = None
        self.owner_snapshot = None
        self.list_args = []
        self.get_or_create_calls = []

    async def get_config(self, skill_id):
        if skill_id == "missing":
            return None
        return self.config

    async def get_latest_run(self, source_id, skill_id):
        return self.latest

    async def get_owner_snapshot(self, source_id, skill_id):
        return self.owner_snapshot

    async def get_check_summaries(self, run_id):
        return []

    async def get_running_run(self, source_id, skill_id):
        return self.running

    async def create_run(self, source_id, skill_id, config):
        run = SkillReadinessRunProgress(
            run_id="run-created",
            source_id=source_id,
            skill_id=skill_id,
            status="running",
        )
        self.created.append(run)
        return run

    async def get_or_create_running_run(
        self,
        source_id,
        skill_id,
        config,
    ):
        self.get_or_create_calls.append(
            (source_id, skill_id, config),
        )
        if self.running is not None:
            return self.running, True
        return await self.create_run(
            source_id,
            skill_id,
            config,
        ), False

    async def update_run_progress(self, run_id, **kwargs):
        return SkillReadinessRunProgress(
            run_id=run_id,
            source_id="source-a",
            skill_id="skill-a",
            status=kwargs.get("status") or "running",
            total_users=kwargs.get("total_users") or 0,
            failure_summary=kwargs.get("failure_summary"),
        )

    async def get_run(self, run_id):
        return SkillReadinessRunProgress(
            run_id=run_id,
            source_id="source-a",
            skill_id="skill-a",
            status="completed",
        )

    async def list_user_results(self, *args, **kwargs):
        self.list_args.append((args, kwargs))
        return [], 0


class _Runner:
    def __init__(self):
        self.scheduled = []
        self.owner_refreshes = []

    def schedule(self, **kwargs):
        self.scheduled.append(kwargs)

    def schedule_owner_refresh(self, **kwargs):
        self.owner_refreshes.append(kwargs)
        return object()


def _service(store=None, runner=None):
    return SkillReadinessService(
        store=store or _Store(),
        registry=build_default_strategy_registry(),
        runner=runner or _Runner(),
    )


@pytest.mark.asyncio
async def test_overview_reports_config_owner_and_latest_summary():
    store = _Store()
    runner = _Runner()
    updated_at = datetime(2026, 6, 24, 10, 30)
    store.owner_snapshot = SkillReadinessOwnerSnapshot(
        source_id="source-a",
        skill_id="skill-a",
        status="completed",
        total_users=2,
        owner_users=1,
        failed_users=1,
        failure_summary="bob: market down",
        owners=[SkillReadinessOwner(user_id="alice")],
        updated_at=updated_at,
    )

    result = await _service(store=store, runner=runner).get_overview(
        "source-a",
        "skill-a",
    )

    assert result.config_found is True
    assert result.startable is True
    assert result.config_checks[0].display_name == "定时任务鉴权"
    assert result.config_checks[0].params == {"required": True}
    assert result.owner_summary.lookup_failed_users == 1
    assert [owner.user_id for owner in result.owners] == ["alice"]
    assert result.owner_lookup_status == "completed"
    assert result.owner_lookup_updated_at == updated_at
    assert runner.owner_refreshes == []


@pytest.mark.asyncio
async def test_overview_without_snapshot_reports_idle_before_run_starts():
    runner = _Runner()

    result = await _service(runner=runner).get_overview("source-a", "skill-a")

    assert result.owner_lookup_status == "idle"
    assert result.owner_lookup_updated_at is None
    assert result.owner_summary.total_users == 0
    assert result.owners == []
    assert runner.owner_refreshes == []


@pytest.mark.asyncio
async def test_overview_without_snapshot_reports_running_while_run_is_running():
    store = _Store()
    store.latest = SkillReadinessRunProgress(
        run_id="run-1",
        source_id="source-a",
        skill_id="skill-a",
        status="running",
    )

    result = await _service(store=store).get_overview("source-a", "skill-a")

    assert result.owner_lookup_status == "running"
    assert result.owner_lookup_updated_at is None
    assert result.owners == []


@pytest.mark.asyncio
async def test_overview_running_placeholder_has_no_owner_data_time():
    store = _Store()
    store.owner_snapshot = SkillReadinessOwnerSnapshot(
        source_id="source-a",
        skill_id="skill-a",
        status="running",
        updated_at=datetime(2026, 6, 24, 10, 30),
    )

    result = await _service(store=store).get_overview("source-a", "skill-a")

    assert result.owner_lookup_status == "running"
    assert result.owner_lookup_updated_at is None


@pytest.mark.asyncio
async def test_start_run_refreshes_owners_when_config_missing():
    runner = _Runner()

    response = await _service(runner=runner).start_run("source-a", "missing")

    assert response.run is None
    assert response.owner_lookup_only is True
    assert response.owner_lookup_scheduled is True
    assert runner.owner_refreshes == [
        {"source_id": "source-a", "skill_id": "missing"},
    ]


@pytest.mark.asyncio
async def test_start_run_refreshes_owners_when_config_not_startable():
    runner = _Runner()
    store = _Store()
    store.config = SkillReadinessConfigRecord(
        skill_id="skill-a",
        config=SkillReadinessConfig(
            checks=[
                {
                    "name": "cron_auth_valid",
                    "enabled": False,
                },
            ],
        ),
    )

    response = await _service(store=store, runner=runner).start_run(
        "source-a",
        "skill-a",
    )

    assert response.run is None
    assert response.owner_lookup_only is True
    assert response.owner_lookup_scheduled is True
    assert store.created == []
    assert runner.scheduled == []
    assert runner.owner_refreshes == [
        {"source_id": "source-a", "skill_id": "skill-a"},
    ]


@pytest.mark.asyncio
async def test_start_run_reuses_existing_running_run():
    store = _Store()
    store.running = SkillReadinessRunProgress(
        run_id="run-existing",
        source_id="source-a",
        skill_id="skill-a",
        status="running",
    )

    response = await _service(store=store).start_run("source-a", "skill-a")

    assert response.reused is True
    assert response.run.run_id == "run-existing"
    assert store.created == []


@pytest.mark.asyncio
async def test_start_run_schedules_owner_checks_and_records_partial_summary():
    runner = _Runner()
    store = _Store()

    response = await _service(store=store, runner=runner).start_run(
        "source-a",
        "skill-a",
    )

    assert response.reused is False
    assert response.run.total_users == 0
    assert runner.scheduled[0]["run_id"] == "run-created"
    assert "owners" not in runner.scheduled[0]
    assert "partial_failure_summary" not in runner.scheduled[0]


@pytest.mark.asyncio
async def test_start_run_uses_atomic_get_or_create_after_owner_lookup():
    """启动检查时必须通过存储层原子入口避免并发重复创建 running run。"""
    runner = _Runner()
    store = _Store()

    await _service(store=store, runner=runner).start_run("source-a", "skill-a")

    assert len(store.get_or_create_calls) == 1
    assert store.get_or_create_calls[0][0:2] == ("source-a", "skill-a")


@pytest.mark.asyncio
async def test_start_run_returns_running_run_before_owner_lookup_finishes():
    runner = _Runner()
    store = _Store()

    response = await _service(store=store, runner=runner).start_run(
        "source-a",
        "skill-a",
    )

    assert response.run.status == "running"
    assert response.run.total_users == 0
    assert runner.scheduled[0]["run_id"] == "run-created"


@pytest.mark.asyncio
async def test_results_are_source_scoped():
    with pytest.raises(SkillReadinessRunNotFound):
        await _service().get_results("run-1", source_id="other-source")


@pytest.mark.asyncio
async def test_results_passes_check_filter_to_store():
    store = _Store()

    await _service(store=store).get_results(
        "run-1",
        source_id="source-a",
        status="abnormal",
        check_name="cron_auth_valid",
        check_status="fail",
    )

    _, kwargs = store.list_args[0]
    assert kwargs["status"] == "abnormal"
    assert kwargs["check_name"] == "cron_auth_valid"
    assert kwargs["check_status"] == "fail"
