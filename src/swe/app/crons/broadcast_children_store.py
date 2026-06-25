# -*- coding: utf-8 -*-
"""定时任务分发用户反查快照存储。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

BroadcastChildrenLookupStatus = Literal[
    "idle",
    "running",
    "completed",
    "failed",
]

_SNAPSHOT_TABLE = "swe_cron_broadcast_child_snapshots"
_UNAVAILABLE_PREFIX = "cron broadcast children storage unavailable"


@dataclass(slots=True)
class CronBroadcastChildrenSnapshot:
    """定时任务分发用户反查快照。"""

    agent_id: str
    source_id: str
    tenant_id: str
    job_id: str
    status: BroadcastChildrenLookupStatus = "idle"
    items: list[dict[str, Any]] = field(default_factory=list)
    tenant_count: int = 0
    failed_tenants: int = 0
    failure_summary: str | None = None
    updated_at: datetime | None = None


class CronBroadcastChildrenStoreUnavailable(RuntimeError):
    """定时任务分发用户快照存储不可用。"""


class CronBroadcastChildrenStore:
    """读写定时任务分发用户反查快照。"""

    def __init__(self, db: Any | None = None):
        """初始化存储；无数据库时退化为进程内快照。"""
        self.db = db
        self._memory: dict[
            tuple[str, str, str, str],
            CronBroadcastChildrenSnapshot,
        ] = {}

    @property
    def is_available(self) -> bool:
        """返回当前数据库连接是否可用。"""
        return self.db is not None and bool(
            getattr(self.db, "is_connected", False),
        )

    async def initialize(self) -> None:
        """幂等初始化快照表。"""
        if not self.is_available:
            return
        await self._call_db(
            "initialize snapshots table",
            self.db.execute,
            _CREATE_TABLE_SQL,
        )

    async def get_snapshot(
        self,
        *,
        agent_id: str,
        source_id: str,
        tenant_id: str,
        job_id: str,
    ) -> CronBroadcastChildrenSnapshot | None:
        """读取某个源定时任务的最新分发用户快照。"""
        key = _key(agent_id, source_id, tenant_id, job_id)
        if not self.is_available:
            return self._memory.get(key)

        row = await self._call_db(
            "get snapshot",
            self.db.fetch_one,
            f"""
                SELECT agent_id, source_id, tenant_id, job_id, status,
                       tenant_count, failed_tenants, failure_summary,
                       items_json, snapshot_updated_at
                FROM {_SNAPSHOT_TABLE}
                WHERE agent_id = %s
                  AND source_id = %s
                  AND tenant_id = %s
                  AND job_id = %s
            """,
            key,
        )
        return _row_to_snapshot(row) if row else None

    async def mark_running(
        self,
        *,
        agent_id: str,
        source_id: str,
        tenant_id: str,
        job_id: str,
        tenant_count: int,
    ) -> bool:
        """抢占刷新任务；已有 running 时返回 False。"""
        key = _key(agent_id, source_id, tenant_id, job_id)
        if not self.is_available:
            current = self._memory.get(key)
            if current is not None and current.status == "running":
                return False
            self._memory[key] = _running_snapshot(
                current,
                agent_id=agent_id,
                source_id=source_id,
                tenant_id=tenant_id,
                job_id=job_id,
                tenant_count=tenant_count,
            )
            return True

        inserted = await self._call_db(
            "insert running snapshot",
            self.db.execute,
            f"""
                INSERT IGNORE INTO {_SNAPSHOT_TABLE} (
                    agent_id, source_id, tenant_id, job_id, status,
                    tenant_count, failed_tenants, failure_summary, items_json
                )
                VALUES (%s, %s, %s, %s, 'running', %s, 0, NULL, '[]')
            """,
            (*key, tenant_count),
        )
        if inserted:
            return True

        updated = await self._call_db(
            "mark snapshot running",
            self.db.execute,
            f"""
                UPDATE {_SNAPSHOT_TABLE}
                SET status = 'running',
                    tenant_count = %s,
                    failed_tenants = 0,
                    failure_summary = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = %s
                  AND source_id = %s
                  AND tenant_id = %s
                  AND job_id = %s
                  AND status <> 'running'
            """,
            (tenant_count, *key),
        )
        return bool(updated)

    async def record_completed(
        self,
        *,
        agent_id: str,
        source_id: str,
        tenant_id: str,
        job_id: str,
        items: list[dict[str, Any]],
        tenant_count: int,
        failed_tenants: int = 0,
        failure_summary: str | None = None,
    ) -> None:
        """保存一次成功完成的反查快照。"""
        await self._record_snapshot(
            agent_id=agent_id,
            source_id=source_id,
            tenant_id=tenant_id,
            job_id=job_id,
            status="completed",
            items=items,
            tenant_count=tenant_count,
            failed_tenants=failed_tenants,
            failure_summary=failure_summary,
        )

    async def record_failed(
        self,
        *,
        agent_id: str,
        source_id: str,
        tenant_id: str,
        job_id: str,
        tenant_count: int,
        failure_summary: str,
    ) -> None:
        """标记反查失败，并保留上一份可展示快照。"""
        key = _key(agent_id, source_id, tenant_id, job_id)
        if not self.is_available:
            current = self._memory.get(key)
            self._memory[key] = _failed_snapshot(
                current,
                agent_id=agent_id,
                source_id=source_id,
                tenant_id=tenant_id,
                job_id=job_id,
                tenant_count=tenant_count,
                failure_summary=failure_summary,
            )
            return

        await self._call_db(
            "mark snapshot failed",
            self.db.execute,
            f"""
                UPDATE {_SNAPSHOT_TABLE}
                SET status = 'failed',
                    tenant_count = %s,
                    failure_summary = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = %s
                  AND source_id = %s
                  AND tenant_id = %s
                  AND job_id = %s
            """,
            (tenant_count, failure_summary, *key),
        )

    async def _record_snapshot(
        self,
        *,
        agent_id: str,
        source_id: str,
        tenant_id: str,
        job_id: str,
        status: BroadcastChildrenLookupStatus,
        items: list[dict[str, Any]],
        tenant_count: int,
        failed_tenants: int,
        failure_summary: str | None,
    ) -> None:
        key = _key(agent_id, source_id, tenant_id, job_id)
        snapshot = CronBroadcastChildrenSnapshot(
            agent_id=agent_id,
            source_id=source_id,
            tenant_id=tenant_id,
            job_id=job_id,
            status=status,
            items=items,
            tenant_count=tenant_count,
            failed_tenants=failed_tenants,
            failure_summary=failure_summary,
            updated_at=datetime.now(),
        )
        if not self.is_available:
            self._memory[key] = snapshot
            return

        await self._call_db(
            "record snapshot",
            self.db.execute,
            f"""
                INSERT INTO {_SNAPSHOT_TABLE} (
                    agent_id, source_id, tenant_id, job_id, status,
                    tenant_count, failed_tenants, failure_summary,
                    items_json, snapshot_updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    tenant_count = VALUES(tenant_count),
                    failed_tenants = VALUES(failed_tenants),
                    failure_summary = VALUES(failure_summary),
                    items_json = VALUES(items_json),
                    snapshot_updated_at = VALUES(snapshot_updated_at),
                    updated_at = CURRENT_TIMESTAMP
            """,
            (
                *key,
                status,
                tenant_count,
                failed_tenants,
                failure_summary,
                json.dumps(items, ensure_ascii=False),
            ),
        )

    async def _call_db(
        self,
        operation: str,
        db_call: Any,
        *args: Any,
    ) -> Any:
        try:
            return await db_call(*args)
        except Exception as exc:
            raise CronBroadcastChildrenStoreUnavailable(
                f"{_UNAVAILABLE_PREFIX}: {operation} failed: {exc}",
            ) from exc


def _key(
    agent_id: str,
    source_id: str,
    tenant_id: str,
    job_id: str,
) -> tuple[str, str, str, str]:
    return (agent_id or "", source_id or "", tenant_id or "", job_id or "")


def _running_snapshot(
    current: CronBroadcastChildrenSnapshot | None,
    *,
    agent_id: str,
    source_id: str,
    tenant_id: str,
    job_id: str,
    tenant_count: int,
) -> CronBroadcastChildrenSnapshot:
    if current is None:
        return CronBroadcastChildrenSnapshot(
            agent_id=agent_id,
            source_id=source_id,
            tenant_id=tenant_id,
            job_id=job_id,
            status="running",
            tenant_count=tenant_count,
        )
    current.status = "running"
    current.tenant_count = tenant_count
    current.failed_tenants = 0
    current.failure_summary = None
    return current


def _failed_snapshot(
    current: CronBroadcastChildrenSnapshot | None,
    *,
    agent_id: str,
    source_id: str,
    tenant_id: str,
    job_id: str,
    tenant_count: int,
    failure_summary: str,
) -> CronBroadcastChildrenSnapshot:
    if current is None:
        return CronBroadcastChildrenSnapshot(
            agent_id=agent_id,
            source_id=source_id,
            tenant_id=tenant_id,
            job_id=job_id,
            status="failed",
            tenant_count=tenant_count,
            failure_summary=failure_summary,
        )
    current.status = "failed"
    current.tenant_count = tenant_count
    current.failure_summary = failure_summary
    return current


def _row_to_snapshot(row: dict[str, Any]) -> CronBroadcastChildrenSnapshot:
    items = _decode_items(row.get("items_json"))
    return CronBroadcastChildrenSnapshot(
        agent_id=str(row.get("agent_id") or ""),
        source_id=str(row.get("source_id") or ""),
        tenant_id=str(row.get("tenant_id") or ""),
        job_id=str(row.get("job_id") or ""),
        status=_status_or_idle(row.get("status")),
        items=items,
        tenant_count=int(row.get("tenant_count") or 0),
        failed_tenants=int(row.get("failed_tenants") or 0),
        failure_summary=row.get("failure_summary"),
        updated_at=row.get("snapshot_updated_at"),
    )


def _decode_items(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _status_or_idle(value: Any) -> BroadcastChildrenLookupStatus:
    text = str(value or "").strip()
    if text in {"idle", "running", "completed", "failed"}:
        return cast(BroadcastChildrenLookupStatus, text)
    return "idle"


_CREATE_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS {_SNAPSHOT_TABLE} (
        agent_id VARCHAR(128) NOT NULL,
        source_id VARCHAR(128) NOT NULL,
        tenant_id VARCHAR(128) NOT NULL,
        job_id VARCHAR(128) NOT NULL,
        status VARCHAR(20) NOT NULL,
        tenant_count INT NOT NULL DEFAULT 0,
        failed_tenants INT NOT NULL DEFAULT 0,
        failure_summary TEXT NULL,
        items_json MEDIUMTEXT NULL,
        snapshot_updated_at TIMESTAMP NULL DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (agent_id, source_id, tenant_id, job_id)
    )
"""
