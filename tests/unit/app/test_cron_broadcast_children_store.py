# -*- coding: utf-8 -*-
"""定时任务分发用户快照存储测试。"""

import asyncio

from swe.app.crons.broadcast_children_store import CronBroadcastChildrenStore


class _Db:
    def __init__(self, execute_results=None):
        self.is_connected = True
        self.executed = []
        self.execute_results = list(execute_results or [])

    async def execute(self, query, params=None):
        self.executed.append((query, params))
        if self.execute_results:
            return self.execute_results.pop(0)
        return 1

    async def fetch_one(self, query, params=None):
        self.executed.append((query, params))
        return None


def test_initialize_creates_snapshot_table():
    db = _Db()
    store = CronBroadcastChildrenStore(db)

    asyncio.run(store.initialize())

    query = db.executed[0][0]
    assert "CREATE TABLE IF NOT EXISTS swe_cron_broadcast_child_snapshots" in query
    assert "items_json MEDIUMTEXT" in query
    assert "snapshot_updated_at TIMESTAMP" in query
    assert "PRIMARY KEY (agent_id, source_id, tenant_id, job_id)" in query


def test_mark_running_claims_only_when_not_already_running():
    claimed_store = CronBroadcastChildrenStore(_Db(execute_results=[1]))
    reused_store = CronBroadcastChildrenStore(_Db(execute_results=[0, 0]))

    claimed = asyncio.run(
        claimed_store.mark_running(
            agent_id="default",
            source_id="source-a",
            tenant_id="tenant-a",
            job_id="job-source",
            tenant_count=2,
        ),
    )
    reused = asyncio.run(
        reused_store.mark_running(
            agent_id="default",
            source_id="source-a",
            tenant_id="tenant-a",
            job_id="job-source",
            tenant_count=2,
        ),
    )

    assert claimed is True
    assert reused is False
