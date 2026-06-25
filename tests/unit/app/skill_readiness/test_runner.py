# -*- coding: utf-8 -*-
"""技能可执行性后台运行器测试。"""

from __future__ import annotations

import asyncio

import pytest

from swe.app.skill_readiness.models import (
    SkillReadinessCheckConfig,
    SkillReadinessCheckResult,
    SkillReadinessConfig,
    SkillReadinessOwner,
)
from swe.app.skill_readiness.owner_resolver import OwnerLookupResult
from swe.app.skill_readiness.runner import SkillReadinessRunner
from swe.app.skill_readiness.strategies import SkillReadinessCheckContext
from swe.config.context import (
    get_current_source_id,
    get_current_tenant_id,
    reset_current_passthrough_headers,
    set_current_passthrough_headers,
)


class _ContextRecordingStrategy:
    name = "context_check"
    display_name = "上下文检查"

    def __init__(self):
        self.seen = []

    async def run(self, context, config):
        self.seen.append(
            (
                context.owner.user_id,
                get_current_tenant_id(),
                get_current_source_id(),
            ),
        )
        return SkillReadinessCheckResult(
            check_name=self.name,
            display_name=self.display_name,
            status="pass",
        )


class _HeaderRecordingStrategy:
    name = "context_check"
    display_name = "Context Check"

    def __init__(self):
        self.seen = []

    async def run(self, context, config):
        self.seen.append(dict(context.passthrough_headers))
        return SkillReadinessCheckResult(
            check_name=self.name,
            display_name=self.display_name,
            status="pass",
        )


class _Registry:
    def __init__(self, strategy):
        self.strategy = strategy

    async def run_check(self, context, config):
        return await self.strategy.run(context, config)


class _ProgressStore:
    def __init__(self):
        self.progress_updates = []
        self.user_results = []
        self.owner_snapshots = []
        self.owner_lookup_running = []
        self.owner_lookup_claimed = True

    async def update_run_progress(self, run_id, **kwargs):
        self.progress_updates.append(kwargs)

    async def record_user_result(self, run_id, user_result):
        self.user_results.append(user_result)

    async def mark_owner_lookup_running(self, source_id, skill_id):
        self.owner_lookup_running.append((source_id, skill_id))
        return self.owner_lookup_claimed

    async def record_owner_snapshot(self, source_id, skill_id, **kwargs):
        self.owner_snapshots.append((source_id, skill_id, kwargs))


class _OwnerResolver:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def resolve_owners(self, source_id, skill_id):
        self.calls.append((source_id, skill_id))
        return self.result


@pytest.mark.asyncio
async def test_user_check_runs_with_owner_tenant_and_source_context():
    """MCP 等策略依赖 contextvars 生成当前 owner 的运行时 header。"""
    strategy = _ContextRecordingStrategy()
    runner = SkillReadinessRunner(
        store=_ProgressStore(),
        registry=_Registry(strategy),
        user_concurrency=1,
    )

    await runner.run(
        run_id="run-1",
        source_id="source-a",
        skill_id="skill-a",
        owners=[SkillReadinessOwner(user_id="alice")],
        config=SkillReadinessConfig(
            checks=[SkillReadinessCheckConfig(name="context_check")],
        ),
    )

    assert strategy.seen == [("alice", "alice", "source-a")]


@pytest.mark.asyncio
async def test_user_check_passes_request_headers_to_mcp_context():
    """MCP 可用性自检需要沿用触发请求透传的鉴权 header。"""
    strategy = _HeaderRecordingStrategy()
    runner = SkillReadinessRunner(
        store=_ProgressStore(),
        registry=_Registry(strategy),
        user_concurrency=1,
    )
    token = set_current_passthrough_headers(
        {"cookie": "auth=token-1"},
    )

    try:
        await runner.run(
            run_id="run-1",
            source_id="source-a",
            skill_id="skill-a",
            owners=[SkillReadinessOwner(user_id="alice")],
            config=SkillReadinessConfig(
                checks=[SkillReadinessCheckConfig(name="context_check")],
            ),
        )
    finally:
        reset_current_passthrough_headers(token)

    assert strategy.seen == [{"cookie": "auth=token-1"}]


@pytest.mark.asyncio
async def test_run_resolves_owners_when_not_provided():
    """start_run 调度后由 runner 在后台解析 owner 并写入快照。"""
    store = _ProgressStore()
    strategy = _ContextRecordingStrategy()
    resolver = _OwnerResolver(
        OwnerLookupResult(
            owners=[SkillReadinessOwner(user_id="alice")],
            total_users=2,
            failed_users=1,
            failures=["bob: market down"],
        ),
    )
    runner = SkillReadinessRunner(
        store=store,
        registry=_Registry(strategy),
        owner_resolver=resolver,
        user_concurrency=1,
    )

    await runner.run(
        run_id="run-1",
        source_id="source-a",
        skill_id="skill-a",
        config=SkillReadinessConfig(
            checks=[SkillReadinessCheckConfig(name="context_check")],
        ),
    )

    assert resolver.calls == [("source-a", "skill-a")]
    assert store.owner_lookup_running == [("source-a", "skill-a")]
    assert store.owner_snapshots[0][2]["status"] == "completed"
    assert store.owner_snapshots[0][2]["failed_users"] == 1
    assert store.progress_updates[0]["total_users"] == 1
    assert store.progress_updates[-1]["status"] == "partial"
    assert [result.user_id for result in store.user_results] == ["alice"]


@pytest.mark.asyncio
async def test_run_marks_failed_when_owner_lookup_all_fails():
    """owner 全量解析失败时 run 在后台失败，而不是阻塞 start_run。"""
    store = _ProgressStore()
    resolver = _OwnerResolver(
        OwnerLookupResult(
            owners=[],
            total_users=2,
            failed_users=2,
            failures=["market down", "tenant source down"],
        ),
    )
    runner = SkillReadinessRunner(
        store=store,
        registry=_Registry(_ContextRecordingStrategy()),
        owner_resolver=resolver,
    )

    await runner.run(
        run_id="run-1",
        source_id="source-a",
        skill_id="skill-a",
        config=SkillReadinessConfig(
            checks=[SkillReadinessCheckConfig(name="context_check")],
        ),
    )

    assert store.owner_snapshots[0][2]["status"] == "failed"
    assert store.progress_updates[-1]["status"] == "failed"
    assert store.progress_updates[-1]["total_users"] == 2
    assert store.user_results == []


@pytest.mark.asyncio
async def test_refresh_owner_snapshot_marks_running_and_records_result():
    """overview 触发刷新时先标记 running，再保存最新快照。"""
    store = _ProgressStore()
    resolver = _OwnerResolver(
        OwnerLookupResult(
            owners=[SkillReadinessOwner(user_id="alice")],
            total_users=1,
        ),
    )
    runner = SkillReadinessRunner(
        store=store,
        registry=_Registry(_ContextRecordingStrategy()),
        owner_resolver=resolver,
    )

    await runner.refresh_owner_snapshot(source_id="source-a", skill_id="skill-a")

    assert store.owner_lookup_running == [("source-a", "skill-a")]
    assert store.owner_snapshots[0][2]["owners"][0].user_id == "alice"


@pytest.mark.asyncio
async def test_refresh_owner_snapshot_skips_when_db_claim_is_running():
    """其他实例已在刷新同一 source/skill 时，本实例不再解析 owner。"""
    store = _ProgressStore()
    store.owner_lookup_claimed = False
    resolver = _OwnerResolver(
        OwnerLookupResult(
            owners=[SkillReadinessOwner(user_id="alice")],
            total_users=1,
        ),
    )
    runner = SkillReadinessRunner(
        store=store,
        registry=_Registry(_ContextRecordingStrategy()),
        owner_resolver=resolver,
    )

    await runner.refresh_owner_snapshot(source_id="source-a", skill_id="skill-a")

    assert store.owner_lookup_running == [("source-a", "skill-a")]
    assert resolver.calls == []
    assert store.owner_snapshots == []


class _FailingStore(_ProgressStore):
    def __init__(self):
        super().__init__()
        self.bad_started = asyncio.Event()
        self.allow_slow = asyncio.Event()
        self.slow_recorded = False
        self.failed_before_slow = False

    async def update_run_progress(self, run_id, **kwargs):
        if kwargs.get("status") == "failed" and not self.slow_recorded:
            self.failed_before_slow = True
        await super().update_run_progress(run_id, **kwargs)

    async def record_user_result(self, run_id, user_result):
        if user_result.user_id == "bad":
            self.bad_started.set()
            raise RuntimeError("db down")
        await self.allow_slow.wait()
        self.slow_recorded = True
        await super().record_user_result(run_id, user_result)


@pytest.mark.asyncio
async def test_run_waits_for_all_user_tasks_before_marking_failed():
    """单个用户写入异常不能让 run 先 failed 后继续接受其他用户结果。"""
    store = _FailingStore()
    strategy = _ContextRecordingStrategy()
    runner = SkillReadinessRunner(
        store=store,
        registry=_Registry(strategy),
        user_concurrency=2,
    )
    run_task = asyncio.create_task(
        runner.run(
            run_id="run-1",
            source_id="source-a",
            skill_id="skill-a",
            owners=[
                SkillReadinessOwner(user_id="bad"),
                SkillReadinessOwner(user_id="slow"),
            ],
            config=SkillReadinessConfig(
                checks=[SkillReadinessCheckConfig(name="context_check")],
            ),
        ),
    )

    await store.bad_started.wait()
    await asyncio.sleep(0)

    try:
        assert store.failed_before_slow is False
    finally:
        store.allow_slow.set()
        await run_task

    assert store.progress_updates[-1]["status"] == "failed"
    assert store.slow_recorded is True
